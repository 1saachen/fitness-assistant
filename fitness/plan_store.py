"""Append-only long-term and daily plans with input snapshot guards."""

import hashlib
from uuid import uuid4

from .storage import Conflict, NotFound, decode, encode, now


def fingerprint(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


class PlanRepository:
    def __init__(self, store):
        self.store = store

    def long_terms(self, db=None):
        if db is None:
            with self.store.connection() as connection:
                return self.long_terms(connection)
        return [decode(r) for r in db.execute('SELECT * FROM long_term_plans ORDER BY version DESC')]

    def days(self, end_date=None, db=None):
        if db is None:
            with self.store.connection() as connection:
                return self.days(end_date, connection)
        query = 'SELECT * FROM daily_plans'
        params = ()
        if end_date is not None:
            query += ' WHERE date <= ?'
            params = (str(end_date),)
        return [decode(r) for r in db.execute(query + ' ORDER BY date DESC, revision DESC', params)]

    def snapshot(self, day, db=None):
        if db is None:
            with self.store.connection() as connection:
                connection.execute('BEGIN')
                return self.snapshot(day, connection)
        profile = decode(db.execute('SELECT * FROM profiles ORDER BY version DESC LIMIT 1').fetchone())
        longs = self.long_terms(db)
        active = next((r for r in longs if r['status'] == 'confirmed' and r['start_date'] <= str(day)), None)
        feedback = [decode(r) for r in db.execute(
            """SELECT f.*,
                (SELECT r.created_at FROM feedback_revisions r WHERE r.feedback_id=f.id
                 ORDER BY r.revision DESC LIMIT 1) AS fact_updated_at
                FROM feedback f WHERE f.status='confirmed' AND f.date<=?
                ORDER BY f.date, f.created_at, f.id""", (str(day),))]
        from .feedback_facts import attach_fact_times
        attach_fact_times(db, feedback)
        # Advice writes do not change input facts; feedback revisions do.
        facts = [{k: r[k] for k in ('id', 'date', 'revision', 'data', 'raw_text', 'fact_updated_at')}
                 for r in feedback]
        days = self.days(day, db)
        from .feedback_memory import FeedbackMemory
        personal_memory = FeedbackMemory(self.store).context(day, db)
        token = fingerprint([profile, active, facts, days, personal_memory])
        return {'profile': profile, 'long_term': active, 'feedback': feedback, 'days': days, 'token': token,
                'personal_memory': personal_memory}

    def create_long(self, start_date, data, trace, profile_version, expected_token=None):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if expected_token is not None and self.snapshot(start_date, db)['token'] != expected_token:
                raise Conflict('档案、反馈或计划已有变化，请重新生成长期计划。')
            if db.execute('SELECT MAX(version) FROM profiles').fetchone()[0] != profile_version:
                raise Conflict('档案已改变，请重新生成长期计划。')
            version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM long_term_plans').fetchone()[0]
            ident = str(uuid4())
            db.execute('INSERT INTO long_term_plans VALUES (?,?,?,?,?,?,?,?)',
                       (ident, version, profile_version, str(start_date), 'draft', encode(data), encode(trace), now()))
            return decode(db.execute('SELECT * FROM long_term_plans WHERE id=?', (ident,)).fetchone())

    def confirm_long(self, ident):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = decode(db.execute('SELECT * FROM long_term_plans WHERE id=?', (ident,)).fetchone())
            if row is None:
                raise NotFound('长期计划不存在。')
            if db.execute('SELECT MAX(version) FROM profiles').fetchone()[0] != row['profile_version']:
                raise Conflict('档案已改变，请重新生成长期计划。')
            if row['status'] == 'confirmed':
                return row
            newer = db.execute(
                "SELECT 1 FROM long_term_plans WHERE status='confirmed' AND version>? AND start_date<=?",
                (row['version'], row['start_date'])).fetchone()
            if newer:
                raise Conflict('已有更新的长期计划，请使用最新版本。')
            db.execute("UPDATE long_term_plans SET status='confirmed' WHERE id=?", (ident,))
            return decode(db.execute('SELECT * FROM long_term_plans WHERE id=?', (ident,)).fetchone())

    def append_day(self, day, data, trace, expected_token, input_fingerprint):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshot = self.snapshot(day, db)
            if snapshot['token'] != expected_token:
                raise Conflict('档案、反馈或当天计划已有更新，请刷新后重试。')
            active = snapshot['long_term']
            if active is None or active['id'] != trace.get('long_term_id'):
                raise Conflict('长期计划已有更新，请刷新当天计划。')
            revision = db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM daily_plans WHERE date=?',
                                  (str(day),)).fetchone()[0]
            ident = str(uuid4())
            db.execute('INSERT INTO daily_plans VALUES (?,?,?,?,?,?,?,?,?)',
                       (ident, str(day), revision, active['id'], snapshot['profile']['version'],
                        encode(data), encode(trace), input_fingerprint, now()))
            return decode(db.execute('SELECT * FROM daily_plans WHERE id=?', (ident,)).fetchone())
