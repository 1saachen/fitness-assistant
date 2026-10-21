import pytest
from test_agent_runtime import ScriptProvider, final
from test_feedback_coach import DAY, candidate

from fitness.config import Settings
from fitness.feedback_coach import FeedbackCoach
from fitness.storage import Conflict, Store


def setup(tmp_path):
    store = Store(tmp_path / 'confirm.db')
    provider = ScriptProvider([])
    service = FeedbackCoach(store, Settings(), provider=provider, today=lambda: DAY)
    return service, provider, store


def test_bad_optional_weight_does_not_drop_valid_completion_or_sleep(tmp_path):
    service, provider, _ = setup(tmp_path)
    row = service.record('今天训练全部做完了，睡了8小时', DAY)
    response = candidate(row, facts={'data': {'date': str(DAY), 'training_completed': True,
        'sleep_hours': 8, 'weight_kg': 120}, 'evidence': {'training_completed': '训练全部做完了',
        'sleep_hours': '睡了8小时', 'weight_kg': '睡了8小时'}})
    provider.replies = iter([final(response)])
    saved = service.analyze(row['id'])
    assert saved['data']['training_completed'] is True
    assert saved['data']['sleep_hours'] == 8
    assert saved['data']['weight_kg'] is None
    assert saved['coaching']['fact_status']['ignored_fields'] == ['weight_kg']


def test_malformed_optional_field_does_not_drop_other_facts(tmp_path):
    service, provider, _ = setup(tmp_path)
    row = service.record('睡了8小时', DAY)
    response = candidate(row, facts={'data': {'date': str(DAY), 'sleep_hours': 8, 'weight_kg': 'wrong'},
                                     'evidence': {'sleep_hours': '睡了8小时'}})
    provider.replies = iter([final(response)])
    saved = service.analyze(row['id'])
    assert saved['data']['sleep_hours'] == 8
    assert saved['data']['weight_kg'] is None


def test_explicit_fact_confirmation_is_versioned_and_blocks_old_plan(tmp_path):
    service, provider, store = setup(tmp_path)
    row = service.record('卧推做了三组', DAY)
    provider.replies = iter([final(candidate(row))])
    saved = service.analyze(row['id'])
    assert saved['coaching']['fact_status']['training_completed']['status'] == 'needs_confirmation'
    confirmed = service.memory.confirm_facts(row['id'], saved['revision'], {'training_completed': True})
    assert confirmed['data']['training_completed'] is True
    assert confirmed['raw_text'] == row['raw_text']
    assert confirmed['coaching']['status'] == 'stale'
    assert len(store.feedback_revisions(row['id'])) == 2
    with pytest.raises(Conflict):
        service.memory.confirm_facts(row['id'], saved['revision'], {'training_completed': False})
    with pytest.raises(Conflict):
        service.retry_plan(row['id'])


def test_confirmation_api_accepts_false_and_rejects_empty_or_unrelated_fields(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from test_api import main
    service, _, store = setup(tmp_path)
    monkeypatch.setattr(main, 'store', store)
    client = TestClient(main.app)
    row = service.record('今天练了一部分', DAY)
    path = f"/api/feedback/{row['id']}/facts/confirm"
    response = client.post(path, json={'expected_revision': row['revision'], 'training_completed': False})
    assert response.status_code == 200
    assert response.json()['data']['training_completed'] is False
    assert client.post(path, json={'expected_revision': row['revision'], 'training_completed': True}).status_code == 409
    assert client.post(path, json={'expected_revision': 2}).status_code == 422
    assert client.post(path, json={'expected_revision': 2, 'weight_kg': 100}).status_code == 422


def test_preference_api_cannot_release_a_restriction(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from test_api import main
    from test_memory_lifecycle import cited
    service, provider, store = setup(tmp_path)
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, '_history_end_date', lambda _:DAY)
    row = service.record('花生过敏', DAY)
    provider.replies = iter([final(candidate(row,memory_updates=[cited(row,key='allergy',category='restriction')]))])
    service.analyze(row['id'])
    client = TestClient(main.app)
    assert client.post('/api/personal-memory/allergy/confirm',json={'expected_version':1,'action':'retire'}).status_code == 409


@pytest.mark.parametrize('text,quote', [('我没有完成训练','完成训练'),('明天打算完成训练','完成训练')])
def test_trimmed_evidence_cannot_remove_negation_or_intention(tmp_path,text,quote):
    service, _, _=setup(tmp_path)
    row=service.record(text,DAY)
    result=candidate(row,facts={'data':{'date':str(DAY),'training_completed':True},
                               'evidence':{'training_completed':quote}})
    assert any(i.path=='facts.training_completed' for i in service.validate(
        result,row,{(row['id'],row['revision']):row}))


def test_action_quote_cannot_remove_tomorrow_context(tmp_path):
    service, _, _=setup(tmp_path)
    row=service.record('明天卧推45kg，8/8/7次',DAY)
    result=candidate(row,facts={'data':{'date':str(DAY),'exercise_results':[{
        'exercise_id':'bench_press','sets':[{'reps':8,'weight_kg':45},{'reps':8,'weight_kg':45},
                                            {'reps':7,'weight_kg':45}]}]},
        'evidence':{'exercise_results':'卧推45kg，8/8/7次'}})
    assert any(i.path=='facts.exercise_results' for i in service.validate(
        result,row,{(row['id'],row['revision']):row}))
