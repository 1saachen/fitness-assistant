import json
from datetime import date

import pytest
from test_agent_runtime import ScriptProvider, final

from fitness.config import Settings
from fitness.models import Profile
from fitness.provider import ProviderError, ProviderReply
from fitness.storage import Conflict, Store, encode

DAY = date(2026, 10, 21)


def candidate(row, **changes):
    result = {'reply': '今天已经完成训练，先恢复，明天再结合状态安排。',
              'suggestions': ['今晚优先睡眠。'], 'questions': [],
              'memory_updates': [{'key': 'training:report', 'category': 'fact',
                  'text': '10月21日用户报告训练后疲劳。',
                  'sources': [{'feedback_id': row['id'], 'revision': row['revision']}],
                  'evidence': [{'feedback_id': row['id'], 'revision': row['revision'], 'quote': row['raw_text']}]}],
              'retire_keys': [], 'decision': {'action': 'keep', 'reason': '日终复盘，无需改动今天。'}}
    result.update(changes)
    return result


class Plans:
    def __init__(self):
        self.calls = []

    def generate_day(self, day, **kwargs):
        self.calls.append(('day', day, kwargs))
        return {'id': 'new-day', 'date': str(day)}

    def create_long_term(self, day, **kwargs):
        self.calls.append(('long', day, kwargs))
        return {'id': 'new-long', 'status': 'draft'}


@pytest.fixture
def coach(tmp_path):
    from fitness.feedback_coach import FeedbackCoach
    store = Store(tmp_path / 'feedback.db')
    provider = ScriptProvider([])
    service = FeedbackCoach(store, Settings(live_enabled=True, api_key='test'),
                            provider=provider, planner=Plans(), today=lambda: DAY)
    return service, provider, store


def test_raw_feedback_survives_model_failure_and_retry_uses_same_record(coach):
    service, provider, store = coach
    row = service.record('今天练完很累，准备睡了', DAY, request_key='once')
    provider.replies = iter([ProviderError('timeout')])
    result = service.analyze(row['id'])
    assert result['coaching']['status'] == 'failed'
    assert store.get_feedback(row['id'])['raw_text'] == row['raw_text']
    assert store.get_feedback(row['id'])['status'] == 'confirmed'
    assert service.record(row['raw_text'], DAY, request_key='once')['id'] == row['id']
    provider.replies = iter([final(candidate(row))])
    assert service.analyze(row['id'])['coaching']['status'] == 'ready'
    assert len(store.feedback()) == 1


def test_narrative_memory_and_keep_decision_without_required_numeric_fields(coach):
    service, provider, _ = coach
    row = service.record('今天练完很累', DAY)
    provider.replies = iter([final(candidate(row))])
    result = service.analyze(row['id'])
    assert result['coaching']['data']['reply'].startswith('今天已经')
    assert service.planner.calls == []
    memory = service.memory.current()
    assert memory['version'] == 1
    assert memory['data']['entries'][0]['sources'][0]['feedback_id'] == row['id']
    assert service.analyze(row['id']) == result
    assert len(provider.messages) == 1


def test_feedback_coach_uses_the_same_supplement_policy(coach):
    from fitness.supplement_agent import SUPPLEMENT_POLICY
    service, provider, _ = coach
    row = service.record('我平时蛋白质已经吃够了，还需要蛋白粉吗？', DAY)
    provider.replies = iter([final(candidate(row, memory_updates=[]))])
    assert service.analyze(row['id'])['coaching']['status'] == 'ready'
    guide = provider.messages[0][0]['content']
    assert SUPPLEMENT_POLICY in guide
    assert '只有用户明确询问某种补剂时' in guide
    assert 'search_coaching_knowledge' in guide


def test_review_cannot_rewrite_today_even_when_model_requests_it(coach):
    service, provider, _ = coach
    row = service.record('今天练完了', DAY)
    invalid = candidate(row, decision={'action': 'adjust_remaining', 'reason': '减量'})
    provider.replies = iter([final(invalid)] * 3)
    result = service.analyze(row['id'])
    assert result['coaching']['status'] == 'failed'
    assert service.planner.calls == []
    assert service.memory.current()['version'] == 0


def test_adjusts_next_day_and_long_term_is_only_a_draft(coach):
    service, provider, _ = coach
    row = service.record('今晚很累，下一次训练请降低RPE', DAY)
    provider.replies = iter([final(candidate(row, decision={'action': 'adjust_next',
        'reason': '下一次降低RPE', 'conditions': '下一次训练RPE下调到6，保留已经完成的训练。'}))])
    result = service.analyze(row['id'])
    assert service.planner.calls[0][1] == date(2026, 10, 22)
    assert result['coaching']['planning_update']['status'] == 'updated'
    row2 = service.record('以后每周只能练两次，请重排长期计划', DAY)
    provider.replies = iter([final(candidate(row2, decision={'action': 'propose_long_term',
        'reason': '每周两练', 'conditions': '每周两练'}))])
    result = service.analyze(row2['id'])
    assert result['coaching']['planning_update']['status'] == 'draft'
    assert service.planner.calls[-1][0] == 'long'
    assert service.planner.calls[-1][1] > DAY


def test_remaining_requires_explicit_mode_and_cannot_change_a_historical_day(coach):
    service, provider, _ = coach
    row = service.record('晚饭还没吃，帮我重新安排', DAY, timing='remaining')
    provider.replies = iter([final(candidate(row, decision={'action': 'adjust_remaining',
        'reason': '晚饭未完成', 'conditions': '仅调整未完成的晚餐'}))])
    assert service.analyze(row['id'])['coaching']['planning_update']['status'] == 'updated'
    assert service.planner.calls[-1][1] == DAY
    with pytest.raises(ValueError):
        service.record('补录昨天', date(2026, 10, 20), timing='remaining')


def test_followup_context_and_history_tool_supply_original_evidence(coach):
    service, provider, _ = coach
    parent = service.record('卧推后肩膀不舒服', DAY)
    provider.replies = iter([final(candidate(parent, questions=['是肌肉酸痛还是关节疼痛？']))])
    service.analyze(parent['id'])
    child = service.record('是肩关节疼，不是肌肉酸', DAY, parent_feedback_id=parent['id'])
    provider.replies = iter([ProviderReply(tool_calls=[{'id': 'read1', 'name': 'read_feedback_history',
        'arguments': {'query': '肩', 'limit': 5}}]), final(candidate(child))])
    service.analyze(child['id'])
    task = json.loads(provider.messages[-2][1]['content'])
    assert task['parent']['data']['questions'] == ['是肌肉酸痛还是关节疼痛？']
    assert parent['raw_text'] in provider.messages[-1][-1]['content']


def test_fabricated_memory_source_is_rejected(coach):
    service, provider, _ = coach
    row = service.record('训练结束', DAY)
    invalid = candidate(row)
    invalid['memory_updates'][0]['sources'][0]['feedback_id'] = 'invented'
    provider.replies = iter([final(invalid)] * 3)
    assert service.analyze(row['id'])['coaching']['status'] == 'failed'
    assert service.memory.current()['version'] == 0


def test_request_key_conflict_does_not_silently_discard_new_text(coach):
    service, _, _ = coach
    service.record('第一个', DAY, request_key='same')
    with pytest.raises(Conflict):
        service.record('另一个', DAY, request_key='same')


def test_stale_analysis_cannot_commit_memory(coach):
    service, provider, store = coach
    row = service.record('今天训练完了', DAY)
    def changed(*args, **kwargs):
        store.save_profile(Profile().model_dump(mode='json'), 0)
        return final(candidate(row))
    provider.complete = changed
    result = service.analyze(row['id'])
    assert result['coaching']['status'] == 'failed'
    assert result['coaching']['error'] == 'input_changed'
    assert service.memory.current()['version'] == 0


def test_model_compaction_preserves_protected_entries_and_originals(coach):
    service, provider, store = coach
    service.memory_budget = 100
    row = service.record('花生过敏，以后都不要安排。训练后觉得累。', DAY)
    result = candidate(row)
    result['memory_updates'].append({'key': 'allergy:peanut', 'category': 'restriction',
        'text': '用户报告花生过敏。', 'sources': result['memory_updates'][0]['sources'],
        'evidence': result['memory_updates'][0]['evidence']})
    from fitness.memory_lifecycle import dated_entry
    compact = {'entries': [dated_entry(e, DAY) for e in result['memory_updates']]}
    provider.replies = iter([final(result), final(compact)])
    response = service.analyze(row['id'])
    assert response['coaching']['memory_status'] == 'compacted'
    assert len(provider.messages) == 2
    assert any(x['key'] == 'allergy:peanut' for x in service.memory.current()['data']['entries'])
    assert store.get_feedback(row['id'])['raw_text'].startswith('花生过敏')


def test_bad_compaction_leaves_old_memory_and_reports_failure(coach):
    service, provider, _ = coach
    service.memory_budget = 100
    row = service.record('花生过敏', DAY)
    result = candidate(row)
    result['memory_updates'][0]['category'] = 'restriction'
    provider.replies = iter([final(result)] + [final({'entries': []})] * 3)
    response = service.analyze(row['id'])
    assert response['coaching']['status'] == 'ready'
    assert response['coaching']['memory_status'] == 'failed'
    assert service.memory.current()['version'] == 0


def test_backup_accepts_new_memory_tables(coach, tmp_path):
    from fitness.data_transfer import create_backup, preview_restore
    service, provider, store = coach
    row = service.record('今天有训练', DAY)
    provider.replies = iter([final(candidate(row))])
    service.analyze(row['id'])
    destination = tmp_path / 'backup.db'
    create_backup(store, destination)
    result = preview_restore(destination)
    assert result['counts']['personal_memory'] == 1
    assert result['counts']['feedback_coaching'] == 1


def test_api_records_then_understands_and_reload_keeps_response(coach, monkeypatch):
    from fastapi.testclient import TestClient
    from test_api import main
    service, provider, store = coach
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'feedback_coach', lambda: service)
    client = TestClient(main.app)
    saved = client.post('/api/feedback/record', json={
        'text': '练完了，很累', 'date': str(DAY), 'request_key': 'api-one'})
    assert saved.status_code == 200
    row = saved.json()
    provider.replies = iter([final(candidate(row))])
    understood = client.post(f"/api/feedback/{row['id']}/understand")
    assert understood.status_code == 200
    assert understood.json()['coaching']['status'] == 'ready'
    assert client.get('/api/state').json()['feedback'][0]['coaching']['data']['reply']
    assert client.get('/api/personal-memory').json()['version'] == 1


def test_api_rechecks_legacy_plan_answer_once_for_profile_sync(coach, monkeypatch):
    from fastapi.testclient import TestClient
    from test_api import main

    service, provider, store = coach
    profile = Profile().model_dump(mode='json')
    profile['training']['usual_training_time'] = None
    store.save_profile(profile, 0)
    row = service.memory.record('通常18点训练', DAY, source_context={
        'kind': 'long_term_conditions', 'answered_questions': ['你通常几点训练？']})
    with store.connection() as db:
        db.execute('UPDATE feedback_coaching SET status=?, data=? WHERE feedback_id=?',
            ('ready', encode({'understanding': candidate(row), 'feedback_revision': 1,
                              'memory_status': 'unchanged', 'planning_update': {'status': 'none'}}),
             row['id']))
    result = candidate(row, profile_updates=[{
        'path': 'training.usual_training_time', 'value': '18点', 'quote': '18点'}])
    provider.replies = iter([final(result)])
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'feedback_coach', lambda: service)
    client = TestClient(main.app)

    first = client.post(f"/api/feedback/{row['id']}/sync-profile")
    repeated = client.post(f"/api/feedback/{row['id']}/sync-profile")

    assert first.status_code == repeated.status_code == 200
    assert first.json()['coaching']['profile_sync']['updated_fields'] == ['通常训练时间']
    assert repeated.json()['coaching']['profile_sync_pending'] is False
    assert store.profile()['data']['training']['usual_training_time'] == '18点'
    assert len(provider.messages) == 1


def test_profile_sync_request_cannot_execute_an_unrelated_feedback_plan_action(coach):
    service, _, store = coach
    row = service.record('明天降低训练强度', DAY)
    decision = {'action': 'adjust_next', 'reason': '用户要求降低强度', 'conditions': '降低训练强度',
                'target_date': str(date(2026, 10, 22))}
    snapshot_token = service.memory.snapshot()['token']
    with store.connection() as db:
        db.execute('UPDATE feedback_coaching SET status=?, data=? WHERE feedback_id=?',
            ('ready', encode({'understanding': {'decision': decision}, 'feedback_revision': 1,
                              'memory_status': 'unchanged', 'planning_input_token': snapshot_token,
                              'planning_update': {'status': 'pending'}}), row['id']))

    result = service.sync_profile(row['id'])

    assert service.planner.calls == []
    assert result['coaching']['planning_update']['status'] == 'pending'


def test_memory_and_raw_narrative_are_available_to_future_training_and_food_models(coach, profile_data):
    from planning_provider import PlanningScriptProvider
    from test_training_live_service import cycle_candidate

    from fitness.daily_planning import DailyPlanningService
    service, provider, store = coach
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    row = service.record('我以后训练日都想吃米饭', DAY)
    understood = candidate(row)
    understood['memory_updates'][0].update(key='food:rice', category='preference', text='训练日偏好米饭')
    provider.replies = iter([final(understood)])
    service.analyze(row['id'])
    planning_provider = PlanningScriptProvider([final(cycle_candidate())])
    planner = DailyPlanningService(store, service.settings, provider=planning_provider)
    planner.create_long_term(date(2026, 10, 22), mode='live')
    training_task = json.loads(planning_provider.messages[0][1]['content'])
    food_task = json.loads(planning_provider.nutrition_messages[0][1]['content'])
    assert training_task['personal_memory']['entries'][0]['text'] == '训练日偏好米饭'
    assert food_task['personal_memory']['entries'][0]['text'] == '训练日偏好米饭'
    assert row['raw_text'] in json.dumps(food_task, ensure_ascii=False)


def test_optional_completed_training_fact_advances_future_cycle_without_changing_original(coach):
    service, provider, store = coach
    row = service.record('今天训练全部做完了，卧推40kg感觉RPE8', DAY)
    understood = candidate(row, facts={'data': {'date': str(DAY), 'training_completed': True},
        'evidence': {'training_completed': '今天训练全部做完了'}})
    provider.replies = iter([final(understood)])
    result = service.analyze(row['id'])
    assert result['data']['training_completed'] is True
    assert store.get_feedback(row['id'])['raw_text'] == row['raw_text']
    assert service.memory.context(DAY)['stale_keys'] == []
    assert service.memory.context(DAY)['entries']


def test_corrected_feedback_invalidates_old_memory_context(coach):
    service, provider, store = coach
    row = service.record('今天睡了6小时', DAY)
    provider.replies = iter([final(candidate(row))])
    service.analyze(row['id'])
    store.confirm_feedback(row['id'], {**row['data'], 'sleep_hours': 8}, row['revision'])
    assert service.memory.context(DAY)['entries'] == []
    assert service.memory.view(store.get_feedback(row['id']))['coaching']['status'] == 'stale'


def test_quote_alone_does_not_authorize_invented_numeric_or_completion_facts(coach):
    service, provider, _ = coach
    row = service.record('今天没训练', DAY)
    invalid = candidate(row, facts={'data': {'date': str(DAY), 'training_completed': True, 'weight_kg': 120},
        'evidence': {'training_completed': '今天没训练', 'weight_kg': '今天没训练'}})
    provider.replies = iter([final(invalid)] * 3)
    response = service.analyze(row['id'])
    assert response['coaching']['status'] == 'ready'
    assert response['coaching']['trace']['ignored_optional_facts']
    assert response['data']['training_completed'] is None
    assert response['data']['weight_kg'] is None


def test_compaction_cannot_turn_a_tentative_pattern_into_a_fact(coach):
    service, provider, _ = coach
    service.memory_budget = 1
    row = service.record('这几次睡少后好像训练更累', DAY)
    original = candidate(row)['memory_updates'][0]
    original.update(category='pattern', text='可能睡少后训练更累，待验证')
    invented = {**original, 'category': 'fact', 'text': '睡少导致疲劳'}
    provider.replies = iter([final({'entries': [invented]})] * 3)
    _entries, status, _trace = service.compact([original])
    assert status == 'failed'


def test_restrictions_cannot_expire_or_be_retired_without_a_correction(coach):
    service, provider, _ = coach
    row = service.record('我花生过敏', DAY)
    original = candidate(row)
    original['memory_updates'][0].update(key='allergy:peanut', category='restriction',
                                        text='用户报告花生过敏', expires_on=str(DAY))
    provider.replies = iter([final(original)] * 3)
    assert service.analyze(row['id'])['coaching']['status'] == 'failed'
    original['memory_updates'][0]['expires_on'] = None
    provider.replies = iter([final(original)])
    service.analyze(row['id'])
    next_row = service.record('今天状态正常', DAY)
    provider.replies = iter([final(candidate(next_row, retire_keys=['allergy:peanut']))] * 3)
    assert service.analyze(next_row['id'])['coaching']['status'] == 'failed'
    assert any(e['key'] == 'allergy:peanut' for e in service.memory.context(date(2026, 10, 22))['entries'])


def test_planner_crash_is_visible_and_execution_can_recover_without_duplicate(coach):
    service, provider, _ = coach
    row = service.record('明天请休息', DAY)
    provider.replies = iter([final(candidate(row, decision={'action': 'adjust_next', 'reason': '恢复',
        'conditions': '明天休息'}))])
    def crash(*args, **kwargs):
        raise RuntimeError('unexpected failure')
    service.planner.generate_day = crash
    result = service.analyze(row['id'])
    assert result['coaching']['planning_update']['status'] == 'failed'
    assert result['coaching']['status'] == 'ready'
    service.planner = Plans()
    assert service.retry_plan(row['id'])['coaching']['planning_update']['status'] == 'updated'
    service.retry_plan(row['id'])
    assert len(service.planner.calls) == 1


def test_expired_plan_execution_recovers_an_already_saved_result(coach, profile_data):
    from datetime import timedelta

    from fitness.daily_planning import DailyPlanningService
    from fitness.plan_store import fingerprint
    from fitness.storage import encode
    service, provider, store = coach
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    planner = DailyPlanningService(store, service.settings)
    long = planner.create_long_term(DAY)
    planner.confirm_long_term(long['id'])
    row = service.record('明天休息', DAY)
    provider.replies = iter([final(candidate(row, decision={'action':'adjust_next', 'reason':'恢复', 'conditions':'明天休息'}))])
    result = service.analyze(row['id'])
    decision = result['coaching']['data']['decision']
    action_id = fingerprint([row['id'], row['revision'], decision])
    saved = planner.generate_day(DAY + timedelta(days=1), mode='demo', feedback_action_id=action_id)
    with store.connection() as db:
        state = json.loads(db.execute('SELECT data FROM feedback_coaching WHERE feedback_id=?', (row['id'],)).fetchone()[0])
        state['planning_update'] = {'status':'applying','started_at':'2026-01-01T00:00:00+00:00'}
        db.execute('UPDATE feedback_coaching SET data=? WHERE feedback_id=?', (encode(state),row['id']))
    service.planner = planner
    recovered = service.analyze(row['id'])
    assert recovered['coaching']['planning_update']['plan_id'] == saved['id']
    assert len(planner.repo.days()) == 1


def test_large_narrative_archive_is_bounded_for_food_planning(coach, profile_data):
    from datetime import timedelta

    from planning_provider import PlanningScriptProvider
    from test_training_live_service import cycle_candidate

    from fitness.daily_planning import DailyPlanningService
    from fitness.models import FeedbackData
    service, _, store = coach
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    for i in range(21):
        day = DAY - timedelta(days=i)
        data = FeedbackData(date=day, training_summary='训练记录' * 400, food_summary='食物记录' * 400).model_dump(mode='json')
        row = store.create_feedback('一整天的训练饮食恢复记录。' * 250, data, 'live', {})
        store.confirm_feedback(row['id'], data, 0)
    provider = PlanningScriptProvider([final(cycle_candidate())])
    planner = DailyPlanningService(store, service.settings, provider=provider)
    planner.create_long_term(DAY, mode='live')
    assert len(json.dumps(provider.nutrition_messages[0],ensure_ascii=False).encode()) < 110000


def test_unrelated_negative_sentence_cannot_clear_an_allergy(coach):
    service, provider, _ = coach
    row = service.record('我花生过敏', DAY)
    original = candidate(row)
    original['memory_updates'][0].update(key='allergy:peanut',category='restriction',text='花生过敏')
    provider.replies = iter([final(original)])
    service.analyze(row['id'])
    next_row = service.record('我今天没有训练', DAY)
    invalid = candidate(next_row, retire_keys=['allergy:peanut'],
        restriction_resolutions={'allergy:peanut':'我今天没有训练'})
    provider.replies = iter([final(invalid)] * 3)
    assert service.analyze(next_row['id'])['coaching']['status'] == 'failed'


def test_compaction_shared_sources_do_not_justify_new_fact_keys(coach):
    service, provider, _ = coach
    service.memory_budget = 1
    row = service.record('睡6小时，可能和疲劳有关', DAY)
    fact = candidate(row)['memory_updates'][0]
    fact.update(key='sleep',text='报告睡了6小时')
    pattern = {**fact,'key':'fatigue_pattern','category':'pattern','text':'可能有关，待验证'}
    invalid = {**fact,'key':'invented_fact','text':'睡少导致疲劳'}
    provider.replies = iter([final({'entries':[invalid]})] * 3)
    assert service.compact([fact,pattern])[1] == 'failed'


def test_personal_memory_allergy_blocks_mango_but_does_not_treat_peanut_oil_as_all_seeds():
    from test_model_led_planning import food_candidate

    from fitness.nutrition_live import validate_nutrition_candidate
    food = food_candidate()
    food['meal_options'][0]['suggestions'] = ['芒果切块100克']
    memory = {'entries':[{'category':'restriction','text':'用户报告芒果过敏'}]}
    assert any(i.code == 'food_restriction' for i in validate_nutrition_candidate(food,Profile(),personal_memory=memory))
    food['meal_options'][0]['suggestions'] = ['豆腐炒蔬菜，使用菜籽油']
    memory['entries'][0]['text'] = '花生过敏，不安排花生油等花生制品。'
    assert not any(i.code == 'food_restriction' for i in validate_nutrition_candidate(food,Profile(),personal_memory=memory))


def test_avoidance_notes_are_not_food_but_sugar_free_allergens_are():
    from test_model_led_planning import food_candidate

    from fitness.nutrition_live import validate_nutrition_candidate
    food = food_candidate()
    memory = {'entries':[{'category':'restriction','text':'花生过敏'}]}
    food['meal_options'][0]['suggestions'] = ['米饭配鸡肉；不使用花生油，避开花生酱。']
    assert not any(i.code == 'food_restriction' for i in validate_nutrition_candidate(food,Profile(),personal_memory=memory))
    food['meal_options'][0]['suggestions'] = ['全麦面包配无糖花生酱']
    assert any(i.code == 'food_restriction' for i in validate_nutrition_candidate(food,Profile(),personal_memory=memory))
    memory['entries'][0]['text'] = '用户报告芒果过敏'
    food['meal_options'][0]['suggestions'] = ['不加糖的芒果奶昔100克']
    assert any(i.code == 'food_restriction' for i in validate_nutrition_candidate(food,Profile(),personal_memory=memory))


@pytest.mark.parametrize('old,quote,expected', [
    ('花生过敏','更正：我没有花生过敏，之前说错了',True),
    ('芒果过敏','更正：没有芒果过敏',True),
    ('右肩疼痛','右肩没有恢复，今天可以走路',False),
    ('花生过敏','今天可以训练了',False),
    ('花生过敏','花生过敏没有解除',False),
])
def test_restriction_resolution_mentions_affected_subject(old,quote,expected):
    from fitness.restrictions import resolution_matches
    assert resolution_matches(old,quote) is expected
