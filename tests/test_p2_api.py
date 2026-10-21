import json
from datetime import date

import pytest

from tests.test_api import configure_client, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    return configure_client(tmp_path, monkeypatch)


def test_import_preview_confirmation_and_duplicate_roundtrip(client):
    content = json.dumps([{'date':'2026-10-10','sleep_hours':7.5,'training_completed':False}])
    payload = {'content':content,'format':'json'}
    preview = client.post('/api/import/feedback/preview', json=payload)
    assert preview.status_code == 200
    assert client.get('/api/state').json()['feedback'] == []
    denied = client.post('/api/import/feedback/confirm', json={**payload, 'batch_id':preview.json()['batch_id']})
    assert denied.status_code == 400
    first = client.post('/api/import/feedback/confirm', json={**payload,
        'batch_id':preview.json()['batch_id'], 'confirmed':True})
    assert first.status_code == 200 and first.json()['imported'] == 1
    again = client.post('/api/import/feedback/confirm', json={**payload,
        'batch_id':preview.json()['batch_id'], 'confirmed':True})
    assert again.json() == first.json()
    assert len(client.get('/api/state').json()['feedback']) == 1


def test_training_preview_confirm_stale_and_original_snapshot(client, profile_data, monkeypatch):
    today = date(2026, 10, 11)
    monkeypatch.setattr(main, '_history_end_date', lambda value: value or today)
    client.put('/api/profile', json={'profile':profile_data,'expected_version':0})
    plan = client.post('/api/plans', json={'start_date':today.isoformat(),'mode':'live'}).json()
    client.post(f"/api/plans/{plan['id']}/confirm")
    feedback = client.post('/api/feedback/parse', json={'text':'今天很累，没练',
        'date':today.isoformat(),'mode':'live'}).json()
    fid = feedback['id']
    client.post(f'/api/feedback/{fid}/confirm', json={'data':feedback['data'],'expected_revision':0})
    preview = client.get(f'/api/feedback/{fid}/training-adjustment').json()
    assert preview['changes']
    assert client.get(f"/api/plans/{plan['id']}/changes").json() == []
    confirmed = client.post(f'/api/feedback/{fid}/training-adjustment/confirm',
                            json={'proposal':preview, 'confirmed':True})
    assert confirmed.status_code == 200, confirmed.text
    assert len(client.get(f"/api/plans/{plan['id']}/changes").json()) == 1
    assert client.get('/api/state').json()['plans'][0]['data'] == plan['data']
    stale = client.post(f'/api/feedback/{fid}/training-adjustment/confirm',
                       json={'proposal':preview, 'confirmed':True})
    assert stale.status_code == 409


def test_abnormal_symptom_blocks_adjustment_and_preserves_warning(client, profile_data, monkeypatch):
    monkeypatch.setattr(main, '_history_end_date', lambda value: value or date(2026, 10, 11))
    client.put('/api/profile', json={'profile':profile_data,'expected_version':0})
    plan = client.post('/api/plans', json={'start_date':'2026-10-11','mode':'live'}).json()
    client.post(f"/api/plans/{plan['id']}/confirm")
    feedback = client.post('/api/feedback/parse', json={'text':'胸痛，很累，没练',
        'date':'2026-10-11','mode':'live'}).json()
    fid = feedback['id']
    client.post(f'/api/feedback/{fid}/confirm', json={'data':feedback['data'],'expected_revision':0})
    response = client.post(f'/api/feedback/{fid}/advice', json={'mode':'live'})
    assert response.status_code == 200
    assert '立即停止' in response.json()['advice']['suggestions'][0]
    assert client.get(f'/api/feedback/{fid}/training-adjustment').json()['changes'] == []


def test_nutrition_endpoint_returns_targets_and_daily_conditions(client, profile_data):
    client.put('/api/profile', json={'profile': profile_data, 'expected_version': 0})
    result = client.post('/api/nutrition/plan', json={
        'date': '2026-10-11', 'meal': '午餐', 'conditions': '只能点外卖，预算18元',
        'available_foods': '黄焖鸡、米饭、青菜', 'desired_foods': '黄焖鸡', 'mode': 'live',
    })
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload['data']['daily_targets']['protein_g'] > 0
    assert len(payload['data']['meal_options']) == 1
    assert '黄焖鸡' in str(payload['data']['meal_options'][0]['suggestions'])
    assert any('18' in item for item in payload['data']['meal_options'][0]['suggestions'])


def test_nutrition_memory_preview_does_not_change_profile(client, profile_data):
    client.put('/api/profile', json={'profile': profile_data, 'expected_version': 0})
    result = client.post('/api/nutrition/memory/preview', json={'text': '以后都不要安排香菜，我对花生过敏'})
    assert result.status_code == 200
    assert all(item['requires_confirmation'] for item in result.json())
    assert client.get('/api/state').json()['profile_version'] == 1


def test_nutrition_plan_can_consume_confirmed_feedback_conditions(client, profile_data):
    client.put('/api/profile', json={'profile': profile_data, 'expected_version': 0})
    feedback = client.post('/api/feedback/parse', json={
        'text': '今天午餐只能点外卖，能买到米饭和青菜，想吃鸡肉',
        'date': '2026-10-11', 'mode': 'live',
    }).json()
    feedback['data'].update(meal_to_plan='午餐', meal_conditions='只能点外卖，预算18元',
                             available_foods='米饭、青菜、鸡肉', desired_foods='鸡肉')
    client.post(f"/api/feedback/{feedback['id']}/confirm",
                json={'data': feedback['data'], 'expected_revision': 0})
    response = client.post('/api/nutrition/plan', json={
        'date': '2026-10-11', 'feedback_id': feedback['id'], 'mode': 'live',
    })
    assert response.status_code == 200
    assert '鸡肉' in str(response.json()['data']['meal_options'][0]['suggestions'])


def test_new_current_plan_between_preview_and_write_rejects_adjustment(client, profile_data, monkeypatch):
    from fitness.agent import DemoAgent
    from fitness.models import Profile

    today = date(2026, 10, 11)
    monkeypatch.setattr(main, '_history_end_date', lambda value: value or today)
    client.put('/api/profile', json={'profile':profile_data, 'expected_version':0})
    plan = client.post('/api/plans', json={'start_date':today.isoformat(), 'mode':'live'}).json()
    client.post(f"/api/plans/{plan['id']}/confirm")
    feedback = client.post('/api/feedback/parse', json={'text':'很累，没练',
        'date':today.isoformat(), 'mode':'live'}).json()
    fid = feedback['id']
    client.post(f'/api/feedback/{fid}/confirm', json={'data':feedback['data'], 'expected_revision':0})
    proposal = client.get(f'/api/feedback/{fid}/training-adjustment').json()
    record_change = main.store.record_plan_change
    def replace_current_plan(**kwargs):
        data = DemoAgent().generate_plan(Profile.model_validate(profile_data), today).model_dump(mode='json')
        replacement = main.store.create_plan(data, 1, today.isoformat(), 'demo', {})
        main.store.confirm_plan(replacement['id'])
        return record_change(**kwargs)
    monkeypatch.setattr(main.store, 'record_plan_change', replace_current_plan)
    response = client.post(f'/api/feedback/{fid}/training-adjustment/confirm',
                           json={'proposal':proposal, 'confirmed':True})
    assert response.status_code == 409
    assert main.store.plan_changes() == []
    assert main.store.plans()[-1]['data'] == plan['data']
