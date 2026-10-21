import sqlite3

import pytest

from fitness.storage import SCHEMA_VERSION, Store


def test_existing_unversioned_database_migrates_without_losing_facts(tmp_path):
    path = tmp_path / "legacy.db"
    store = Store(path)
    saved = store.save_profile({"existing": "fact"}, 0)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=0")
        db.execute("DROP TABLE IF EXISTS plan_changes")
        db.execute("DROP TABLE IF EXISTS import_batches")
        db.execute("DROP TABLE IF EXISTS import_items")
    migrated = Store(path)
    assert migrated.profile() == saved
    with migrated.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {
            "profiles", "plans", "feedback", "feedback_revisions", "plan_changes", "import_batches", "import_items"
        }


def test_future_schema_rejected_before_schema_changes(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="schema|版本"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0


def change_fixture(tmp_path):
    store = Store(tmp_path / "changes.db")
    store.save_profile({"facts": True}, 0)
    days = [{"day_index": i, "kind": "training", "estimated_minutes": 40,
             "exercises": [{"exercise_id": "squat", "sets": 3}]} for i in range(7)]
    plan = store.create_plan({"days": days}, 1, "2026-10-11", "demo", {})
    plan = store.confirm_plan(plan["id"])
    data = {"date": "2026-10-11", "sleep_hours": 5}
    feedback = store.create_feedback("sleep", data, "demo", {})
    feedback = store.confirm_feedback(feedback["id"], data, 0)
    return store, plan, feedback


def test_plan_changes_are_idempotent_immutable_and_revision_guarded(tmp_path):
    from fitness.storage import Conflict

    store, plan, feedback = change_fixture(tmp_path)
    changes = [{"path": "days.0.exercises.0.sets", "old_value": 3, "new_value": 2}]
    record = store.record_plan_change(plan["id"], feedback["id"], "2026-10-11", changes, 1, 1)
    assert store.record_plan_change(plan["id"], feedback["id"], "2026-10-11", changes, 1, 1) == record
    assert store.plan_changes(plan["id"]) == [record]
    assert store.plans()[0]["data"] == plan["data"]
    store.save_profile({"changed": True}, 1)
    with pytest.raises(Conflict):
        store.record_plan_change(plan["id"], feedback["id"], "2026-10-11", changes, 1, 1)


@pytest.mark.parametrize("path,old,new", [
    ("days.1.exercises.0.sets", 3, 2), ("days.0.exercises.0.sets", 3, 4),
    ("days.0.exercises.0.sets", 3, 0), ("days.0.exercises.0.sets", 9, 2),
    ("days.0.exercises.4.sets", 3, 2), ("nutrition.approach", "a", "b"),
    ("days.00.exercises.0.sets", 3, 2), ("days.0.exercises.00.sets", 3, 2),
])
def test_plan_change_rejects_other_days_increases_and_invalid_old_values(tmp_path, path, old, new):
    store, plan, feedback = change_fixture(tmp_path)
    with pytest.raises(ValueError):
        store.record_plan_change(plan["id"], feedback["id"], "2026-10-11",
                                 [{"path": path, "old_value": old, "new_value": new}], 1, 1)
    assert store.plan_changes() == []


def test_plan_changes_require_confirmed_matching_feedback(tmp_path):
    from fitness.storage import Conflict

    store, plan, feedback = change_fixture(tmp_path)
    changes = [{"path": "days.0.exercises.0.sets", "old_value": 3, "new_value": 2}]
    with pytest.raises(Conflict):
        store.record_plan_change(plan["id"], feedback["id"], "2026-10-12", changes, 1, 1)
    with pytest.raises(Conflict):
        store.record_plan_change(plan["id"], feedback["id"], "2026-10-11", changes, 1, 0)


def test_saved_advice_adjustment_preview_carries_its_atomic_updated_timestamp(tmp_path):
    store, plan, feedback = change_fixture(tmp_path)
    changes = [{"path": "days.0.exercises.0.sets", "old_value": 3, "new_value": 2}]
    proposal = {"plan_id": plan["id"], "feedback_id": feedback["id"], "day_date": feedback["date"],
                "changes": changes, "expected_profile_version": 1, "expected_feedback_revision": 1,
                "expected_feedback_updated_at": feedback["updated_at"]}
    trace = {"training_adjustment_preview": proposal}
    advised = store.save_advice(feedback["id"], {"summary": "recovery"}, None, 1, trace=trace,
                               expected_updated_at=feedback["updated_at"], expected_profile_version=1)
    saved = advised["trace"]["training_adjustment_preview"]
    assert saved["expected_feedback_updated_at"] == advised["updated_at"]
    assert trace["training_adjustment_preview"]["expected_feedback_updated_at"] == feedback["updated_at"]
    assert store.record_plan_change(**saved)["changes"] == changes
