"""Coverage contracts for the deliberate baseline strategy library."""

import importlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from fitness.knowledge import build_manifest

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
