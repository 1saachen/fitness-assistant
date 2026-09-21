"""Deliberately curated baseline strategies and fail-closed source coverage."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError

from fitness.knowledge import build_manifest
from fitness.models import FeedbackData, KnowledgeCitation, KnowledgeVideo, Profile, StrategySnapshot


class StrategyCoverageError(ValueError):
    """A strategy library does not account for its approved source manifest."""


def _ids(prefix: str, numbers: tuple[int, ...]) -> set[str]:
    return {f"{prefix}-{number:03d}" for number in numbers}


TRAINING_CARDIO = _ids("mvp-training", (1, 2, 3, 4, 12))
TRAINING_STRENGTH = _ids("mvp-training", (4, 5, 6, 7, 8, 9, 10))
TRAINING_ENERGY = _ids("mvp-training", (11, 13))
TRAINING_MONITORING = _ids("mvp-training", (11, 12, 13))
DIET_ENERGY = _ids("mvp-diet_fat_loss", (1, 2, 3, 4, 5, 8, 10, 12, 13, 14, 16, 17))
DIET_STRUCTURE = _ids("mvp-diet_fat_loss", (6, 7, 8, 9, 11, 13, 14, 15, 16, 18))
DIET_ACTIVITY = _ids("mvp-diet_fat_loss", (17,))
DIET_MONITORING = _ids("mvp-diet_fat_loss", (2, 3, 4, 7, 10, 14, 15, 16, 17))


def validate_strategy_coverage(
    manifest: list[dict], strategies: list[dict], reference_only: list[dict] | None = None,
) -> dict[str, int]:
    """Validate approved manifest coverage; reference-only records require id/reason.

    Items may support multiple strategies, but may not repeat within one strategy.
    Reference-only items must be disjoint from strategy sources.
    """
    for field, records in (("manifest", manifest), ("strategies", strategies),
                           ("reference_only", [] if reference_only is None else reference_only)):
        if not isinstance(records, list):
            raise StrategyCoverageError(f"{field} must be a list of mappings")
        for index, record in enumerate(records):
            location = f"{field}[{index}]"
            if not isinstance(record, Mapping):
                raise StrategyCoverageError(f"{location} must be a mapping")
            item_id = record.get("id")
            if not isinstance(item_id, str) or not item_id.strip():
                raise StrategyCoverageError(f"{location}.id must be a nonempty string")
            if field == "strategies":
                item_ids = record.get("knowledge_item_ids")
                if not isinstance(item_ids, list):
                    raise StrategyCoverageError(f"{location}.knowledge_item_ids must be a list")
                for item_index, knowledge_id in enumerate(item_ids):
                    if not isinstance(knowledge_id, str) or not knowledge_id.strip():
                        raise StrategyCoverageError(
                            f"{location}.knowledge_item_ids[{item_index}] must be a nonempty string"
                        )
            elif field == "reference_only":
                reason = record.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    raise StrategyCoverageError(f"{location}.reason must be a nonempty string")
    approved = {row["id"] for row in manifest}
    if len(approved) != len(manifest):
        raise StrategyCoverageError("duplicate manifest item IDs")
    seen_strategies: set[str] = set()
    covered: set[str] = set()
    for strategy in strategies:
        strategy_id = strategy["id"]
        if strategy_id in seen_strategies:
            raise StrategyCoverageError(f"duplicate strategy ID: {strategy_id}")
        seen_strategies.add(strategy_id)
        item_ids = strategy["knowledge_item_ids"]
        if len(item_ids) != len(set(item_ids)):
            raise StrategyCoverageError(f"duplicate knowledge item ID in strategy: {strategy_id}")
        covered.update(item_ids)
    references: set[str] = set()
    for record in reference_only or []:
        item_id = record["id"]
        if item_id in references or item_id in covered:
            raise StrategyCoverageError(f"duplicate reference-only item: {item_id}")
        references.add(item_id)
    unknown = (covered | references) - approved
    if unknown:
        raise StrategyCoverageError(f"unknown referenced item IDs: {sorted(unknown)}")
    missing = approved - covered - references
    if missing:
        raise StrategyCoverageError(f"missing approved item IDs: {sorted(missing)}")
    return {"approved": len(approved), "covered": len(covered), "reference_only": len(references)}


def build_strategy_library(manifest: list[dict]) -> list[dict]:
    """Build seven modules without implicitly classifying future training/diet items."""
    supplements = {row["id"] for row in manifest if row["collection"] == "supplements"}
    sleep = {
        row["id"] for row in manifest
        if row["collection"] == "sleep_recovery" or row["id"].startswith("couren-")
    }
    definitions = [
        (
            "fat-loss-energy", "fat_loss", "减脂目标与能量平衡",
            "用多周趋势评估适度热量缺口，避免把出汗或单日体重变化当作减脂结果。",
            ["采用可持续的热量缺口，并根据多周体重与执行情况调整。",
             "出现明显疲劳、恢复下降或过度节食信号时先检查缺口是否过大。"],
            ["fat_loss"], TRAINING_ENERGY | DIET_ENERGY,
        ),
        (
            "diet-protein", "nutrition", "饮食结构与蛋白质",
            "优先建立可持续的总摄入、蛋白质和必需脂肪来源，再处理进餐时机。",
            ["每餐优先保留可识别的蛋白质来源并记录外食中的隐藏热量。",
             "不因减脂而长期压低必需脂肪摄入。"],
            ["fat_loss", "muscle_gain", "general_health"], DIET_STRUCTURE,
        ),
        (
            "strength-retention", "training", "抗阻训练与力量保持",
            "减脂期保留规律抗阻训练、动作质量和可恢复的训练强度。",
            ["优先维持主要动作的技术和训练强度，再按恢复情况调整训练量。",
             "负重、间歇和动作选择必须匹配经验、器械和当日状态。"],
            ["fat_loss", "muscle_gain", "general_health"], TRAINING_STRENGTH,
        ),
        (
            "cardio-activity", "training", "有氧与日常活动",
            "用可持续的有氧和日常活动增加总消耗，不夸大单次后燃或局部出汗。",
            ["有氧安排服从力量训练恢复和长期执行。",
             "平台期同时检查日常活动量，不只增加正式训练。"],
            ["fat_loss", "general_health"], TRAINING_CARDIO | DIET_ACTIVITY,
        ),
        (
            "sleep-recovery", "sleep_recovery", "睡眠、疲劳与恢复",
            "先处理睡眠时长、环境、咖啡因酒精和行为习惯，再考虑补充剂。",
            ["连续睡眠不足或疲劳时降低当日训练压力并观察趋势。",
             "可穿戴数据用于观察趋势，不能替代症状和专业评估。"],
            ["fat_loss", "muscle_gain", "general_health"], sleep,
        ),
        (
            "supplement-priority", "supplements", "补剂优先级与安全边界",
            "补剂是饮食、训练和睡眠之后的可选工具，应结合缺口、适用条件和产品质量。",
            ["不因视频提及就默认推荐，也不自动生成个体剂量。",
             "疾病、药物、特殊人群或高剂量场景必须转向专业评估。"],
            ["fat_loss", "muscle_gain", "general_health"], supplements,
        ),
        (
            "monitoring-adjustment", "monitoring", "监测、平台期与调整",
            "结合多周体重、围度、力量、睡眠、疲劳和执行率判断是否调整。",
            ["单日波动不触发长期计划变更。",
             "先定位执行、记录、活动量和恢复问题，再改变热量或训练安排。"],
            ["fat_loss", "muscle_gain", "general_health"], TRAINING_MONITORING | DIET_MONITORING,
        ),
    ]
    strategies = [
        {
            "id": strategy_id, "domain": domain, "title": title, "summary": summary,
            "action_rules": rules, "applicability": goals,
            "limitations": ["来源包含视频作者观点，存在转录与证据局限；审核通过不代表医学共识。"],
            "safety_boundary": (
                "不自动生成个体化剂量或医疗建议；涉及疾病、药物、特殊人群、"
                "持续症状或训练风险时需专业评估。"
            ),
            "knowledge_item_ids": sorted(item_ids),
        }
        for strategy_id, domain, title, summary, rules, goals, item_ids in definitions
    ]
    validate_strategy_coverage(manifest, strategies)
    return strategies


@dataclass(frozen=True)
class RetrievalIssue:
    id: str
    label: str
    terms: tuple[str, ...]
    collections: tuple[str, ...]
    knowledge_item_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeContextResult:
    strategies: tuple[StrategySnapshot, ...] = ()
    citations: tuple[KnowledgeCitation, ...] = ()
    issues: tuple[RetrievalIssue, ...] = ()
    query_terms: tuple[str, ...] = ()
    status: str = "ok"


_CONTEXT_ERRORS = (OSError, UnicodeError, json.JSONDecodeError, ValidationError, StrategyCoverageError)


def _citation(row: dict, matched_issues: tuple[str, ...] = ()) -> KnowledgeCitation:
    source = row["source"]
    videos = source.get("videos") or [{
        "bvid": None, "title": source["video_title"], "url": source["video_url"],
        "published_at": source.get("published_at"),
    }]
    return KnowledgeCitation(
        id=row["id"], title=row["title"], collection=row["collection"],
        excerpt=(row["metadata"].get("claim") or row["text"])[:2000],
        creator_name=source["creator_name"], videos=[KnowledgeVideo.model_validate(video) for video in videos],
        matched_issues=list(matched_issues),
    )


def _has_weight_plateau(history: list[dict], current: FeedbackData) -> bool:
    window_start = current.date - timedelta(days=21)
    measurements = {current.date: current.weight_kg} if current.weight_kg is not None else {}
    for record in history:
        if not isinstance(record, Mapping) or record.get("status") != "confirmed":
            continue
        data = record.get("data")
        if not isinstance(data, Mapping):
            continue
        try:
            entry = FeedbackData.model_validate({"date": record.get("date"), **data})
        except ValidationError:
            continue
        if entry.weight_kg is not None and window_start <= entry.date <= current.date:
            # Current feedback takes precedence; history arrives newest first.
            measurements.setdefault(entry.date, entry.weight_kg)
    if len(measurements) < 3 or (max(measurements) - min(measurements)).days < 14:
        return False
    # Require stable measurements throughout the period, not merely similar endpoints.
    return max(measurements.values()) - min(measurements.values()) <= 0.3 + 1e-9


def _mentions_supplement(title: str, raw_text: str) -> bool:
    title_folded, text_folded = title.casefold(), raw_text.casefold()
    if len(title) > 1:
        return title_folded in text_folded
    if text_folded.strip() == title_folded:
        return True
    return any(pattern in text_folded for pattern in (
        f"补{title_folded}", f"{title_folded}补剂", f"{title_folded}剂",
        f"缺{title_folded}", f"{title_folded}片", f"{title_folded}元素",
    ))


def _extract_issues(feedback: FeedbackData, raw_text: str, history: list[dict],
                    manifest: list[dict]) -> tuple[RetrievalIssue, ...]:
    issues = []
    if feedback.sleep_hours is not None and feedback.sleep_hours < 7:
        issues.append(RetrievalIssue("short_sleep", "睡眠不足", ("睡眠", "睡眠时长", "恢复"),
                                     ("sleep_recovery", "supplements")))
    if feedback.fatigue:
        issues.append(RetrievalIssue("training_fatigue", "训练疲劳", ("疲劳", "恢复", "训练量"),
                                     ("training", "sleep_recovery")))
    if feedback.food_summary or any(term in raw_text for term in ("吃", "食堂", "外卖", "饮食")):
        issues.append(RetrievalIssue("diet_adherence", "饮食执行", ("饮食记录", "隐藏热量", "蛋白质"),
                                     ("fat_loss",)))
    if feedback.weight_kg is not None:
        issues.append(RetrievalIssue("weight_trend", "体重趋势", ("体重变化", "长期减脂评估"), ("fat_loss",)))
    supplement_titles = tuple(dict.fromkeys(
        row["title"] for row in manifest
        if row["collection"] == "supplements" and _mentions_supplement(row["title"], raw_text)
    ))
    if supplement_titles:
        issues.append(RetrievalIssue("supplement_question", "补剂问题",
                                     tuple(dict.fromkeys((*supplement_titles, "补剂"))), ("supplements",)))
    if _has_weight_plateau(history, feedback):
        issues.append(RetrievalIssue("weight_plateau", "体重平台期", ("体重变化", "平台期", "热量缺口"),
                                     ("fat_loss", "training")))
    return tuple(issues)


def _retrieve_issue(issue: RetrievalIssue, manifest: list[dict]) -> RetrievalIssue:
    scored = []
    for row in manifest:
        title, body = row["title"].casefold(), row["text"].casefold()
        matched = {term for term in issue.terms if term.casefold() in title or term.casefold() in body}
        if not matched:
            continue
        score = sum(
            12 * (term.casefold() == title) + 4 * title.count(term.casefold()) + body.count(term.casefold())
            for term in matched
        )
        if row["collection"] in issue.collections:
            score += 2
        scored.append((score, row["id"], matched))
    scored.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    selected = scored[:3]
    matched_terms = set().union(*(entry[2] for entry in scored))
    covered = set().union(*(entry[2] for entry in selected))
    if len(matched_terms) >= 3 and covered != matched_terms:
        for candidate in scored[3:]:
            if not candidate[2] - covered:
                continue
            selected.append(candidate)
            covered.update(candidate[2])
            if len(selected) == 5 or covered == matched_terms:
                break
    return replace(issue, knowledge_item_ids=tuple(entry[1] for entry in selected))


class KnowledgeContextService:
    """Build deterministic context from current approved cards and reviewed strategies."""

    def __init__(self, knowledge_root: Path, strategy_path: Path):
        self.knowledge_root = Path(knowledge_root)
        self.strategy_path = Path(strategy_path)

    def _load(self) -> tuple[list[dict], list[tuple[dict, StrategySnapshot]]]:
        if not self.knowledge_root.is_dir():
            raise StrategyCoverageError("knowledge root must be an existing directory")
        try:
            manifest = build_manifest(self.knowledge_root)
        except ValueError as error:
            # The manifest API reports referential-integrity errors as plain ValueError.
            # Translate only those known data failures; programming errors must propagate.
            if type(error) is ValueError and str(error).startswith((
                "duplicate source id:", "duplicate knowledge id:", "missing source for knowledge item:",
            )):
                raise StrategyCoverageError(str(error)) from error
            raise
        if not manifest:
            raise StrategyCoverageError("knowledge root has no approved items")
        manifest.sort(key=lambda row: row["id"])
        artifact = json.loads(self.strategy_path.read_text(encoding="utf-8"))
        if not isinstance(artifact, Mapping):
            raise StrategyCoverageError("strategy artifact must be a mapping")
        if type(artifact.get("version")) is not int or artifact["version"] != 1:
            raise StrategyCoverageError("unsupported strategy artifact version")
        if not isinstance(artifact.get("strategies"), list):
            raise StrategyCoverageError("strategies must be a list")
        if not isinstance(artifact.get("reference_only"), list):
            raise StrategyCoverageError("reference_only must be a list")
        persisted_coverage = artifact.get("coverage")
        if (not isinstance(persisted_coverage, Mapping)
                or set(persisted_coverage) != {"approved", "covered", "reference_only"}
                or any(type(value) is not int or value < 0 for value in persisted_coverage.values())):
            raise StrategyCoverageError("coverage must contain exactly three nonnegative integer counts")
        strategies = artifact["strategies"]
        report = validate_strategy_coverage(manifest, strategies, artifact["reference_only"])
        if dict(persisted_coverage) != report:
            raise StrategyCoverageError("persisted coverage does not match the approved manifest")
        validated = []
        for strategy in strategies:
            applicability = strategy.get("applicability")
            if (not isinstance(applicability, list) or not applicability
                    or any(goal not in ("fat_loss", "muscle_gain", "general_health") for goal in applicability)):
                raise StrategyCoverageError("strategy applicability must contain supported goals")
            snapshot = StrategySnapshot.model_validate({
                key: strategy[key] for key in StrategySnapshot.model_fields if key in strategy
            })
            validated.append((strategy, snapshot))
        return manifest, validated

    def for_plan(self, profile: Profile) -> KnowledgeContextResult:
        try:
            manifest, validated = self._load()
            strategies = tuple(snapshot for strategy, snapshot in validated
                               if profile.goals.primary in strategy["applicability"])
            selected_ids = {item_id for strategy in strategies for item_id in strategy.knowledge_item_ids}
            citations = tuple(_citation(row) for row in manifest if row["id"] in selected_ids)
            return KnowledgeContextResult(strategies=strategies, citations=citations)
        except _CONTEXT_ERRORS:
            return KnowledgeContextResult(status="unavailable")

    def for_feedback(self, profile: Profile, feedback: FeedbackData, raw_text: str,
                     history: list[dict]) -> KnowledgeContextResult:
        try:
            manifest, _ = self._load()
            issues = tuple(_retrieve_issue(issue, manifest)
                           for issue in _extract_issues(feedback, raw_text, history, manifest))
            matches: dict[str, list[str]] = {}
            for issue in issues:
                for item_id in issue.knowledge_item_ids:
                    matches.setdefault(item_id, []).append(issue.id)
            citations = tuple(_citation(row, tuple(matches[row["id"]]))
                              for row in manifest if row["id"] in matches)
            query_terms = tuple(dict.fromkeys(term for issue in issues for term in issue.terms))
            return KnowledgeContextResult(citations=citations, issues=issues, query_terms=query_terms)
        except _CONTEXT_ERRORS:
            return KnowledgeContextResult(status="unavailable")
