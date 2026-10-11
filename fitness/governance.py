"""Read-only provenance and membership audit; approval is never evidence upgrade."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from .knowledge_context import KnowledgeContextService, StrategyCoverageError


def membership_rows(manifest: list[dict]) -> list[dict]:
    """Fingerprint meaning/provenance as well as IDs so equal counts cannot hide edits."""
    rows = []
    for row in sorted(manifest, key=lambda value: value["id"]):
        serialized = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        rows.append({"id": row["id"], "collection": row["collection"],
                     "source_id": row["metadata"]["source_id"],
                     "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest()})
    return rows


def strategy_fingerprints(strategies: list[dict]) -> dict[str, str]:
    """Fingerprint the full editorial rule, including safety and applicability."""
    return {row["id"]: hashlib.sha256(json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest() for row in strategies}


def audit_knowledge(knowledge_root: Path, membership_path: Path) -> dict:
    """Audit fresh approved manifest and the exact production strategy loader.

    Missing/invalid coverage is unavailable. Valid coverage with changed membership
    needs explicit editorial review and a new snapshot, never automatic acceptance.
    """
    report = {"status": "unavailable", "coverage": None, "errors": []}
    try:
        manifest, strategies = KnowledgeContextService(
            Path(knowledge_root), Path(knowledge_root) / "baseline-strategies.json",
        )._load()
        snapshot = json.loads(Path(membership_path).read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict) or snapshot.get("version") != 1 or not isinstance(snapshot.get("members"), list):
            raise StrategyCoverageError("invalid membership manifest")
        fields = {"id", "collection", "source_id", "sha256"}
        if any(not isinstance(row, dict) or set(row) != fields
               or any(not isinstance(value, str) or not value for value in row.values()) for row in snapshot["members"]):
            raise StrategyCoverageError("invalid membership manifest member")
        prior = {row["id"]: row for row in snapshot["members"]}
        if not prior or len(prior) != len(snapshot["members"]):
            raise StrategyCoverageError("empty or duplicate membership manifest")
        current = {row["id"]: row for row in membership_rows(manifest)}
        strategy_snapshot = snapshot.get("strategy_memberships")
        if (not isinstance(strategy_snapshot, dict) or not strategy_snapshot
                or any(not isinstance(key, str) or not isinstance(ids, list)
                       or any(not isinstance(item, str) for item in ids)
                       or len(ids) != len(set(ids)) for key, ids in strategy_snapshot.items())):
            raise StrategyCoverageError("invalid strategy membership manifest")
        current_strategies = {raw["id"]: sorted(raw["knowledge_item_ids"]) for raw, _ in strategies}
        prior_fingerprints = snapshot.get("strategy_fingerprints")
        if (not isinstance(prior_fingerprints, dict) or set(prior_fingerprints) != set(strategy_snapshot)
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in prior_fingerprints.values())):
            raise StrategyCoverageError("invalid strategy content fingerprints")
        current_fingerprints = strategy_fingerprints([raw for raw, _ in strategies])
        changes = {"added": sorted(current.keys() - prior.keys()), "removed": sorted(prior.keys() - current.keys()),
                   "changed": sorted(item for item in current.keys() & prior.keys() if current[item] != prior[item]),
                   "changed_strategies": sorted(key for key in current_strategies.keys() | strategy_snapshot.keys()
                                                if current_strategies.get(key) != strategy_snapshot.get(key)),
                   "changed_strategy_content": sorted(key for key in current_fingerprints.keys() | prior_fingerprints.keys()
                                                      if current_fingerprints.get(key) != prior_fingerprints.get(key))}
        safety_findings = []
        for raw, _ in strategies:
            text = "\n".join([str(raw.get("safety_boundary", "")), *raw.get("action_rules", [])])
            if re.search(r"(?:允许|可以|应当|必须)自动(?:生成|推荐|提供)(?:个体化|个人|个体)剂量", text):
                safety_findings.append({"strategy_id": raw["id"], "reason": "obvious automated individual dosing permission",
                                        "requires_human_review": True, "is_medical_proof": False})
        artifact = json.loads((Path(knowledge_root) / "baseline-strategies.json").read_text(encoding="utf-8"))
        reviews = []
        for row in manifest:
            metadata = row["metadata"]
            if row["collection"] != "supplements":
                continue
            reviews.append({"id": row["id"], "title": row["title"], "source_id": metadata["source_id"],
                            "evidence_level": metadata["evidence_level"],
                            "automated_checks": {"source_present": bool(row["source"]),
                                                 "editorial_note_present": bool(metadata.get("review_note")),
                                                 "explanation_present": bool(metadata.get("explanation")),
                                                 "safety_boundary_present": bool(metadata.get("safety_level"))},
                            "requires_human_review": ["verify transcript and ASR ambiguity", "verify independent evidence and applicability",
                                                      "assess conditions, medications and special populations",
                                                      "check dose statements, interactions and product quality",
                                                      "preserve uncertainty; do not generate individual dose or purchase advice"]})
        report.update({
            "status": "review_required" if any(changes.values()) or safety_findings else "ok", "coverage": artifact["coverage"],
            "strategy_safety_findings": safety_findings,
            "membership_changes": changes, "source_type_counts": dict(Counter(row["metadata"]["source_type"] for row in manifest)),
            "evidence_level_counts": dict(Counter(row["metadata"]["evidence_level"] for row in manifest)),
            "provenance_layers": {
                "creator_statement": {"description": "Video creator claim with creator/source/video attribution; may contain ASR uncertainty.", "is_medical_consensus": False},
                "editorial_strategy": {"description": "Reviewed baseline synthesis with explicit source-card membership and safety boundary.", "independent_evidence_upgrade": False},
                "system_judgement": {"description": "Rules infer current issues, rank cards and choose bounded advice from user facts.", "clinical_validation": False},
            },
            "strategies": [{"id": raw["id"], "knowledge_item_ids": raw["knowledge_item_ids"],
                            "limitations": raw.get("limitations", []), "safety_boundary": raw.get("safety_boundary")}
                           for raw, _ in strategies],
            "supplement_reviews": reviews,
            "stale_pending_explanation_ids": sorted(row["id"] for row in manifest
                                                    if "review_status 为 pending" in (row["metadata"].get("explanation") or "")),
            "limitations": ["Review approval records permission to use a conservative source summary, not scientific consensus.",
                            "Automated checks verify metadata and membership, not efficacy, dose safety or transcript accuracy.",
                            "Creator evidence labels are existing editorial labels; no independent study verification was performed."],
        })
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, StrategyCoverageError) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    return report
