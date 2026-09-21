import json
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import DemoAgent
from .config import ROOT, Settings
from .knowledge import build_manifest, search_knowledge
from .knowledge_context import KnowledgeContextService
from .models import (
    FeedbackConfirm,
    FeedbackData,
    ModeRequest,
    ParseRequest,
    PlanRequest,
    Profile,
    ProfileSave,
)
from .review import ReviewNotFound, ReviewService
from .storage import Conflict, NotFound, Store

settings = Settings.from_env()
store = Store(settings.db_path)
app = FastAPI(title="循序 Fitness Assistant")
app.mount("/static", StaticFiles(directory=str(ROOT / "fitness/static")), name="static")
agent = DemoAgent()
review_service = ReviewService(
    ROOT / "data/ingest/bilibili-20260916/mvp-final-card-candidates.json",
    ROOT / "data/local/knowledge-review-decisions.json",
    ROOT / "data/knowledge",
    ROOT / "data/ingest/bilibili-20260916/nutrition-era-catalog.json",
)
knowledge_context_service = KnowledgeContextService(
    ROOT / "data/knowledge",
    ROOT / "data/knowledge/baseline-strategies.json",
)


class KnowledgeReviewRequest(BaseModel):
    status: Literal["pending", "approved", "rejected"]
    note: str = Field(default="", max_length=2000)


@app.get("/")
def index():
    return FileResponse(str(ROOT / "fitness/static/index.html"))


def err(e):
    if isinstance(e, Conflict):
        raise HTTPException(409, str(e))
    if isinstance(e, NotFound):
        raise HTTPException(404, str(e))
    raise e


@app.get("/api/state")
def state():
    record = store.profile()
    return {
        "profile": record["data"] if record else None,
        "profile_version": record["version"] if record else 0,
        "plans": store.plans(),
        "feedback": store.feedback(),
        "mode": "demo",
        "available_modes": ["demo"],
        "model": None,
        "example_available": settings.example_path.exists(),
        "today": datetime.now(ZoneInfo(settings.timezone)).date().isoformat(),
    }


def require_demo(mode):
    if mode != "demo":
        raise HTTPException(503, "在线模型尚未接入，请使用演示模式。")


@app.get("/api/example-profile")
def example():
    if not settings.example_path.exists():
        raise HTTPException(404, "示例档案不存在")
    return json.loads(settings.example_path.read_text(encoding="utf-8"))


@app.put("/api/profile")
def profile(req: ProfileSave):
    try:
        return store.save_profile(req.profile.model_dump(mode="json"), req.expected_version)
    except (Conflict, NotFound) as e:
        err(e)


@app.post("/api/plans")
def plan(req: PlanRequest):
    require_demo(req.mode)
    p = store.profile()
    if not p:
        raise HTTPException(409, "请先保存档案")
    profile_data = Profile.model_validate(p["data"])
    context = knowledge_context_service.for_plan(profile_data)
    data = agent.generate_plan(profile_data, req.start_date, context).model_dump(mode="json")
    trace = {
        "steps": ["baseline_strategy_selection", "planner"],
        "strategy_ids": [strategy["id"] for strategy in data["strategy_context"]],
        "knowledge_item_ids": data["source_ids"],
        "knowledge_status": context.status,
    }
    return store.create_plan(data, p["version"], req.start_date.isoformat(), req.mode, trace)


@app.post("/api/plans/{ident}/confirm")
def confirm_plan(ident: str):
    try:
        return store.confirm_plan(ident)
    except (Conflict, NotFound) as e:
        err(e)


@app.post("/api/feedback/parse")
def parse(req: ParseRequest):
    require_demo(req.mode)
    data = agent.parse_feedback(req.text, req.date).model_dump(mode="json")
    return store.create_feedback(req.text, data, req.mode, {"steps": ["parser"]})


@app.post("/api/feedback/{ident}/confirm")
def confirm_feedback(ident: str, req: FeedbackConfirm):
    try:
        return store.confirm_feedback(
            ident,
            req.data.model_dump(mode="json"),
            req.expected_revision,
            trace={"steps": ["parser"]},
        )
    except (Conflict, NotFound) as e:
        err(e)


@app.post("/api/feedback/{ident}/advice")
def advice(ident: str, req: ModeRequest):
    require_demo(req.mode)
    try:
        row = store.get_feedback(ident)
        if row["status"] != "confirmed":
            raise HTTPException(409, "请先确认反馈")
        p = store.profile()
        if not p:
            raise HTTPException(409, "请先保存档案")
        profile_data = Profile.model_validate(p["data"])
        feedback_data = FeedbackData.model_validate(row["data"])
        history = store.feedback()
        context = knowledge_context_service.for_feedback(
            profile_data,
            feedback_data,
            row["raw_text"],
            history,
        )
        a = agent.advice(
            profile_data,
            feedback_data,
            history,
            context,
        ).model_dump(mode="json")
        advice_trace = {
            "steps": ["issue_extraction", "knowledge_retrieval", "advisor"],
            "issues": [issue.id for issue in context.issues],
            "profile_goal": profile_data.goals.primary,
            "issue_goal_context": [
                {
                    "issue": issue.id,
                    "terms": list(issue.goal_terms),
                    "collections": list(issue.goal_collections),
                }
                for issue in context.issues
            ],
            "knowledge_query_terms": list(context.query_terms),
            "knowledge_item_ids": a["source_ids"],
            "knowledge_status": context.status,
        }
        return store.save_advice(
            ident,
            a,
            None,
            row["revision"],
            trace=advice_trace,
            expected_updated_at=row["updated_at"],
            expected_profile_version=p["version"],
        )
    except (Conflict, NotFound) as e:
        err(e)


@app.get("/api/feedback/{ident}/revisions")
def revisions(ident: str):
    try:
        return store.feedback_revisions(ident)
    except (Conflict, NotFound) as e:
        err(e)


@app.get("/api/sources")
def sources():
    return [
        {
            "id": "acsm-exercise-guidance",
            "title": "ACSM exercise guidance",
            "url": "https://www.acsm.org/",
            "note": "训练与健康参考",
        },
        {
            "id": "nih-ods-facts",
            "title": "NIH ODS fact sheets",
            "url": "https://ods.od.nih.gov/factsheets/list-all/",
            "note": "补剂信息参考",
        },
    ]


@app.get("/api/knowledge/search")
def knowledge_search(q: str, limit: int = 8):
    if not q.strip():
        raise HTTPException(400, "请输入检索词")
    if limit < 1 or limit > 20:
        raise HTTPException(400, "limit 必须在 1 到 20 之间")
    return {"query": q, "items": search_knowledge(ROOT / "data/knowledge", q, limit)}


@app.get("/api/knowledge/review")
def knowledge_review():
    return {"counts": review_service.summary(), "cards": review_service.cards()}


@app.post("/api/knowledge/review/publish")
def publish_knowledge_review():
    result = review_service.publish()
    result["manifest_items"] = len(build_manifest(review_service.knowledge_root))
    return result


@app.post("/api/knowledge/review/{card_id}")
def save_knowledge_review(card_id: str, req: KnowledgeReviewRequest):
    try:
        return review_service.review(card_id, req.status, req.note)
    except ReviewNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/health")
def health():
    return {"ok": True}
