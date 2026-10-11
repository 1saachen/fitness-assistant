import json
import shutil
from importlib import import_module
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def audit(root=None, membership=None):
    return import_module("fitness.governance").audit_knowledge(
        root or ROOT / "data/knowledge",
        membership or ROOT / "data/evaluation/membership.json",
    )


def test_real_governance_preserves_provenance_and_evidence_limitations():
    report = audit()
    assert report["status"] == "ok"
    assert report["coverage"] == {"approved": 74, "covered": 74, "reference_only": 0}
    assert report["source_type_counts"] == {"creator_opinion": 74}
    assert report["provenance_layers"]["creator_statement"]["is_medical_consensus"] is False
    assert report["provenance_layers"]["editorial_strategy"]["independent_evidence_upgrade"] is False
    assert report["provenance_layers"]["system_judgement"]["clinical_validation"] is False
    assert len(report["supplement_reviews"]) == 36
    assert all(row["requires_human_review"] for row in report["supplement_reviews"])
    assert report["stale_pending_explanation_ids"] == []


def test_membership_requires_review_even_when_same_count_and_coverage(tmp_path):
    membership = json.loads((ROOT / "data/evaluation/membership.json").read_text(encoding="utf-8"))
    membership["members"][0]["collection"] = "training"
    path = tmp_path / "membership.json"
    path.write_text(json.dumps(membership), encoding="utf-8")
    report = audit(membership=path)
    assert report["status"] == "review_required"
    assert report["membership_changes"]["changed"]


@pytest.mark.parametrize("damage", ["missing_root", "missing_strategy", "coverage", "unknown_source", "new_card"])
def test_unavailable_audit_never_reports_full_coverage(tmp_path, damage):
    root = tmp_path / "knowledge"
    shutil.copytree(ROOT / "data/knowledge", root)
    if damage == "missing_root":
        root = tmp_path / "missing"
    elif damage == "missing_strategy":
        (root / "baseline-strategies.json").unlink()
    elif damage == "coverage":
        path = root / "baseline-strategies.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["coverage"]["covered"] = 0
        path.write_text(json.dumps(artifact), encoding="utf-8")
    else:
        path = root / "training/mvp-approved.json"
        cards = json.loads(path.read_text(encoding="utf-8"))
        if damage == "unknown_source":
            cards[0]["source_id"] = "missing-source"
        else:
            cards.append({**cards[0], "id": "new-approved-card"})
        path.write_text(json.dumps(cards), encoding="utf-8")
    report = audit(root)
    assert report["status"] == "unavailable"
    assert report["coverage"] is None
    assert report["errors"]


def test_missing_membership_manifest_is_unavailable(tmp_path):
    assert audit(membership=tmp_path / "missing.json")["status"] == "unavailable"


def test_strategy_membership_change_requires_review_with_valid_coverage(tmp_path):
    root = tmp_path / "knowledge"
    shutil.copytree(ROOT / "data/knowledge", root)
    path = root / "baseline-strategies.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["strategies"][0]["knowledge_item_ids"].remove("mvp-diet_fat_loss-002")
    # Card remains covered in monitoring; total coverage is unchanged.
    path.write_text(json.dumps(artifact), encoding="utf-8")
    report = audit(root)
    assert report["status"] == "review_required"
    assert "fat-loss-energy" in report["membership_changes"]["changed_strategies"]


def test_strategy_content_change_requires_review_even_with_same_membership(tmp_path):
    root = tmp_path / "knowledge"
    shutil.copytree(ROOT / "data/knowledge", root)
    path = root / "baseline-strategies.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["strategies"][0]["summary"] = "Changed editorial rule"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    report = audit(root)
    assert report["status"] == "review_required"
    assert "fat-loss-energy" in report["membership_changes"]["changed_strategy_content"]


def test_obvious_individual_dosing_boundary_requires_review_even_with_refreshed_hash(tmp_path):
    module = import_module("fitness.governance")
    root = tmp_path / "knowledge"
    shutil.copytree(ROOT / "data/knowledge", root)
    path = root / "baseline-strategies.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["strategies"][5]["safety_boundary"] = "允许自动生成个体化剂量。"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    snapshot = json.loads((ROOT / "data/evaluation/membership.json").read_text(encoding="utf-8"))
    snapshot["strategy_fingerprints"] = module.strategy_fingerprints(artifact["strategies"])
    membership = tmp_path / "membership.json"
    membership.write_text(json.dumps(snapshot), encoding="utf-8")
    report = audit(root, membership)
    assert report["status"] == "review_required"
    assert report["strategy_safety_findings"][0]["strategy_id"] == "supplement-priority"
    assert report["strategy_safety_findings"][0]["requires_human_review"] is True
