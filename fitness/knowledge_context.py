"""Deliberately curated baseline strategies and fail-closed source coverage."""

from collections.abc import Mapping


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
