"""Versioned personal memory and independently durable feedback, with write guards."""

import re
from datetime import datetime, timedelta
from uuid import uuid4

from .memory_lifecycle import dated_entry
from .models import FeedbackData
from .plan_store import fingerprint
from .storage import Conflict, NotFound, decode, encode, now

PROTECTED = {'preference', 'restriction', 'question'}


def estimated_tokens(value):
    # Conservative for mixed Chinese/ASCII JSON; this is a context budget, not disk usage.
    return len(encode(value).encode('utf-8')) // 2 + 1


def select_recent_reports(rows, *, end_date, days=14, limit=21):
    """Bound by calendar time and distribute the count budget across reporting days."""
    start = str(end_date - timedelta(days=days - 1))
    by_day = {}
    for row in sorted(rows, key=lambda r: (str(r['date']), str(r.get('created_at') or ''),
                                         str(r.get('id') or '')), reverse=True):
        if row.get('status', 'confirmed') != 'confirmed' or not start <= str(row['date']) <= str(end_date):
            continue
        by_day.setdefault(str(row['date']), []).append(row)
    selected = []
    while by_day and len(selected) < limit:
        for day in list(by_day):
            selected.append(by_day[day].pop(0))
            if not by_day[day]:
                del by_day[day]
            if len(selected) == limit:
                break
    return sorted(selected, key=lambda r: (str(r['date']), str(r.get('created_at') or ''), str(r.get('id') or '')))


def compact_feedback_reports(rows, *, end_date, days=14, limit=21, budget_bytes=40000):
    """Recent narrative context has an explicit size budget; originals remain retrievable."""
    selected, used = [], 0
    for row in reversed(select_recent_reports(rows, end_date=end_date, days=days, limit=limit)):
        item = {'feedback_id': row.get('id'), 'revision': row.get('revision'), 'date': row['date']}
        truncated = []
        for key, value in row['data'].items():
            if value is None or value in ([], {}):
                continue
            if isinstance(value, str) and len(value) > 500:
                value = value[:500]
                truncated.append(key)
            if isinstance(value, list) and len(value) > 8:
                value = value[:8]
                truncated.append(key)
            item[key] = value
        item['raw_text'] = row.get('raw_text', '')[:800]
        if len(row.get('raw_text', '')) > 800:
            truncated.append('raw_text')
        item['truncated_fields'] = truncated
        size = len(encode(item).encode('utf-8'))
        if used + size > budget_bytes:
            break
        used += size
        selected.append(item)
    return list(reversed(selected))


class FeedbackMemory:
    def __init__(self, store):
        self.store = store

    def current(self, db=None):
        if db is None:
            with self.store.connection() as connection:
                return self.current(connection)
        return decode(db.execute('SELECT * FROM personal_memory ORDER BY version DESC LIMIT 1').fetchone()) or {
            'version': 0, 'data': {'entries': []}, 'trace': {}, 'created_at': None}

    def context(self, day, db=None):
        if db is None:
            with self.store.connection() as connection:
                connection.execute('BEGIN')
                return self.context(day, connection)
        memory = self.current(db)
        sources = {r['id']: dict(r) for r in db.execute('SELECT id,date,revision FROM feedback')}
        entries, stale, expired, future, legacy = [], [], [], [], []
        for entry in memory['data']['entries']:
            source_changed = any(sources.get(s['feedback_id'], {}).get('revision') != s['revision']
                                 for s in entry['sources'])
            if source_changed:
                stale.append(entry['key'])
                # Raw reports are immutable: editing a weight does not revoke a reported allergy.
                if entry['category'] != 'restriction' or any(s['feedback_id'] not in sources for s in entry['sources']):
                    continue
            if any(sources[s['feedback_id']]['date'] > str(day) for s in entry['sources']):
                future.append(entry['key'])
                continue
            fallback = max(sources[s['feedback_id']]['date'] for s in entry['sources'])
            entry = dated_entry(entry, fallback)
            if entry['event_date'] > str(day):
                future.append(entry['key'])
                continue
            if entry['category'] != 'restriction' and entry.get('expires_on') and entry['expires_on'] < str(day):
                expired.append(entry['key'])
                continue
            if source_changed:
                entry['verification'] = 'source_changed_recheck'
            elif entry.get('confirmed_at'):
                entry['verification'] = 'user_confirmed'
            elif not entry.get('evidence'):
                legacy.append(entry['key'])
                entry['verification'] = 'legacy_unverified'
            else:
                entry['verification'] = 'quoted_user_report' if entry['category'] != 'pattern' else 'tentative_pattern'
            entries.append(entry)
        return {'version': memory['version'], 'entries': entries, 'stale_keys': stale,
                'expired_keys': expired, 'future_keys': future, 'legacy_keys': legacy,
                'superseded_keys': list(dict.fromkeys(key for entry in entries for key in entry.get('supersedes', []))),
                'source_kind': 'personal_memory', 'estimated_tokens': estimated_tokens(entries)}

    def confirm_preference(self, key, expected_version, action, day):
        if action not in {'confirm', 'retire'}:
            raise ValueError('不支持的偏好操作。')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            memory = self.current(db)
            if memory['version'] != expected_version:
                raise Conflict('个人记忆已有更新，请刷新后再确认。')
            active = next((e for e in self.context(day, db)['entries'] if e['key'] == key), None)
            if not active or active['category'] != 'preference':
                raise Conflict('这条偏好已失效；限制解除请使用明确的反馈或恢复确认入口。')
            entries = memory['data']['entries']
            entry = next(e for e in entries if e['key'] == key)
            stamp, ident = now(), str(uuid4())
            text = ('我确认这条长期偏好：' if action == 'confirm' else '我不再采用这条长期偏好：') + entry['text']
            facts = FeedbackData(date=day).model_dump(mode='json')
            trace = {'source': 'user_preference_confirmation', 'memory_key': key, 'action': action}
            db.execute('INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (ident, str(day), text, 'confirmed', 1, encode(facts), None, None, 'live', encode(trace), stamp, stamp))
            db.execute('INSERT INTO feedback_revisions VALUES (?,?,?,?)', (ident, 1, encode(facts), stamp))
            if action == 'retire':
                entries = [e for e in entries if e['key'] != key]
            else:
                entry['confirmed_at'] = stamp
                entry['sources'] = [*entry['sources'][-29:], {'feedback_id': ident, 'revision': 1}]
                entry['evidence'] = [*entry.get('evidence', [])[-29:],
                    {'feedback_id': ident, 'revision': 1, 'quote': text}]
            db.execute('INSERT INTO personal_memory VALUES (?,?,?,?)',
                (memory['version'] + 1, encode({'entries': entries}), encode(trace), stamp))
            return self.current(db)

    def record(self, text, day, *, timing='review', request_key=None, parent_feedback_id=None):
        key = request_key or str(uuid4())
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = decode(db.execute('SELECT * FROM feedback_coaching WHERE request_key=?', (key,)).fetchone())
            if old:
                row = self.store_row(db, old['feedback_id'])
                if (row['raw_text'] != text or row['date'] != str(day) or old['timing'] != timing
                        or old['parent_feedback_id'] != parent_feedback_id):
                    raise Conflict('同一提交标识的内容已变化，请使用新的提交。')
                return self.view(row, db)
            if parent_feedback_id:
                parent = self.store_row(db, parent_feedback_id)
                if parent['date'] > str(day):
                    raise ValueError('补充反馈日期不能早于关联原记录的日期。')
            ident, stamp = str(uuid4()), now()
            data = FeedbackData(date=day).model_dump(mode='json')
            trace = {'steps': ['raw_feedback'], 'source': 'user_report'}
            db.execute('INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                       (ident, str(day), text, 'confirmed', 1, encode(data), None, None,
                        'live', encode(trace), stamp, stamp))
            db.execute('INSERT INTO feedback_revisions VALUES (?,?,?,?)', (ident, 1, encode(data), stamp))
            db.execute('INSERT INTO feedback_coaching VALUES (?,?,?,?,?,?,?,?,?)',
                       (ident, key, parent_feedback_id, timing, 'saved', None, '{}', '{}', stamp))
            return self.view(self.store_row(db, ident), db)

    @staticmethod
    def store_row(db, ident):
        row = decode(db.execute('SELECT * FROM feedback WHERE id=?', (ident,)).fetchone())
        if row is None:
            raise NotFound('反馈不存在。')
        return row

    def view(self, row, db=None):
        if db is None:
            with self.store.connection() as connection:
                return self.view(row, connection)
        coaching = decode(db.execute('SELECT * FROM feedback_coaching WHERE feedback_id=?', (row['id'],)).fetchone())
        if coaching:
            data = coaching['data']
            stale = data.get('feedback_revision', row['revision']) != row['revision']
            row = {**row, 'coaching': {**coaching, 'status': 'stale' if stale else coaching['status'],
                'data': data.get('understanding'), 'planning_update': data.get('planning_update', {'status': 'none'}),
                'memory_status': data.get('memory_status', 'pending'), 'error': data.get('error')}}
            row['coaching']['planning_input_token'] = data.get('planning_input_token')
            ignored = coaching['trace'].get('ignored_optional_facts', [])
            ignored_fields = []
            for item in ignored:
                path = item['path'].split('.')
                field = path[2] if len(path) > 2 and path[1] in {'data', 'evidence'} else (
                    path[1] if len(path) > 1 else 'facts')
                if field not in ignored_fields:
                    ignored_fields.append(field)
            training_mentioned = bool(row['data'].get('exercise_results') or re.search(
                r'训练|卧推|深蹲|硬拉|引体|练|跑步|运动', row['raw_text']))
            row['coaching']['fact_status'] = {'ignored_fields': ignored_fields}
            for field, mentioned in [('training_completed', training_mentioned),
                                     ('diet_followed_plan', bool(re.search(r'按计划|饮食执行', row['raw_text'])))]:
                value = row['data'].get(field)
                row['coaching']['fact_status'][field] = {
                    'status': 'confirmed' if value is not None else 'needs_confirmation' if mentioned else 'unknown',
                    'value': value}
        return row

    def confirm_facts(self, ident, expected_revision, facts):
        if not facts or not facts.keys() <= {'training_completed', 'diet_followed_plan'} or any(
                type(v) is not bool for v in facts.values()):
            raise ValueError('请明确确认训练或饮食执行状态。')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.store_row(db, ident)
            if row['revision'] != expected_revision:
                raise Conflict('反馈已有更新，请刷新后再确认。')
            data = {**row['data'], **facts}
            trace = {**row['trace'], 'user_confirmed_facts': {
                **row['trace'].get('user_confirmed_facts', {}), **facts}}
            revision, stamp = row['revision'] + 1, now()
            db.execute('UPDATE feedback SET data=?,revision=?,trace=?,updated_at=? WHERE id=?',
                       (encode(data), revision, encode(trace), stamp, ident))
            db.execute('INSERT INTO feedback_revisions VALUES (?,?,?,?)', (ident, revision, encode(data), stamp))
            return self.view(self.store_row(db, ident), db)

    def snapshot(self, db=None):
        if db is None:
            with self.store.connection() as connection:
                connection.execute('BEGIN')
                return self.snapshot(connection)
        inputs = {}
        # Advice/trace writes do not change facts. Include every raw revision and all plan versions.
        for table, fields in [('profiles', 'version,data'),
                              ('feedback', 'id,date,raw_text,revision,data,status'),
                              ('long_term_plans', 'id,version,status,data'),
                              ('daily_plans', 'id,date,revision,data')]:
            inputs[table] = [dict(row) for row in db.execute(f'SELECT {fields} FROM {table} ORDER BY 1')]
        memory = self.current(db)
        return {'token': fingerprint([inputs, memory['version']]), 'memory': memory}

    def begin(self, ident, *, force=False):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.view(self.store_row(db, ident), db)
            if 'coaching' not in row:
                raise Conflict('这条历史反馈请使用原有编辑流程，或新增一条补充反馈。')
            coaching = row['coaching']
            if coaching['status'] == 'ready' and not force:
                return row, None, None
            if coaching['status'] == 'processing' and datetime.fromisoformat(coaching['updated_at']) > (
                    datetime.fromisoformat(now()) - timedelta(minutes=10)):
                raise Conflict('模型正在理解这条反馈，请稍后刷新。')
            snapshot = self.snapshot(db)
            claim = str(uuid4())
            db.execute("UPDATE feedback_coaching SET status='processing', input_token=?, trace=?, updated_at=? "
                       'WHERE feedback_id=?', (snapshot['token'], encode({'claim': claim}), now(), ident))
            return row, snapshot, claim

    def fail(self, ident, claim, reason, trace):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = decode(db.execute('SELECT * FROM feedback_coaching WHERE feedback_id=?', (ident,)).fetchone())
            if row['trace'].get('claim') == claim:
                db.execute("UPDATE feedback_coaching SET status='failed', data=?, trace=?, updated_at=? "
                           'WHERE feedback_id=?', (encode({'error': reason}), encode(trace), now(), ident))
        return self.view(self.store.get_feedback(ident))

    def commit(self, row, snapshot, claim, understanding, entries, memory_status, trace):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = decode(db.execute('SELECT * FROM feedback_coaching WHERE feedback_id=?', (row['id'],)).fetchone())
            if (self.snapshot(db)['token'] != snapshot['token'] or current['trace'].get('claim') != claim):
                raise Conflict('输入已经变化，请重新理解反馈。')
            memory_version = snapshot['memory']['version']
            if memory_status != 'failed' and entries != snapshot['memory']['data']['entries']:
                memory_version += 1
                db.execute('INSERT INTO personal_memory VALUES (?,?,?,?)',
                           (memory_version, encode({'entries': entries}), encode(trace), now()))
            # Optional structured facts supplement the narrative; the original report is immutable.
            if understanding.get('facts'):
                facts = {**row['data'], **{key: value for key, value in understanding['facts']['data'].items()
                                         if value is not None and value not in ([], {})}}
                if facts != row['data']:
                    revision = row['revision'] + 1
                    db.execute('UPDATE feedback SET data=?, revision=?, updated_at=? WHERE id=?',
                               (encode(facts), revision, now(), row['id']))
                    db.execute('INSERT INTO feedback_revisions VALUES (?,?,?,?)',
                               (row['id'], revision, encode(facts), now()))
                    # Memory was based on the unchanged raw report; carry its citation forward.
                    if memory_version > snapshot['memory']['version']:
                        for entry in entries:
                            for source in entry['sources']:
                                if source['feedback_id'] == row['id']:
                                    source['revision'] = revision
                            for source in entry.get('evidence', []):
                                if source['feedback_id'] == row['id']:
                                    source['revision'] = revision
                        db.execute('UPDATE personal_memory SET data=? WHERE version=?',
                                   (encode({'entries': entries}), memory_version))
                    row = {**row, 'revision': revision}
            result = {'understanding': understanding, 'feedback_revision': row['revision'],
                      'memory_status': memory_status, 'memory_version': memory_version,
                      'planning_update': {'status': 'pending'} if understanding['decision']['action'] != 'keep'
                          else {'status': 'none'}}
            result['planning_input_token'] = self.snapshot(db)['token']
            db.execute("UPDATE feedback_coaching SET status='ready', data=?, trace=?, updated_at=? WHERE feedback_id=?",
                       (encode(result), encode(trace), now(), row['id']))
        return self.view(self.store.get_feedback(row['id']))

    def plan_status(self, ident, status, *, expected='pending', expected_value=None):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = decode(db.execute('SELECT * FROM feedback_coaching WHERE feedback_id=?', (ident,)).fetchone())
            if row['data'].get('planning_update', {}).get('status') != expected:
                return False
            if expected_value is not None and row['data']['planning_update'] != expected_value:
                return False
            row['data']['planning_update'] = status
            db.execute('UPDATE feedback_coaching SET data=?,updated_at=? WHERE feedback_id=?',
                       (encode(row['data']), now(), ident))
            return True
