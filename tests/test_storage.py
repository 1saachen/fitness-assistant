import pytest

from fitness.models import FeedbackData, Profile


def test_profile_survives_reopen_and_rejects_stale_edit(tmp_path, profile_data):
    from fitness.storage import Conflict, Store
    db = tmp_path / "test.db"
    store = Store(db)
    p = Profile.model_validate(profile_data).model_dump(mode="json")
    saved = store.save_profile(p, 0)
    assert Store(db).profile() == saved
    with pytest.raises(Conflict):
        store.save_profile(p, 0)


def test_feedback_confirmation_is_idempotent_and_corrections_have_history(tmp_path):
    from fitness.storage import Conflict, Store
    store = Store(tmp_path / "test.db")
    data = FeedbackData(date="2026-09-10", sleep_hours=6).model_dump(mode="json")
    draft = store.create_feedback("睡了六小时", data, "demo", [])
    assert store.feedback()[0]["status"] != "confirmed"
    record = store.confirm_feedback(draft["id"], data, 0)
    assert store.confirm_feedback(draft["id"], data, 0) == record
    assert len(store.feedback()) == 1
    corrected = dict(data, sleep_hours=7)
    with pytest.raises(Conflict):
        store.confirm_feedback(draft["id"], corrected, 0)
    updated = store.confirm_feedback(draft["id"], corrected, 1)
    assert updated["revision"] == 2
    assert len(store.feedback_revisions(draft["id"])) == 2
    assert store.feedback_revisions(draft["id"])[0]["data"]["sleep_hours"] == 6


def test_plan_cannot_confirm_after_profile_changes(tmp_path, profile_data):
    from fitness.storage import Conflict, Store
    store = Store(tmp_path / "test.db")
    p = Profile.model_validate(profile_data).model_dump(mode="json")
    store.save_profile(p, 0)
    plan = store.create_plan({"title": "draft"}, 1, "2026-09-10", "demo", [])
    store.save_profile(p, 1)
    with pytest.raises(Conflict):
        store.confirm_plan(plan["id"])
    assert store.plans()[0]["profile_version"] == 1
    assert store.plans()[0]["status"] == "draft"


def test_advice_failure_does_not_lose_feedback(tmp_path):
    from fitness.storage import Store
    store = Store(tmp_path / "test.db")
    data = FeedbackData(date="2026-09-10").model_dump(mode="json")
    draft = store.create_feedback("今天休息", data, "demo", [])
    store.confirm_feedback(draft["id"], data, 0)
    store.save_advice(draft["id"], None, "模型暂时不可用", 1)
    assert store.get_feedback(draft["id"])["status"] == "confirmed"
    assert store.get_feedback(draft["id"])["advice_error"] == "模型暂时不可用"


def test_save_advice_atomically_persists_trace_and_legacy_success_preserves_it(tmp_path):
    from fitness.storage import Store

    store = Store(tmp_path / "test.db")
    data = FeedbackData(date="2026-09-21", sleep_hours=6).model_dump(mode="json")
    draft = store.create_feedback("睡了六小时", data, "demo", {"steps": ["parser"]})
    confirmed = store.confirm_feedback(draft["id"], data, 0)
    trace = {
        "steps": ["issue_extraction", "knowledge_retrieval", "advisor"],
        "issues": ["short_sleep"],
        "knowledge_query_terms": ["睡眠", "恢复"],
        "knowledge_item_ids": ["sleep-001"],
        "knowledge_status": "ok",
    }

    saved = store.save_advice(
        draft["id"],
        {"summary": "建议", "suggestions": ["早点休息"]},
        None,
        confirmed["revision"],
        trace=trace,
    )
    assert saved["trace"] == trace
    assert store.get_feedback(draft["id"])["trace"] == trace

    legacy = store.save_advice(
        draft["id"],
        {"summary": "更新建议", "suggestions": ["继续观察"]},
        None,
        confirmed["revision"],
    )
    assert legacy["trace"] == trace
    assert store.get_feedback(draft["id"])["trace"] == trace


def test_feedback_revision_clears_advice_and_retrieval_trace_atomically(tmp_path):
    from fitness.storage import Store

    store = Store(tmp_path / "test.db")
    data = FeedbackData(date="2026-09-21", sleep_hours=6).model_dump(mode="json")
    draft = store.create_feedback("睡了六小时", data, "demo", {"steps": ["parser"]})
    confirmed = store.confirm_feedback(draft["id"], data, 0, trace={"steps": ["parser"]})
    advice_trace = {
        "steps": ["issue_extraction", "knowledge_retrieval", "advisor"],
        "issues": ["short_sleep"],
        "knowledge_query_terms": ["睡眠", "恢复"],
        "knowledge_item_ids": ["sleep-001"],
        "knowledge_status": "ok",
    }
    advised = store.save_advice(
        draft["id"],
        {"summary": "建议", "suggestions": ["早点休息"]},
        None,
        confirmed["revision"],
        trace=advice_trace,
    )
    assert store.confirm_feedback(draft["id"], data, confirmed["revision"]) == advised

    corrected = dict(data, sleep_hours=7.5)
    revised = store.confirm_feedback(
        draft["id"],
        corrected,
        confirmed["revision"],
        trace={"steps": ["parser"]},
    )
    assert revised["advice"] is None
    assert revised["advice_error"] is None
    assert revised["trace"] == {"steps": ["parser"]}
    assert store.get_feedback(draft["id"])["trace"] == {"steps": ["parser"]}


def test_save_advice_rejects_reused_snapshot_and_stale_profile(tmp_path, profile_data, monkeypatch):
    from fitness import storage as storage_module
    from fitness.storage import Conflict, Store

    store = Store(tmp_path / "test.db")
    profile = Profile.model_validate(profile_data).model_dump(mode="json")
    saved_profile = store.save_profile(profile, 0)
    data = FeedbackData(date="2026-09-21", sleep_hours=6).model_dump(mode="json")
    draft = store.create_feedback("睡了六小时", data, "demo", {"steps": ["parser"]})
    confirmed = store.confirm_feedback(draft["id"], data, 0)
    monkeypatch.setattr(storage_module, "now", lambda: confirmed["updated_at"])
    first = store.save_advice(
        draft["id"],
        {"summary": "第一次", "suggestions": ["早点休息"]},
        None,
        confirmed["revision"],
        trace={"steps": ["advisor"], "status": "ok"},
        expected_updated_at=confirmed["updated_at"],
        expected_profile_version=saved_profile["version"],
    )

    with pytest.raises(Conflict):
        store.save_advice(
            draft["id"],
            {"summary": "第二次", "suggestions": ["覆盖第一次"]},
            None,
            confirmed["revision"],
            trace={"steps": ["advisor"], "status": "ok"},
            expected_updated_at=confirmed["updated_at"],
            expected_profile_version=saved_profile["version"],
        )
    assert store.get_feedback(draft["id"])["advice"] == first["advice"]

    current = store.get_feedback(draft["id"])
    store.save_profile(profile, saved_profile["version"])
    with pytest.raises(Conflict):
        store.save_advice(
            draft["id"],
            {"summary": "旧档案", "suggestions": ["不应保存"]},
            None,
            current["revision"],
            trace={"steps": ["advisor"], "status": "ok"},
            expected_updated_at=current["updated_at"],
            expected_profile_version=saved_profile["version"],
        )
    assert store.get_feedback(draft["id"])["advice"] == first["advice"]


def test_failed_advice_without_trace_replaces_old_retrieval_trace(tmp_path):
    from fitness.storage import Store

    store = Store(tmp_path / "test.db")
    data = FeedbackData(date="2026-09-21", sleep_hours=6).model_dump(mode="json")
    draft = store.create_feedback("睡了六小时", data, "demo", {"steps": ["parser"]})
    confirmed = store.confirm_feedback(draft["id"], data, 0)
    retrieval_trace = {
        "steps": ["issue_extraction", "knowledge_retrieval", "advisor"],
        "issues": ["short_sleep"],
        "knowledge_item_ids": ["sleep-001"],
        "knowledge_status": "ok",
    }
    success = store.save_advice(
        draft["id"],
        {"summary": "建议", "suggestions": ["早点休息"]},
        None,
        confirmed["revision"],
        trace=retrieval_trace,
    )

    failed = store.save_advice(
        draft["id"],
        None,
        "模型暂时不可用",
        confirmed["revision"],
        expected_updated_at=success["updated_at"],
    )
    assert failed["advice"] is None
    assert failed["advice_error"] == "模型暂时不可用"
    assert failed["trace"] == {"steps": ["advisor"], "status": "failed"}

