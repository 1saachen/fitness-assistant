from datetime import date, timedelta

import pytest

from fitness.config import Settings
from fitness.models import Profile
from fitness.storage import Conflict, Store


def configure_model_api(monkeypatch, store):
    from planning_provider import ModelledTestProvider
    from test_api import main

    from fitness.orchestration import FitnessAgent

    settings = Settings(api_key='synthetic-test-key')
    provider = ModelledTestProvider()
    agent = FitnessAgent(store, main.knowledge_context_service, settings, provider=provider)
    monkeypatch.setattr(main, 'settings', settings)
    monkeypatch.setattr(main, 'planning_service', lambda: agent)
    monkeypatch.setattr('fitness.provider.OpenAICompatibleProvider', lambda *args, **kwargs: provider)
    monkeypatch.setattr('fitness.nutrition_live.OpenAICompatibleProvider', lambda *args, **kwargs: provider)


@pytest.fixture
def planner(tmp_path, profile_data):
    from fitness.daily_planning import DailyPlanningService
    store = Store(tmp_path / 'plans.db')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    return DailyPlanningService(store, Settings()), store


def setup_long(service, start='2026-10-20'):
    draft = service.create_long_term(date.fromisoformat(start), ['推', '拉', '腿', '休息'])
    return service.confirm_long_term(draft['id'])


def test_empty_profile_can_save_and_create_plans_without_invented_measurements(tmp_path):
    from fitness.daily_planning import DailyPlanningService
    store = Store(tmp_path / 'empty-profile.db')
    store.save_profile(Profile.model_validate({}).model_dump(mode='json'), 0)
    service = DailyPlanningService(store, Settings())

    long = service.create_long_term(date(2026, 10, 20))
    assert long['data']['goals']['primary'] is None
    assert long['data']['nutrition']['daily_targets'] is None
    service.confirm_long_term(long['id'])
    daily = service.generate_day(date(2026, 10, 20))
    assert daily['data']['water']['base_ml'] is None


def feedback(store, day, **facts):
    from fitness.models import FeedbackData
    data = FeedbackData(date=day, **facts).model_dump(mode='json')
    row = store.create_feedback(facts.get('training_summary') or '用户确认的反馈', data, 'demo', {})
    return store.confirm_feedback(row['id'], data, 0)


def test_nutrition_review_requires_weight_and_diet_adherence_samples():
    from fitness.daily_planning import nutrition_review
    end = date(2026, 10, 20)
    sparse = [
        {'date': '2026-10-19', 'status': 'confirmed', 'data': {'weight_kg': 75, 'diet_followed_plan': True}},
        {'date': '2026-10-20', 'status': 'confirmed', 'data': {'weight_kg': 74.8, 'diet_followed_plan': True}},
    ]
    result = nutrition_review(sparse, end, 'fat_loss')
    assert result['status'] == 'insufficient_data'
    assert result['suggested_adjustment_kcal'] is None


def test_nutrition_review_recommends_small_cut_only_after_stable_adherence():
    from fitness.daily_planning import nutrition_review
    end = date(2026, 10, 20)
    rows = []
    for day, weight in [('2026-10-07', 75), ('2026-10-10', 75.1), ('2026-10-13', 75),
                        ('2026-10-15', 75.05), ('2026-10-18', 75), ('2026-10-20', 75.02)]:
        rows.append({'date': day, 'status': 'confirmed', 'data': {
            'weight_kg': weight, 'diet_followed_plan': True}})
    result = nutrition_review(rows, end, 'fat_loss')
    assert result['status'] == 'monitor'
    assert result['suggested_adjustment_kcal'] is None
    assert any('前后两周体重均值' in item for item in result['evidence'])
    assert '核对餐食份量' in result['recommendation']


def test_nutrition_review_never_adjusts_calories_for_low_adherence_or_single_day_spike():
    from fitness.daily_planning import nutrition_review
    rows = [
        {'date': '2026-10-07', 'status': 'confirmed', 'data': {'weight_kg': 75, 'diet_followed_plan': False}},
        {'date': '2026-10-10', 'status': 'confirmed', 'data': {'weight_kg': 75, 'diet_followed_plan': False}},
        {'date': '2026-10-13', 'status': 'confirmed', 'data': {'weight_kg': 75, 'diet_followed_plan': False}},
        {'date': '2026-10-15', 'status': 'confirmed', 'data': {'weight_kg': 75, 'diet_followed_plan': False}},
        {'date': '2026-10-18', 'status': 'confirmed', 'data': {'weight_kg': 75, 'diet_followed_plan': False}},
        {'date': '2026-10-20', 'status': 'confirmed', 'data': {'weight_kg': 80, 'diet_followed_plan': False}},
    ]
    result = nutrition_review(rows, date(2026, 10, 20), 'fat_loss')
    assert result['status'] == 'insufficient_data'
    assert result['suggested_adjustment_kcal'] is None


def test_nutrition_review_gain_direction_accounts_for_fatigue_and_goal():
    from fitness.daily_planning import nutrition_review
    rows = []
    for day, weight in [('2026-10-07', 75), ('2026-10-10', 75.1), ('2026-10-13', 75),
                        ('2026-10-15', 75.05), ('2026-10-18', 75), ('2026-10-20', 75.02)]:
        rows.append({'date': day, 'status': 'confirmed', 'data': {
            'weight_kg': weight, 'diet_followed_plan': True, 'fatigue': '明显疲劳'}})
    gain = nutrition_review(rows, date(2026, 10, 20), 'muscle_gain')
    maintenance = nutrition_review(rows, date(2026, 10, 20), 'general_health')
    assert gain['suggested_adjustment_kcal'] == 100
    assert maintenance['suggested_adjustment_kcal'] is None


def test_nutrition_review_fast_loss_with_repeated_fatigue_suggests_more_energy():
    from fitness.daily_planning import nutrition_review
    rows = []
    for day, weight in [('2026-10-07', 76), ('2026-10-10', 75.8), ('2026-10-13', 75.5),
                        ('2026-10-15', 75.2), ('2026-10-18', 74.9), ('2026-10-20', 74.5)]:
        rows.append({'date': day, 'status': 'confirmed', 'data': {
            'weight_kg': weight, 'diet_followed_plan': True, 'fatigue': '持续疲劳'}})
    result = nutrition_review(rows, date(2026, 10, 20), 'fat_loss')
    assert result['suggested_adjustment_kcal'] == 100
    assert '疲劳' in result['recommendation']


def test_nutrition_review_fast_gain_suggests_small_energy_reduction():
    from fitness.daily_planning import nutrition_review
    rows = []
    for day, weight in [('2026-10-07', 75), ('2026-10-10', 75.1), ('2026-10-13', 75.2),
                        ('2026-10-15', 75.4), ('2026-10-18', 75.6), ('2026-10-20', 75.8)]:
        rows.append({'date': day, 'status': 'confirmed', 'data': {
            'weight_kg': weight, 'diet_followed_plan': True}})
    result = nutrition_review(rows, date(2026, 10, 20), 'muscle_gain')
    assert result['suggested_adjustment_kcal'] == -100
    assert '盈余' in result['recommendation']


def test_daily_plan_surfaces_review_evidence_without_changing_confirmed_targets(planner):
    service, store = planner
    long = setup_long(service)
    original_targets = long['data']['nutrition']['daily_targets']
    for day, weight in [('2026-10-07', 75), ('2026-10-10', 75.1), ('2026-10-13', 75),
                        ('2026-10-15', 75.05), ('2026-10-18', 75), ('2026-10-20', 75.02)]:
        feedback(store, day, weight_kg=weight, diet_followed_plan=True)
    daily = service.generate_day(date(2026, 10, 20))
    assert any('前后两周体重均值' in item for item in daily['data']['review_suggestions'])
    assert any('核对餐食份量' in item for item in daily['data']['review_suggestions'])
    assert daily['trace']['nutrition_review']['suggested_adjustment_kcal'] is None
    assert service.repo.long_terms()[0]['data']['nutrition']['daily_targets'] == original_targets


def test_long_term_is_versioned_confirmed_and_not_limited_to_seven_days(planner):
    service, _store = planner
    long = setup_long(service)
    assert long['status'] == 'confirmed'
    assert len(long['data']['cycle']) == 4
    assert long['data']['nutrition']['daily_targets']['calories_kcal'] > 0
    later = service.generate_day(date(2026, 11, 3))
    assert later['long_term_id'] == long['id']
    assert later['data']['training']['label'] == '推'
    assert later['data']['water']['base_ml'] > 0
    assert {'早餐', '午餐', '晚餐'} <= {m['meal'] for m in later['data']['nutrition']['meal_options']}


def test_completion_advances_once_and_missing_feedback_defers(planner):
    service, store = planner
    setup_long(service)
    first = service.generate_day(date(2026, 10, 20))
    assert service.generate_day(date(2026, 10, 20))['id'] == first['id']
    assert service.generate_day(date(2026, 10, 21))['data']['training']['label'] == '推'
    feedback(store, '2026-10-20', training_completed=True)
    second = service.generate_day(date(2026, 10, 21))
    assert second['data']['training']['label'] == '拉'
    assert service.generate_day(date(2026, 10, 21))['id'] == second['id']


def test_feedback_drives_today_and_preserves_eaten_meal(planner):
    service, store = planner
    setup_long(service)
    first = service.generate_day(date(2026, 10, 20))
    eaten = service.complete_meal(first['id'], '早餐', first['revision'])
    breakfast = eaten['data']['nutrition']['meal_options'][0]
    feedback(store, '2026-10-20', training_summary='今天很累不想练，明天再练', fatigue='很累')
    updated = service.generate_day(date(2026, 10, 20), conditions='晚餐只能点外卖')
    assert updated['data']['decision']['action'] == 'defer'
    assert updated['data']['training']['kind'] == 'rest'
    assert updated['data']['nutrition']['meal_options'][0] == breakfast
    assert '早餐' in updated['data']['completed_meals']
    assert service.generate_day(date(2026, 10, 21))['data']['cycle_index'] == 0


def test_confirm_rejects_profile_change(planner):
    service, store = planner
    draft = service.create_long_term(date(2026, 10, 20), ['推', '休息'])
    store.save_profile(store.profile()['data'], 1)
    with pytest.raises(Conflict):
        service.confirm_long_term(draft['id'])


def test_three_on_one_off_follows_completed_sessions_across_week_boundary(planner):
    service, store = planner
    setup_long(service)
    labels = []
    for offset in range(9):
        day = date(2026, 10, 20) + timedelta(days=offset)
        row = service.generate_day(day)
        labels.append(row['data']['training']['label'])
        if row['data']['training']['kind'] == 'training':
            feedback(store, day.isoformat(), training_completed=True)
    assert labels == ['推', '拉', '腿', '休息', '推', '拉', '腿', '休息', '推']


def test_daily_revision_rejects_stale_meal_completion(planner):
    service, _ = planner
    setup_long(service)
    first = service.generate_day(date(2026, 10, 20))
    service.generate_day(date(2026, 10, 20), conditions='今天没时间训练')
    with pytest.raises(Conflict):
        service.complete_meal(first['id'], '早餐', first['revision'])


def test_new_api_full_loop_and_feedback_refresh(tmp_path, monkeypatch, profile_data):
    from fastapi.testclient import TestClient
    from test_api import main
    store = Store(tmp_path / 'api.db')
    monkeypatch.setattr(main, 'store', store)
    configure_model_api(monkeypatch, store)
    monkeypatch.setattr(main, '_history_end_date', lambda value: value or date(2026, 10, 20))
    client = TestClient(main.app)
    assert client.put('/api/profile', json={'profile': profile_data, 'expected_version': 0}).status_code == 200
    draft = client.post('/api/long-term-plans', json={'start_date': '2026-10-20'} )
    assert draft.status_code == 200
    assert client.post(f"/api/long-term-plans/{draft.json()['id']}/confirm").status_code == 200
    daily = client.post('/api/daily-plans', json={'date':'2026-10-20'}).json()
    assert daily['data']['training']['label'] == '推'
    parsed = client.post('/api/feedback/parse', json={'date':'2026-10-20', 'text':'今天很累不想练', 'mode':'live'}).json()
    assert client.post(f"/api/feedback/{parsed['id']}/confirm", json={
        'data': parsed['data'], 'expected_revision': parsed['revision']}).status_code == 200
    state = client.get('/api/planning/state?date=2026-10-20').json()
    assert state['daily_plans'][0]['id'] == daily['id']
    updated = client.post('/api/daily-plans', json={'date':'2026-10-20'}).json()
    assert updated['data']['decision']['action'] == 'defer'
    assert len(state['long_term_plans']) == 1


def test_planning_state_keeps_complete_history_and_real_today(tmp_path, monkeypatch, profile_data):
    from fastapi.testclient import TestClient
    from test_api import main
    store = Store(tmp_path / 'state.db')
    monkeypatch.setattr(main, 'store', store)
    configure_model_api(monkeypatch, store)
    monkeypatch.setattr(main, '_history_end_date', lambda value: date(2026, 10, 20) if value is None else value)
    client = TestClient(main.app)
    assert client.put('/api/profile', json={'profile': profile_data, 'expected_version': 0}).status_code == 200
    draft = client.post('/api/long-term-plans', json={'start_date': '2026-10-20'}).json()
    client.post(f"/api/long-term-plans/{draft['id']}/confirm")
    client.post('/api/daily-plans', json={'date': '2026-10-20'})
    client.post('/api/daily-plans', json={'date': '2026-10-21'})
    state = client.get('/api/planning/state?date=2026-10-21').json()
    assert state['today'] == '2026-10-20'
    assert {row['date'] for row in state['daily_plans']} == {'2026-10-20', '2026-10-21'}


def test_restriction_release_api_records_a_revision(tmp_path, monkeypatch, profile_data):
    from fastapi.testclient import TestClient
    from test_api import main
    store = Store(tmp_path / 'release.db')
    monkeypatch.setattr(main, 'store', store)
    configure_model_api(monkeypatch, store)
    client = TestClient(main.app)
    assert client.put('/api/profile', json={'profile': profile_data, 'expected_version': 0}).status_code == 200
    draft = client.post('/api/long-term-plans', json={'start_date': '2026-10-20'}).json()
    client.post(f"/api/long-term-plans/{draft['id']}/confirm")
    daily = client.post('/api/daily-plans', json={
        'date': '2026-10-20', 'conditions': '肩膀受伤了'}).json()
    response = client.post(f"/api/daily-plans/{daily['id']}/restrictions/release", json={
        'area': 'shoulder', 'expected_revision': daily['revision'],
        'confirmation_text': '已确认恢复情况和活动范围'})
    assert response.status_code == 200
    assert response.json()['revision'] == daily['revision'] + 1
    assert client.post(f"/api/daily-plans/{daily['id']}/restrictions/release", json={
        'area': 'shoulder', 'expected_revision': daily['revision'],
        'confirmation_text': '已确认恢复情况和活动范围'}).status_code == 409


def test_backup_restore_includes_new_plan_history(planner, tmp_path):
    from fitness.data_transfer import create_backup, restore_backup
    service, store = planner
    setup_long(service)
    daily = service.generate_day(date(2026, 10, 20))
    backup = tmp_path / 'backup.db'
    result = create_backup(store, backup)
    target = tmp_path / 'restored.db'
    restore_backup(backup, target, result['fingerprint'], confirmed=True)
    from fitness.plan_store import PlanRepository
    assert PlanRepository(Store(target)).days()[0] == daily


def test_separate_food_feedback_does_not_erase_training_completion(planner):
    service, store = planner
    setup_long(service)
    service.generate_day(date(2026, 10, 20))
    feedback(store, '2026-10-20', training_completed=True, sleep_hours=8)
    feedback(store, '2026-10-20', food_summary='米饭和鸡肉')
    assert service.generate_day(date(2026, 10, 21))['data']['cycle_index'] == 1
    feedback(store, '2026-10-20', training_completed=False)
    assert service.generate_day(date(2026, 10, 21))['data']['cycle_index'] == 0


def test_old_daily_cannot_be_reassigned_when_marking_a_meal(planner):
    service, _ = planner
    setup_long(service)
    old = service.generate_day(date(2026, 10, 20))
    new = service.create_long_term(date(2026, 10, 20), ['腿', '休息'])
    service.confirm_long_term(new['id'])
    with pytest.raises(Conflict):
        service.complete_meal(old['id'], '早餐', old['revision'])


def test_restriction_release_is_explicit_audited_and_new_injury_reactivates(planner):
    service, _ = planner
    setup_long(service)
    hurt = service.generate_day(date(2026, 10, 20), '肩膀受伤了')
    assert hurt['data']['decision']['action'] == 'pause'
    released = service.release_restriction(hurt['id'], 'shoulder', hurt['revision'], '已确认恢复情况和活动范围，解除本次限制')
    assert released['revision'] > hurt['revision']
    healthy = service.generate_day(date(2026, 10, 20))
    assert healthy['data']['decision']['action'] == 'train'
    assert healthy['trace']['restriction_releases']
    assert service.generate_day(date(2026, 10, 21))['data']['decision']['action'] == 'train'
    again = service.generate_day(date(2026, 10, 21), '今天肩膀又疼了')
    assert again['data']['decision']['action'] == 'pause'


def test_release_blocks_stale_revision_and_empty_confirmation(planner):
    service, _ = planner
    setup_long(service)
    hurt = service.generate_day(date(2026, 10, 20), '肩膀受伤了')
    with pytest.raises(ValueError):
        service.release_restriction(hurt['id'], 'shoulder', hurt['revision'], '')
    updated = service.complete_meal(hurt['id'], '早餐', hurt['revision'])
    with pytest.raises(Conflict):
        service.release_restriction(hurt['id'], 'shoulder', hurt['revision'], '已确认恢复情况及活动范围')
    assert updated['revision'] > hurt['revision']


def test_explicit_urgent_release_clears_only_the_reported_condition(planner):
    service, _ = planner
    setup_long(service)
    urgent = service.generate_day(date(2026, 10, 20), '今天胸痛和呼吸困难')
    assert urgent['data']['decision']['action'] == 'pause'
    released = service.release_restriction(urgent['id'], 'urgent_symptoms', urgent['revision'],
                                           '已接受专业评估并确认可以恢复日常活动')
    reevaluated = service.generate_day(date(2026, 10, 20))
    assert reevaluated['data']['decision']['action'] == 'train'
    assert any(not r['active'] for r in reevaluated['data']['decision']['restrictions'])
    assert released['trace']['restriction_releases']
    assert service.generate_day(date(2026, 10, 21), '今天再次出现胸痛')['data']['decision']['action'] == 'pause'


def test_daily_condition_injury_cannot_be_cleared_by_blank_edit(planner):
    service, _ = planner
    setup_long(service)
    service.generate_day(date(2026, 10, 20), '肩膀受伤了')
    updated = service.generate_day(date(2026, 10, 20), '')
    assert any(r['area'] == 'shoulder' and r['active'] for r in updated['data']['decision']['restrictions'])
    tomorrow = service.generate_day(date(2026, 10, 21))
    assert any(r['area'] == 'shoulder' and r['active'] for r in tomorrow['data']['decision']['restrictions'])


def test_rest_day_nutrition_retains_targets_and_completed_meals(planner):
    service, _ = planner
    long = setup_long(service)
    row = service.generate_day(date(2026, 10, 20))
    eaten = service.complete_meal(row['id'], '早餐', row['revision'])
    rest = service.generate_day(date(2026, 10, 20), '今天很累不想练')
    nutrition = rest['data']['nutrition']
    assert nutrition['daily_targets'] == long['data']['nutrition']['daily_targets']
    assert sum(m['estimated_kcal'] for m in nutrition['meal_options']) == nutrition['daily_targets']['calories_kcal']
    assert '休息' in nutrition['approach']
    assert '训练后' not in {m['meal'] for m in nutrition['meal_options']}
    assert nutrition['meal_options'][0] == eaten['data']['nutrition']['meal_options'][0]


def test_completed_training_survives_earlier_same_day_deferral(planner):
    service, store = planner
    setup_long(service)
    original = service.generate_day(date(2026, 10, 20))
    service.generate_day(date(2026, 10, 20), '今天很累不想练')
    feedback(store, '2026-10-20', training_completed=True)
    completed = service.generate_day(date(2026, 10, 20))
    assert completed['data']['training'] == original['data']['training']
    assert service.generate_day(date(2026, 10, 21))['data']['cycle_index'] == 1


def test_advice_write_does_not_reorder_completion_or_reactivate_injury(planner):
    service, store = planner
    setup_long(service)
    service.generate_day(date(2026, 10, 20))
    old = feedback(store, '2026-10-20', training_completed=False)
    feedback(store, '2026-10-20', training_completed=True)
    store.save_advice(old['id'], {'summary': '建议'}, None, old['revision'])
    assert service.generate_day(date(2026, 10, 21))['data']['cycle_index'] == 1
    injury = feedback(store, '2026-10-21', training_summary='肩膀受伤了')
    hurt = service.generate_day(date(2026, 10, 21))
    service.release_restriction(hurt['id'], 'shoulder', hurt['revision'], '专业评估后已确认活动范围')
    store.save_advice(injury['id'], {'summary': '建议'}, None, injury['revision'])
    assert service.generate_day(date(2026, 10, 22))['data']['decision']['action'] == 'train'


def test_food_feedback_retains_raw_text_injury_and_partial_release(planner):
    service, store = planner
    setup_long(service)
    from fitness.models import FeedbackData
    data = FeedbackData(date='2026-10-20').model_dump(mode='json')
    raw = store.create_feedback('肩膀受伤了', data, 'demo', {})
    store.confirm_feedback(raw['id'], data, 0)
    feedback(store, '2026-10-20', food_summary='米饭')
    row = service.generate_day(date(2026, 10, 20))
    assert row['data']['decision']['action'] == 'pause'
    both = service.generate_day(date(2026, 10, 20), '肩膀和膝盖受伤了')
    service.release_restriction(both['id'], 'shoulder', both['revision'], '确认肩部恢复及活动范围')
    next_day = service.generate_day(date(2026, 10, 21))
    assert any(r['area'] == 'knee' and r['active'] for r in next_day['data']['decision']['restrictions'])


def test_same_urgent_condition_reported_again_after_release_pauses(planner):
    service, _ = planner
    setup_long(service)
    text = '今天胸痛和呼吸困难'
    hurt = service.generate_day(date(2026, 10, 20), text)
    service.release_restriction(hurt['id'], 'urgent_symptoms', hurt['revision'], '专业评估后确认可以恢复活动')
    assert service.generate_day(date(2026, 10, 20))['data']['decision']['action'] == 'train'
    assert service.generate_day(date(2026, 10, 20), text)['data']['decision']['action'] == 'pause'


@pytest.mark.parametrize('raw_text', ['肩膀受伤了', '普通反馈'])
def test_unrelated_feedback_edit_does_not_reactivate_released_injury(planner, raw_text):
    service, store = planner
    setup_long(service)
    from fitness.models import FeedbackData
    data = FeedbackData(date='2026-10-20', training_summary='肩膀受伤了').model_dump(mode='json')
    draft = store.create_feedback(raw_text, data, 'demo', {})
    report = store.confirm_feedback(draft['id'], data, 0)
    hurt = service.generate_day(date(2026, 10, 20))
    service.release_restriction(hurt['id'], 'shoulder', hurt['revision'], '专业评估后确认肩部活动范围')
    store.confirm_feedback(report['id'], {**data, 'weight_kg': 75}, report['revision'])
    assert service.generate_day(date(2026, 10, 21))['data']['decision']['action'] == 'train'
    edited = store.get_feedback(report['id'])
    store.confirm_feedback(report['id'], {**edited['data'], 'training_summary': '今天肩膀再次受伤了'}, edited['revision'])
    assert service.generate_day(date(2026, 10, 21))['data']['decision']['action'] == 'pause'


def test_food_only_feedback_preserves_same_day_fatigue_intent(planner):
    service, store = planner
    setup_long(service)
    from fitness.models import FeedbackData
    text = '今天很累不想练'
    data = FeedbackData(date='2026-10-20', fatigue='有点累').model_dump(mode='json')
    draft = store.create_feedback(text, data, 'demo', {})
    store.confirm_feedback(draft['id'], data, 0)
    assert service.generate_day(date(2026, 10, 20))['data']['decision']['action'] == 'defer'
    feedback(store, '2026-10-20', food_summary='午餐吃了米饭')
    assert service.generate_day(date(2026, 10, 20))['data']['decision']['action'] == 'defer'
