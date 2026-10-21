import atexit
import importlib
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fitness.config import Settings
from fitness.knowledge_context import KnowledgeContextResult, KnowledgeContextService
from fitness.models import AdviceData, FeedbackData, KnowledgeCitation, StrategySnapshot
from fitness.provider import ProviderReply
from fitness.review import ReviewService
from fitness.storage import Store

_MAIN_IMPORT_DIRECTORY = tempfile.TemporaryDirectory(prefix="fitness-api-tests-")
atexit.register(_MAIN_IMPORT_DIRECTORY.cleanup)
_PREVIOUS_DB_PATH = os.environ.get("FITNESS_DB_PATH")
os.environ["FITNESS_DB_PATH"] = str(Path(_MAIN_IMPORT_DIRECTORY.name) / "import.sqlite3")
main = importlib.import_module("fitness.main")
if _PREVIOUS_DB_PATH is None:
    del os.environ["FITNESS_DB_PATH"]
else:
    os.environ["FITNESS_DB_PATH"] = _PREVIOUS_DB_PATH


def legacy_trace(trace):
    """Old trace contract is preserved alongside the new tool/usage metadata."""
    return {key: value for key, value in trace.items()
            if key not in {'tool_calls', 'provider', 'trend', 'similar_history', 'training_adjustment_preview',
                           'nutrition_planner', 'parser_provider'}}


def write_knowledge_library(root):
    source = {
        "id": "test-source",
        "creator_name": "Test creator",
        "video_title": "Test video",
        "video_url": "https://example.org/video",
        "published_at": "2026-09-01",
    }
    (root / "sources").mkdir(parents=True)
    (root / "sources" / "source.json").write_text(json.dumps(source), encoding="utf-8")
    cards = [
        *[("sleep_recovery", f"睡眠 睡眠时长 恢复 {index}") for index in range(3)],
        *[("training", f"疲劳 恢复 训练量 {index}") for index in range(3)],
        *[("fat_loss", f"饮食记录 隐藏热量 蛋白质 {index}") for index in range(3)],
    ]
    item_ids = []
    for index, (collection, title) in enumerate(cards):
        item_id = f"api-card-{index:02d}"
        item_ids.append(item_id)
        folder = root / collection
        folder.mkdir(exist_ok=True)
        item = {
            "id": item_id,
            "collection": collection,
            "title": title,
            "claim": title,
            "source_id": source["id"],
            "source_type": "creator_opinion",
            "evidence_level": "limited",
            "review_status": "approved",
        }
        (folder / f"{index}.json").write_text(json.dumps(item), encoding="utf-8")
    artifact = {
        "version": 1,
        "coverage": {"approved": len(item_ids), "covered": len(item_ids), "reference_only": 0},
        "strategies": [
            {
                "id": "api-baseline",
                "domain": "training",
                "title": "API baseline",
                "summary": "Reviewed baseline used by the API integration test.",
                "action_rules": ["Keep changes sustainable."],
                "applicability": ["fat_loss"],
                "knowledge_item_ids": item_ids,
            }
        ],
        "reference_only": [],
    }
    strategy_path = root / "baseline-strategies.json"
    strategy_path.write_text(json.dumps(artifact), encoding="utf-8")
    return strategy_path


def configure_client(tmp_path, monkeypatch, *, missing_strategy=False):
    monkeypatch.setattr(main, 'settings', Settings(api_key='synthetic-test-key'))

    class ModelProvider:
        def complete(self, messages, tools=None, **kwargs):
            payload = json.loads(messages[1]['content'])
            if '你是饮食规划 Agent' in messages[0]['content']:
                from test_agent_runtime import final
                return final({'approach': '测试模型按当次条件安排单餐',
                    'daily_targets': payload['reference_targets'], 'questions': [], 'budget_note': '按实际价格核实',
                    'meal_options': [{'meal': payload.get('meal') or '午餐',
                        'suggestions': [payload.get('desired_foods') or '米饭配青菜', payload.get('conditions') or '份量按需调整']}]})
            baseline = payload['baseline']
            candidate = baseline if 'text' in payload else {'summary': baseline['summary']}
            return ProviderReply(content=json.dumps(candidate, ensure_ascii=False))

    monkeypatch.setattr('fitness.provider.OpenAICompatibleProvider', lambda _: ModelProvider())
    monkeypatch.setattr('fitness.nutrition_live.OpenAICompatibleProvider', lambda _: ModelProvider())
    monkeypatch.setattr(main, "store", Store(tmp_path / "test.sqlite3"))
    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        '{"cards":[{"id":"supplements-001","collection":"supplements",'
        '"title":"肌酸","creator_statement":[{"statement":"作者认为肌酸有助于力量训练",'
        '"source_claim_ids":["bili:BVtest001:1"]}],"source_claim_ids":["bili:BVtest001:1"],'
        '"source_bvids":["BVtest001"],"uncertainty":"待复核",'
        '"safety_boundary":"不构成医疗建议","review_status":"pending"}]}',
        encoding="utf-8",
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"videos":[{"bvid":"BVtest001","url":"https://example.com/BVtest001",'
        '"title":"测试视频","owner_name":"测试创作者","published_date":"2026-09-20"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        main,
        "review_service",
        ReviewService(candidates, tmp_path / "reviews.json", tmp_path / "knowledge", catalog),
    )
    knowledge_root = tmp_path / "approved-knowledge"
    strategy_path = write_knowledge_library(knowledge_root)
    if missing_strategy:
        strategy_path.unlink()
    monkeypatch.setattr(
        main,
        "knowledge_context_service",
        KnowledgeContextService(knowledge_root, strategy_path),
        raising=False,
    )
    return TestClient(main.app)


@pytest.fixture
def client(tmp_path, monkeypatch):
    return configure_client(tmp_path, monkeypatch)


@pytest.fixture
def unavailable_client(tmp_path, monkeypatch):
    return configure_client(tmp_path, monkeypatch, missing_strategy=True)


def test_main_import_uses_isolated_test_database():
    real_database = main.ROOT / "data/local/fitness.sqlite3"
    assert main.store.path.resolve() != real_database.resolve()


def test_profile_version_survives_reload(client, profile_data):
    for version in range(3):
        response = client.put("/api/profile", json={"profile": profile_data, "expected_version": version})
        assert response.status_code == 200
        assert client.get("/api/state").json()["profile_version"] == version + 1
    conflict = client.put("/api/profile", json={"profile": profile_data, "expected_version": 1})
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "profile_version_conflict",
        "message": "档案已有更新，请刷新后再保存。",
        "retryable": True,
    }


def test_profile_endpoint_accepts_an_empty_optional_profile(client):
    response = client.put('/api/profile', json={'profile': {}, 'expected_version': 0})
    assert response.status_code == 200
    assert response.json()['data']['personal']['weight_kg'] is None
    assert response.json()['data']['goals']['primary'] is None


def test_strength_baseline_round_trips_without_becoming_mandatory(client):
    baseline = {'bench_press_1rm_kg': 80, 'pull_up_max_reps': 0,
                'recorded_on': '2026-10-21', 'notes': '估算，含杆总重'}
    response = client.put('/api/profile', json={'profile': {
        'training': {'strength_baseline': baseline}}, 'expected_version': 0})
    assert response.status_code == 200
    saved = client.get('/api/state').json()['profile']['training']['strength_baseline']
    assert saved.items() >= baseline.items()
    assert saved['squat_1rm_kg'] is None


def test_complete_confirm_correct_flow(client, profile_data):
    assert client.post("/api/plans", json={"start_date": "2026-09-14", "mode": "live"}).status_code == 409
    client.put("/api/profile", json={"profile": profile_data, "expected_version": 0})
    plan = client.post("/api/plans", json={"start_date": "2026-09-14", "mode": "live"}).json()
    assert plan["status"] == "draft"
    assert plan["data"]["strategy_context"]
    assert plan["data"]["knowledge_context"]
    assert legacy_trace(plan["trace"]) == {
        "steps": ["baseline_strategy_selection", "planner"],
        "strategy_ids": ["api-baseline"],
        "knowledge_item_ids": plan["data"]["source_ids"],
        "knowledge_status": "ok",
    }
    assert client.post(f"/api/plans/{plan['id']}/confirm").json()["status"] == "confirmed"
    feedback = client.post(
        "/api/feedback/parse",
        json={"text": "完成训练，睡了6小时，今天很累，吃食堂", "date": "2026-09-14", "mode": "live"},
    ).json()
    path = f"/api/feedback/{feedback['id']}"
    assert feedback["data"]["intake_kcal"] is None
    assert client.post(path + "/advice", json={"mode": "live"}).status_code == 409
    feedback["data"]["food_summary"] = None
    confirmed = client.post(path + "/confirm", json={"data": feedback["data"], "expected_revision": 0}).json()
    assert confirmed["revision"] == 1
    advised = client.post(path + "/advice", json={"mode": "live"}).json()
    assert advised["advice"]["knowledge_context"]
    assert len(advised["advice"]["knowledge_context"]) > 5
    assert legacy_trace(advised["trace"]) == {
        "steps": ["issue_extraction", "knowledge_retrieval", "advisor"],
        "issues": ["short_sleep", "training_fatigue", "diet_adherence"],
        "profile_goal": "fat_loss",
        "issue_goal_context": [
            {"issue": "short_sleep", "terms": ["减脂"], "collections": ["fat_loss"]},
            {"issue": "training_fatigue", "terms": ["减脂"], "collections": ["fat_loss"]},
            {"issue": "diet_adherence", "terms": ["减脂"], "collections": ["fat_loss"]},
        ],
        "knowledge_query_terms": [
            "睡眠",
            "睡眠时长",
            "恢复",
            "疲劳",
            "训练量",
            "饮食记录",
            "隐藏热量",
            "蛋白质",
        ],
        "knowledge_item_ids": advised["advice"]["source_ids"],
        "knowledge_status": "ok",
    }
    persisted = next(
        item for item in client.get("/api/state").json()["feedback"] if item["id"] == feedback["id"]
    )
    assert persisted["trace"] == advised["trace"]
    confirmed["data"]["sleep_hours"] = 7.5
    corrected = client.post(
        path + "/confirm", json={"data": confirmed["data"], "expected_revision": 1}
    ).json()
    assert corrected["advice"] is None
    assert corrected['trace']['steps'] == ['parser']
    assert corrected['trace']['parser_provider']['status'] == 'ok'
    persisted_after_correction = next(
        item for item in client.get("/api/state").json()["feedback"] if item["id"] == feedback["id"]
    )
    assert persisted_after_correction["advice"] is None
    assert persisted_after_correction['trace']['steps'] == ['parser']
    assert persisted_after_correction['trace']['parser_provider']['status'] == 'ok'
    assert len(client.get(path + "/revisions").json()) == 2


def test_missing_knowledge_artifact_degrades_without_blocking_core_api(
    unavailable_client, profile_data,
):
    unavailable_client.put("/api/profile", json={"profile": profile_data, "expected_version": 0})
    assert unavailable_client.get("/api/state").json()["knowledge_status"] == "unavailable"
    plan_response = unavailable_client.post(
        "/api/plans", json={"start_date": "2026-09-21", "mode": "live"}
    )
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["data"]["strategy_context"] == []
    assert plan["data"]["knowledge_context"] == []
    assert legacy_trace(plan["trace"]) == {
        "steps": ["baseline_strategy_selection", "planner"],
        "strategy_ids": [],
        "knowledge_item_ids": [],
        "knowledge_status": "unavailable",
    }

    feedback = unavailable_client.post(
        "/api/feedback/parse",
        json={"text": "睡了5小时，很累，吃外卖", "date": "2026-09-21", "mode": "live"},
    ).json()
    path = f"/api/feedback/{feedback['id']}"
    unavailable_client.post(path + "/confirm", json={"data": feedback["data"], "expected_revision": 0})
    advice_response = unavailable_client.post(path + "/advice", json={"mode": "live"})
    assert advice_response.status_code == 200
    advised = advice_response.json()
    assert advised["advice"]["knowledge_context"] == []
    assert legacy_trace(advised["trace"]) == {
        "steps": ["issue_extraction", "knowledge_retrieval", "advisor"],
        "issues": [],
        "profile_goal": "fat_loss",
        "issue_goal_context": [],
        "knowledge_query_terms": [],
        "knowledge_item_ids": [],
        "knowledge_status": "unavailable",
    }


def test_advice_trace_keeps_generation_goal_after_profile_changes(client, profile_data):
    row = confirmed_feedback(client, profile_data)
    advised = client.post(f"/api/feedback/{row['id']}/advice", json={"mode": "live"}).json()
    assert advised["trace"]["profile_goal"] == "fat_loss"
    assert advised["trace"]["issue_goal_context"] == [
        {"issue": "short_sleep", "terms": ["减脂"], "collections": ["fat_loss"]},
    ]

    changed_profile = deepcopy(profile_data)
    changed_profile["goals"]["primary"] = "general_health"
    assert client.put(
        "/api/profile", json={"profile": changed_profile, "expected_version": 1},
    ).status_code == 200

    state = client.get("/api/state").json()
    persisted = next(item for item in state["feedback"] if item["id"] == row["id"])
    assert state["profile"]["goals"]["primary"] == "general_health"
    assert persisted["trace"] == advised["trace"]
    assert persisted["trace"]["profile_goal"] == "fat_loss"


def test_plan_trace_reports_only_context_that_fit_persistence_limits(client, profile_data, monkeypatch):
    strategies = tuple(
        StrategySnapshot(
            id=f"oversized-strategy-{index:02d}",
            title=f"Oversized strategy {index}",
            summary="Reviewed baseline",
        )
        for index in range(21)
    )
    citations = tuple(
        KnowledgeCitation(
            id=f"oversized-{index:03d}",
            title=f"Oversized {index}",
            excerpt="Creator claim",
            creator_name="Test creator",
            collection="training",
        )
        for index in range(101)
    )

    class OversizedService:
        def for_plan(self, profile):
            return KnowledgeContextResult(strategies=strategies, citations=citations)

    monkeypatch.setattr(main, "knowledge_context_service", OversizedService())
    client.put("/api/profile", json={"profile": profile_data, "expected_version": 0})
    assert client.get("/api/state").json()["knowledge_status"] == "capacity_exceeded"
    plan = client.post("/api/plans", json={"start_date": "2026-09-21", "mode": "live"}).json()
    assert plan["data"]["strategy_context"] == []
    assert plan["data"]["source_ids"] == []
    assert plan["trace"]["strategy_ids"] == []
    assert plan["trace"]["knowledge_item_ids"] == []
    assert plan["trace"]["knowledge_status"] == "capacity_exceeded"


def test_advice_trace_reports_atomic_capacity_degradation(client, profile_data, monkeypatch):
    citations = tuple(
        KnowledgeCitation(
            id=f"oversized-{index:03d}",
            title=f"Oversized {index}",
            excerpt="Creator claim",
            creator_name="Test creator",
            collection="training",
        )
        for index in range(101)
    )

    class OversizedService:
        def for_feedback(self, profile, feedback, raw_text, history):
            return KnowledgeContextResult(citations=citations)

    monkeypatch.setattr(main, "knowledge_context_service", OversizedService())
    row = confirmed_feedback(client, profile_data)
    advised = client.post(f"/api/feedback/{row['id']}/advice", json={"mode": "live"}).json()

    assert advised["advice"]["knowledge_context"] == []
    assert advised["advice"]["source_ids"] == []
    assert advised["advice"]["suggestions"] == [
        "保持训练动作质量和逐步增加重量",
        "优先保证规律睡眠与蛋白质来源",
        "昨晚睡眠偏少，今天优先补足休息，避免用补剂替代规律作息。",
    ]
    assert advised["trace"]["knowledge_item_ids"] == []
    assert advised["trace"]["knowledge_status"] == "capacity_exceeded"


def test_unavailable_plan_trace_takes_precedence_over_capacity(client, profile_data, monkeypatch):
    strategies = tuple(
        StrategySnapshot(
            id=f"unavailable-strategy-{index:02d}",
            title=f"Unavailable strategy {index}",
            summary="Unavailable context",
        )
        for index in range(21)
    )

    class OversizedService:
        def for_plan(self, profile):
            return KnowledgeContextResult(status="unavailable", strategies=strategies)

    monkeypatch.setattr(main, "knowledge_context_service", OversizedService())
    client.put("/api/profile", json={"profile": profile_data, "expected_version": 0})
    plan = client.post("/api/plans", json={"start_date": "2026-09-21", "mode": "live"}).json()

    assert plan["data"]["strategy_context"] == []
    assert plan["trace"]["strategy_ids"] == []
    assert plan["trace"]["knowledge_status"] == "unavailable"


def test_unexpected_context_programming_error_is_not_hidden(client, profile_data, monkeypatch):
    class BrokenService:
        def for_plan(self, profile):
            raise RuntimeError("programming defect")

    monkeypatch.setattr(main, "knowledge_context_service", BrokenService())
    client.put("/api/profile", json={"profile": profile_data, "expected_version": 0})
    with pytest.raises(RuntimeError, match="programming defect"):
        client.post("/api/plans", json={"start_date": "2026-09-21", "mode": "live"})


def confirmed_feedback(client, profile_data):
    client.put("/api/profile", json={"profile": profile_data, "expected_version": 0})
    feedback = client.post(
        "/api/feedback/parse",
        json={"text": "睡了6小时", "date": "2026-09-21", "mode": "live"},
    ).json()
    client.post(
        f"/api/feedback/{feedback['id']}/confirm",
        json={"data": feedback["data"], "expected_revision": 0},
    )
    return main.store.get_feedback(feedback["id"])


def test_advice_rejects_feedback_changed_during_generation(client, profile_data, monkeypatch):
    row = confirmed_feedback(client, profile_data)
    concurrent_advice = {"summary": "并发结果", "suggestions": ["保留此结果"]}

    def mutate_feedback(profile, feedback, history, context):
        main.store.save_advice(
            row["id"],
            concurrent_advice,
            None,
            row["revision"],
            trace={"steps": ["advisor"], "status": "concurrent"},
        )
        return AdviceData(summary="陈旧结果", suggestions=["不应覆盖"])

    monkeypatch.setattr(main.agent, "advice", mutate_feedback)
    response = client.post(f"/api/feedback/{row['id']}/advice", json={"mode": "live"})
    assert response.status_code == 409
    persisted = main.store.get_feedback(row["id"])
    assert persisted["advice"] == concurrent_advice
    assert persisted["trace"] == {"steps": ["advisor"], "status": "concurrent"}


def test_advice_rejects_profile_changed_during_generation(client, profile_data, monkeypatch):
    row = confirmed_feedback(client, profile_data)

    def mutate_profile(profile, feedback, history, context):
        changed = deepcopy(profile_data)
        changed["personal"]["weight_kg"] = 72
        main.store.save_profile(changed, 1)
        return AdviceData(summary="旧档案结果", suggestions=["不应保存"])

    monkeypatch.setattr(main.agent, "advice", mutate_profile)
    response = client.post(f"/api/feedback/{row['id']}/advice", json={"mode": "live"})
    assert response.status_code == 409
    persisted = main.store.get_feedback(row["id"])
    assert persisted["advice"] is None
    assert persisted['trace']['steps'] == ['parser']
    assert persisted['trace']['parser_provider']['status'] == 'ok'


def test_state_defaults_to_live_when_configured(client, monkeypatch):
    monkeypatch.setattr(main.settings, "live_enabled", True)
    monkeypatch.setattr(main.settings, "api_key", "test-key")
    state = client.get("/api/state").json()
    assert state["mode"] == "live"
    assert state["available_modes"] == ["live"]
    assert state['model_configured'] is True
    monkeypatch.setattr(main.settings, "api_key", "")
    state = client.get('/api/state').json()
    assert state['mode'] == 'live'
    assert state['model_configured'] is False
    assert state['available_modes'] == []


def test_live_is_unavailable_not_disguised_demo(client, monkeypatch):
    monkeypatch.setattr(main.settings, 'api_key', '')
    assert client.get('/api/state').json()['model_configured'] is False
    response = client.post(
        "/api/feedback/parse", json={"text": "完成训练", "date": "2026-09-14", "mode": "live"}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "model_not_configured",
        "message": "请先在 .env 配置自己的模型 API：FITNESS_API_KEY、FITNESS_BASE_URL 和 FITNESS_MODEL，然后重启服务。",
        "retryable": False,
    }
    assert client.get("/api/state").json()["feedback"] == []


def test_state_exposes_knowledge_status_and_export_endpoints(client, profile_data):
    client.put("/api/profile", json={"profile": profile_data, "expected_version": 0})
    plan = client.post("/api/plans", json={"start_date": "2026-09-22", "mode": "live"}).json()
    assert client.get("/api/state").json()["knowledge_status"] == "ok"

    for export_type, query in (
        ("plan", {"plan_id": plan["id"]}),
        ("feedback", {}),
        ("advice", {}),
    ):
        response = client.get(f"/api/export/{export_type}?format=json", params=query)
        if export_type == "plan":
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/json")
            assert response.json()["items"][0]["id"] == plan["id"]
        else:
            assert response.status_code == 404
            assert response.json()["detail"]["code"] == "export_not_found"

    invalid = client.get("/api/export/plan", params={"format": "xml", "plan_id": plan["id"]})
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "export_format_invalid"


def test_export_includes_recent_feedback_and_advice(client, profile_data):
    row = confirmed_feedback(client, profile_data)
    advised = client.post(f"/api/feedback/{row['id']}/advice", json={"mode": "live"}).json()

    feedback_export = client.get("/api/export/feedback?format=csv")
    assert feedback_export.status_code == 200
    assert row["id"] in feedback_export.text
    advice_export = client.get(
        "/api/export/advice", params={"format": "markdown", "feedback_id": advised["id"]}
    )
    assert advice_export.status_code == 200
    assert "健身助手建议导出" in advice_export.text
    assert "根据这次反馈给出短期建议" in advice_export.text


def seed_confirmed_history(day, **values):
    data = FeedbackData(date=day, **values).model_dump(mode="json")
    draft = main.store.create_feedback("历史反馈", data, "demo", {"steps": ["parser"]})
    return main.store.confirm_feedback(draft["id"], data, 0, trace={"steps": ["parser"]})


def test_history_recent_and_trends_api_use_explicit_confirmed_facts(client):
    seed_confirmed_history(
        "2026-10-11", sleep_hours=6, weight_kg=79, fatigue="累",
        training_completed=False, diet_followed_plan=False,
    )
    seed_confirmed_history(
        "2026-10-08", sleep_hours=7, weight_kg=79.5,
        training_completed=True, diet_followed_plan=True,
    )
    seed_confirmed_history("2026-10-05", sleep_hours=5, weight_kg=80, training_completed=True)
    old = FeedbackData(date="2026-10-04", sleep_hours=9).model_dump(mode="json")
    old_draft = main.store.create_feedback("窗口外", old, "demo", {"steps": ["parser"]})
    main.store.confirm_feedback(old_draft["id"], old, 0)
    draft = FeedbackData(date="2026-10-10", sleep_hours=2).model_dump(mode="json")
    main.store.create_feedback("未确认", draft, "demo", {"steps": ["parser"]})

    recent = client.get(
        "/api/history/recent",
        params={"days": 7, "end_date": "2026-10-11", "metric": "diet_followed_plan"},
    )
    assert recent.status_code == 200
    assert recent.json()["count"] == 2
    trends = client.get(
        "/api/history/trends", params={"days": 7, "end_date": "2026-10-11"}
    )
    assert trends.status_code == 200
    assert trends.json()["metrics"]["weight_kg"]["change"] == -1
    assert trends.json()["metrics"]["diet_execution"]["valid_count"] == 2
    assert trends.json()["metrics"]["diet_execution"]["rate"] == 0.5


def test_similar_history_api_excludes_current_and_returns_previous_advice(client):
    previous = seed_confirmed_history("2026-10-01", sleep_hours=5.5, fatigue="累")
    main.store.save_advice(
        previous["id"],
        {"summary": "过去先降低训练压力", "suggestions": ["早点休息"]},
        None,
        previous["revision"],
    )
    current = seed_confirmed_history("2026-10-11", sleep_hours=6, fatigue="很累")

    response = client.get(f"/api/history/similar/{current['id']}", params={"limit": 3})

    assert response.status_code == 200
    assert response.json()["matches"][0]["id"] == previous["id"]
    assert response.json()["matches"][0]["previous_advice_summary"] == "过去先降低训练压力"
    missing = client.get("/api/history/similar/missing")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "not_found"


def test_history_api_rejects_unsupported_windows_and_metrics(client):
    window = client.get(
        "/api/history/trends", params={"days": 30, "end_date": "2026-10-11"}
    )
    metric = client.get(
        "/api/history/recent",
        params={"days": 7, "end_date": "2026-10-11", "metric": "imagined_metric"},
    )

    assert window.status_code == 400
    assert window.json()["detail"]["code"] == "history_query_invalid"
    assert metric.status_code == 400
    assert metric.json()["detail"]["code"] == "history_query_invalid"


def test_knowledge_review_and_publish_flow(client):
    payload = client.get("/api/knowledge/review").json()
    assert payload["counts"] == {"total": 1, "pending": 1, "approved": 0, "rejected": 0}
    assert payload["cards"][0]["review_status"] == "pending"

    approved = client.post(
        "/api/knowledge/review/supplements-001",
        json={"status": "approved", "note": "来源清晰"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert client.get("/api/knowledge/review").json()["counts"]["approved"] == 1

    published = client.post("/api/knowledge/review/publish").json()
    assert published["published_cards"] == 1
    assert published["manifest_items"] == 1


def test_knowledge_review_rejects_unknown_card(client):
    response = client.post(
        "/api/knowledge/review/missing",
        json={"status": "approved", "note": ""},
    )
    assert response.status_code == 404
