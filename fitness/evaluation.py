"""Reproducible, held-out retrieval evaluation for the local knowledge corpus."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .knowledge import build_manifest
from .knowledge_context import KnowledgeContextResult, KnowledgeContextService
from .models import FeedbackData, Profile


class IssueLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    preferred_collections: list[str] = Field(default_factory=list)
    expected_ids: list[str] = Field(default_factory=list)
    forbidden_collections: list[str] = Field(default_factory=list)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    category: str
    split: str = "held_out"
    goal: str = "fat_loss"
    raw_text: str = ""
    feedback: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[IssueLabel] = Field(default_factory=list)


class CharacterTfidf:
    """Offline semantic candidate based on character n-gram TF-IDF.

    This is a lexical similarity control, deliberately not an embedding model.
    It makes no claim about neural/vector retrieval quality.
    """

    def __init__(self, corpus: list[dict[str, Any]], ngram: int = 2):
        self.rows = corpus
        self.ngram = ngram
        self.docs = [self._grams(row.get("text", "")) for row in corpus]
        df = Counter(g for grams in self.docs for g in set(grams))
        self.idf = {g: math.log((1 + len(self.docs)) / (1 + count)) + 1 for g, count in df.items()}
        self.vectors = [self._vector(grams) for grams in self.docs]

    def _grams(self, text: str) -> list[str]:
        compact = re.sub(r"\s+", "", str(text).casefold())
        if len(compact) < self.ngram:
            return [compact] if compact else []
        return [compact[i : i + self.ngram] for i in range(len(compact) - self.ngram + 1)]

    def _vector(self, grams: list[str]) -> dict[str, float]:
        counts = Counter(grams)
        return {g: (1 + math.log(count)) * self.idf.get(g, 1.0) for g, count in counts.items()}

    def search(self, query: str, limit: int = 3) -> tuple[str, ...]:
        vector = self._vector(self._grams(query))
        if not vector:
            return ()
        norm = math.sqrt(sum(v * v for v in vector.values()))
        ranked = []
        for row, candidate in zip(self.rows, self.vectors, strict=True):
            denom = norm * math.sqrt(sum(v * v for v in candidate.values()))
            score = sum(vector.get(g, 0.0) * value for g, value in candidate.items()) / denom if denom else 0.0
            if score:
                ranked.append((score, row["id"]))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[1] for item in ranked[:limit])


def load_cases(path: Path) -> list[EvaluationCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    values = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise TypeError("evaluation fixture must contain a cases list")
    cases = [EvaluationCase.model_validate(value) for value in values]
    if not cases or any(case.split != "held_out" for case in cases):
        raise ValueError("evaluation cases must be nonempty held_out cases")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("duplicate evaluation case IDs")
    return cases


def _validate_labels(cases: list[EvaluationCase], manifest: list[dict[str, Any]]) -> None:
    ids = {row["id"] for row in manifest}
    collections = {row["id"]: row["collection"] for row in manifest}
    for case in cases:
        if len({label.id for label in case.issues}) != len(case.issues):
            raise ValueError(f"duplicate issue labels in {case.id}")
        for label in case.issues:
            if set(label.expected_ids) - ids:
                raise ValueError(f"unknown labeled IDs in {case.id}: {sorted(set(label.expected_ids) - ids)}")
            if (set(label.preferred_collections + label.forbidden_collections) - set(collections.values())):
                raise ValueError(f"unknown labeled collection in {case.id}/{label.id}")
            if any(collections[item] in label.forbidden_collections for item in label.expected_ids):
                raise ValueError(f"contradictory expected/forbidden labels in {case.id}/{label.id}")
            if set(label.preferred_collections) & set(label.forbidden_collections):
                raise ValueError(f"contradictory collection labels in {case.id}/{label.id}")
            if not label.expected_ids or not label.preferred_collections:
                raise ValueError(f"positive issue requires expected cards and preferred collection: {case.id}/{label.id}")


def _feedback(case: EvaluationCase) -> FeedbackData:
    return FeedbackData.model_validate({"date": "2026-09-21", **case.feedback})


def score_case(case: EvaluationCase, result: Any, manifest: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {row["id"]: row for row in manifest}
    observed = {issue.id: list(issue.knowledge_item_ids) for issue in result.issues}
    unknown_ids = sorted({item for ids in observed.values() for item in ids} - set(by_id))
    labels = []
    for label in case.issues:
        ranked = observed.get(label.id, [])
        top3 = set(ranked[:3])
        forbidden = [item for item in ranked if item in by_id and by_id[item]["collection"] in label.forbidden_collections]
        labels.append({
            "id": label.id, "ranked_ids": ranked, "expected_ids": label.expected_ids,
            "preferred_collection_hit": any(item in by_id and by_id[item]["collection"] in label.preferred_collections for item in ranked[:3]),
            "top3_coverage": sum(item in top3 for item in label.expected_ids) / len(label.expected_ids) if label.expected_ids else 1.0,
            "misleading_ids": forbidden,
        })
    unexpected = sorted(set(observed) - {label.id for label in case.issues})
    matched = {item for ids in observed.values() for item in ids}
    citations = [citation.id for citation in result.citations]
    expected_matches = {item: sorted(issue for issue, ids in observed.items() if item in ids) for item in matched}
    actual_matches = {citation.id: sorted(citation.matched_issues) for citation in result.citations}
    multiple = sum(len(ids) for ids in observed.values()) > len(matched)
    return {"id": case.id, "category": case.category, "issues": labels,
            "unexpected_issue_ids": unexpected, "missing_issue_ids": sorted({label.id for label in case.issues} - set(observed)),
            "status": "invalid_retrieval" if unknown_ids else result.status,
            "unknown_retrieval_ids": unknown_ids, "cross_issue_overlap": multiple,
            "citation_count": len(citations), "dedup_saved": sum(len(ids) for ids in observed.values()) - len(citations),
            "dedup_correct": len(citations) == len(set(citations)) and set(citations) == matched and actual_matches == expected_matches}


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [label for row in rows for label in row["issues"]]
    overlaps = [row for row in rows if row["cross_issue_overlap"]]
    retrieved = sum(len(label["ranked_ids"]) for label in labels)
    misleading = sum(len(label["misleading_ids"]) for label in labels)
    return {
        "case_count": len(rows), "issue_count": len(labels),
        "preferred_collection_hit_rate": sum(label["preferred_collection_hit"] for label in labels) / len(labels) if labels else 0.0,
        "top3_coverage": sum(label["top3_coverage"] for label in labels) / len(labels) if labels else 0.0,
        "misleading_recall_count": misleading,
        "misleading_recall_rate": misleading / retrieved if retrieved else 0.0,
        "unexpected_issue_count": sum(len(row["unexpected_issue_ids"]) for row in rows),
        "missing_issue_count": sum(len(row["missing_issue_ids"]) for row in rows),
        "unavailable_case_count": sum(row["status"] != "ok" for row in rows),
        "invalid_retrieval_case_count": sum(row["status"] == "invalid_retrieval" for row in rows),
        "cross_issue_overlap_cases": len(overlaps),
        "cross_issue_dedup_success_rate": sum(row["dedup_correct"] for row in overlaps) / len(overlaps) if overlaps else None,
        "duplicate_citations_saved": sum(row["dedup_saved"] for row in overlaps),
    }


def evaluate_retrieval(knowledge_root: Path, cases: list[EvaluationCase]) -> dict[str, Any]:
    manifest = build_manifest(Path(knowledge_root))
    _validate_labels(cases, manifest)
    service = KnowledgeContextService(Path(knowledge_root), Path(knowledge_root) / "baseline-strategies.json")
    keyword_cases = []
    tfidf_cases = []
    tfidf = CharacterTfidf(manifest)
    for case in cases:
        profile = Profile.model_validate({"personal": {"age_years": 22, "height_cm": 180, "weight_kg": 80},
                                          "goals": {"primary": case.goal}})
        result = service.for_feedback(profile, _feedback(case), case.raw_text, case.history)
        keyword_cases.append(score_case(case, result, manifest))
        # Hold issue extraction fixed. The candidate changes only card ranking;
        # raw feedback and issue terms are inputs, human relevance labels are not.
        candidate_issues = tuple(replace(issue, knowledge_item_ids=tfidf.search(
            " ".join((case.raw_text, *issue.terms, *issue.goal_terms)),
        )) for issue in result.issues)
        candidate = KnowledgeContextResult(status=result.status, issues=candidate_issues)
        tfidf_cases.append(score_case(case, candidate, manifest))
    return {
        "corpus": {"approved_cards": len(manifest), "collections": dict(Counter(row["collection"] for row in manifest))},
        "keyword": {"method": "KnowledgeContextService keyword scoring", "cases": keyword_cases, "metrics": _metrics(keyword_cases)},
        "tfidf": {"method": "offline character bigram TF-IDF lexical control; not embeddings", "is_embedding_model": False,
                  "cases": tfidf_cases, "metrics": {key: value for key, value in _metrics(tfidf_cases).items()
                  if not key.startswith("cross_issue") and key != "duplicate_citations_saved"}},
        "embedding_assessment": {"measured": False, "decision": "defer vector infrastructure", "reason": "No local embedding model is configured; TF-IDF is provided only as an offline semantic candidate."},
    }
