"""Versioned personal memory and independently durable feedback, with write guards."""

from datetime import datetime, timedelta
from uuid import uuid4

from .models import FeedbackData
from .plan_store import fingerprint
from .storage import Conflict, NotFound, decode, encode, now

PROTECTED = {'preference', 'restriction', 'question'}


def estimated_tokens(value):
    # Conservative for mixed Chinese/ASCII JSON; this is a context budget, not disk usage.
    return len(encode(value).encode('utf-8')) // 2 + 1


def compact_feedback_reports(rows, *, limit=21, budget_bytes=40000):
    """Recent narrative context has an explicit size budget; originals remain retrievable."""
    selected, used = [], 0
    for row in reversed(rows[-limit:]):
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
        entries, stale = [], []
        for entry in memory['data']['entries']:
            if any(sources.get(s['feedback_id'], {}).get('revision') != s['revision'] for s in entry['sources']):
                stale.append(entry['key'])
                continue
            if any(sources[s['feedback_id']]['date'] > str(day) for s in entry['sources']):
                continue
            if entry['category'] != 'restriction' and entry.get('expires_on') and entry['expires_on'] < str(day):
                continue
            entries.append(entry)
        return {'version': memory['version'], 'entries': entries, 'stale_keys': stale,
                'source_kind': 'personal_memory', 'estimated_tokens': estimated_tokens(entries)}

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
                self.store_row(db, parent_feedback_id)
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
        return row

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
