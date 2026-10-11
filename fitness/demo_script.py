"""Run the complete local demo flow without an external model."""

from datetime import date
from pathlib import Path

from .config import ROOT, Settings
from .demo import DemoDataError, initialize_demo_profile
from .knowledge_context import KnowledgeContextService
from .models import Profile
from .orchestration import FitnessAgent
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
    agent = FitnessAgent(store, context_service, Settings(db_path=store.path))

    plan_run = agent.plan(profile, start_date, 'demo')
    plan_data = plan_run.data.model_dump(mode="json")
    plan = store.create_plan(
        plan_data,
        profile_row["version"],
        start_date.isoformat(),
        "demo",
        plan_run.trace,
    )
    plan = store.confirm_plan(plan["id"])

    raw_text = "完成训练，睡了6小时，今天很累，吃食堂"
    feedback_data = agent.parse(raw_text, start_date, 'demo').data.model_dump(mode="json")
    feedback = store.create_feedback(raw_text, feedback_data, "demo", {"steps": ["parser"]})
    feedback = store.confirm_feedback(
        feedback["id"], feedback_data, 0, trace={"steps": ["parser"]}
    )
    advice_run = agent.advise(feedback, 'demo')
    advice = advice_run.data.model_dump(mode='json')
    advice_trace = advice_run.trace
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
