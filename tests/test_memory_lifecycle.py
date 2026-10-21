from datetime import date

from test_agent_runtime import ScriptProvider, final
from test_feedback_coach import DAY, candidate

from fitness.config import Settings
from fitness.feedback_coach import FeedbackCoach
from fitness.storage import Store, encode, now


def setup(tmp_path):
    store = Store(tmp_path / 'memory.db')
    provider = ScriptProvider([])
    service = FeedbackCoach(store, Settings(), provider=provider, today=lambda: DAY)
    return service, provider, store


def cited(row, **changes):
    entry = {'key': 'fatigue', 'category': 'fact', 'text': row['raw_text'],
             'sources': [{'feedback_id': row['id'], 'revision': row['revision']}],
             'evidence': [{'feedback_id': row['id'], 'revision': row['revision'], 'quote': row['raw_text']}]}
    return {**entry, **changes}


def test_new_memory_requires_real_quotes_and_patterns_require_distinct_days(tmp_path):
    service, _, _ = setup(tmp_path)
    row = service.record('今天练完很累', DAY)
    sources = {(row['id'], row['revision']): row}
    missing = candidate(row, memory_updates=[cited(row, evidence=[])])
    assert any(i.path == 'memory_updates.evidence' for i in service.validate(missing, row, sources))
    invented = candidate(row, memory_updates=[cited(row, evidence=[{
        'feedback_id': row['id'], 'revision': row['revision'], 'quote': '不存在的引文'}])])
    assert any(i.path == 'memory_updates.evidence' for i in service.validate(invented, row, sources))
    pattern = candidate(row, memory_updates=[cited(row, category='pattern')])
    assert any(i.path == 'memory_updates.sources' for i in service.validate(pattern, row, sources))


def test_temporary_memory_gets_event_date_and_expires_without_losing_original(tmp_path):
    service, provider, store = setup(tmp_path)
    row = service.record('今天练完很累', DAY)
    provider.replies = iter([final(candidate(row, memory_updates=[cited(row)]))])
    result = service.analyze(row['id'])
    assert result['coaching']['status'] == 'ready'
    entry = service.memory.current()['data']['entries'][0]
    assert entry['event_date'] == str(DAY)
    assert entry['expires_on'] == '2026-11-03'
    assert service.memory.context(date(2026, 11, 4))['entries'] == []
    assert service.memory.context(date(2026, 11, 4))['expired_keys'] == ['fatigue']
    assert store.get_feedback(row['id'])['raw_text'] == row['raw_text']


def test_explicit_supersession_removes_old_preference_and_tracks_relationship(tmp_path):
    service, provider, _ = setup(tmp_path)
    old = service.record('以后训练日喜欢米饭', DAY)
    provider.replies = iter([final(candidate(old, memory_updates=[cited(old, key='food:rice', category='preference')]))])
    service.analyze(old['id'])
    new = service.record('更正：以后训练日喜欢面条，不再偏好米饭', DAY)
    provider.replies = iter([final(candidate(new, memory_updates=[cited(new, key='food:noodles',
        category='preference', supersedes=['food:rice'])]))])
    assert service.analyze(new['id'])['coaching']['status'] == 'ready'
    entries = service.memory.context(DAY)['entries']
    assert [e['key'] for e in entries] == ['food:noodles']
    assert entries[0]['supersedes'] == ['food:rice']
    assert service.memory.context(DAY)['superseded_keys'] == ['food:rice']


def test_supersession_cannot_bypass_restriction_release(tmp_path):
    service, provider, _ = setup(tmp_path)
    old = service.record('花生过敏', DAY)
    provider.replies = iter([final(candidate(old, memory_updates=[cited(old, key='allergy', category='restriction')]))])
    service.analyze(old['id'])
    new = service.record('今天想吃米饭', DAY)
    update = candidate(new, memory_updates=[cited(new, key='food', supersedes=['allergy'])])
    assert any(i.path == 'restriction_resolutions' for i in service.validate(
        update, new, {(new['id'], new['revision']): new}))


def test_legacy_temporary_facts_age_out_but_restrictions_remain_marked(tmp_path):
    service, _, store = setup(tmp_path)
    row = service.record('以前很累，花生过敏', date(2020, 1, 1))
    entries = [{key: value for key, value in cited(row, key='old').items() if key != 'evidence'}]
    entries.append({**entries[0], 'key': 'allergy', 'category': 'restriction', 'text': '花生过敏'})
    with store.connection() as db:
        db.execute('INSERT INTO personal_memory VALUES (?,?,?,?)', (1, encode({'entries': entries}), '{}', now()))
    context = service.memory.context(DAY)
    assert context['expired_keys'] == ['old']
    assert context['entries'][0]['key'] == 'allergy'
    assert context['entries'][0]['verification'] == 'legacy_unverified'


def test_single_day_intention_cannot_become_enduring_preference(tmp_path):
    service, _, _ = setup(tmp_path)
    row = service.record('明天想吃米饭', DAY)
    result = candidate(row, memory_updates=[cited(row, category='preference')])
    assert any(i.path == 'memory_updates.category' for i in service.validate(
        result, row, {(row['id'], row['revision']): row}))


def test_unrelated_source_fact_correction_does_not_silently_remove_allergy(tmp_path):
    service, provider, store = setup(tmp_path)
    row = service.record('花生过敏，体重80kg', DAY)
    provider.replies = iter([final(candidate(row, memory_updates=[cited(row, key='allergy', category='restriction')]))])
    service.analyze(row['id'])
    store.confirm_feedback(row['id'], {**row['data'], 'weight_kg': 79}, row['revision'])
    context = service.memory.context(DAY)
    assert context['stale_keys'] == ['allergy']
    assert context['entries'][0]['key'] == 'allergy'
    assert context['entries'][0]['verification'] == 'source_changed_recheck'


def test_preference_can_be_explicitly_confirmed_and_retired_with_version_guard(tmp_path):
    import pytest

    from fitness.storage import Conflict
    service, provider, store = setup(tmp_path)
    row = service.record('以后训练日喜欢米饭', DAY)
    provider.replies = iter([final(candidate(row, memory_updates=[cited(row, key='food:rice', category='preference')]))])
    service.analyze(row['id'])
    confirmed = service.memory.confirm_preference('food:rice', 1, 'confirm', DAY)
    assert confirmed['version'] == 2
    assert confirmed['data']['entries'][0]['confirmed_at']
    assert service.memory.context(DAY)['entries'][0]['verification'] == 'user_confirmed'
    with pytest.raises(Conflict):
        service.memory.confirm_preference('food:rice', 1, 'retire', DAY)
    retired = service.memory.confirm_preference('food:rice', 2, 'retire', DAY)
    assert retired['data']['entries'] == []
    assert len(store.feedback(limit=None)) == 3


def test_model_cannot_claim_that_user_confirmed_a_memory(tmp_path):
    service, _, _ = setup(tmp_path)
    row = service.record('以后喜欢米饭', DAY)
    result = candidate(row, memory_updates=[cited(row, category='preference', confirmed_at='2026-10-21T01:00:00Z')])
    assert any(i.path == 'memory_updates.confirmed_at' for i in service.validate(
        result, row, {(row['id'], row['revision']): row}))


def test_compaction_cannot_strip_evidence_or_renew_a_pattern(tmp_path):
    service, provider, _ = setup(tmp_path)
    service.memory_budget = 1
    row = service.record('今天很累', DAY)
    entry = cited(row, category='pattern', event_date='2026-10-21', expires_on='2026-11-10')
    invalid = {**entry, 'evidence': [], 'event_date':'2027-01-01', 'expires_on':None}
    provider.replies = iter([final({'entries':[invalid]})] * 3)
    assert service.compact([entry])[1] == 'failed'


def test_supersession_needs_an_explicit_correction_and_future_like_is_not_long_term(tmp_path):
    service, provider, _ = setup(tmp_path)
    old = service.record('我平时喜欢米饭', DAY)
    provider.replies = iter([final(candidate(old, memory_updates=[cited(old,key='rice',category='preference')]))])
    service.analyze(old['id'])
    row = service.record('明天喜欢吃面条', DAY)
    change = candidate(row, memory_updates=[cited(row,key='noodles',category='preference',supersedes=['rice'])])
    paths = {i.path for i in service.validate(change,row,{(row['id'],row['revision']):row})}
    assert 'memory_updates.supersedes' in paths
    assert 'memory_updates.category' in paths
