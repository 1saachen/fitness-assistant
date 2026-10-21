from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError
from test_agent_runtime import ScriptProvider, final


def step(sets=4, exercise_id='dumbbell_row'):
    return {'label': '拉', 'kind': 'training', 'estimated_minutes': 15, 'exercises': [
        {'exercise_id': exercise_id, 'name': '单臂哑铃划船', 'sets': sets,
         'reps_min': 8, 'reps_max': 12, 'rest_seconds': 90}]}


def day_candidate():
    return {'summary': '根据今天的时间安排拉部训练。', 'assumptions': ['每次重复约4秒'],
        'source_ids': [], 'questions': [], 'action': 'train', 'training': step(),
        'reasons': ['器械与时间满足本次安排'], 'scheduled_time': None,
        'load_description': '中等训练量'}


def task(profile_data, kind='day', **kwargs):
    from fitness.models import Profile
    from fitness.training_contracts import TrainingTask
    return TrainingTask(kind=kind, date=date(2026, 10, 20),
        profile=Profile.model_validate(profile_data), profile_version=1,
        cycle=[step(3)], **kwargs)


def test_rest_step_cannot_hide_exercises():
    from fitness.training_contracts import TrainingStep
    data = step()
    data['kind'] = 'rest'
    with pytest.raises(ValidationError):
        TrainingStep.model_validate(data)


def test_string_sets_are_not_silently_coerced():
    from fitness.training_contracts import TrainingStep
    data = step()
    data['exercises'][0]['sets'] = '3'
    with pytest.raises(ValidationError):
        TrainingStep.model_validate(data)


def test_live_day_keeps_model_sets_instead_of_local_template(profile_data):
    from fitness.config import Settings
    from fitness.training_agent import TrainingPlannerAgent
    provider = ScriptProvider([final(day_candidate())])
    result = TrainingPlannerAgent(Settings(live_enabled=True), provider).plan_day_live(task(profile_data))
    assert result.status == 'draft_ready'
    assert result.candidate['training']['exercises'][0]['sets'] == 4
    assert len(provider.messages) == 1
    assert 'profile' in provider.messages[0][1]['content']


def test_live_day_preserves_supported_weight_and_target_rpe(profile_data):
    from fitness.config import Settings
    from fitness.training_agent import TrainingPlannerAgent
    candidate = day_candidate()
    candidate['training']['exercises'][0].update(weight_kg=20, target_rpe=7.5)
    result = TrainingPlannerAgent(Settings(live_enabled=True), ScriptProvider([final(candidate)])).plan_day_live(
        task(profile_data))
    exercise = result.candidate['training']['exercises'][0]
    assert exercise['weight_kg'] == 20
    assert exercise['target_rpe'] == 7.5


def test_live_cycle_is_generated_by_model(profile_data):
    from fitness.config import Settings
    from fitness.training_agent import TrainingPlannerAgent
    candidate = {k: deepcopy(v) for k, v in day_candidate().items()
                 if k in {'summary', 'assumptions', 'source_ids', 'questions'}}
    candidate['cycle'] = [step()]
    result = TrainingPlannerAgent(Settings(live_enabled=True), ScriptProvider([final(candidate)])
        ).plan_cycle_live(task(profile_data, 'cycle'))
    assert result.status == 'draft_ready' and result.candidate['cycle'][0]['exercises'][0]['sets'] == 4


def test_live_cycle_uses_only_known_facts_when_profile_is_blank():
    from fitness.config import Settings
    from fitness.training_agent import TrainingPlannerAgent
    candidate = {'summary': '按保守起始条件安排徒手训练。',
        'assumptions': ['未提供单次时长，按30分钟上限估算', '运动限制状态未知，采用低强度安排'],
        'source_ids': [], 'questions': [], 'cycle': [step(2, 'push_up')]}
    result = TrainingPlannerAgent(Settings(live_enabled=True), ScriptProvider([final(candidate)])).plan_cycle_live(
        task({}, 'cycle'))
    assert result.status == 'draft_ready'


def test_training_system_prompt_guides_plan_quality_and_missing_inputs(profile_data):
    from fitness.config import Settings
    from fitness.training_agent import TrainingPlannerAgent
    provider = ScriptProvider([final(day_candidate())])
    result = TrainingPlannerAgent(Settings(live_enabled=True), provider).plan_day_live(task(profile_data))
    assert result.status == 'draft_ready'
    role = provider.messages[0][0]['content']
    assert '依从性（用户确实做得下去）' in role
    assert '从对应范围低端起步' in role
    assert '每个动作都应有清楚的进步方向' in role
    assert '不因字段为空而要求用户补齐或返回 needs_input' in role
    assert '不得声称未持久化规则会自动执行' in role
    assert '每块主要肌群尽量在一个循环中安排至少两次有效刺激' in role
    assert '初学者复合动作以5至8次为主，辅助动作以8至12次为主' in role
    assert '大多数训练组保留1至3次余力' in role
    assert '停滞但睡眠、营养、疼痛和疲劳均无明显问题时，可谨慎增加相关动作/肌群约20%每周训练组' in role
    assert '持续疲劳、关节不适、睡眠变差或恢复受损时减少约20%训练量' in role
    assert '深蹲和硬拉的训练量组保留2至3次余力' in role
    assert '优先调用get_training_history' in role
    assert 'exercise_results' in role and 'target_rpe' in role
    assert '只有数据不足时留空' in role
    assert '不得把计划重量当成实际完成重量' in role


def test_conflicting_equipment_is_returned_to_model_for_repair(profile_data):
    from fitness.config import Settings
    from fitness.training_agent import TrainingPlannerAgent
    invalid = day_candidate()
    invalid['training'] = step(exercise_id='squat')
    provider = ScriptProvider([final(invalid), final(day_candidate())])
    result = TrainingPlannerAgent(Settings(live_enabled=True), provider).plan_day_live(task(profile_data))
    assert result.status == 'draft_ready' and result.trace['calls'] == 2
    assert 'equipment' in provider.messages[1][-1]['content']


def test_disabled_live_never_calls_provider(profile_data):
    from fitness.config import Settings
    from fitness.training_agent import TrainingPlannerAgent
    provider = ScriptProvider([])
    result = TrainingPlannerAgent(Settings(live_enabled=False), provider).plan_day_live(task(profile_data))
    assert result.status == 'failed' and result.reason_code == 'live_disabled'
    assert provider.messages == []


def test_urgent_symptoms_skip_provider_and_return_explicit_safety_pause(profile_data):
    from fitness.config import Settings
    from fitness.training_agent import TrainingPlannerAgent
    provider = ScriptProvider([])
    result = TrainingPlannerAgent(Settings(live_enabled=True), provider).plan_day_live(
        task(profile_data, conditions='今天胸痛', state={'urgent_stop': True}))
    assert result.status == 'draft_ready'
    assert result.candidate['action'] == 'pause'
    assert result.trace['status'] == 'skipped_safety'
    assert provider.messages == []


def test_explicit_skip_cannot_be_turned_into_training(profile_data):
    from fitness.training_validation import validate_training_candidate
    issues = validate_training_candidate(day_candidate(), task(profile_data,
        conditions='今天明确跳过', state={'current_intent': '今天明确跳过'}), {})
    assert any(i.code == 'explicit_skip' for i in issues)


def test_legacy_completed_training_defaults_do_not_look_like_a_mutation(profile_data):
    from fitness.training_validation import validate_training_candidate
    completed = step()
    candidate = day_candidate()
    issues = validate_training_candidate(candidate, task(profile_data,
        completed_training=completed), {})
    assert not any(issue.code == 'completed_immutable' for issue in issues)


def test_live_plan_day_legacy_entry_does_not_silently_fallback(profile_data):
    from fitness.agent_contracts import PlanningRunError
    from fitness.config import Settings
    from fitness.models import Profile
    from fitness.training_agent import TrainingPlannerAgent
    provider = ScriptProvider([final(status='needs_input', questions=['今天可以训练多久？'])])
    agent = TrainingPlannerAgent(Settings(live_enabled=True), provider)
    profile = Profile.model_validate(profile_data)
    with pytest.raises(PlanningRunError):
        agent.plan_day(profile, [step()], 0, date(2026,10,20), [], [], mode='live')
