"""Coverage contracts for the deliberate baseline strategy library."""

import importlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from fitness.knowledge import build_manifest
from fitness.models import FeedbackData, Profile

ROOT = Path(__file__).resolve().parents[1] / "data" / "knowledge"
STRATEGY_IDS = {
    "fat-loss-energy", "diet-protein", "strength-retention", "cardio-activity",
    "sleep-recovery", "supplement-priority", "monitoring-adjustment",
}


def context_module():
    assert importlib.util.find_spec("fitness.knowledge_context") is not None, (
        "the strategy coverage module must exist"
    )
    return importlib.import_module("fitness.knowledge_context")


def ids(prefix, numbers):
    return {f"{prefix}-{number:03d}" for number in numbers}


def test_real_approved_library_has_exact_memberships_and_complete_coverage():
    context = context_module()
    manifest = build_manifest(ROOT)
    strategies = context.build_strategy_library(manifest)
    assert len(manifest) == 74
    assert len(strategies) == 7
    assert {row["id"] for row in strategies} == STRATEGY_IDS
    assert context.validate_strategy_coverage(manifest, strategies) == {
        "approved": 74, "covered": 74, "reference_only": 0,
    }
    training = lambda numbers: ids("mvp-training", numbers)
    diet = lambda numbers: ids("mvp-diet_fat_loss", numbers)
    expected = {
        "fat-loss-energy": training([11, 13]) | diet([1, 2, 3, 4, 5, 8, 10, 12, 13, 14, 16, 17]),
        "diet-protein": diet([6, 7, 8, 9, 11, 13, 14, 15, 16, 18]),
        "strength-retention": training([4, 5, 6, 7, 8, 9, 10]),
        "cardio-activity": training([1, 2, 3, 4, 12]) | diet([17]),
        "monitoring-adjustment": training([11, 12, 13]) | diet([2, 3, 4, 7, 10, 14, 15, 16, 17]),
        "supplement-priority": {r["id"] for r in manifest if r["collection"] == "supplements"},
        "sleep-recovery": {
            r["id"] for r in manifest
            if r["collection"] == "sleep_recovery" or r["id"].startswith("couren-")
        },
    }
    for strategy in strategies:
        assert set(strategy) == {
            "id", "domain", "title", "summary", "action_rules", "applicability",
            "limitations", "safety_boundary", "knowledge_item_ids",
        }
        assert strategy["knowledge_item_ids"] == sorted(expected[strategy["id"]])
        assert "fat_loss" in strategy["applicability"]
        assert len(strategy["action_rules"]) == 2
        assert isinstance(strategy["limitations"], list)
        assert strategy["limitations"]
        assert all(isinstance(entry, str) for entry in strategy["limitations"])
        assert any("作者观点" in entry for entry in strategy["limitations"])
        assert "个体化剂量" in strategy["safety_boundary"]
        assert "医疗建议" in strategy["safety_boundary"]


def test_new_training_item_requires_deliberate_assignment():
    context = context_module()
    manifest = build_manifest(ROOT)
    manifest.append({"id": "new-training-999", "collection": "training"})
    with pytest.raises(context.StrategyCoverageError, match="new-training-999"):
        context.build_strategy_library(manifest)


@pytest.mark.parametrize("mutation,match", [
    ("unknown", "unknown"), ("duplicate_strategy", "duplicate strategy"),
    ("duplicate_item", "duplicate.*item"), ("missing", "missing"),
])
def test_invalid_strategy_coverage_is_rejected(mutation, match):
    context = context_module()
    manifest = build_manifest(ROOT)
    strategies = deepcopy(context.build_strategy_library(manifest))
    if mutation == "unknown":
        strategies[0]["knowledge_item_ids"].append("unknown-item")
    elif mutation == "duplicate_strategy":
        strategies.append(deepcopy(strategies[0]))
    elif mutation == "duplicate_item":
        strategies[0]["knowledge_item_ids"].append(strategies[0]["knowledge_item_ids"][0])
    else:
        for strategy in strategies:
            strategy["knowledge_item_ids"] = []
    with pytest.raises(context.StrategyCoverageError, match=match):
        context.validate_strategy_coverage(manifest, strategies)


def test_reference_only_requires_reason_and_accounts_for_unassigned_item():
    context = context_module()
    manifest = build_manifest(ROOT)
    strategies = context.build_strategy_library(manifest)
    manifest.append({"id": "new-training-999", "collection": "training"})
    references = [{"id": "new-training-999", "reason": "等待人工判断适用策略"}]
    assert context.validate_strategy_coverage(manifest, strategies, references) == {
        "approved": 75, "covered": 74, "reference_only": 1,
    }
    for invalid in [
        [{"id": "new-training-999", "reason": "  "}],
        [{"id": "unknown-item", "reason": "待审核"}],
        references * 2,
        [{"id": manifest[0]["id"], "reason": "已覆盖不应重复"}],
    ]:
        with pytest.raises(context.StrategyCoverageError):
            context.validate_strategy_coverage(manifest, strategies, invalid)


def test_cli_writes_utf8_validated_artifact(tmp_path):
    output = tmp_path / "nested" / "strategies.json"
    result = subprocess.run(
        [sys.executable, "-m", "fitness.strategy_cli", "--root", str(ROOT), "--output", str(output)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "built 7 strategies covering 74 items ->" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["reference_only"] == []
    assert payload["coverage"] == {"approved": 74, "covered": 74, "reference_only": 0}
    assert payload["strategies"][0]["title"] == "减脂目标与能量平衡"
    assert "减脂目标与能量平衡" in output.read_text(encoding="utf-8")
    assert list(output.parent.iterdir()) == [output]


@pytest.mark.parametrize("field", ["manifest", "strategies", "reference_only"])
@pytest.mark.parametrize("value", [{}, "", (), 42])
def test_coverage_rejects_non_list_containers(field, value):
    context = context_module()
    arguments = {"manifest": [], "strategies": [], "reference_only": []}
    arguments[field] = value
    with pytest.raises(context.StrategyCoverageError, match=field):
        context.validate_strategy_coverage(**arguments)


@pytest.mark.parametrize("field", ["manifest", "strategies"])
def test_coverage_rejects_null_required_containers(field):
    context = context_module()
    arguments = {"manifest": [], "strategies": []}
    arguments[field] = None
    with pytest.raises(context.StrategyCoverageError, match=field):
        context.validate_strategy_coverage(**arguments)


@pytest.mark.parametrize("field", ["manifest", "strategies", "reference_only"])
@pytest.mark.parametrize("record", [None, "item", [], 42])
def test_coverage_rejects_non_mapping_records(field, record):
    context = context_module()
    arguments = {"manifest": [], "strategies": [], "reference_only": []}
    arguments[field] = [record]
    with pytest.raises(context.StrategyCoverageError, match=field):
        context.validate_strategy_coverage(**arguments)


@pytest.mark.parametrize("field", ["manifest", "strategies", "reference_only"])
@pytest.mark.parametrize("id_fields", [{}, {"id": None}, {"id": 42}, {"id": []}, {"id": ""}, {"id": "  "}])
def test_coverage_rejects_invalid_record_ids(field, id_fields):
    context = context_module()
    arguments = {"manifest": [], "strategies": [], "reference_only": []}
    arguments[field] = [{"knowledge_item_ids": [], "reason": "Review pending", **id_fields}]
    with pytest.raises(context.StrategyCoverageError, match=field):
        context.validate_strategy_coverage(**arguments)


@pytest.mark.parametrize("item_fields", [
    {}, {"knowledge_item_ids": None}, {"knowledge_item_ids": {}},
    {"knowledge_item_ids": ""}, {"knowledge_item_ids": ()},
    {"knowledge_item_ids": [None]}, {"knowledge_item_ids": [[]]},
    {"knowledge_item_ids": [""]}, {"knowledge_item_ids": ["  "]},
    {"knowledge_item_ids": ["unknown-item", 42]},
])
def test_coverage_rejects_invalid_item_lists_before_sorting(item_fields):
    context = context_module()
    with pytest.raises(context.StrategyCoverageError, match="knowledge_item_ids"):
        context.validate_strategy_coverage([], [{"id": "strategy", **item_fields}])


@pytest.mark.parametrize("reason_fields", [
    {}, {"reason": None}, {"reason": 42}, {"reason": []}, {"reason": ""}, {"reason": "  "},
])
def test_coverage_rejects_invalid_reference_reasons(reason_fields):
    context = context_module()
    with pytest.raises(context.StrategyCoverageError, match="reason"):
        context.validate_strategy_coverage([], [], [{"id": "reference", **reason_fields}])


def make_service(root=ROOT, strategy_path=None):
    context = context_module()
    assert hasattr(context, "KnowledgeContextService"), "knowledge context service is missing"
    return context.KnowledgeContextService(root, strategy_path or root / "baseline-strategies.json")


def feedback(**values):
    return FeedbackData(date="2026-09-21", **values)


def write_library(root, cards, source_overrides=None):
    source = {
        "id": "source", "creator_name": "Test creator", "video_title": "Legacy video",
        "video_url": "https://example.org/legacy", "published_at": "2026-01-01",
        **(source_overrides or {}),
    }
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "source.json").write_text(json.dumps(source), encoding="utf-8")
    approved = []
    for index, card in enumerate(cards):
        item = {
            "id": f"card-{index:02d}", "collection": "training", "title": "General",
            "claim": "General claim", "source_id": "source", "source_type": "creator_opinion",
            "evidence_level": "limited", "review_status": "approved", **card,
        }
        folder = root / item["collection"]
        folder.mkdir(exist_ok=True)
        (folder / f"{index}.json").write_text(json.dumps(item), encoding="utf-8")
        if item["review_status"] == "approved":
            approved.append(item["id"])
    artifact = {
        "coverage": {"approved": len(approved), "covered": len(approved), "reference_only": 0},
        "version": 1, "reference_only": [], "strategies": [{
            "id": "strategy", "title": "Reviewed strategy", "summary": "Reviewed summary",
            "action_rules": ["Keep a record"], "applicability": ["fat_loss"],
            "domain": "training", "knowledge_item_ids": approved,
        }],
    }
    (root / "baseline-strategies.json").write_text(json.dumps(artifact), encoding="utf-8")
    return root


def test_plan_loads_all_seven_reviewed_strategies_and_74_sources(profile_data):
    result = make_service().for_plan(Profile.model_validate(profile_data))
    assert result.status == "ok"
    assert len(result.strategies) == 7
    assert {strategy.id for strategy in result.strategies} == STRATEGY_IDS
    assert len(result.citations) == 74
    assert [citation.id for citation in result.citations] == sorted(row["id"] for row in build_manifest(ROOT))
    assert {item for strategy in result.strategies for item in strategy.knowledge_item_ids} == {
        citation.id for citation in result.citations
    }


def test_multi_issue_retrieval_is_per_issue_and_merges_shared_cards(tmp_path, profile_data):
    cards = [
        {"id": "shared", "title": "恢复", "collection": "sleep_recovery"},
        *[{"title": f"睡眠时长 {i}", "collection": "sleep_recovery"} for i in range(3)],
        *[{"title": f"疲劳训练量 {i}"} for i in range(3)],
        *[{"title": f"饮食记录隐藏热量蛋白质 {i}", "collection": "fat_loss"} for i in range(3)],
        {"id": "irrelevant", "collection": "sleep_recovery"},
        {"id": "pending", "title": "睡眠时长恢复", "review_status": "pending"},
    ]
    service = make_service(write_library(tmp_path, cards))
    profile = Profile.model_validate(profile_data)
    result = service.for_feedback(profile, feedback(sleep_hours=5, fatigue="疲惫", food_summary="食堂"), "", [])
    assert result.status == "ok"
    assert [issue.id for issue in result.issues] == ["short_sleep", "training_fatigue", "diet_adherence"]
    assert all(1 <= len(issue.knowledge_item_ids) <= 5 for issue in result.issues)
    assert len(result.citations) > 5
    assert len({citation.id for citation in result.citations}) == len(result.citations)
    shared = next(citation for citation in result.citations if citation.id == "shared")
    assert shared.matched_issues == ["short_sleep", "training_fatigue"]
    assert not {"pending", "irrelevant"} & {citation.id for citation in result.citations}
    assert result.query_terms == ("睡眠", "睡眠时长", "恢复", "疲劳", "训练量", "饮食记录", "隐藏热量", "蛋白质")
    assert service.for_feedback(profile, feedback(sleep_hours=5, fatigue="疲惫", food_summary="食堂"), "", []) == result


@pytest.mark.parametrize("goal,goal_terms,expected_first", [
    ("fat_loss", ("减脂",), "fat-loss-choice"),
    ("muscle_gain", ("增肌", "蛋白质"), "muscle-gain-choice"),
    ("general_health", ("饮食结构",), "general-health-choice"),
])
def test_feedback_goal_context_is_an_auditable_tiebreaker(
    tmp_path, profile_data, goal, goal_terms, expected_first,
):
    root = write_library(tmp_path, [
        {"id": "fat-loss-choice", "title": "饮食记录与减脂", "collection": "fat_loss"},
        {"id": "muscle-gain-choice", "title": "饮食记录与增肌", "collection": "fat_loss"},
        {"id": "general-health-choice", "title": "饮食记录与饮食结构", "collection": "fat_loss"},
        {"id": "generic-choice", "title": "饮食记录与日常", "collection": "fat_loss"},
    ])
    profile_data["goals"]["primary"] = goal

    result = make_service(root).for_feedback(
        Profile.model_validate(profile_data), feedback(food_summary="食堂饮食没记录"), "", [],
    )

    assert [issue.id for issue in result.issues] == ["diet_adherence"]
    issue = result.issues[0]
    assert issue.goal_terms == goal_terms
    assert not set(goal_terms) - {"蛋白质"} & set(result.query_terms)
    assert issue.knowledge_item_ids[0] == expected_first


def test_real_feedback_prioritizes_each_issue_collection(profile_data):
    profile = Profile.model_validate(profile_data)
    result = make_service().for_feedback(
        profile,
        feedback(sleep_hours=5.5, fatigue="今天训练很累", food_summary="食堂饮食也没记录"),
        "昨晚只睡了5.5小时，今天训练很累，食堂饮食也没记录",
        [],
    )
    citations = {citation.id: citation for citation in result.citations}
    issues = {issue.id: issue for issue in result.issues}

    assert set(issues) == {"short_sleep", "training_fatigue", "diet_adherence"}
    assert all(3 <= len(issue.knowledge_item_ids) <= 5 for issue in issues.values())
    short_sleep = [citations[item_id].collection for item_id in issues["short_sleep"].knowledge_item_ids[:3]]
    training_fatigue = [
        citations[item_id].collection for item_id in issues["training_fatigue"].knowledge_item_ids[:3]
    ]
    diet_adherence = [citations[item_id].collection for item_id in issues["diet_adherence"].knowledge_item_ids[:3]]
    assert short_sleep == ["sleep_recovery"] * 3
    assert training_fatigue[0] == "training"
    assert set(training_fatigue) <= {"training", "sleep_recovery"}
    assert diet_adherence == ["fat_loss"] * 3


@pytest.mark.parametrize("failure", ["missing_root", "file_root", "empty_root", "invalid_items", "missing_source", "duplicate_source", "duplicate_item", "missing_strategy", "invalid_json", "invalid_utf8", "list", "version", "bool_version", "no_reference_only", "null_reference_only", "invalid_strategy", "coverage", "applicability"])
def test_invalid_context_degrades_without_partial_results(tmp_path, profile_data, failure):
    root = write_library(tmp_path / "knowledge", [{"title": "睡眠"}])
    strategy = root / "baseline-strategies.json"
    artifact = json.loads(strategy.read_text(encoding="utf-8"))
    if failure == "missing_root":
        root = tmp_path / "missing"
    elif failure == "file_root":
        root = strategy
    elif failure == "empty_root":
        root = tmp_path / "empty"
        root.mkdir()
    elif failure == "invalid_items":
        (root / "training" / "0.json").write_text("{}", encoding="utf-8")
    elif failure == "missing_source":
        (root / "sources" / "source.json").unlink()
    elif failure == "duplicate_source":
        (root / "sources" / "duplicate.json").write_bytes((root / "sources" / "source.json").read_bytes())
    elif failure == "duplicate_item":
        (root / "training" / "duplicate.json").write_bytes((root / "training" / "0.json").read_bytes())
    elif failure == "missing_strategy":
        strategy.unlink()
    elif failure == "invalid_json":
        strategy.write_text("{", encoding="utf-8")
    elif failure == "invalid_utf8":
        strategy.write_bytes(b"\xff")
    else:
        if failure == "list":
            artifact = []
        elif failure == "version":
            artifact["version"] = 2
        elif failure == "bool_version":
            artifact["version"] = True
        elif failure == "no_reference_only":
            del artifact["reference_only"]
        elif failure == "null_reference_only":
            artifact["reference_only"] = None
        elif failure == "invalid_strategy":
            artifact["strategies"][0]["summary"] = 1
        elif failure == "coverage":
            artifact["strategies"][0]["knowledge_item_ids"] = []
        else:
            artifact["strategies"][0]["applicability"] = "fat_loss"
        strategy.write_text(json.dumps(artifact), encoding="utf-8")
    service = make_service(root, strategy)
    profile = Profile.model_validate(profile_data)
    for result in [service.for_plan(profile), service.for_feedback(profile, feedback(sleep_hours=5), "", [])]:
        assert result.status == "unavailable"
        assert result.strategies == result.citations == result.issues == result.query_terms == ()


@pytest.mark.parametrize("entrypoint", ["plan", "feedback"])
@pytest.mark.parametrize("coverage", [
    "missing", None, [], "invalid", 1,
    {}, {"approved": 1, "covered": 1},
    {"approved": 1, "covered": 1, "reference_only": 0, "extra": 0},
    *[{"approved": 1, "covered": 1, "reference_only": 0, field: value}
      for field in ("approved", "covered", "reference_only")
      for value in (None, "1", 1.0, True, False, -1, 2)],
])
def test_persisted_coverage_must_match_fresh_report(tmp_path, profile_data, entrypoint, coverage):
    root = write_library(tmp_path, [{"title": "睡眠"}])
    strategy_path = root / "baseline-strategies.json"
    artifact = json.loads(strategy_path.read_text(encoding="utf-8"))
    if coverage == "missing":
        del artifact["coverage"]
    else:
        artifact["coverage"] = coverage
    strategy_path.write_text(json.dumps(artifact), encoding="utf-8")
    service = make_service(root)
    profile = Profile.model_validate(profile_data)
    result = (service.for_plan(profile) if entrypoint == "plan"
              else service.for_feedback(profile, feedback(sleep_hours=5), "", []))
    assert result.status == "unavailable"
    assert result.strategies == result.citations == result.issues == result.query_terms == ()


@pytest.mark.parametrize("videos", [None, [], [
    {"bvid": "BV1", "title": "Structured 1", "url": "https://example.org/1"},
    {"bvid": "BV2", "title": "V" * 500, "url": "javascript:ignored-later", "published_at": "2025-01-01"},
]])
def test_citations_preserve_structured_videos_or_legacy_fallback(tmp_path, profile_data, videos):
    root = write_library(tmp_path, [{"title": "K" * 300, "claim": "C" * 2000, "explanation": "E" * 4000}],
                         {} if videos is None else {"videos": videos})
    result = make_service(root).for_plan(Profile.model_validate(profile_data))
    assert result.status == "ok"
    citation = result.citations[0]
    assert citation.title == "K" * 300
    assert citation.excerpt == "C" * 2000
    assert citation.creator_name == "Test creator"
    assert citation.collection == "training"
    assert citation.matched_issues == []
    if videos:
        assert [video.model_dump() for video in citation.videos] == [
            {"published_at": None, **video} for video in videos
        ]
    else:
        assert citation.videos[0].model_dump() == {
            "bvid": None, "title": "Legacy video", "url": "https://example.org/legacy", "published_at": "2026-01-01",
        }
        assert len(citation.videos) == 1


def test_supplement_issue_uses_exact_approved_title_and_goal_alone_is_not_issue(tmp_path, profile_data):
    root = write_library(tmp_path, [
        {"title": "肌酸", "collection": "supplements"},
        {"title": "咖啡因", "collection": "supplements"},
        {"title": "未审核补剂", "collection": "supplements", "review_status": "pending"},
    ])
    service = make_service(root)
    profile = Profile.model_validate(profile_data)
    result = service.for_feedback(profile, feedback(), "肌酸和咖啡因，肌酸", [])
    assert [issue.id for issue in result.issues] == ["supplement_question"]
    assert result.issues[0].terms == ("肌酸", "咖啡因", "补剂")
    assert result.issues[0].collections == ("supplements",)
    assert len(result.citations) == 2
    assert service.for_feedback(profile, feedback(), "未审核补剂", []).issues == ()
    assert service.for_feedback(profile, feedback(), "", []).citations == ()


@pytest.mark.parametrize("title,raw_text", [
    ("Omega-3", "omega-3怎么用"), ("PQQ", "想了解pqq"), ("维生素D", "维生素d有用吗"),
])
def test_supplement_names_match_case_insensitively_with_canonical_terms(tmp_path, profile_data, title, raw_text):
    service = make_service(write_library(tmp_path, [{"title": title, "collection": "supplements"}]))
    result = service.for_feedback(Profile.model_validate(profile_data), feedback(), raw_text, [])
    assert [issue.id for issue in result.issues] == ["supplement_question"]
    assert result.issues[0].terms == (title, "补剂")


@pytest.mark.parametrize("raw_text,expected", [
    ("今天举铁很开心", False), ("今天坐地铁去训练", False),
    ("我想补铁", True), ("铁补剂", True), ("铁剂", True), ("是不是缺铁", True),
    ("铁片有用吗", True), ("铁元素", True), (" 铁 ", True),
])
def test_single_character_supplement_requires_explicit_context(tmp_path, profile_data, raw_text, expected):
    service = make_service(write_library(tmp_path, [{"title": "铁", "collection": "supplements"}]))
    result = service.for_feedback(Profile.model_validate(profile_data), feedback(), raw_text, [])
    assert ("supplement_question" in {issue.id for issue in result.issues}) is expected


@pytest.mark.parametrize("days,weights,statuses,expected", [
    ([1, 8, 15], [73, 73.1, 73.2], ["confirmed"] * 3, True),
    ([1, 8, 14], [73, 73.1, 73.2], ["confirmed"] * 3, False),
    ([1, 15], [73, 73.1], ["confirmed"] * 2, False),
    ([1, 8, 15], [73, 73.1, 73.2], ["confirmed", "draft", "confirmed"], False),
    ([1, 8, 15], [73, 73.1, 74], ["confirmed"] * 3, False),
    ([1, 8, 15], [73, 73.1, 73.3], ["confirmed"] * 3, True),
])
def test_plateau_requires_confirmed_weight_history_over_two_weeks(tmp_path, profile_data, days, weights, statuses, expected):
    service = make_service(write_library(tmp_path, [{"title": "体重变化平台期", "collection": "fat_loss"}]))
    history = [{"date": f"2026-09-{day:02d}", "status": status, "data": {"weight_kg": weight}}
               for day, weight, status in zip(days, weights, statuses, strict=True)]
    current = FeedbackData(date=f"2026-09-{days[-1]:02d}", weight_kg=weights[-1])
    result = service.for_feedback(Profile.model_validate(profile_data), current, "", history)
    assert ("weight_plateau" in {issue.id for issue in result.issues}) is expected
    assert result.issues[0].id == "weight_trend"
    assert len(result.citations) == 1


@pytest.mark.parametrize("measurements,current_weight,expected", [
    ([('2026-09-21', 72), ('2026-09-08', 72.1), ('2026-09-01', 72), ('2026-08-01', 75)], 72, True),
    ([('2026-01-21', 72), ('2026-01-08', 72.1), ('2026-01-01', 72)], None, False),
    ([('2026-09-21', 73), ('2026-09-08', 73), ('2026-09-01', 73)], 72, False),
    ([('2026-09-21', 72), ('2026-09-08', 72), ('2026-09-08', 73), ('2026-09-01', 72)], None, True),
    ([('2026-09-08', 72.1), ('2026-09-01', 72)], 72, True),
    ([('2026-09-08', 72.1), ('2026-08-31', 72)], 72, True),
    ([('2026-09-08', 72.1), ('2026-08-30', 72)], 72, False),
    ([('2026-09-22', 75), ('2026-09-08', 72.1), ('2026-09-01', 72)], 72, True),
    ([('2026-09-01', 72), ('2026-09-01', 72)], 72, False),
])
def test_plateau_uses_recent_window_and_authoritative_measurements(
    tmp_path, profile_data, measurements, current_weight, expected,
):
    service = make_service(write_library(tmp_path, [{"title": "体重变化平台期", "collection": "fat_loss"}]))
    history = [{"date": day, "status": "confirmed", "data": {"weight_kg": weight}}
               for day, weight in measurements]
    result = service.for_feedback(Profile.model_validate(profile_data), feedback(weight_kg=current_weight), "", history)
    assert ("weight_plateau" in {issue.id for issue in result.issues}) is expected


@pytest.mark.parametrize("full_coverage,expected_count", [(True, 3), (False, 4)])
def test_expansion_only_adds_cards_needed_for_term_coverage(tmp_path, profile_data, full_coverage, expected_count):
    cards = [{"title": "睡眠时长恢复" if full_coverage else "睡眠时长", "collection": "sleep_recovery"}
             for _ in range(6)]
    cards.append({"id": "z-recovery", "title": "恢复辅助", "collection": "sleep_recovery"})
    service = make_service(write_library(tmp_path, cards))
    result = service.for_feedback(Profile.model_validate(profile_data), feedback(sleep_hours=6), "", [])
    assert len(result.issues[0].knowledge_item_ids) == expected_count
    assert result.issues[0].knowledge_item_ids[:3] == ("card-00", "card-01", "card-02")
    if not full_coverage:
        assert result.issues[0].knowledge_item_ids[-1] == "z-recovery"


def test_only_two_matching_terms_does_not_expand(tmp_path, profile_data):
    cards = [{"title": "睡眠", "collection": "sleep_recovery"} for _ in range(6)]
    cards.append({"title": "恢复", "collection": "training"})
    result = make_service(write_library(tmp_path, cards)).for_feedback(
        Profile.model_validate(profile_data), feedback(sleep_hours=6), "", [],
    )
    assert len(result.issues[0].knowledge_item_ids) == 3


def test_supplement_issue_never_exceeds_five_even_with_more_uncovered_terms(tmp_path, profile_data):
    titles = ["肌酸", "咖啡因", "乳清", "鱼油", "镁", "维生素D"]
    service = make_service(write_library(tmp_path, [
        {"title": title, "collection": "supplements"} for title in titles
    ]))
    result = service.for_feedback(Profile.model_validate(profile_data), feedback(), "、".join(titles) + "补镁", [])
    assert len(result.issues) == 1
    assert len(result.issues[0].knowledge_item_ids) == len(result.citations) == 5


def test_scoring_is_case_insensitive_and_prioritizes_title_matches(tmp_path, profile_data):
    root = write_library(tmp_path, [
        {"id": "z-title", "title": "CREATINE", "collection": "supplements"},
        {"id": "b-substring", "title": "creatine overview", "collection": "training"},
        {"id": "a-body", "claim": "Creatine", "collection": "supplements"},
        {"id": "irrelevant", "collection": "supplements"},
    ])
    result = make_service(root).for_feedback(Profile.model_validate(profile_data), feedback(), "CREATINE", [])
    assert result.issues[0].knowledge_item_ids == ("z-title", "a-body", "b-substring")


def test_exact_generic_fatigue_title_cannot_override_collection_boundary(tmp_path, profile_data):
    root = write_library(tmp_path, [
        {"id": "preferred-body", "title": "训练恢复建议", "claim": "疲劳", "collection": "training"},
        {"id": "nonpreferred-exact", "title": "疲劳", "collection": "supplements"},
    ])

    result = make_service(root).for_feedback(
        Profile.model_validate(profile_data), feedback(fatigue="今天很累"), "", [],
    )

    assert result.issues[0].id == "training_fatigue"
    assert result.issues[0].knowledge_item_ids == ("preferred-body",)


def test_generic_fatigue_expansion_stays_with_issue_collections(tmp_path, profile_data):
    root = write_library(tmp_path, [
        {"id": "training-fatigue", "title": "训练后恢复", "claim": "疲劳恢复训练量", "collection": "training"},
        {"id": "sleep-recovery", "title": "睡眠恢复", "claim": "疲劳恢复睡眠", "collection": "sleep_recovery"},
        {"id": "supplement-fatigue", "title": "维生素B12与训练疲劳", "claim": "疲劳恢复补剂", "collection": "supplements"},
    ])
    result = make_service(root).for_feedback(
        Profile.model_validate(profile_data), feedback(fatigue="训练后疲劳"), "", [],
    )
    issue = result.issues[0]
    assert issue.id == "training_fatigue"
    assert "supplement-fatigue" not in issue.knowledge_item_ids


def test_exact_supplement_title_remains_retrievable(tmp_path, profile_data):
    root = write_library(tmp_path, [
        {"id": "supplement-b12", "title": "维生素B12", "claim": "补剂适用条件", "collection": "supplements"},
        {"id": "training-b12", "title": "训练恢复", "claim": "维生素B12疲劳", "collection": "training"},
    ])
    result = make_service(root).for_feedback(
        Profile.model_validate(profile_data), feedback(), "维生素B12适用条件", [],
    )
    assert result.issues[0].id == "supplement_question"
    assert result.issues[0].knowledge_item_ids[0] == "supplement-b12"


@pytest.mark.parametrize("raw_text", ["今天吃得多", "食堂", "外卖", "饮食情况"])
def test_raw_food_mentions_create_diet_issue_without_structured_summary(tmp_path, profile_data, raw_text):
    service = make_service(write_library(tmp_path, [{"title": "蛋白质", "collection": "fat_loss"}]))
    result = service.for_feedback(Profile.model_validate(profile_data), feedback(sleep_hours=7), raw_text, [])
    assert [issue.id for issue in result.issues] == ["diet_adherence"]


def test_manifest_is_reloaded_and_applicability_filters_plan(tmp_path, profile_data):
    root = write_library(tmp_path, [{"title": "睡眠"}])
    service = make_service(root)
    profile = Profile.model_validate(profile_data)
    assert len(service.for_plan(profile).strategies) == 1
    other_goal = profile.model_copy(update={"goals": profile.goals.model_copy(update={"primary": "muscle_gain"})})
    assert service.for_plan(other_goal).strategies == ()
    item_path = root / "training" / "0.json"
    item = json.loads(item_path.read_text(encoding="utf-8"))
    item["review_status"] = "pending"
    item_path.write_text(json.dumps(item), encoding="utf-8")
    assert service.for_plan(profile).status == "unavailable"


@pytest.mark.parametrize("error", [RuntimeError, ValueError, TypeError, KeyError])
def test_unexpected_programming_error_is_not_hidden(tmp_path, profile_data, monkeypatch, error):
    service = make_service(write_library(tmp_path, [{"title": "睡眠"}]))

    def broken_manifest(root):
        raise error("programming defect")

    monkeypatch.setattr(context_module(), "build_manifest", broken_manifest)
    with pytest.raises(error, match="programming defect"):
        service.for_plan(Profile.model_validate(profile_data))
