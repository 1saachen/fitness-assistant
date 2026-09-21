"""Transactional, versioned local storage. Generated drafts never overwrite facts."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


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
    for key in ("data", "trace", "advice"):
        if key in result and result[key] is not None:
            result[key] = json.loads(result[key])
    return result


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
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
            """)

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

    def feedback(self):
        with self.connection() as db:
            return [decode(r) for r in db.execute(
                "SELECT * FROM feedback ORDER BY date DESC, created_at DESC LIMIT 100"
            )]

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
            if trace is not None:
                saved_trace = encode(trace)
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
                    next_stamp(row["updated_at"]),
                    ident,
                    expected_revision,
                    snapshot_updated_at,
                ),
            )
            if updated.rowcount != 1:
                raise Conflict("反馈已变化，请重新生成建议。")
            return decode(db.execute("SELECT * FROM feedback WHERE id=?", (ident,)).fetchone())
