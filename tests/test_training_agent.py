import importlib
import importlib.util
import json
from datetime import date

import pytest

from fitness.config import Settings
from fitness.models import Exercise, Profile
from fitness.provider import ProviderReply

DAY = date(2026, 10, 20)


def planner(**kwargs):
    assert importlib.util.find_spec('fitness.training_agent') is not None, 'training planner is not implemented'
    return importlib.import_module('fitness.training_agent').TrainingPlannerAgent(**kwargs)


def test_build_three_training_one_rest_cycle(profile_data):
    agent = planner()
    cycle = agent.build_cycle(Profile.model_validate(profile_data))
    assert [step['label'] for step in cycle] == ['推', '拉', '腿', '休息']
    assert [step['kind'] for step in cycle] == ['training', 'training', 'training', 'rest']
    for step in cycle:
        assert set(step) == {'label', 'kind', 'exercises', 'estimated_minutes'}
        assert step['estimated_minutes'] <= 40
        for exercise in step['exercises']:
            Exercise.model_validate(exercise)


def test_custom_cycle_is_not_tied_to_a_week(profile_data):
    labels = ['胸', '背', '休息', '腿', '休息']
    assert [s['label'] for s in planner().build_cycle(Profile.model_validate(profile_data), labels)] == labels


@pytest.mark.parametrize('labels', [[], ['推'] * 15, [''], ['x' * 201]])
def test_invalid_cycle_labels_are_rejected(profile_data, labels):
    with pytest.raises(ValueError):
        planner().build_cycle(Profile.model_validate(profile_data), labels)


def test_equipment_never_assumes_gym_when_unknown(profile_data):
    profile_data['training']['available_equipment'] = None
    cycle = planner().build_cycle(Profile.model_validate(profile_data))
    ids = {x['exercise_id'] for step in cycle for x in step['exercises']}
    assert ids
    assert ids <= {'bodyweight_squat', 'glute_bridge', 'dead_bug', 'push_up'}


def run_day(profile_data, *, index=0, **kwargs):
    agent = kwargs.pop('agent', None) or planner()
    profile = Profile.model_validate(profile_data)
    return agent.plan_day(profile, agent.build_cycle(profile), index, DAY,
                          kwargs.pop('history', []), kwargs.pop('restrictions', []), **kwargs)


def test_generating_normal_training_never_advances_cycle(profile_data):
    result = run_day(profile_data)
    assert result['action'] == 'train'
    assert result['cycle_index'] == result['next_cycle_index'] == 0
    assert result['training']['exercises']
    assert set(result) == {'action', 'cycle_index', 'next_cycle_index', 'training',
                           'restrictions', 'reasons', 'questions', 'provider'}
    assert result['provider']['calls'] == 0


def test_rest_day_keeps_current_progress_until_completion(profile_data):
    result = run_day(profile_data, index=3)
    assert result['action'] == 'rest'
    assert result['next_cycle_index'] == 3


@pytest.mark.parametrize('conditions', ['今天很累不想练，明天再练', '今天没时间训练，安排明天', '今天休息不练了'])
def test_fatigue_or_unavailability_defers_training(profile_data, conditions):
    result = run_day(profile_data, conditions=conditions)
    assert result['action'] == 'defer'
    assert result['next_cycle_index'] == 0
    assert result['training']['kind'] == 'rest'
    assert not result['training']['exercises']


def test_yesterday_fatigue_is_not_a_permanent_defer(profile_data):
    result = run_day(profile_data, history=[{'date': '2026-10-19',
        'raw_text': '今天很累不想练，明天再练', 'data': {'fatigue': '很累'}}])
    assert result['action'] == 'train'


def test_yesterday_severe_sleep_loss_defers_today_but_not_indefinitely(profile_data):
    history = [{'date': '2026-10-19', 'data': {'sleep_hours': 4}}]
    result = run_day(profile_data, history=history)
    assert result['action'] == 'defer'
    assert result['next_cycle_index'] == 0
    history[0]['date'] = '2026-10-18'
    assert run_day(profile_data, history=history)['action'] == 'train'


def test_continuous_recent_fatigue_defers_today(profile_data):
    history = [{'date': '2026-10-18', 'data': {'fatigue': '很累'}},
               {'date': '2026-10-19', 'data': {'fatigue': '持续疲劳'}}]
    assert run_day(profile_data, history=history)['action'] == 'defer'


def test_recent_short_sleep_reduces_volume_without_advancing_cycle(profile_data):
    history = [{'date': '2026-10-19', 'data': {'sleep_hours': 5.5}}]
    result = run_day(profile_data, history=history)
    assert result['action'] == 'train'
    assert result['next_cycle_index'] == 0
    assert all(exercise['sets'] <= 2 for exercise in result['training']['exercises'])
    assert any('睡眠' in reason for reason in result['reasons'])


def test_negated_pain_or_fatigue_does_not_create_restriction(profile_data):
    result = run_day(profile_data, conditions='没有肩膀疼痛，也没有疲劳，正常训练')
    assert result['action'] == 'train'
    assert result['restrictions'] == []


def test_explicit_skip_advances_exactly_one_step(profile_data):
    result = run_day(profile_data, conditions='这次训练直接跳过，不用补')
    assert result['action'] == 'skip'
    assert result['next_cycle_index'] == 1
    assert result['training']['exercises'] == []


def test_shoulder_injury_creates_persistent_restriction(profile_data):
    result = run_day(profile_data, conditions='肩膀受伤了不想练肩')
    assert result['action'] == 'skip'
    assert result['next_cycle_index'] == 1
    assert result['training']['exercises'] == []
    restriction = result['restrictions'][0]
    assert restriction['area'] == 'shoulder'
    assert restriction['active'] is True
    assert restriction['source_date'] == DAY.isoformat()
    tomorrow = run_day(profile_data, index=2, restrictions=result['restrictions'])
    assert tomorrow['action'] == 'train'
    assert {x['exercise_id'] for x in tomorrow['training']['exercises']} == {'bodyweight_squat'}
    assert tomorrow['questions']


def test_restriction_blocks_other_shoulder_loading_movements(profile_data):
    restriction = [{'area': 'shoulder', 'reason': '受伤', 'source_date': '2026-10-19', 'active': True}]
    result = run_day(profile_data, index=1, restrictions=restriction)
    assert result['action'] == 'pause'
    assert result['training']['exercises'] == []


def test_restriction_allows_rest_step_without_clearing_restriction(profile_data):
    restriction = [{'area': 'shoulder', 'reason': '受伤', 'source_date': '2026-10-19', 'active': True}]
    result = run_day(profile_data, index=3, restrictions=restriction)
    assert result['action'] == 'rest'
    assert result['restrictions'] == restriction


def test_unmapped_injury_cannot_allow_apparently_unrelated_training(profile_data):
    result = run_day(profile_data, index=2, conditions='受伤了，还不清楚哪里有问题')
    assert result['action'] == 'pause'
    assert result['training']['exercises'] == []


def test_partial_same_day_feedback_retains_previous_sleep_fact(profile_data):
    history = [
        {'date': '2026-10-19', 'created_at': '2026-10-19T08:00:00',
         'data': {'sleep_hours': 4, 'fatigue': None}},
        {'date': '2026-10-19', 'created_at': '2026-10-19T12:00:00',
         'data': {'sleep_hours': None, 'fatigue': '正常'}},
    ]
    assert run_day(profile_data, history=history)['action'] == 'defer'


def test_latest_explicit_sleep_correction_replaces_previous_fact(profile_data):
    history = [
        {'date': '2026-10-19', 'created_at': '2026-10-19T08:00:00', 'data': {'sleep_hours': 4}},
        {'date': '2026-10-19', 'created_at': '2026-10-19T12:00:00', 'data': {'sleep_hours': 8}},
    ]
    assert run_day(profile_data, history=history)['action'] == 'train'


def test_knee_restriction_filters_lower_body_loads(profile_data):
    profile_data['training']['available_equipment'] = ['barbell', 'machine']
    result = run_day(profile_data, index=2, restrictions=[{
        'area': 'knee', 'reason': '膝盖受伤', 'source_date': '2026-10-19', 'active': True}])
    assert result['action'] == 'pause'
    assert not result['training']['exercises']


def test_unrelated_safe_training_still_respects_today_fatigue(profile_data):
    restriction = [{'area': 'shoulder', 'reason': '受伤', 'source_date': '2026-10-19', 'active': True}]
    result = run_day(profile_data, index=2, restrictions=restriction, conditions='今天很累不想练')
    assert result['action'] == 'defer'
    assert not result['training']['exercises']


def test_explicit_release_suppresses_old_feedback_injury(profile_data):
    restriction = [{'area': 'shoulder', 'reason': '受伤', 'source_date': '2026-10-19',
        'active': False, 'resolved_on': '2026-10-20', 'resolved_at': '2026-10-20T08:00:00Z',
        'released_conditions': []}]
    history = [{'date': '2026-10-19', 'fact_updated_at': '2026-10-19T09:00:00Z',
                'data': {'training_summary': '肩膀受伤了'}}]
    result = run_day(profile_data, restrictions=restriction, history=history)
    assert result['action'] == 'train'
    assert result['restrictions'] == restriction
    history[0]['fact_updated_at'] = '2026-10-20T09:00:00Z'
    revised = run_day(profile_data, restrictions=restriction, history=history)
    assert revised['action'] == 'pause'
    assert any(r['active'] for r in revised['restrictions'])


def test_release_suppresses_only_exact_released_conditions(profile_data):
    restriction = [{'area': 'shoulder', 'active': False, 'resolved_on': '2026-10-20',
        'resolved_at': '2026-10-20T08:00:00Z',
        'released_conditions': [{'date': DAY.isoformat(), 'text': '肩膀受伤了'}]}]
    result = run_day(profile_data, restrictions=restriction, conditions='肩膀受伤了',
                     conditions_recorded_at='2026-10-20T07:00:00Z')
    assert result['action'] == 'train'
    updated = run_day(profile_data, restrictions=restriction, conditions='肩膀又受伤了',
                      conditions_recorded_at='2026-10-20T07:00:00Z')
    assert updated['action'] == 'pause'


def test_same_condition_reported_again_after_release_is_new_injury(profile_data):
    restriction = [{'area': 'shoulder', 'active': False, 'resolved_at': '2026-10-20T08:00:00Z',
        'released_conditions': [{'date': DAY.isoformat(), 'text': '肩膀受伤了'}]}]
    result = run_day(profile_data, restrictions=restriction, conditions='肩膀受伤了',
                     conditions_recorded_at='2026-10-20T09:00:00Z')
    assert result['action'] == 'pause'
    assert any(r['area'] == 'shoulder' and r['active'] for r in result['restrictions'])


def test_raw_feedback_release_uses_creation_time_not_later_data_revision(profile_data):
    restriction = [{'area': 'shoulder', 'active': False, 'resolved_at': '2026-10-20T10:00:00Z',
        'released_conditions': []}]
    history = [{'date': DAY.isoformat(), 'raw_text': '肩膀受伤了',
        'created_at': '2026-10-20T08:00:00Z', 'updated_at': '2026-10-20T12:00:00Z', 'data': {}}]
    assert run_day(profile_data, restrictions=restriction, history=history)['action'] == 'train'


def test_structured_feedback_release_uses_fact_update_time(profile_data):
    restriction = [{'area': 'shoulder', 'active': False, 'resolved_at': '2026-10-20T10:00:00Z',
        'released_conditions': []}]
    history = [{'date': DAY.isoformat(), 'raw_text': '', 'created_at': '2026-10-20T08:00:00Z',
        'fact_updated_at': '2026-10-20T11:00:00Z', 'data': {'training_summary': '肩膀受伤了'}}]
    assert run_day(profile_data, restrictions=restriction, history=history)['action'] == 'pause'


def test_release_cannot_override_profile_health_limit(profile_data):
    profile_data['health'] = {'exercise_limiting_conditions_status': 'has_conditions',
                              'exercise_limiting_conditions_details': '肩部损伤'}
    restriction = [{'area': 'shoulder', 'active': False, 'resolved_on': DAY.isoformat(),
                    'resolved_at': '2026-10-20T08:00:00Z', 'released_conditions': []}]
    assert run_day(profile_data, restrictions=restriction)['action'] == 'pause'


def test_injury_from_history_is_retained(profile_data):
    result = run_day(profile_data, history=[{'date': '2026-10-19',
        'raw_text': '肩膀受伤了', 'data': {'training_summary': '肩膀受伤了'}}])
    assert result['action'] == 'pause'
    assert result['restrictions'][0]['source_date'] == '2026-10-19'


def test_recovery_mention_requires_confirmation_instead_of_auto_clear(profile_data):
    restrictions = [{'area': 'shoulder', 'reason': '受伤', 'source_date': '2026-10-19', 'active': True}]
    result = run_day(profile_data, restrictions=restrictions, conditions='肩膀已经好了，恢复训练')
    assert result['action'] == 'pause'
    assert result['restrictions'] == restrictions
    assert any('确认' in question for question in result['questions'])


def test_explicit_skip_with_injury_still_preserves_restrictions(profile_data):
    result = run_day(profile_data, conditions='肩膀受伤了，这次训练直接跳过')
    assert result['action'] == 'skip'
    assert result['next_cycle_index'] == 1
    assert result['restrictions'][0]['active']
    assert not result['training']['exercises']


def test_urgent_symptoms_pause_training(profile_data):
    result = run_day(profile_data, conditions='今天胸痛还有呼吸困难，跳过训练')
    assert result['action'] == 'pause'
    assert result['next_cycle_index'] == 0
    assert not result['training']['exercises']
    assert any('就医' in reason for reason in result['reasons'])


def test_earlier_raw_injury_survives_later_food_only_feedback(profile_data):
    history = [
        {'date': DAY.isoformat(), 'raw_text': '肩膀受伤了',
         'created_at': '2026-10-20T08:00:00Z', 'data': {}},
        {'date': DAY.isoformat(), 'raw_text': '中午吃了米饭',
         'created_at': '2026-10-20T12:00:00Z', 'data': {'food_summary': '米饭'}},
    ]
    result = run_day(profile_data, history=history)
    assert result['action'] in {'pause', 'skip'}
    assert not result['training']['exercises']
    assert any(r['area'] == 'shoulder' and r['active'] for r in result['restrictions'])


def test_earlier_same_day_fatigue_survives_later_food_only_feedback(profile_data):
    history = [
        {'date': DAY.isoformat(), 'raw_text': '今天很累不想练，明天再练',
         'created_at': '2026-10-20T08:00:00Z', 'data': {}},
        {'date': DAY.isoformat(), 'raw_text': '中午吃了米饭',
         'created_at': '2026-10-20T12:00:00Z', 'data': {'food_summary': '米饭'}},
    ]
    assert run_day(profile_data, history=history)['action'] == 'defer'


def test_latest_same_day_food_only_feedback_does_not_replace_fatigue_decision(profile_data):
    history = [
        {'date': DAY.isoformat(), 'raw_text': '今天很累不想练，明天再练',
         'created_at': '2026-10-20T08:00:00Z', 'data': {'fatigue': '很累'}},
        {'date': DAY.isoformat(), 'raw_text': '中午吃了米饭',
         'created_at': '2026-10-20T12:00:00Z', 'data': {'food_summary': '米饭'}},
    ]
    assert run_day(profile_data, history=history)['action'] == 'defer'


def test_later_fatigue_recovery_correction_clears_same_day_defer(profile_data):
    history = [
        {'date': DAY.isoformat(), 'raw_text': '今天很累不想练，明天再练',
         'created_at': '2026-10-20T08:00:00Z', 'data': {}},
        {'date': DAY.isoformat(), 'raw_text': '现在不累了，状态恢复，可以训练',
         'created_at': '2026-10-20T12:00:00Z', 'data': {}},
    ]
    assert run_day(profile_data, history=history)['action'] == 'train'
    assert run_day(profile_data, history=list(reversed(history)))['action'] == 'train'


def test_current_recovery_condition_takes_precedence_over_older_feedback(profile_data):
    history = [{'date': DAY.isoformat(), 'raw_text': '今天很累不想练',
                'created_at': '2026-10-20T08:00:00Z', 'data': {}}]
    result = run_day(profile_data, history=history, conditions='现在不累了，可以训练',
                     conditions_recorded_at='2026-10-20T12:00:00Z')
    assert result['action'] == 'train'


def test_explicit_current_recovery_clears_recent_fatigue_defer(profile_data):
    history = [{'date': '2026-10-18', 'data': {'fatigue': '很累'}},
               {'date': '2026-10-19', 'data': {'fatigue': '持续疲劳'}}]
    result = run_day(profile_data, history=history, conditions='现在不累了，状态恢复，可以训练')
    assert result['action'] == 'train'


def test_fatigue_correction_does_not_release_active_injury(profile_data):
    history = [
        {'date': DAY.isoformat(), 'raw_text': '今天很累不想练，肩膀受伤了',
         'created_at': '2026-10-20T08:00:00Z', 'data': {}},
        {'date': DAY.isoformat(), 'raw_text': '现在不累了，状态恢复，可以训练',
         'created_at': '2026-10-20T12:00:00Z', 'data': {}},
    ]
    result = run_day(profile_data, history=history)
    assert result['action'] in {'pause', 'skip'}
    assert not result['training']['exercises']
    assert any(r['area'] == 'shoulder' and r['active'] for r in result['restrictions'])


def test_exact_released_urgent_condition_does_not_retrigger(profile_data):
    text = '今天胸痛还有呼吸困难'
    restriction = [{'area': 'urgent_symptoms', 'active': False,
        'resolved_at': '2026-10-20T08:00:00Z',
        'released_conditions': [{'date': DAY.isoformat(), 'text': text}]}]
    assert run_day(profile_data, restrictions=restriction, conditions=text,
                   conditions_recorded_at='2026-10-20T07:00:00Z')['action'] == 'train'
    assert run_day(profile_data, restrictions=restriction, conditions=text,
                   conditions_recorded_at='2026-10-20T09:00:00Z')['action'] == 'pause'
    assert run_day(profile_data, restrictions=restriction, conditions=text + '又发生了',
                   conditions_recorded_at='2026-10-20T07:00:00Z')['action'] == 'pause'


def test_urgent_feedback_release_obeys_fact_timestamp(profile_data):
    restriction = [{'area': 'urgent_symptoms', 'active': False,
        'resolved_at': '2026-10-20T10:00:00Z', 'released_conditions': []}]
    history = [{'date': DAY.isoformat(), 'data': {'training_summary': '今天胸痛'},
        'fact_updated_at': '2026-10-20T08:00:00Z', 'updated_at': '2026-10-20T12:00:00Z'}]
    assert run_day(profile_data, restrictions=restriction, history=history)['action'] == 'train'
    history[0]['fact_updated_at'] = '2026-10-20T11:00:00Z'
    assert run_day(profile_data, restrictions=restriction, history=history)['action'] == 'pause'


def test_synthetic_conditions_release_is_per_area(profile_data):
    text = '肩膀和膝盖受伤了'
    history = [{'source_kind': 'conditions', 'date': DAY.isoformat(), 'raw_text': text,
                'created_at': '2026-10-20T08:00:00Z', 'data': {}}]
    restriction = [{'area': 'shoulder', 'active': False,
        'resolved_at': '2026-10-20T10:00:00Z',
        'released_conditions': [{'date': DAY.isoformat(), 'text': text}]}]
    result = run_day(profile_data, restrictions=restriction, history=history)
    assert not any(r['area'] == 'shoulder' and r['active'] for r in result['restrictions'])
    assert any(r['area'] == 'knee' and r['active'] for r in result['restrictions'])


def test_released_shoulder_does_not_hide_urgent_in_same_condition(profile_data):
    text = '肩膀受伤了，还有胸痛'
    restriction = [{'area': 'shoulder', 'active': False,
        'resolved_at': '2026-10-20T10:00:00Z',
        'released_conditions': [{'date': DAY.isoformat(), 'text': text}]}]
    result = run_day(profile_data, restrictions=restriction, conditions=text)
    assert result['action'] == 'pause'
    assert any(r['area'] == 'urgent_symptoms' and r['active'] for r in result['restrictions'])


def test_profile_health_limits_block_automatic_training(profile_data):
    profile_data['health'] = {'exercise_limiting_conditions_status': 'has_conditions',
                              'exercise_limiting_conditions_details': '肩部损伤'}
    result = run_day(profile_data)
    assert result['action'] == 'pause'
    assert not result['training']['exercises']


class Provider:
    def __init__(self, output):
        self.output = output
        self.calls = 0

    def complete(self, messages, tools=None, **kwargs):
        self.calls += 1
        return ProviderReply(content=json.dumps(self.output), usage={'total_tokens': 12})


def test_invalid_model_action_fails_without_local_fallback(profile_data):
    from fitness.agent_contracts import PlanningRunError
    provider = Provider({'action': 'invent_exercises'})
    agent = planner(settings=Settings(live_enabled=True), provider=provider)
    with pytest.raises(PlanningRunError) as error:
        run_day(profile_data, agent=agent, mode='live')
    assert error.value.result.candidate is None
    assert error.value.result.reason_code == 'output_invalid'
    assert error.value.result.trace['calls'] == provider.calls == 3
    assert error.value.result.trace['usage'] == {'total_tokens': 36}


def test_model_can_select_conservative_defer_without_changing_prescription(profile_data):
    provider = Provider({'status': 'draft_ready', 'questions': [], 'candidate': {
        'summary': '根据当天状态顺延', 'action': 'defer', 'training': {
            'label': '恢复', 'kind': 'rest', 'exercises': [], 'estimated_minutes': 0}}})
    result = run_day(profile_data, agent=planner(settings=Settings(live_enabled=True), provider=provider),
                     mode='live', conditions='今天状态低迷，想调整训练')
    assert result['action'] == 'defer'
    assert result['next_cycle_index'] == 0
    assert result['training']['exercises'] == []
    assert result['provider']['status'] == 'ok'


def test_model_cannot_bypass_health_guard_or_demo_opt_in(profile_data):
    provider = Provider({'action': 'train'})
    agent = planner(settings=Settings(live_enabled=True), provider=provider)
    result = run_day(profile_data, agent=agent, mode='live', conditions='训练时胸痛、呼吸困难')
    assert result['action'] == 'pause'
    assert provider.calls == 0
    assert result['provider']['status'] == 'skipped_safety'
    run_day(profile_data, agent=agent, mode='demo')
    assert provider.calls == 0


def test_saved_cycle_cannot_inject_unknown_exercises(profile_data):
    agent = planner()
    profile = Profile.model_validate(profile_data)
    cycle = agent.build_cycle(profile)
    cycle[0]['exercises'][0]['exercise_id'] = 'unsafe_unknown'
    result = agent.plan_day(profile, cycle, 0, DAY, [], [])
    assert result['action'] == 'pause'
    assert result['training']['exercises'] == []
