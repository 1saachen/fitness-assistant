import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from planning_provider import PlanningScriptProvider as ScriptProvider
from test_agent_runtime import final
from test_api import main
from test_training_live_service import cycle_candidate

from fitness.config import Settings
from fitness.models import FeedbackData, Profile
from fitness.orchestration import FitnessAgent
from fitness.provider import ProviderError
from fitness.storage import Store


@pytest.fixture
def live_api(tmp_path, monkeypatch, profile_data):
    store = Store(tmp_path / 'api-live.db')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    settings = Settings(live_enabled=True, api_key='synthetic-test-key')
    provider = ScriptProvider([])
    agent = FitnessAgent(store, None, settings, provider=provider)
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'settings', settings)
    monkeypatch.setattr(main, 'planning_service', lambda: agent)
    monkeypatch.setattr(main, '_history_end_date', lambda value: value or date(2026, 10, 20))
    return TestClient(main.app), agent, provider, store


def test_needs_input_returns_questions_and_followup_token(live_api):
    client, _agent, provider, _store = live_api
    provider.replies = iter([final(status='needs_input', questions=['每天能训练多久？'])])
    response = client.post('/api/long-term-plans', json={'mode': 'live'})
    assert response.status_code == 422
    detail = response.json()['detail']
    assert detail['status'] == 'needs_input'
    assert detail['questions'] == ['每天能训练多久？']
    assert detail['start_date'] == '2026-10-20'
    assert len(detail['snapshot_token']) == 64 and detail['run_id']
    provider.replies = iter([final(cycle_candidate())])
    response = client.post('/api/long-term-plans', json={'mode': 'live', 'conditions': '每天20分钟',
        'expected_snapshot_token': detail['snapshot_token']})
    assert response.status_code == 200
    assert response.json()['data']['cycle'][0]['exercises'][0]['sets'] == 4


def test_long_term_plan_defaults_to_today_and_agent_selected_cycle(live_api):
    client, _agent, provider, _store = live_api
    provider.replies = iter([final(cycle_candidate())])
    response = client.post('/api/long-term-plans', json={'mode': 'live'})
    assert response.status_code == 200
    assert response.json()['start_date'] == '2026-10-20'
    task = json.loads(provider.messages[0][-1]['content'])
    assert task.get('cycle_labels') is None


def test_standalone_nutrition_live_calls_model_and_reports_source(live_api, monkeypatch):
    client, _, provider, _ = live_api
    monkeypatch.setattr('fitness.nutrition_live.OpenAICompatibleProvider', lambda _: provider)
    response = client.post('/api/nutrition/plan', json={'date': '2026-10-20', 'mode': 'live',
        'conditions': '今天在食堂吃'})
    assert response.status_code == 200
    assert response.json()['source'] == 'model'
    assert response.json()['data']['approach'] == '模拟模型餐单'
    assert len(provider.nutrition_messages) == 1


def test_standalone_live_nutrition_failure_is_not_a_local_template(live_api, monkeypatch):
    from test_agent_runtime import ScriptProvider as RawProvider
    client, _, _, _ = live_api
    provider = RawProvider([ProviderError('timeout')])
    monkeypatch.setattr('fitness.nutrition_live.OpenAICompatibleProvider', lambda _: provider)
    response = client.post('/api/nutrition/plan', json={'date': '2026-10-20', 'mode': 'live'})
    assert response.status_code == 504
    assert response.json()['detail']['code'] == 'timeout'
    assert 'data' not in response.json()


@pytest.mark.parametrize('reason,code', [('timeout', 504), ('network_error', 502)])
def test_provider_failure_is_explicit_without_saved_plan(live_api, reason, code):
    client, _, provider, _ = live_api
    provider.replies = iter([ProviderError(reason)])
    response = client.post('/api/long-term-plans', json={'start_date': '2026-10-20', 'mode': 'live'})
    assert response.status_code == code
    assert response.json()['detail']['status'] == 'failed'
    assert reason in response.json()['detail']['message']
    assert response.json()['detail']['retryable'] is True
    assert client.get('/api/planning/state').json()['long_term_plans'] == []


def test_invalid_output_reports_stage_and_actionable_validation_without_candidate(live_api, monkeypatch):
    from fitness.agent_contracts import PlanningRunError, RunResult
    client, agent, _, _ = live_api
    def fail(*args, **kwargs):
        raise PlanningRunError(RunResult('failed-run', 'failed', reason_code='output_invalid', trace={
            'stage': 'supplements', 'validation': [[{'path': 'summary', 'code': 'unsafe_content',
                'message': '请删除数字用量。'}]], 'private_candidate': 'never expose'}), 'snapshot')
    monkeypatch.setattr(agent, 'create_long_term', fail)
    detail = client.post('/api/long-term-plans', json={'mode': 'live'}).json()['detail']
    assert detail['stage'] == 'supplements'
    assert '补剂建议' in detail['message'] and '请删除数字用量' in detail['message']
    assert detail['validation_errors'][0]['path'] == 'summary'
    assert 'never expose' not in json.dumps(detail)


def test_feedback_confirmation_does_not_replan_today(live_api):
    client, agent, provider, store = live_api
    long = agent.create_long_term(date(2026, 10, 20))
    agent.confirm_long_term(long['id'])
    agent.generate_day(date(2026, 10, 20))
    with store.connection() as db:
        db.execute("UPDATE daily_plans SET trace=json_set(trace, '$.mode', 'live')")
    provider.replies = iter([ProviderError('timeout')])
    before = len(provider.messages)
    data = FeedbackData(date=date(2026, 10, 20), sleep_hours=6).model_dump(mode='json')
    feedback = store.create_feedback('睡了6小时', data, 'demo', {})
    response = client.post(f"/api/feedback/{feedback['id']}/confirm",
        json={'data': data, 'expected_revision': 0})
    assert response.status_code == 200
    assert response.json()['status'] == 'confirmed'
    assert response.json()['planning_update']['status'] == 'none'
    assert len(provider.messages) == before
    assert store.get_feedback(feedback['id'])['status'] == 'confirmed'
