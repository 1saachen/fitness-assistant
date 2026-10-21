from datetime import date

import pytest
from planning_provider import PlanningScriptProvider as ScriptProvider
from test_agent_runtime import final
from test_training_live import day_candidate, step

from fitness.config import Settings
from fitness.daily_planning import DailyPlanningService
from fitness.models import Profile
from fitness.provider import ProviderError
from fitness.storage import Conflict, Store

DAY = date(2026, 10, 20)


def service(tmp_path, profile_data, replies):
    store = Store(tmp_path / 'live.db')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    return DailyPlanningService(store, Settings(live_enabled=True),
        provider=ScriptProvider(replies)), store


def cycle_candidate():
    return {'summary': '模型规划的循环', 'assumptions': ['训练时间为估算'],
            'source_ids': [], 'questions': [], 'cycle': [step()]}


def test_service_saves_model_cycle_and_daily_sets(tmp_path, profile_data):
    svc, _ = service(tmp_path, profile_data, [final(cycle_candidate()), final(day_candidate())])
    long = svc.create_long_term(DAY, mode='live')
    assert long['data']['cycle'][0]['exercises'][0]['sets'] == 4
    assert long['trace']['training_source'] == 'model'
    assert long['trace']['nutrition_source'] == 'model'
    svc.confirm_long_term(long['id'])
    daily = svc.generate_day(DAY, mode='live')
    assert daily['data']['training']['exercises'][0]['sets'] == 4
    assert daily['trace']['mode'] == 'live'
    assert svc.generate_day(DAY, mode='live')['id'] == daily['id']
    reopened = DailyPlanningService(Store(tmp_path / 'live.db'), Settings(live_enabled=True))
    assert reopened.repo.days()[0]['data']['training']['exercises'][0]['sets'] == 4
    assert reopened.repo.long_terms()[0]['status'] == 'confirmed'


def test_strength_baseline_actual_results_and_prescription_remain_independent(tmp_path, profile_data):
    import json
    from datetime import timedelta

    from fitness.models import FeedbackData
    profile_data['training'].update(available_equipment=['barbell', 'bodyweight'], gym_access=True,
        strength_baseline={'bench_press_1rm_kg': 80, 'pull_up_max_reps': 0,
                           'recorded_on': '2026-10-01', 'notes': '1RM为估算值'})
    original = cycle_candidate()
    original['cycle'][0]['exercises'][0].update(exercise_id='barbell_bench_press', name='杠铃卧推',
                                              weight_kg=50, target_rpe=8)
    following = day_candidate()
    following['training']['exercises'][0].update(exercise_id='barbell_bench_press', name='杠铃卧推',
                                                weight_kg=45, target_rpe=7.5)
    svc, store = service(tmp_path, profile_data, [final(original), final(following)])
    long = svc.confirm_long_term(svc.create_long_term(DAY, mode='live')['id'])
    actual = FeedbackData(date=DAY, training_completed=True, exercise_results=[{
        'exercise_id': 'barbell_bench_press', 'weight_kg': 45, 'rpe': 9}]).model_dump(mode='json')
    row = store.create_feedback('卧推45kg，8/8/7次，末组RPE9，今天训练已完成', actual, 'live', {})
    store.confirm_feedback(row['id'], actual, 0)
    daily = svc.generate_day(DAY + timedelta(days=1), mode='live')
    task = json.loads(svc.training.provider.messages[-1][1]['content'])
    assert task['profile']['training']['strength_baseline']['bench_press_1rm_kg'] == 80
    assert task['profile']['training']['strength_baseline']['pull_up_max_reps'] == 0
    assert task['cycle'][0]['exercises'][0]['weight_kg'] == 50
    assert task['recent_reports'][0]['exercise_results'][0]['weight_kg'] == 45
    assert '8/8/7' in task['recent_reports'][0]['raw_text']
    assert daily['data']['training']['exercises'][0]['weight_kg'] == 45
    saved_long = next(item for item in svc.repo.long_terms() if item['id'] == long['id'])
    assert saved_long['data']['cycle'][0]['exercises'][0]['weight_kg'] == 50
    assert store.profile()['data']['training']['strength_baseline']['bench_press_1rm_kg'] == 80


@pytest.mark.parametrize('reply', [final(status='needs_input', questions=['可以训练多久？']), ProviderError('timeout')])
def test_incomplete_run_never_writes_local_fallback(tmp_path, profile_data, reply):
    from fitness.agent_contracts import PlanningRunError
    svc, _ = service(tmp_path, profile_data, [reply])
    with pytest.raises(PlanningRunError):
        svc.create_long_term(DAY, mode='live')
    assert svc.repo.long_terms() == []


def test_long_term_generation_rejects_feedback_changed_during_model_call(tmp_path, profile_data):
    svc, store = service(tmp_path, profile_data, [])
    class ConcurrentProvider:
        def complete(self, *args, **kwargs):
            from fitness.models import FeedbackData
            data = FeedbackData(date=DAY, sleep_hours=6).model_dump(mode='json')
            row = store.create_feedback('睡了6小时', data, 'demo', {})
            store.confirm_feedback(row['id'], data, 0)
            return final(cycle_candidate())
    svc.training.provider = ConcurrentProvider()
    with pytest.raises(Conflict):
        svc.create_long_term(DAY, mode='live')
    assert svc.repo.long_terms() == []


def test_live_failed_day_retains_previous_plan_and_eaten_meal(tmp_path, profile_data):
    from fitness.agent_contracts import PlanningRunError
    svc, _ = service(tmp_path, profile_data, [final(cycle_candidate()), final(day_candidate()), ProviderError('timeout')])
    svc.confirm_long_term(svc.create_long_term(DAY, mode='live')['id'])
    daily = svc.generate_day(DAY, mode='live')
    svc.complete_meal(daily['id'], '早餐', daily['revision'])
    before = svc.repo.days()
    with pytest.raises(PlanningRunError):
        svc.generate_day(DAY, conditions='调整今天训练', mode='live')
    assert svc.repo.days() == before


def test_completed_training_is_preserved_without_a_new_model_call(tmp_path, profile_data):
    from fitness.models import FeedbackData
    svc, store = service(tmp_path, profile_data, [final(cycle_candidate()), final(day_candidate())])
    svc.confirm_long_term(svc.create_long_term(DAY, mode='live')['id'])
    daily = svc.generate_day(DAY, mode='live')
    data = FeedbackData(date=DAY, training_completed=True).model_dump(mode='json')
    feedback = store.create_feedback('完成训练', data, 'demo', {})
    store.confirm_feedback(feedback['id'], data, 0)
    revised = svc.generate_day(DAY, conditions='今天训练已完成', mode='live')
    assert revised['data']['training'] == daily['data']['training']
    assert len(svc.training.provider.messages) == 2


def test_followup_rejects_stale_snapshot(tmp_path, profile_data):
    from fitness.agent_contracts import PlanningRunError
    svc, store = service(tmp_path, profile_data, [final(status='needs_input', questions=['多少分钟？'])])
    with pytest.raises(PlanningRunError) as error:
        svc.create_long_term(DAY, mode='live')
    store.save_profile(store.profile()['data'], 1)
    with pytest.raises(Conflict):
        svc.create_long_term(DAY, mode='live', conditions='20分钟',
            expected_snapshot_token=error.value.snapshot_token)


def test_task_honors_profile_limit_even_when_conditions_offer_longer(tmp_path, profile_data):
    svc, _ = service(tmp_path, profile_data, [])
    task = svc._task(svc.repo.snapshot(DAY), DAY, 'day', Profile.model_validate(profile_data),
                     '今天有90分钟', {})
    assert task.time_limit_minutes == 40


def test_long_term_keeps_symptoms_from_superseded_daily_conditions(tmp_path, profile_data):
    from fitness.agent_contracts import PlanningRunError
    svc, _ = service(tmp_path, profile_data, [final(cycle_candidate())] * 3)
    svc.confirm_long_term(svc.create_long_term(DAY)['id'])
    svc.generate_day(DAY, conditions='肩膀受伤了')
    svc.generate_day(DAY, conditions='今天在食堂吃饭')
    with pytest.raises(PlanningRunError):
        svc.create_long_term(DAY, mode='live')


def test_completed_demo_training_keeps_original_source_during_live_refresh(tmp_path, profile_data):
    from fitness.models import FeedbackData
    svc, store = service(tmp_path, profile_data, [])
    svc.confirm_long_term(svc.create_long_term(DAY)['id'])
    daily = svc.generate_day(DAY)
    data = FeedbackData(date=DAY, training_completed=True).model_dump(mode='json')
    row = store.create_feedback('训练已完成', data, 'demo', {})
    store.confirm_feedback(row['id'], data, 0)
    revised = svc.generate_day(DAY, mode='live')
    assert revised['data']['training'] == daily['data']['training']
    assert revised['trace']['training_source'] == 'deterministic_local'
    assert svc.training.provider.messages == []
