import json
from datetime import date
from types import SimpleNamespace

import pytest

from fitness.agent import DemoAgent
from fitness.config import ROOT, Settings
from fitness.knowledge_context import KnowledgeContextService
from fitness.models import FeedbackData, Profile
from fitness.orchestration import FitnessAgent
from fitness.storage import Store
from fitness.tools import LocalTools

DAY = date(2026, 10, 20)


@pytest.fixture
def context(tmp_path, profile_data):
    from fitness.daily_planning import DailyPlanningService
    store = Store(tmp_path / 'daily-agent.db')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    knowledge = KnowledgeContextService(ROOT / 'data/knowledge', ROOT / 'data/knowledge/baseline-strategies.json')
    planner = DailyPlanningService(store, Settings(), knowledge)
    draft = planner.create_long_term(DAY)
    long = planner.confirm_long_term(draft['id'])
    day = planner.generate_day(DAY)
    data = FeedbackData(date=DAY, fatigue='很累', training_completed=False).model_dump(mode='json')
    feedback = store.create_feedback('今天很累，没练', data, 'demo', {})
    feedback = store.confirm_feedback(feedback['id'], data, 0)
    return store, knowledge, planner, long, day, feedback


def test_new_plan_context_takes_precedence_over_legacy_week(context):
    store, knowledge, _planner, long, day, row = context
    weekly = store.create_plan(DemoAgent().generate_plan(Profile.model_validate(store.profile()['data']), DAY)
                              .model_dump(mode='json'), 1, DAY.isoformat(), 'demo', {})
    store.confirm_plan(weekly['id'])
    result = LocalTools(store, knowledge, row, today=DAY).call('get_current_plan', {})
    assert result.status == 'ok'
    assert result.payload['plan']['kind'] == 'long_term_daily'
    assert result.payload['plan']['long_term']['id'] == long['id']
    assert result.payload['plan']['daily']['id'] == day['id']


def test_long_term_context_exists_without_saved_daily_plan(context):
    store, knowledge, _planner, long, _day, row = context
    row = {**row, 'data': {**row['data'], 'date': '2026-10-21'}}
    result = LocalTools(store, knowledge, row).call('get_current_plan', {})
    assert result.status == 'ok'
    assert result.payload['plan']['long_term']['id'] == long['id']
    assert result.payload['plan']['daily'] is None


def test_training_preview_reads_daily_decision_without_writing(context):
    store, knowledge, planner, long, day, row = context
    before = planner.repo.days()
    result = LocalTools(store, knowledge, row, today=DAY).call('adjust_today_training', {})
    assert result.payload['changes'] == []
    assert result.payload['long_term_id'] == long['id']
    assert result.payload['daily_plan_id'] == day['id']
    assert result.payload['training'] == day['data']['training']
    assert result.payload['decision'] == day['data']['decision']
    assert result.payload['needs_refresh'] is True
    assert planner.repo.days() == before
    assert store.plan_changes() == []


def test_daily_context_rejects_plan_from_previous_long_term_version(context):
    store, knowledge, planner, _long, _day, row = context
    draft = planner.create_long_term(DAY, ['腿', '休息'])
    new_long = planner.confirm_long_term(draft['id'])
    result = LocalTools(store, knowledge, row, today=DAY).current_plan()
    assert result['long_term']['id'] == new_long['id']
    assert result['daily'] is None


def test_advise_supplies_daily_context_to_model_without_mutation(context):
    store, knowledge, planner, long, day, row = context
    before = planner.repo.days()

    class Provider:
        def complete(self, messages, tools=None):
            context = json.loads(messages[1]['content'])['current_plan']
            assert context['long_term']['id'] == long['id']
            assert context['daily']['id'] == day['id']
            return SimpleNamespace(content='{"summary":"结合当天安排，先恢复。"}', tool_calls=[], usage={})

    run = FitnessAgent(store, knowledge, Settings(live_enabled=True), provider=Provider()).advise(row, 'live', today=DAY)
    assert run.trace['provider']['status'] == 'ok'
    assert next(t for t in run.trace['tool_calls'] if t['name'] == 'get_current_plan')['status'] == 'ok'
    assert run.trace['training_adjustment_preview']['daily_plan_id'] == day['id']
    assert planner.repo.days() == before


def test_main_agent_coordinates_plan_lifecycle(tmp_path, profile_data):
    store = Store(tmp_path / 'lifecycle.db')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    knowledge = KnowledgeContextService(ROOT / 'data/knowledge', ROOT / 'data/knowledge/baseline-strategies.json')
    agent = FitnessAgent(store, knowledge, Settings())
    draft = agent.create_long_term(DAY, ['推', '休息'])
    long = agent.confirm_long_term(draft['id'])
    day = agent.generate_day(DAY)
    marked = agent.complete_meal(day['id'], '早餐', day['revision'])
    assert marked['long_term_id'] == long['id']
    assert '早餐' in marked['data']['completed_meals']
