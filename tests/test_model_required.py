from datetime import date

import pytest
from fastapi.testclient import TestClient
from test_api import main
from test_orchestration import setup_history

from fitness.config import Settings
from fitness.models import Profile
from fitness.orchestration import FitnessAgent
from fitness.provider import ProviderError
from fitness.storage import Store


@pytest.fixture
def unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'settings', Settings(api_key=''))
    monkeypatch.setattr(main, 'store', Store(tmp_path / 'model-required.db'))
    return TestClient(main.app)


def test_state_requires_user_model_configuration(unconfigured):
    state = unconfigured.get('/api/state').json()
    assert state['mode'] == 'live'
    assert state['available_modes'] == []
    assert state['model_configured'] is False


@pytest.mark.parametrize('path,body', [
    ('/api/plans', {'start_date': '2026-10-21'}),
    ('/api/long-term-plans', {}),
    ('/api/long-term-plans/stream', {}),
    ('/api/daily-plans', {'date': '2026-10-21'}),
    ('/api/daily-plans/stream', {'date': '2026-10-21'}),
    ('/api/nutrition/plan', {'date': '2026-10-21'}),
    ('/api/feedback/parse', {'date': '2026-10-21', 'text': '睡了7小时'}),
    ('/api/feedback/missing/advice', {}),
    ('/api/feedback/missing/understand', {}),
    ('/api/feedback/missing/retry-plan', {}),
    ('/api/feedback/missing/training-adjustment/confirm', {'proposal': {}, 'confirmed': True}),
])
def test_model_actions_require_key_before_work(unconfigured, path, body):
    response = unconfigured.post(path, json=body)
    assert response.status_code == 503, response.text
    assert response.json()['detail']['code'] == 'model_not_configured'
    assert 'API' in response.json()['detail']['message']
    assert main.store.plans() == []
    assert main.store.feedback() == []


@pytest.mark.parametrize('path,body', [
    ('/api/plans', {'start_date': '2026-10-21'}),
    ('/api/long-term-plans', {}),
    ('/api/daily-plans', {'date': '2026-10-21'}),
    ('/api/nutrition/plan', {'date': '2026-10-21'}),
    ('/api/feedback/parse', {'date': '2026-10-21', 'text': '睡了7小时'}),
    ('/api/feedback/missing/advice', {}),
])
def test_demo_requests_are_rejected(unconfigured, path, body):
    response = unconfigured.post(path, json={**body, 'mode': 'demo'})
    assert response.status_code == 422, response.text


def test_local_food_memory_preview_requires_model(unconfigured):
    response = unconfigured.post('/api/nutrition/memory/preview', json={'text': '不吃香菜'})
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'model_not_configured'


def test_local_training_adjustment_preview_requires_model(unconfigured):
    response = unconfigured.get('/api/feedback/missing/training-adjustment')
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'model_not_configured'


def test_raw_feedback_is_preserved_without_model(unconfigured):
    response = unconfigured.post('/api/feedback/record', json={
        'date': '2026-10-21', 'text': '今天很累，先记下来', 'request_key': 'without-model',
    })
    assert response.status_code == 200, response.text
    assert response.json()['raw_text'] == '今天很累，先记下来'
    assert response.json()['coaching']['status'] == 'saved'


def test_key_enables_model_without_legacy_switch(monkeypatch):
    monkeypatch.setattr('fitness.config.load_dotenv', lambda *a, **k: None)
    monkeypatch.setenv('FITNESS_LIVE_ENABLED', 'false')
    monkeypatch.setenv('FITNESS_API_KEY', 'synthetic-test-key')
    assert Settings.from_env().live_enabled is True


def test_upstream_failure_returns_error_without_local_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'settings', Settings(api_key='synthetic-test-key'))
    monkeypatch.setattr(main, 'store', Store(tmp_path / 'provider-error.db'))

    class FailedProvider:
        def create_long_term(self, *args, **kwargs):
            raise ProviderError('timeout')

    monkeypatch.setattr(main, 'planning_service', FailedProvider)
    response = TestClient(main.app).post('/api/long-term-plans', json={'start_date': '2026-10-21'})
    assert response.status_code == 504
    assert response.json()['detail']['code'] == 'timeout'
    assert main.store.plans() == []


@pytest.mark.parametrize('operation', ['plan', 'parse', 'advise'])
def test_model_failure_does_not_return_local_generation(tmp_path, profile_data, operation):
    store, row, knowledge = setup_history(tmp_path, profile_data)

    class UnavailableProvider:
        def complete(self, *args, **kwargs):
            raise ProviderError('timeout')

    agent = FitnessAgent(store, knowledge, Settings(api_key='synthetic-test-key', live_enabled=True),
                         provider=UnavailableProvider())
    with pytest.raises(ProviderError, match='timeout'):
        if operation == 'plan':
            agent.plan(Profile.model_validate(profile_data), date(2026, 10, 21), 'live')
        elif operation == 'parse':
            agent.parse('睡了7小时', date(2026, 10, 21), 'live')
        else:
            agent.advise(row, 'live')
