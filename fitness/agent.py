import re

from .knowledge_context import KnowledgeContextResult
from .models import AdviceData, FeedbackData
from .planning import generate_plan, persistent_context_snapshots


def _creator_references(context, citations, available_slots):
    if context.status != "ok" or available_slots <= 0:
        return []
    citations_by_id = {citation.id: citation for citation in citations}
    suggestions = []
    seen_issue_ids = set()
    for issue in context.issues:
        if issue.id in seen_issue_ids:
            continue
        seen_issue_ids.add(issue.id)
        citation = next(
            (
                citations_by_id[item_id]
                for item_id in issue.knowledge_item_ids
                if item_id in citations_by_id
            ),
            None,
        )
        if citation is None:
            continue
        reference = citation.excerpt.split("。", 1)[0][:80]
        suggestions.append(
            f"知识库参考（视频观点）：{issue.label}：{reference}。"
            "仅作创作者参考，请结合适用条件理解，不作为个体补剂剂量或医疗结论。"
        )
        if len(suggestions) == available_slots:
            break
    return suggestions


class DemoAgent:
    mode = "demo"

    def generate_plan(self, profile, start_date, context=None):
        return generate_plan(profile, start_date, context)

    def parse_feedback(self, text, day):
        sleep = None
        match = re.search(r"(?:睡了|睡眠)\s*(\d+(?:\.\d+)?)\s*小时?", text)
        if match:
            sleep = float(match.group(1))
        weight = None
        match = re.search(r"体重\s*(\d+(?:\.\d+)?)\s*(?:kg|公斤)?", text)
        if match:
            weight = float(match.group(1))
        completed = (
            True
            if any(item in text for item in ("完成训练", "练完", "训练完成"))
            else False
            if any(item in text for item in ("没练", "未训练", "跳过"))
            else None
        )
        return FeedbackData(
            date=day,
            training_summary=text if completed is not None else None,
            training_completed=completed,
            food_summary="食堂" if "食堂" in text else None,
            sleep_hours=sleep,
            weight_kg=weight,
            fatigue="有点累" if "累" in text else None,
            uncertainties=["未提供精确食物份量，未估算热量"] if "吃" in text or "食堂" in text else [],
        )

    def advice(self, profile, feedback, history, context=None):
        context = context or KnowledgeContextResult()
        _, citations = persistent_context_snapshots(context)
        suggestions = ["保持训练动作质量和逐步增加重量", "优先保证规律睡眠与蛋白质来源"]
        if feedback.fatigue:
            suggestions.append("今天感到疲劳时降低训练量，观察连续几天趋势")
        suggestions.extend(_creator_references(context, citations, 8 - len(suggestions)))
        return AdviceData(
            summary="根据这次反馈给出短期建议，单日数据不足以改变长期计划。",
            suggestions=suggestions,
            source_ids=[citation.id for citation in citations],
            knowledge_context=citations,
        )
