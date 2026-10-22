import json
from datetime import date, timedelta

import pytest
from test_agent_runtime import final
from test_feedback_coach import candidate
from test_memory_lifecycle import cited

from fitness.config import Settings
from fitness.daily_planning import DailyPlanningService
from fitness.feedback_coach import COACH_GUIDE, FeedbackCoach
from fitness.feedback_memory import FeedbackMemory
from fitness.models import Profile
from fitness.provider import ProviderError
from fitness.storage import Conflict, Store, encode

DAY = date(2026, 10, 21)


def test_model_can_retain_enduring_facts_beyond_temporary_window(tmp_path):
    store = Store(tmp_path / 'memory.db')
    row = FeedbackMemory(store).record('主要吃食堂，伙食预算50元/天。今天很累。', DAY)
    from test_agent_runtime import ScriptProvider
    provider = ScriptProvider([final(candidate(row, memory_updates=[
        cited(row, key='budget', retention='long_term', text='伙食预算50元/天', evidence=[{
            'feedback_id': row['id'], 'revision': 1, 'quote': '伙食预算50元/天'}]),
        cited(row, key='fatigue', text='今天很累', evidence=[{
            'feedback_id': row['id'], 'revision': 1, 'quote': '今天很累'}]),
    ]))] * 3)
    coach = FeedbackCoach(store, Settings(), provider=provider, today=lambda: DAY)
    assert coach.analyze(row['id'])['coaching']['status'] == 'ready'
    later = FeedbackMemory(Store(store.path)).context(DAY + timedelta(days=90))
    assert [entry['key'] for entry in later['entries']] == ['budget']
    assert later['entries'][0]['expires_on'] is None
    assert later['expired_keys'] == ['fatigue']


class MemoryProvider:
    def __init__(self, store, *, fail=False, profile_updates=None):
        self.store, self.fail, self.calls = store, fail, []
        self.profile_updates = profile_updates or []

    def complete(self, messages, tools=None, **kwargs):
        if '你是补剂规划 Agent' in messages[0]['content']:
            from planning_provider import supplement_reply
            return supplement_reply(messages)
        task = json.loads(messages[1]['content'])
        self.calls.append(task)
        if self.fail:
            raise ProviderError('timeout')
        row = self.store.get_feedback(task['feedback']['id'])
        # Even a planner action returned by the model must not escape this entry point.
        result = candidate(row, memory_updates=[
            cited(row, key='diet:context', retention='long_term')],
            decision={'action': 'propose_long_term', 'reason': '调整预算', 'conditions': row['raw_text']})
        result['profile_updates'] = self.profile_updates
        return final(result)


def service_with_memory(tmp_path, monkeypatch, profile_data, *, fail_memory=False):
    store = Store(tmp_path / 'plans.db')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    provider = MemoryProvider(store, fail=fail_memory)
    service = DailyPlanningService(store, Settings(), provider=provider)
    contexts = []
    # Exercise persistence and context building; avoid a paid planning model.
    def training(task, **kwargs):
        contexts.append(task)
        raise ProviderError('planning_stopped')
    monkeypatch.setattr(service.training, 'plan_cycle_live', training)
    return service, provider, store, contexts


def test_long_answer_persists_before_planning_and_retry_does_not_duplicate(tmp_path, monkeypatch, profile_data):
    service, provider, store, contexts = service_with_memory(tmp_path, monkeypatch, profile_data)
    kwargs = {'mode': 'live', 'conditions': '主要食堂，预算每天50元',
              'answered_questions': ['通常在哪吃饭？预算多少？']}
    for _ in range(2):
        with pytest.raises(ProviderError, match='planning_stopped'):
            service.create_long_term(DAY, **kwargs)
    assert len(provider.calls) == 1
    assert len(store.feedback()) == 1
    assert provider.calls[0]['answered_questions'] == kwargs['answered_questions']
    assert len(contexts) == 2
    assert contexts[0].personal_memory['entries'][0]['text'] == kwargs['conditions']
    assert service.repo.long_terms() == []
    assert store.profile()['version'] == 1


def test_long_term_answers_update_profile_before_generating_plan(tmp_path, monkeypatch, profile_data):
    from fitness.agent_contracts import RunResult

    service, provider, store, _ = service_with_memory(tmp_path, monkeypatch, profile_data)
    saved = store.profile()
    profile = saved['data']
    profile['nutrition']['primary_meal_source'] = None
    profile['nutrition']['food_budget']['amount'] = None
    profile['nutrition']['food_budget']['period'] = None
    profile['training']['usual_training_time'] = None
    store.save_profile(profile, saved['version'])
    text = '主要在食堂吃饭，预算每天50元，通常18点训练'
    provider.profile_updates = [
        {'path': 'nutrition.primary_meal_source', 'value': '食堂', 'quote': '食堂'},
        {'path': 'nutrition.food_budget.amount', 'value': 50, 'quote': '50元'},
        {'path': 'nutrition.food_budget.period', 'value': 'day', 'quote': '每天'},
        {'path': 'training.usual_training_time', 'value': '18点', 'quote': '18点'},
    ]
    monkeypatch.setattr(service.training, 'plan_cycle_live', lambda task, **kwargs: RunResult(
        'cycle', 'draft_ready', candidate={'cycle': service.training.build_cycle(task.profile),
        'summary': '测试循环', 'assumptions': [], 'questions': []}))
    monkeypatch.setattr(service.nutrition, 'plan_live', lambda profile, **kwargs: RunResult(
        'nutrition', 'draft_ready', candidate=service.nutrition.plan(profile).model_dump(mode='json')))

    plan = service.create_long_term(DAY, mode='live', conditions=text, answered_questions=[
        '你主要吃食堂、自炊还是外卖？每天或每周伙食预算多少？', '你通常几点训练？'])

    updated = store.profile()
    assert updated['version'] == saved['version'] + 2
    assert updated['data']['nutrition']['primary_meal_source'] == '食堂'
    assert updated['data']['nutrition']['food_budget']['amount'] == 50
    assert updated['data']['nutrition']['food_budget']['period'] == 'day'
    assert updated['data']['training']['usual_training_time'] == '18点'
    assert plan['profile_version'] == updated['version']
    assert plan['trace']['conditions_memory']['profile_updated_fields'] == [
        '主要饮食来源', '饮食预算', '通常训练时间']
    assert service.confirm_long_term(plan['id'])['status'] == 'confirmed'


def test_conflicting_profile_answer_is_not_silently_applied(tmp_path, monkeypatch, profile_data):
    from fitness.agent_contracts import RunResult

    service, provider, store, _ = service_with_memory(tmp_path, monkeypatch, profile_data)
    provider.profile_updates = [{'path': 'nutrition.primary_meal_source', 'value': '外卖', 'quote': '外卖'}]
    monkeypatch.setattr(service.training, 'plan_cycle_live', lambda task, **kwargs: RunResult(
        'cycle', 'draft_ready', candidate={'cycle': service.training.build_cycle(task.profile),
        'summary': '测试循环', 'assumptions': [], 'questions': []}))
    monkeypatch.setattr(service.nutrition, 'plan_live', lambda profile, **kwargs: RunResult(
        'nutrition', 'draft_ready', candidate=service.nutrition.plan(profile).model_dump(mode='json')))

    plan = service.create_long_term(DAY, mode='live', conditions='我改成外卖了',
                                    answered_questions=['你主要吃食堂、自炊还是外卖？'])

    assert store.profile()['version'] == 1
    assert store.profile()['data']['nutrition']['primary_meal_source'] == 'school_cafeteria'
    assert plan['trace']['conditions_memory']['profile_conflict_fields'] == ['主要饮食来源']
    assert '暂未覆盖' in plan['trace']['conditions_memory']['message']


def test_failed_memory_retains_original_and_can_retry(tmp_path, monkeypatch, profile_data):
    service, provider, store, contexts = service_with_memory(tmp_path, monkeypatch, profile_data, fail_memory=True)
    kwargs = {'mode': 'live', 'conditions': '花生过敏'}
    with pytest.raises(ProviderError, match='planning_stopped'):
        service.create_long_term(DAY, **kwargs)
    row = store.feedback()[0]
    assert row['raw_text'] == kwargs['conditions']
    assert FeedbackMemory(store).view(row)['coaching']['status'] == 'failed'
    provider.fail = False
    with pytest.raises(ProviderError, match='planning_stopped'):
        service.create_long_term(DAY, **kwargs)
    assert len(store.feedback()) == 1
    assert contexts[-1].personal_memory['entries']


def test_stale_snapshot_rejected_before_recording_answer(tmp_path, monkeypatch, profile_data):
    service, provider, store, _ = service_with_memory(tmp_path, monkeypatch, profile_data)
    with pytest.raises(Conflict):
        service.create_long_term(DAY, mode='live', conditions='主要食堂', expected_snapshot_token='0' * 64)
    assert store.feedback() == []
    assert provider.calls == []


def test_daily_training_and_nutrition_receive_long_answer_after_restart(tmp_path, monkeypatch, profile_data):
    from fitness.agent_contracts import RunResult
    service, provider, store, _ = service_with_memory(tmp_path, monkeypatch, profile_data)
    received = []

    def cycle(task, **kwargs):
        return RunResult('cycle', 'draft_ready', candidate={'cycle': service.training.build_cycle(task.profile),
            'summary': '测试循环', 'assumptions': [], 'questions': []})

    def nutrition(profile, **context):
        received.append(context['personal_memory'])
        return RunResult('nutrition', 'draft_ready', candidate=service.nutrition.plan(profile).model_dump(mode='json'))

    monkeypatch.setattr(service.training, 'plan_cycle_live', cycle)
    monkeypatch.setattr(service.nutrition, 'plan_live', nutrition)
    text = '主要食堂，伙食每天50元，通常18点训练'
    long = service.create_long_term(DAY, mode='live', conditions=text)
    assert long['data']['conditions'] == text
    assert long['trace']['conditions_memory']['status'] == 'updated'
    service.confirm_long_term(long['id'])
    reopened = DailyPlanningService(Store(store.path), Settings(), provider=provider)

    def daily(task, **kwargs):
        received.append(task.personal_memory)
        return RunResult('day', 'draft_ready', candidate=reopened.training.plan_day(
            task.profile, task.cycle, task.cycle_index, task.date, task.history, []))

    monkeypatch.setattr(reopened.training, 'plan_day_live', daily)
    monkeypatch.setattr(reopened.nutrition, 'plan_live', nutrition)
    result = reopened.generate_day(DAY + timedelta(days=90), mode='live')
    assert result['long_term_id'] == long['id']
    assert len(received) == 3
    assert all(memory['entries'][0]['text'] == text for memory in received)
    assert len(provider.calls) == 1, 'automatic daily generation must not run memory extraction again'


def test_model_may_choose_not_to_store_any_memory(tmp_path, monkeypatch, profile_data):
    service, provider, store, _ = service_with_memory(tmp_path, monkeypatch, profile_data)
    def nothing(messages, tools=None, **kwargs):
        return final({'reply': '收到', 'memory_updates': [], 'decision': {'action': 'keep', 'reason': '无需记忆'}})
    monkeypatch.setattr(provider, 'complete', nothing)
    with pytest.raises(ProviderError, match='planning_stopped'):
        service.create_long_term(DAY, mode='live', conditions='谢谢')
    assert FeedbackMemory(store).current()['version'] == 0
    row = FeedbackMemory(store).view(store.feedback()[0])
    assert row['coaching']['memory_status'] == 'unchanged'


def test_long_term_fact_is_protected_during_compaction(tmp_path):
    from test_agent_runtime import ScriptProvider
    store = Store(tmp_path / 'compact.db')
    row = FeedbackMemory(store).record('主要食堂，伙食预算50元/天', DAY)
    entry = cited(row, key='budget', retention='long_term')
    provider = ScriptProvider([final({'entries': []})] * 3)
    coach = FeedbackCoach(store, Settings(), provider=provider, today=lambda: DAY, memory_budget=1)
    compacted, status, _ = coach.compact([entry])
    assert compacted == [entry]
    assert status == 'failed'


def test_daily_answer_is_remembered_and_memory_failure_is_visible(tmp_path, monkeypatch, profile_data):
    from fitness.agent_contracts import PlanningRunError, RunResult
    service, provider, store, _ = service_with_memory(tmp_path, monkeypatch, profile_data, fail_memory=True)
    long = service.create_long_term(DAY)
    service.confirm_long_term(long['id'])
    monkeypatch.setattr(service.training, 'plan_day_live', lambda *args, **kwargs:
        RunResult('day', 'needs_input', questions=['请说明今天时间']))
    with pytest.raises(PlanningRunError) as caught:
        service.generate_day(DAY, mode='live', conditions='通常18点训练')
    assert caught.value.conditions_memory['status'] == 'failed'
    assert caught.value.conditions_memory['feedback_id'] == store.feedback()[0]['id']
    provider.fail = False
    with pytest.raises(PlanningRunError):
        service.generate_day(DAY, mode='live', conditions='通常18点训练')
    assert FeedbackMemory(store).context(DAY)['entries']
    assert len(store.feedback()) == 1


def test_question_text_is_not_accepted_as_user_memory_evidence(tmp_path):
    store = Store(tmp_path / 'quotes.db')
    row = FeedbackMemory(store).record('没有', DAY, source_context={
        'kind': 'long_term_conditions', 'answered_questions': ['有无食物过敏？']})
    coach = FeedbackCoach(store, Settings(), today=lambda: DAY)
    invalid = cited(row, key='allergy', category='restriction', evidence=[{
        'feedback_id': row['id'], 'revision': 1, 'quote': '食物过敏'}])
    issues = coach.validate(candidate(row, memory_updates=[invalid]), row, {(row['id'], 1): row})
    assert any(issue.path == 'memory_updates.evidence' for issue in issues)


def test_enduring_preference_question_can_classify_a_short_answer(tmp_path):
    store = Store(tmp_path / 'short-answer.db')
    row = FeedbackMemory(store).record('食堂', DAY, source_context={
        'kind': 'long_term_conditions', 'answered_questions': ['你主要吃食堂、自炊还是外卖？']})
    coach = FeedbackCoach(store, Settings(), today=lambda: DAY)
    preference = cited(row, key='meal:venue', category='preference', retention='long_term',
                       text='平时主要在食堂就餐',
                       evidence=[{'feedback_id': row['id'], 'revision': 1, 'quote': '食堂'}])
    issues = coach.validate(candidate(row, memory_updates=[preference]), row, {(row['id'], 1): row})
    assert not any(issue.path in {'memory_updates.category', 'memory_updates.retention'} for issue in issues)


def test_profile_update_must_be_supported_by_the_current_answer(tmp_path):
    store = Store(tmp_path / 'profile-evidence.db')
    row = FeedbackMemory(store).record('食堂', DAY, source_context={
        'kind': 'long_term_conditions', 'answered_questions': ['你主要吃食堂、自炊还是外卖？']})
    coach = FeedbackCoach(store, Settings(), today=lambda: DAY)
    result = candidate(row)
    result['profile_updates'] = [{'path': 'nutrition.primary_meal_source', 'value': '外卖',
                                  'quote': '外卖'}]
    issues = coach.validate(result, row, {(row['id'], 1): row})
    assert any(issue.path == 'profile_updates.evidence' for issue in issues)


def test_daily_answer_to_enduring_question_can_update_profile(tmp_path):
    store = Store(tmp_path / 'daily-profile-evidence.db')
    row = FeedbackMemory(store).record('平时18点训练', DAY, source_context={
        'kind': 'daily_conditions', 'answered_questions': ['你平时通常几点训练？']})
    result = candidate(row)
    result['profile_updates'] = [{'path': 'training.usual_training_time', 'value': '18点',
                                  'quote': '18点'}]
    issues = FeedbackCoach(store, Settings(), today=lambda: DAY).validate(result, row, {(row['id'], 1): row})
    assert not any(issue.path.startswith('profile_updates') for issue in issues)


def test_retry_understanding_also_updates_profile_once(tmp_path):
    from test_agent_runtime import ScriptProvider

    store = Store(tmp_path / 'retry-profile.db')
    store.save_profile(Profile().model_dump(mode='json'), 0)
    memory = FeedbackMemory(store)
    row = memory.record('通常18点训练', DAY, source_context={'kind': 'long_term_conditions'})
    result = candidate(row)
    result['profile_updates'] = [{'path': 'training.usual_training_time', 'value': '18点',
                                  'quote': '18点'}]
    coach = FeedbackCoach(store, Settings(), provider=ScriptProvider([final(result)]), today=lambda: DAY)
    saved = coach.analyze(row['id'])
    assert store.profile()['data']['training']['usual_training_time'] == '18点'
    assert saved['coaching']['profile_sync']['updated_fields'] == ['通常训练时间']
    coach.analyze(row['id'])
    assert store.profile()['version'] == 2


def test_legacy_plan_answer_can_be_rechecked_for_profile_sync_idempotently(tmp_path):
    from test_agent_runtime import ScriptProvider

    store = Store(tmp_path / 'legacy-profile-sync.db')
    profile = Profile().model_dump(mode='json')
    profile['training']['usual_training_time'] = None
    store.save_profile(profile, 0)
    memory = FeedbackMemory(store)
    row = memory.record('通常18点训练', DAY, source_context={
        'kind': 'long_term_conditions', 'answered_questions': ['你通常几点训练？']})
    with store.connection() as db:
        db.execute('UPDATE feedback_coaching SET status=?, data=? WHERE feedback_id=?',
            ('ready', encode({'understanding': candidate(row), 'feedback_revision': 1,
                              'memory_status': 'unchanged', 'profile_sync': {
                                  'before_version': 1, 'version': 1,
                                  'updated_fields': [], 'conflict_fields': []},
                              'planning_update': {'status': 'none'}}), row['id']))
    assert memory.view(store.get_feedback(row['id']))['coaching']['profile_sync_pending'] is True
    result = candidate(row)
    result['profile_updates'] = [{'path': 'training.usual_training_time', 'value': '18点',
                                  'quote': '18点'}]
    provider = ScriptProvider([final(result)] * 2)
    coach = FeedbackCoach(store, Settings(), provider=provider, today=lambda: DAY)

    saved = coach.sync_profile(row['id'])
    version_after_sync = store.profile()['version']
    repeated = coach.sync_profile(row['id'])

    assert saved['coaching']['profile_sync']['checked'] is True
    assert saved['coaching']['profile_sync']['updated_fields'] == ['通常训练时间']
    assert repeated['coaching']['profile_sync']['checked'] is True
    assert repeated['coaching']['profile_sync']['updated_fields'] == ['通常训练时间']
    assert repeated['coaching']['profile_sync_pending'] is False
    assert store.profile()['version'] == version_after_sync
    assert len(provider.messages) == 1
    assert store.profile()['data']['training']['usual_training_time'] == '18点'


def test_coach_guide_allows_scoped_profile_updates_without_overwriting_existing_values():
    assert 'profile_updates' in COACH_GUIDE
    assert '获准时只用有原文依据的profile_updates填补空字段' in COACH_GUIDE


@pytest.mark.parametrize(('text', 'path', 'value', 'quote'), [
    ('今天18点训练', 'training.usual_training_time', '18点', '18点'),
    ('今天只吃食堂', 'nutrition.primary_meal_source', '食堂', '食堂'),
    ('今天预算50元', 'nutrition.food_budget.amount', 50, '50元'),
    ('不知道有没有过敏', 'nutrition.food_allergy_status', 'none_known_self_reported', '没有'),
])
def test_temporary_or_uncertain_answers_do_not_become_profile_facts(tmp_path, text, path, value, quote):
    store = Store(tmp_path / 'temporary-profile.db')
    row = FeedbackMemory(store).record(text, DAY, source_context={
        'kind': 'long_term_conditions', 'answered_questions': ['你平时几点训练，主要在哪吃饭？']})
    result = candidate(row)
    result['profile_updates'] = [{'path': path, 'value': value, 'quote': quote}]
    issues = FeedbackCoach(store, Settings(), today=lambda: DAY).validate(result, row, {(row['id'], 1): row})
    assert any(issue.path.startswith('profile_updates') for issue in issues)


def test_profile_change_during_understanding_keeps_user_edit_and_original(tmp_path):
    store = Store(tmp_path / 'concurrent-profile.db')
    store.save_profile(Profile().model_dump(mode='json'), 0)
    row = FeedbackMemory(store).record('通常18点训练', DAY, source_context={'kind': 'long_term_conditions'})

    class EditingProvider:
        def complete(self, messages, tools=None, **kwargs):
            profile = store.profile()
            profile['data']['training']['usual_training_time'] = '20点'
            store.save_profile(profile['data'], profile['version'])
            result = candidate(row)
            result['profile_updates'] = [{'path': 'training.usual_training_time', 'value': '18点', 'quote': '18点'}]
            return final(result)

    saved = FeedbackCoach(store, Settings(), provider=EditingProvider(), today=lambda: DAY).analyze(row['id'])
    assert saved['coaching']['error'] == 'input_changed'
    assert store.profile()['data']['training']['usual_training_time'] == '20点'
    assert store.get_feedback(row['id'])['raw_text'] == '通常18点训练'


def test_conflicting_budget_period_does_not_apply_only_the_amount(tmp_path):
    from test_agent_runtime import ScriptProvider

    store = Store(tmp_path / 'budget-conflict.db')
    profile = Profile().model_dump(mode='json')
    profile['nutrition']['food_budget']['period'] = 'week'
    store.save_profile(profile, 0)
    row = FeedbackMemory(store).record('伙食预算每天50元', DAY, source_context={'kind': 'long_term_conditions'})
    result = candidate(row)
    result['profile_updates'] = [
        {'path': 'nutrition.food_budget.amount', 'value': 50, 'quote': '50元'},
        {'path': 'nutrition.food_budget.period', 'value': 'day', 'quote': '每天'},
    ]
    saved = FeedbackCoach(store, Settings(), provider=ScriptProvider([final(result)]), today=lambda: DAY).analyze(row['id'])
    assert store.profile()['data']['nutrition']['food_budget']['amount'] is None
    assert store.profile()['version'] == 1
    assert saved['coaching']['profile_sync']['conflict_fields'] == ['饮食预算']


def test_negative_allergy_status_does_not_contradict_existing_details(tmp_path):
    from test_agent_runtime import ScriptProvider

    store = Store(tmp_path / 'allergy-conflict.db')
    profile = Profile().model_dump(mode='json')
    profile['nutrition']['food_allergy_details'] = '花生过敏'
    store.save_profile(profile, 0)
    row = FeedbackMemory(store).record('没有食物过敏', DAY, source_context={'kind': 'long_term_conditions'})
    result = candidate(row)
    result['profile_updates'] = [{'path': 'nutrition.food_allergy_status',
        'value': 'none_known_self_reported', 'quote': '没有食物过敏'}]
    saved = FeedbackCoach(store, Settings(), provider=ScriptProvider([final(result)]),
                          today=lambda: DAY).analyze(row['id'])
    assert store.profile()['data']['nutrition']['food_allergy_status'] == 'unknown'
    assert store.profile()['data']['nutrition']['food_allergy_details'] == '花生过敏'
    assert saved['coaching']['profile_sync']['conflict_fields'] == ['食物过敏情况']


@pytest.mark.parametrize('category', ['fact', 'preference'])
def test_model_cannot_make_a_one_time_answer_permanent_from_the_question(tmp_path, category):
    store = Store(tmp_path / f'temporary-{category}.db')
    row = FeedbackMemory(store).record('今天很累', DAY, source_context={
        'kind': 'long_term_conditions', 'answered_questions': ['你平时训练时间是什么时候？']})
    coach = FeedbackCoach(store, Settings(), today=lambda: DAY)
    temporary = cited(row, key='fatigue', category=category, retention='long_term',
                      text='长期偏好或事实', evidence=[{
                          'feedback_id': row['id'], 'revision': 1, 'quote': '今天很累'}])
    issues = coach.validate(candidate(row, memory_updates=[temporary]), row, {(row['id'], 1): row})
    assert any(issue.path == 'memory_updates.retention' for issue in issues)


def test_today_scope_cannot_be_overridden_by_mainly_in_a_long_term_question(tmp_path):
    store = Store(tmp_path / 'temporary-mainly.db')
    text = '今天主要在食堂吃饭'
    row = FeedbackMemory(store).record(text, DAY, source_context={
        'kind': 'long_term_conditions', 'answered_questions': ['你主要吃食堂、自炊还是外卖？']})
    coach = FeedbackCoach(store, Settings(), today=lambda: DAY)
    temporary = cited(row, key='meal:venue', category='fact', retention='long_term',
                      text='主要在食堂吃饭', evidence=[{
                          'feedback_id': row['id'], 'revision': 1, 'quote': text}])
    issues = coach.validate(candidate(row, memory_updates=[temporary]), row, {(row['id'], 1): row})
    assert any(issue.path == 'memory_updates.retention' for issue in issues)
