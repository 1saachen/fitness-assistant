"""Run the complete local demo flow without an external model."""

from datetime import date
from pathlib import Path

from .agent import DemoAgent
from .config import ROOT
from .demo import DemoDataError, initialize_demo_profile
from .knowledge_context import KnowledgeContextService
from .models import FeedbackData, Profile
from .planning import context_persistence_status
from .storage import Store


def run_demo_walkthrough(store: Store, profile_path: Path, start_date: date) -> dict:
    """Create a plan, confirm feedback and generate advice in one local run."""
    if store.plans() or store.feedback():
        raise DemoDataError("演示数据库已有计划或反馈，请先使用 reset --confirm。")
    initialize_demo_profile(store, profile_path)
    profile_row = store.profile()
    profile = Profile.model_validate(profile_row["data"])
    context_service = KnowledgeContextService(
        ROOT / "data/knowledge", ROOT / "data/knowledge/baseline-strategies.json"
    )
    agent = DemoAgent()

    plan_context = context_service.for_plan(profile)
    plan_data = agent.generate_plan(profile, start_date, plan_context).model_dump(mode="json")
    plan = store.create_plan(
        plan_data,
        profile_row["version"],
        start_date.isoformat(),
        "demo",
        {
            "steps": ["baseline_strategy_selection", "planner"],
            "strategy_ids": [row["id"] for row in plan_data["strategy_context"]],
            "knowledge_item_ids": plan_data["source_ids"],
            "knowledge_status": context_persistence_status(plan_context),
        },
    )
    plan = store.confirm_plan(plan["id"])

    raw_text = "完成训练，睡了6小时，今天很累，吃食堂"
    feedback_data = agent.parse_feedback(raw_text, start_date).model_dump(mode="json")
    feedback = store.create_feedback(raw_text, feedback_data, "demo", {"steps": ["parser"]})
    feedback = store.confirm_feedback(
        feedback["id"], feedback_data, 0, trace={"steps": ["parser"]}
    )
    feedback_model = FeedbackData.model_validate(feedback["data"])
    history = store.feedback()
    advice_context = context_service.for_feedback(profile, feedback_model, raw_text, history)
    advice = agent.advice(profile, feedback_model, history, advice_context).model_dump(mode="json")
    advice_trace = {
        "steps": ["issue_extraction", "knowledge_retrieval", "advisor"],
        "issues": [issue.id for issue in advice_context.issues],
        "profile_goal": profile.goals.primary,
        "issue_goal_context": [
            {
                "issue": issue.id,
                "terms": list(issue.goal_terms),
                "collections": list(issue.goal_collections),
            }
            for issue in advice_context.issues
        ],
        "knowledge_query_terms": list(advice_context.query_terms),
        "knowledge_item_ids": advice["source_ids"],
        "knowledge_status": context_persistence_status(advice_context),
    }
    feedback = store.save_advice(
        feedback["id"],
        advice,
        None,
        feedback["revision"],
        trace=advice_trace,
        expected_updated_at=feedback["updated_at"],
        expected_profile_version=profile_row["version"],
    )
    return {
        "status": "completed",
        "profile_version": profile_row["version"],
        "plan_id": plan["id"],
        "plan_status": plan["status"],
        "feedback_id": feedback["id"],
        "feedback_status": feedback["status"],
        "advice_generated": feedback["advice"] is not None,
        "plan_knowledge_status": plan["trace"]["knowledge_status"],
        "advice_knowledge_status": feedback["trace"]["knowledge_status"],
    }
