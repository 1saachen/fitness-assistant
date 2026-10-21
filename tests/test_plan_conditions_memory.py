import json
from datetime import date, timedelta

import pytest
from test_agent_runtime import final
from test_feedback_coach import candidate
from test_memory_lifecycle import cited

from fitness.config import Settings
from fitness.daily_planning import DailyPlanningService
from fitness.feedback_coach import FeedbackCoach
from fitness.feedback_memory import FeedbackMemory
from fitness.models import Profile
from fitness.provider import ProviderError
from fitness.storage import Conflict, Store

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
    def __init__(self, store, *, fail=False):
        self.store, self.fail, self.calls = store, fail, []

    def complete(self, messages, tools=None, **kwargs):
        task = json.loads(messages[1]['content'])
        self.calls.append(task)
        if self.fail:
            raise ProviderError('timeout')
        row = self.store.get_feedback(task['feedback']['id'])
        # Even a planner action returned by the model must not escape this entry point.
        return final(candidate(row, memory_updates=[
            cited(row, key='diet:context', retention='long_term')],
            decision={'action': 'propose_long_term', 'reason': '调整预算', 'conditions': row['raw_text']}))


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
