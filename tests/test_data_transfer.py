import json
import sqlite3
import subprocess
import sys

import pytest

from fitness.exporting import render_export
from fitness.models import FeedbackData
from fitness.storage import Conflict, Store


def transfer_module():
    from fitness import data_transfer
    return data_transfer


def saved_feedback(store, day="2026-10-11", sleep=6):
    data = FeedbackData(date=day, sleep_hours=sleep, training_completed=True).model_dump(mode="json")
    draft = store.create_feedback("训练完成，睡了六小时", data, "demo", {"secret": "untrusted"})
    confirmed = store.confirm_feedback(draft["id"], data, 0)
    return store.save_advice(confirmed["id"], {"summary": "untrusted advice"}, None, 1,
                             trace={"secret": "untrusted"})


@pytest.mark.parametrize("format", ["json", "csv", "markdown"])
def test_import_export_preview_requires_confirmation_and_ignores_advice(tmp_path, format):
    transfer = transfer_module()
    source = Store(tmp_path / "source.db")
    feedback = saved_feedback(source)
    content = render_export("feedback", [feedback], format).content
    target = Store(tmp_path / "target.db")
    preview = transfer.preview_feedback_import(content, format)
    assert preview["errors"] == []
    assert len(preview["items"]) == 1
    assert target.feedback() == []
    with pytest.raises(ValueError, match="确认|confirm"):
        transfer.confirm_feedback_import(target, content, format, preview["batch_id"])
    result = transfer.confirm_feedback_import(target, content, format, preview["batch_id"], confirmed=True)
    assert result["imported"] == 1
    row = target.feedback()[0]
    assert row["status"] == "confirmed"
    assert row["data"]["sleep_hours"] == 6
    assert row["advice"] is None
    assert "untrusted" not in json.dumps(row["trace"])
    assert len(target.feedback_revisions(row["id"])) == 1
    repeated = transfer.confirm_feedback_import(target, content, format, preview["batch_id"], confirmed=True)
    assert repeated == result
    assert len(target.feedback()) == 1


def test_import_fingerprints_deduplicate_across_batches_and_preserve_distinct_same_date(tmp_path):
    transfer = transfer_module()
    store = Store(tmp_path / "test.db")
    first = json.dumps([{"date": "2026-10-11", "sleep_hours": 6}])
    p = transfer.preview_feedback_import(first, "json")
    transfer.confirm_feedback_import(store, first, "json", p["batch_id"], confirmed=True)
    second = json.dumps([{"date": "2026-10-11", "sleep_hours": 6},
                         {"date": "2026-10-11", "sleep_hours": 7}])
    p = transfer.preview_feedback_import(second, "json")
    result = transfer.confirm_feedback_import(store, second, "json", p["batch_id"], confirmed=True)
    assert result["imported"] == 1
    assert result["duplicates"] == 1
    assert len(store.feedback()) == 2


def test_invalid_batch_imports_nothing_and_rejects_changed_preview(tmp_path):
    transfer = transfer_module()
    store = Store(tmp_path / "test.db")
    content = json.dumps([{"date": "2026-10-11", "sleep_hours": 6},
                          {"date": "2026-10-12", "sleep_hours": 30}])
    preview = transfer.preview_feedback_import(content, "json")
    assert preview["errors"]
    with pytest.raises(ValueError):
        transfer.confirm_feedback_import(store, content, "json", preview["batch_id"], confirmed=True)
    valid = json.dumps([{"date": "2026-10-11", "sleep_hours": 6}])
    with pytest.raises(Conflict):
        transfer.confirm_feedback_import(store, valid, "json", preview["batch_id"], confirmed=True)
    assert store.feedback() == []


def test_draft_source_not_imported_and_unknown_fact_fields_rejected():
    transfer = transfer_module()
    content = json.dumps([{"status": "draft", "data": {"date": "2026-10-11"}},
                          {"date": "2026-10-11", "unrecognized_fact": "no"}])
    preview = transfer.preview_feedback_import(content, "json")
    assert preview["skipped"] == 1
    assert preview["errors"]


def test_backup_contains_committed_wal_and_refuses_existing_destination(tmp_path):
    transfer = transfer_module()
    source = Store(tmp_path / "source.db")
    # Keep a reader open so committed WAL frames cannot disappear at close.
    with sqlite3.connect(source.path) as keeper:
        keeper.execute("PRAGMA journal_mode=WAL")
        keeper.execute("SELECT * FROM feedback").fetchall()
        saved = saved_feedback(source)
        target = tmp_path / "backup.db"
        report = transfer.create_backup(source, target)
        assert report["counts"]["feedback"] == 1
        assert Store(target).get_feedback(saved["id"]) == saved
        with pytest.raises(FileExistsError):
            transfer.create_backup(source, target)


def test_restore_requires_explicit_fingerprints_and_preserves_previous_data(tmp_path):
    transfer = transfer_module()
    source = Store(tmp_path / "source.db")
    saved = saved_feedback(source)
    backup = tmp_path / "backup.db"
    transfer.create_backup(source, backup)
    target = tmp_path / "target.db"
    old = Store(target)
    old_profile = old.save_profile({"original": True}, 0)
    preview = transfer.preview_restore(backup, target)
    with pytest.raises(ValueError, match="确认|confirm"):
        transfer.restore_backup(backup, target, preview["source_fingerprint"])
    with pytest.raises(Conflict):
        transfer.restore_backup(backup, target, preview["source_fingerprint"], confirmed=True)
    result = transfer.restore_backup(backup, target, preview["source_fingerprint"], confirmed=True,
                                     expected_target_fingerprint=preview["target_fingerprint"])
    assert Store(target).get_feedback(saved["id"]) == saved
    assert Store(result["previous_backup"]).profile() == old_profile


def test_restore_rejects_modified_source_target_future_or_corrupt_schema(tmp_path):
    transfer = transfer_module()
    source = Store(tmp_path / "backup.db")
    target = tmp_path / "target.db"
    dest = Store(target)
    preview = transfer.preview_restore(source.path, target)
    dest.save_profile({"changed": True}, 0)
    with pytest.raises(Conflict):
        transfer.restore_backup(source.path, target, preview["source_fingerprint"], confirmed=True,
                                expected_target_fingerprint=preview["target_fingerprint"])
    assert dest.profile()["data"] == {"changed": True}
    malformed = tmp_path / "wrong.db"
    with sqlite3.connect(malformed) as db:
        db.execute("CREATE TABLE profiles(wrong TEXT)")
    with pytest.raises(ValueError):
        transfer.preview_restore(malformed)
    future = tmp_path / "future.db"
    Store(future)
    with sqlite3.connect(future) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError):
        transfer.preview_restore(future)


def test_cli_preview_performs_no_import_and_confirm_uses_preview_id(tmp_path):
    Store(tmp_path / "local.db")
    content_path = tmp_path / "feedback.json"
    content_path.write_text('[{"date":"2026-10-11","sleep_hours":6}]', encoding="utf-8")
    command = [sys.executable, "-m", "fitness.data_cli", "import-preview", "--source", str(content_path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    preview = json.loads(result.stdout)
    assert len(preview["items"]) == 1
    assert Store(tmp_path / "local.db").feedback() == []
    command = [sys.executable, "-m", "fitness.data_cli", "import-confirm", "--source", str(content_path),
               "--database", str(tmp_path / "local.db"), "--batch-id", preview["batch_id"], "--confirm"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["imported"] == 1


def test_restore_detects_wal_only_updates_and_preview_is_read_only(tmp_path):
    transfer = transfer_module()
    source = Store(tmp_path / "backup.db")
    target = Store(tmp_path / "target.db")
    with sqlite3.connect(target.path) as keeper:
        keeper.execute("PRAGMA wal_autocheckpoint=0")
        keeper.execute("BEGIN")
        keeper.execute("SELECT * FROM profiles").fetchall()
        preview = transfer.preview_restore(source.path, target.path)
        target.save_profile({"wal_only": True}, 0)
        with pytest.raises(Conflict):
            transfer.restore_backup(source.path, target.path, preview["source_fingerprint"], confirmed=True,
                                    expected_target_fingerprint=preview["target_fingerprint"])
        assert target.profile()["data"] == {"wal_only": True}


def test_restore_confirm_validates_schema_before_any_destination_write(tmp_path):
    transfer = transfer_module()
    corrupt = tmp_path / "corrupt.db"
    Store(corrupt)
    with sqlite3.connect(corrupt) as db:
        db.execute("DROP TABLE feedback")
        db.execute("CREATE TABLE feedback(wrong TEXT)")
    target = tmp_path / "existing.db"
    store = Store(target)
    store.save_profile({"preserve": True}, 0)
    import hashlib
    fingerprint = hashlib.sha256(corrupt.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        transfer.restore_backup(corrupt, target, fingerprint, confirmed=True,
                                expected_target_fingerprint=transfer.preview_restore(target)["source_fingerprint"])
    assert store.profile()["data"] == {"preserve": True}


def test_import_transaction_rolls_back_on_storage_failure(tmp_path):
    transfer = transfer_module()
    store = Store(tmp_path / "test.db")
    content = json.dumps([{"date": "2026-10-11"}, {"date": "2026-10-12"}])
    preview = transfer.preview_feedback_import(content, "json")
    with store.connection() as db:
        db.execute("""CREATE TRIGGER fail_second BEFORE INSERT ON feedback
                   WHEN NEW.date='2026-10-12' BEGIN SELECT RAISE(ABORT, 'write failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        transfer.confirm_feedback_import(store, content, "json", preview["batch_id"], confirmed=True)
    assert store.feedback() == []
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == 0


def test_legacy_backup_restore_migrates_and_preview_accepts_four_tables(tmp_path):
    transfer = transfer_module()
    legacy = Store(tmp_path / "legacy.db")
    profile = legacy.save_profile({"legacy": True}, 0)
    with legacy.connection() as db:
        db.execute("DROP TABLE import_items")
        db.execute("DROP TABLE import_batches")
        db.execute("DROP TABLE plan_changes")
        db.execute("PRAGMA user_version=0")
    preview = transfer.preview_restore(legacy.path)
    target = tmp_path / "new.db"
    transfer.restore_backup(legacy.path, target, preview["source_fingerprint"], confirmed=True)
    assert Store(target).profile() == profile
    with Store(target).connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3


def test_markdown_json_facts_are_validated_and_wrong_export_kind_rejected():
    transfer = transfer_module()
    content = '# Facts\n```json\n[{"date":"2026-10-11","sleep_hours":6}]\n```'
    preview = transfer.preview_feedback_import(content, "markdown")
    assert preview["items"][0]["data"]["sleep_hours"] == 6
    with pytest.raises(ValueError):
        transfer.preview_feedback_import('{"type":"advice","items":[{"date":"2026-10-11"}]}', "json")


def test_cli_unconfirmed_import_does_not_create_database(tmp_path):
    source = tmp_path / "feedback.json"
    source.write_text('[{"date":"2026-10-11"}]', encoding="utf-8")
    target = tmp_path / "never.db"
    command = [sys.executable, "-m", "fitness.data_cli", "import-confirm", "--source", str(source),
               "--database", str(target), "--batch-id", "x"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 2
    assert not target.exists()


@pytest.mark.parametrize("raw", [{"invalid": "object"}, ["invalid"], "x" * 4001])
def test_invalid_raw_text_is_rejected_during_preview_and_no_writes(tmp_path, raw):
    transfer = transfer_module()
    store = Store(tmp_path / "test.db")
    content = json.dumps([{"data": {"date": "2026-10-11"}, "raw_text": raw}])
    preview = transfer.preview_feedback_import(content, "json")
    assert preview["errors"]
    with pytest.raises(ValueError):
        transfer.confirm_feedback_import(store, content, "json", preview["batch_id"], confirmed=True)
    assert store.feedback() == []


def test_restore_rejects_target_created_while_source_snapshot_is_validated(tmp_path, monkeypatch):
    transfer = transfer_module()
    source = Store(tmp_path / "source.db")
    source.save_profile({"source": True}, 0)
    target = tmp_path / "racing.db"
    preview = transfer.preview_restore(source.path, target)
    real_store = transfer.Store
    def racing_store(path):
        if Path(path).name == "snapshot.db":
            real_store(target).save_profile({"appeared": True}, 0)
        return real_store(path)
    from pathlib import Path
    monkeypatch.setattr(transfer, "Store", racing_store)
    with pytest.raises(Conflict):
        transfer.restore_backup(source.path, target, preview["source_fingerprint"], confirmed=True)
    assert real_store(target).profile()["data"] == {"appeared": True}


def test_backup_refuses_destination_created_after_initial_check(tmp_path, monkeypatch):
    transfer = transfer_module()
    source = Store(tmp_path / "source.db")
    target = tmp_path / "racing.db"
    real_validate = transfer._validate_database
    def racing_validate(path):
        real_validate(path)
        Store(target).save_profile({"appeared": True}, 0)
    monkeypatch.setattr(transfer, "_validate_database", racing_validate)
    with pytest.raises(FileExistsError):
        transfer.create_backup(source, target)
    assert Store(target).profile()["data"] == {"appeared": True}
