"""Transactional, versioned local storage. Generated drafts never overwrite facts."""

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 3


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


def now():
    return datetime.now(UTC).isoformat()


def next_stamp(previous):
    stamp = now()
    if stamp > previous:
        return stamp
    return (datetime.fromisoformat(previous) + timedelta(microseconds=1)).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def decode(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("data", "trace", "advice", "changes", "trigger_issues", "evidence", "result"):
        if key in result and result[key] is not None:
            result[key] = json.loads(result[key])
    return result


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("Unsupported future database schema version")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            # Re-read after the write lock: another process may have migrated.
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("Unsupported future database schema version")
            migrations = ["""
                CREATE TABLE IF NOT EXISTS profiles (
                    version INTEGER PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, version INTEGER UNIQUE NOT NULL,
                    profile_version INTEGER NOT NULL REFERENCES profiles(version),
                    start_date TEXT NOT NULL, status TEXT NOT NULL,
                    data TEXT NOT NULL, mode TEXT NOT NULL, trace TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY, date TEXT NOT NULL, raw_text TEXT NOT NULL,
                    status TEXT NOT NULL, revision INTEGER NOT NULL,
                    data TEXT NOT NULL, advice TEXT, advice_error TEXT,
                    mode TEXT NOT NULL, trace TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback_revisions (
                    feedback_id TEXT NOT NULL REFERENCES feedback(id), revision INTEGER NOT NULL,
                    data TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (feedback_id, revision)
                );
            """, """
                CREATE TABLE IF NOT EXISTS plan_changes (
                    id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                    plan_id TEXT NOT NULL REFERENCES plans(id),
                    feedback_id TEXT NOT NULL REFERENCES feedback(id),
                    day_date TEXT NOT NULL, profile_version INTEGER NOT NULL,
                    feedback_revision INTEGER NOT NULL, changes TEXT NOT NULL,
                    trigger_issues TEXT NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """, """
                CREATE TABLE IF NOT EXISTS import_batches (
                    batch_id TEXT PRIMARY KEY, result TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS import_items (
                    fingerprint TEXT PRIMARY KEY, feedback_id TEXT NOT NULL REFERENCES feedback(id),
                    batch_id TEXT NOT NULL REFERENCES import_batches(batch_id)
                );
            """]
            for index in range(version, SCHEMA_VERSION):
                for statement in migrations[index].split(";"):
                    if statement.strip():
                        db.execute(statement)
                db.execute(f"PRAGMA user_version={index + 1}")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def profile(self):
        with self.connection() as db:
            return decode(db.execute("SELECT * FROM profiles ORDER BY version DESC LIMIT 1").fetchone())

    def save_profile(self, data, expected_version):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("SELECT COALESCE(MAX(version), 0) FROM profiles").fetchone()[0]
            if version != expected_version:
                raise Conflict("档案已有更新，请刷新后再保存。")
            db.execute("INSERT INTO profiles VALUES (?, ?, ?)", (version + 1, encode(data), now()))
            return decode(db.execute("SELECT * FROM profiles WHERE version=?", (version + 1,)).fetchone())

    def plans(self):
        with self.connection() as db:
            return [decode(r) for r in db.execute("SELECT * FROM plans ORDER BY version DESC LIMIT 100")]

    def create_plan(self, data, profile_version, start_date, mode, trace):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("SELECT COALESCE(MAX(version), 0)+1 FROM plans").fetchone()[0]
            ident = str(uuid4())
            db.execute("INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                ident, version, profile_version, start_date, "draft", encode(data), mode, encode(trace), now()
            ))
            return decode(db.execute("SELECT * FROM plans WHERE id=?", (ident,)).fetchone())

    def confirm_plan(self, ident):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            plan = decode(db.execute("SELECT * FROM plans WHERE id=?", (ident,)).fetchone())
            if plan is None:
                raise NotFound("计划不存在。")
            if plan["status"] == "confirmed":
                return plan
            version = db.execute("SELECT MAX(version) FROM profiles").fetchone()[0]
            if version != plan["profile_version"]:
                raise Conflict("档案已改变，请根据最新档案重新生成计划。")
            db.execute("UPDATE plans SET status='confirmed' WHERE id=?", (ident,))
            return decode(db.execute("SELECT * FROM plans WHERE id=?", (ident,)).fetchone())

    def feedback(self, limit=100):
        with self.connection() as db:
            query = "SELECT * FROM feedback ORDER BY date DESC, created_at DESC"
            if limit is not None:
                query += " LIMIT ?"
                rows = db.execute(query, (limit,))
            else:
                rows = db.execute(query)
            return [decode(r) for r in rows]

    def get_feedback(self, ident):
        with self.connection() as db:
            row = decode(db.execute("SELECT * FROM feedback WHERE id=?", (ident,)).fetchone())
            if row is None:
                raise NotFound("反馈不存在。")
            return row

    def create_feedback(self, raw_text, data, mode, trace):
        with self.connection() as db:
            ident, stamp = str(uuid4()), now()
            db.execute("INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                ident, data["date"], raw_text, "draft", 0, encode(data), None, None,
                mode, encode(trace), stamp, stamp
            ))
            return decode(db.execute("SELECT * FROM feedback WHERE id=?", (ident,)).fetchone())

    def confirm_feedback(self, ident, data, expected_revision, trace=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = decode(db.execute("SELECT * FROM feedback WHERE id=?", (ident,)).fetchone())
            if row is None:
                raise NotFound("反馈不存在。")
            if row["status"] == "confirmed" and row["data"] == data:
                return row
            if row["revision"] != expected_revision:
                raise Conflict("反馈已有更新，请刷新后再修改。")
            revision, stamp = row["revision"] + 1, now()
            revision_trace = {"steps": ["parser"]} if trace is None else trace
            updated = db.execute(
                """UPDATE feedback SET date=?, data=?, revision=?, status='confirmed',
                   trace=?, updated_at=?, advice=NULL, advice_error=NULL
                   WHERE id=? AND revision=?""",
                (
                    data["date"],
                    encode(data),
                    revision,
                    encode(revision_trace),
                    stamp,
                    ident,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                raise Conflict("反馈已有更新，请刷新后再修改。")
            db.execute("INSERT INTO feedback_revisions VALUES (?, ?, ?, ?)",
                       (ident, revision, encode(data), stamp))
            return decode(db.execute("SELECT * FROM feedback WHERE id=?", (ident,)).fetchone())

    def feedback_revisions(self, ident):
        self.get_feedback(ident)
        with self.connection() as db:
            return [decode(r) for r in db.execute(
                "SELECT revision, data, created_at FROM feedback_revisions WHERE feedback_id=? ORDER BY revision",
                (ident,)
            )]

    def save_advice(
        self,
        ident,
        advice,
        error,
        expected_revision,
        trace=None,
        expected_updated_at=None,
        expected_profile_version=None,
    ):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if expected_profile_version is not None:
                profile_version = db.execute("SELECT MAX(version) FROM profiles").fetchone()[0]
                if profile_version != expected_profile_version:
                    raise Conflict("档案已变化，请重新生成建议。")
            row = db.execute(
                "SELECT revision, status, trace, updated_at FROM feedback WHERE id=?",
                (ident,),
            ).fetchone()
            if row is None:
                raise NotFound("反馈不存在。")
            if row["revision"] != expected_revision or row["status"] != "confirmed":
                raise Conflict("反馈已变化，请重新生成建议。")
            snapshot_updated_at = row["updated_at"] if expected_updated_at is None else expected_updated_at
            if row["updated_at"] != snapshot_updated_at:
                raise Conflict("反馈已变化，请重新生成建议。")
            saved_stamp = next_stamp(row["updated_at"])
            if trace is not None:
                current_trace = deepcopy(trace)
                if isinstance(current_trace, dict) and isinstance(
                    current_trace.get("training_adjustment_preview"), dict
                ):
                    current_trace["training_adjustment_preview"]["expected_feedback_updated_at"] = saved_stamp
                saved_trace = encode(current_trace)
            elif advice is None and error is not None:
                saved_trace = encode({"steps": ["advisor"], "status": "failed"})
            else:
                saved_trace = row["trace"]
            updated = db.execute(
                """UPDATE feedback SET advice=?, advice_error=?, trace=?, updated_at=?
                   WHERE id=? AND revision=? AND status='confirmed' AND updated_at=?""",
                (
                    encode(advice) if advice is not None else None,
                    error,
                    saved_trace,
                    saved_stamp,
                    ident,
                    expected_revision,
                    snapshot_updated_at,
                ),
            )
            if updated.rowcount != 1:
                raise Conflict("反馈已变化，请重新生成建议。")
            return decode(db.execute("SELECT * FROM feedback WHERE id=?", (ident,)).fetchone())

    def plan_changes(self, plan_id=None):
        with self.connection() as db:
            query, params = "SELECT * FROM plan_changes", ()
            if plan_id is not None:
                query += " WHERE plan_id=?"
                params = (plan_id,)
            return [decode(row) for row in db.execute(query + " ORDER BY created_at, id", params)]

    def record_plan_change(
        self, plan_id, feedback_id, day_date, changes, expected_profile_version,
        expected_feedback_revision, *, trigger_issues=None, evidence=None,
        expected_feedback_updated_at=None, expected_plan_change_count=None,
    ):
        """Append validated reductions; the confirmed base plan is immutable."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            plan = decode(db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone())
            feedback = decode(db.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone())
            if plan is None or feedback is None:
                raise NotFound("计划或反馈不存在。")
            profile_version = db.execute("SELECT MAX(version) FROM profiles").fetchone()[0]
            if (profile_version != expected_profile_version or plan["profile_version"] != profile_version
                    or plan["status"] != "confirmed"):
                raise Conflict("档案或计划已变化，请重新预览。")
            # A newer confirmed plan for the same profile and date window makes
            # this preview stale, even when the old plan itself remains valid.
            relevant = db.execute(
                """SELECT id FROM plans
                   WHERE status='confirmed' AND profile_version=?
                     AND date(?) >= date(start_date)
                     AND date(?) < date(start_date, '+7 day')
                   ORDER BY version DESC LIMIT 1""",
                (profile_version, day_date, day_date),
            ).fetchone()
            if relevant is None or relevant["id"] != plan_id:
                raise Conflict("当前日期已有更新的确认计划，请重新预览。")
            if (feedback["status"] != "confirmed" or feedback["revision"] != expected_feedback_revision
                    or feedback["date"] != day_date
                    or (expected_feedback_updated_at is not None
                        and feedback["updated_at"] != expected_feedback_updated_at)):
                raise Conflict("反馈已变化或日期不匹配，请重新预览。")
            day_index = (date.fromisoformat(day_date) - date.fromisoformat(plan["start_date"])).days
            if day_index not in range(7):
                raise ValueError("调整日期必须在计划的七天内。")
            if not isinstance(changes, list) or not 1 <= len(changes) <= 8:
                raise ValueError("调整必须包含 1 到 8 项。")
            fingerprint_data = [plan_id, feedback_id, day_date, expected_profile_version,
                                expected_feedback_revision, changes]
            fingerprint = hashlib.sha256(encode(fingerprint_data).encode()).hexdigest()
            existing = decode(db.execute(
                "SELECT * FROM plan_changes WHERE fingerprint=?", (fingerprint,)
            ).fetchone())
            if existing is not None:
                return existing
            prior = [decode(row) for row in db.execute(
                "SELECT * FROM plan_changes WHERE plan_id=? ORDER BY created_at, id", (plan_id,)
            )]
            if expected_plan_change_count is not None and len(prior) != expected_plan_change_count:
                raise Conflict("计划调整已变化，请重新预览。")
            days = [day for day in plan["data"].get("days", []) if day.get("day_index") == day_index]
            if len(days) != 1:
                raise ValueError("计划中不存在唯一对应日期。")
            effective = {}
            for previous in prior:
                for change in previous["changes"]:
                    effective[change["path"]] = change["new_value"]
            seen = set()
            for change in changes:
                if not isinstance(change, dict) or set(change) != {"path", "old_value", "new_value"}:
                    raise ValueError("调整项格式无效。")
                path = change["path"]
                match = re.fullmatch(r"days\.(\d+)\.exercises\.(\d+)\.sets", str(path))
                if (match is None or int(match[1]) != day_index or path in seen
                        or path != f"days.{day_index}.exercises.{int(match[2])}.sets"):
                    raise ValueError("仅允许调整指定日期的动作组数。")
                seen.add(path)
                exercise_index = int(match[2])
                exercises = days[0].get("exercises", [])
                if exercise_index >= len(exercises):
                    raise ValueError("动作不存在。")
                original = effective.get(path, exercises[exercise_index]["sets"])
                old, new = change["old_value"], change["new_value"]
                if (type(old) is not int or type(new) is not int or old != original
                        or not 1 <= new < old):
                    raise ValueError("只能减少组数，旧值必须与当前计划一致。")
            ident = str(uuid4())
            db.execute("INSERT INTO plan_changes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                ident, fingerprint, plan_id, feedback_id, day_date, expected_profile_version,
                expected_feedback_revision, encode(changes), encode(trigger_issues or []),
                encode(evidence or {}), now(),
            ))
            return decode(db.execute("SELECT * FROM plan_changes WHERE id=?", (ident,)).fetchone())
