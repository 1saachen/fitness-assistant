"""Safe local import, export backup and restore helpers.

Import treats files as untrusted input: only validated FeedbackData facts are
accepted; generated advice and trace fields are intentionally discarded.
"""

import csv
import hashlib
import io
import json
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .models import FeedbackData
from .storage import SCHEMA_VERSION, Conflict, Store, decode, encode, now


@contextmanager
def _sqlite(path, **kwargs):
    db = sqlite3.connect(path, **kwargs)
    try:
        with db:
            yield db
    finally:
        db.close()


def _fingerprint(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def _parse_rows(content: str, import_format: str):
    if import_format == "json":
        payload = json.loads(content)
        if isinstance(payload, dict):
            if payload.get("type", "feedback") != "feedback" or payload.get("export_version", 1) != 1:
                raise ValueError("仅支持版本 1 的反馈导入文件。")
            payload = payload.get("items", [payload])
        if not isinstance(payload, list):
            raise ValueError("JSON 导入需要记录列表。")
        return payload
    if import_format == "csv":
        rows = list(csv.DictReader(io.StringIO(content)))
        return [{"status": row.get("status", "confirmed"), "raw_text": row.get("raw_text", ""),
                 "data": {key: value for key, value in row.items() if key in _FACT_FIELDS}}
                for row in rows]
    if import_format == "markdown":
        blocks = re.findall(r"```json\s*\n(.*?)\n```", content, re.DOTALL)
        if blocks:
            return [row for block in blocks for row in _parse_rows(block, "json")]
        rows = []
        for match in re.finditer(r"##\s+(\d{4}-\d{2}-\d{2}).*?(?=\n##\s+|\Z)", content, re.DOTALL):
            section = match.group(0)
            status = re.search(r"反馈状态：\s*(\w+)", section)
            row = {"data": {"date": match.group(1)}, "status": status.group(1) if status else "confirmed"}
            facts = row["data"]
            sleep = re.search(r"睡眠：\s*([0-9]+(?:\.[0-9]+)?)", section)
            if sleep:
                facts["sleep_hours"] = float(sleep.group(1))
            training = re.search(r"训练：\s*(.+)", section)
            if training and training.group(1).strip() not in {"未记录", "无"}:
                facts["training_summary"] = training.group(1).strip()
            fatigue = re.search(r"疲劳：\s*(.+)", section)
            if fatigue and fatigue.group(1).strip() not in {"未记录", "无"}:
                facts["fatigue"] = fatigue.group(1).strip()
            raw = re.search(r"原始记录：\s*(.+)", section)
            row["raw_text"] = raw.group(1).strip() if raw else ""
            rows.append(row)
        if not rows:
            raise ValueError("Markdown 中未找到反馈记录。")
        return rows
    raise ValueError(f"不支持的导入格式：{import_format}")


_FACT_FIELDS = set(FeedbackData.model_fields)


def _fact_from_row(row):
    if not isinstance(row, dict):
        raise TypeError("记录必须是对象。")
    if "status" in row and row["status"] != "confirmed":
        return None
    raw_text = row.get("raw_text", "")
    if not isinstance(raw_text, str) or len(raw_text) > 4000:
        raise ValueError("raw_text 必须是 4000 字以内的文本。")
    raw = row.get("data") if isinstance(row.get("data"), dict) else row
    # Export columns contain generated fields and CSV strings; only known facts survive.
    unknown = set(raw) - _FACT_FIELDS
    if unknown:
        raise ValueError(f"未知事实字段：{', '.join(sorted(unknown))}")
    clean = dict(raw)
    for key in ("training_completed", "diet_followed_plan"):
        if isinstance(clean.get(key), str):
            text = clean[key].strip().lower()
            if not text:
                clean[key] = None
            elif text in {"true", "1", "yes", "是"}:
                clean[key] = True
            elif text in {"false", "0", "no", "否"}:
                clean[key] = False
            else:
                raise ValueError(f"{key} 必须为布尔值或留空。")
    for key in ("sleep_hours", "sleep_date", "weight_kg", "intake_kcal"):
        if clean.get(key) in ("", None):
            clean.pop(key, None)
    if isinstance(clean.get("uncertainties"), str):
        try:
            clean["uncertainties"] = json.loads(clean["uncertainties"])
        except json.JSONDecodeError:
            clean["uncertainties"] = [clean["uncertainties"]]
    return FeedbackData.model_validate(clean).model_dump(mode="json")


def preview_feedback_import(content: str, import_format: str = "json") -> dict:
    """Parse and validate an import without writing any database state."""
    try:
        rows = _parse_rows(content, import_format)
    except (ValueError, json.JSONDecodeError, csv.Error) as exc:
        raise ValueError(f"无法解析导入：{exc}") from exc
    items, errors, skipped = [], [], 0
    for index, row in enumerate(rows):
        try:
            fact = _fact_from_row(row)
            if fact is None:
                skipped += 1
                continue
            items.append({
                "fingerprint": _fingerprint(fact), "data": fact,
                "raw_text": row.get("raw_text", "") if isinstance(row, dict) else "",
            })
        except (ValidationError, ValueError, TypeError) as exc:
            errors.append({"index": index, "error": str(exc)})
    batch_id = _fingerprint({"format": import_format, "content": content})
    return {"batch_id": batch_id, "format": import_format, "items": items,
            "errors": errors, "skipped": skipped}


def confirm_feedback_import(store: Store, content: str, import_format: str,
                            expected_batch_id: str, *, confirmed: bool = False) -> dict:
    if not confirmed:
        raise ValueError("导入确认前不会写入数据，请提供 confirmed=True。")
    preview = preview_feedback_import(content, import_format)
    if preview["batch_id"] != expected_batch_id:
        raise Conflict("预览批次已变化，请重新预览。")
    if preview["errors"]:
        raise ValueError("预览中存在无效记录，未导入任何数据。")
    imported, duplicates, records = 0, 0, []
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        existing_batch = db.execute("SELECT result FROM import_batches WHERE batch_id=?", (expected_batch_id,)).fetchone()
        if existing_batch:
            return json.loads(existing_batch[0])
        db.execute("INSERT INTO import_batches VALUES (?, ?, ?)", (expected_batch_id, "{}", now()))
        for item in preview["items"]:
            if db.execute("SELECT 1 FROM import_items WHERE fingerprint=?", (item["fingerprint"],)).fetchone():
                duplicates += 1
                continue
            ident, stamp = _fingerprint([expected_batch_id, item["fingerprint"]])[:32], now()
            # UUID-like stable ids are unnecessary; this id is unique per batch/fact.
            db.execute("INSERT INTO feedback VALUES (?, ?, ?, 'confirmed', 1, ?, NULL, NULL, 'demo', ?, ?, ?)",
                       (ident, item["data"]["date"], item["raw_text"], encode(item["data"]), encode({}), stamp, stamp))
            db.execute("INSERT INTO feedback_revisions VALUES (?, 1, ?, ?)", (ident, encode(item["data"]), stamp))
            db.execute("INSERT INTO import_items VALUES (?, ?, ?)", (item["fingerprint"], ident, expected_batch_id))
            record = decode(db.execute("SELECT * FROM feedback WHERE id=?", (ident,)).fetchone())
            records.append(record)
            imported += 1
        result = {"batch_id": expected_batch_id, "imported": imported,
                  "duplicates": duplicates, "records": records}
        db.execute("UPDATE import_batches SET result=? WHERE batch_id=?", (encode(result), expected_batch_id))
        return result


def _db_fingerprint(path: Path) -> str:
    with _sqlite(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        return _connection_fingerprint(db)


def _connection_fingerprint(db):
    digest = hashlib.sha256()
    schema = list(db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"))
    digest.update(encode([db.execute("PRAGMA user_version").fetchone()[0], schema]).encode())
    for kind, name, _ in schema:
        if kind == "table":
            quoted = '"' + name.replace('"', '""') + '"'
            rows = sorted(encode(list(row)) for row in db.execute(f"SELECT * FROM {quoted}"))
            digest.update(encode([name, rows]).encode())
    return digest.hexdigest()


def _counts(path: Path):
    with _sqlite(path) as db:
        try:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] if name in tables else 0
                    for name in ("profiles", "plans", "feedback", "feedback_revisions", "plan_changes",
                                 "import_batches", "import_items", "long_term_plans", "daily_plans",
                                 "personal_memory", "feedback_coaching")}
        except sqlite3.Error as exc:
            raise ValueError("不是有效的 fitness 数据库。") from exc


def _validate_database(path: Path):
    required = {"profiles", "plans", "feedback", "feedback_revisions"}
    columns = {
        "profiles": {"version", "data", "created_at"},
        "plans": {"id", "version", "profile_version", "start_date", "status", "data", "mode", "trace", "created_at"},
        "feedback": {"id", "date", "raw_text", "status", "revision", "data", "trace", "created_at",
                     "updated_at", "advice", "advice_error", "mode"},
        "feedback_revisions": {"feedback_id", "revision", "data", "created_at"},
        "plan_changes": {"id", "fingerprint", "plan_id", "feedback_id", "day_date", "profile_version",
                         "feedback_revision", "changes", "trigger_issues", "evidence", "created_at"},
        "import_batches": {"batch_id", "result", "created_at"},
        "import_items": {"fingerprint", "feedback_id", "batch_id"},
        "long_term_plans": {"id", "version", "profile_version", "start_date", "status",
                            "data", "trace", "created_at"},
        "daily_plans": {"id", "date", "revision", "long_term_id", "profile_version",
                        "data", "trace", "input_fingerprint", "created_at"},
        "personal_memory": {"version", "data", "trace", "created_at"},
        "feedback_coaching": {"feedback_id", "request_key", "parent_feedback_id", "timing",
                              "status", "input_token", "data", "trace", "updated_at"},
    }
    try:
        with _sqlite(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.execute("BEGIN")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("Unsupported future database schema version")
            if version >= 2:
                required.add("plan_changes")
            if version >= 3:
                required.update(("import_batches", "import_items"))
            if version >= 4:
                required.update(("long_term_plans", "daily_plans"))
            if version >= 5:
                required.update(("personal_memory", "feedback_coaching"))
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required <= tables or tables - set(columns):
                raise ValueError("数据库缺少 fitness 必需表。")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
                raise ValueError("恢复不支持自定义触发器或视图。")
            for table in tables:
                expected = columns[table]
                actual = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                if expected != actual:
                    raise ValueError(f"数据库表 {table} 结构无效。")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("数据库完整性检查失败。")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("数据库关联记录不完整。")
    except sqlite3.Error as exc:
        raise ValueError("不是有效的 fitness 数据库。") from exc


def create_backup(store: Store, destination: Path) -> dict:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _validate_database(store.path)
    # Reserve the name atomically; a late creator must never be overwritten.
    with destination.open("xb"):
        pass
    # sqlite backup includes committed WAL frames and gives a transaction-consistent snapshot.
    with store.connection() as source, _sqlite(destination) as target:
        source.backup(target)
    return {"path": str(destination), "fingerprint": _db_fingerprint(destination), "counts": _counts(destination)}


def preview_restore(source: Path, target: Path | None = None) -> dict:
    source, target = Path(source), Path(target) if target is not None else None
    if not source.exists():
        raise FileNotFoundError(source)
    _validate_database(source)
    return {"source": str(source), "source_fingerprint": _db_fingerprint(source),
            "target": str(target) if target else None,
            "target_fingerprint": _db_fingerprint(target) if target and target.exists() else None,
            "counts": _counts(source)}


def restore_backup(source: Path, target: Path, expected_source_fingerprint: str, *,
                   confirmed: bool = False, expected_target_fingerprint: str | None = None) -> dict:
    if not confirmed:
        raise ValueError("恢复会替换本地数据库，请先预览并提供 confirmed=True。")
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise ValueError("备份来源与恢复目标不能相同。")
    _validate_database(source)
    existed = target.exists()
    previous_backup = None
    with tempfile.TemporaryDirectory(prefix="fitness-restore-") as temporary:
        snapshot = Path(temporary) / "snapshot.db"
        with _sqlite(source.resolve().as_uri() + "?mode=ro", uri=True) as incoming, _sqlite(snapshot) as copied:
            incoming.backup(copied)
        _validate_database(snapshot)
        if _db_fingerprint(snapshot) != expected_source_fingerprint:
            raise Conflict("备份文件已变化，请重新预览。")
        migrated = Store(snapshot)
        if existed:
            _validate_database(target)
        elif expected_target_fingerprint is not None:
            raise Conflict("目标数据库已变化，请重新预览。")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not existed:
            try:
                with target.open("xb"):
                    pass
            except FileExistsError as exc:
                raise Conflict("目标数据库在预览后出现，请重新预览。") from exc
        # Replace data inside SQLite's writer transaction, never replace an open
        # database file or leave old WAL frames beside a new database.
        with _sqlite(target, timeout=10) as destination, migrated.connection() as incoming:
            destination.execute("PRAGMA foreign_keys=OFF")
            destination.execute("BEGIN IMMEDIATE")
            if not existed and destination.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]:
                raise Conflict("目标数据库在预览后出现，请重新预览。")
            if existed and _connection_fingerprint(destination) != expected_target_fingerprint:
                raise Conflict("目标数据库已变化，请重新预览。")
            if existed:
                suffix = datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')
                previous_backup = target.with_name(target.name + f".before-restore-{suffix}.db")
                with _sqlite(target) as original, _sqlite(previous_backup) as preserved:
                    original.backup(preserved)
            for (name,) in destination.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                destination.execute(f'DROP TABLE "{name}"')
            for name, sql in incoming.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"):
                destination.execute(sql)
                rows = incoming.execute(f'SELECT * FROM "{name}"').fetchall()
                if rows:
                    values = ','.join('?' for _ in rows[0])
                    destination.executemany(f'INSERT INTO "{name}" VALUES ({values})', [tuple(row) for row in rows])
            destination.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            if destination.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("恢复的数据库关联记录不完整。")
    return {"path": str(target), "previous_backup": str(previous_backup) if previous_backup else None,
            "fingerprint": _db_fingerprint(target), "counts": _counts(target)}
