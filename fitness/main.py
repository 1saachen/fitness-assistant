import json
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import DemoAgent
from .config import ROOT, Settings
from .data_transfer import confirm_feedback_import, preview_feedback_import
from .exporting import ExportFormatError, render_export
from .history import HistoryQueryError, explain_similar_feedback, get_recent_feedback, summarize_recent_trend
from .knowledge import build_manifest, search_knowledge
from .knowledge_context import KnowledgeContextService
from .models import (
    Contract,
    FeedbackConfirm,
    ModeRequest,
    ParseRequest,
    PlanRequest,
    Profile,
    ProfileSave,
)
from .orchestration import FitnessAgent
from .planning import context_persistence_status
from .review import ReviewNotFound, ReviewService
from .storage import Conflict, NotFound, Store
from .tools import LocalTools

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


class ImportRequest(Contract):
    content: str = Field(min_length=1, max_length=1_000_000)
    format: Literal['json', 'csv', 'markdown']
    batch_id: str | None = None
    confirmed: bool = False


class AdjustmentConfirm(Contract):
    proposal: dict
    confirmed: bool = False


@app.post('/api/import/feedback/preview')
def import_preview(req: ImportRequest):
    try:
        return preview_feedback_import(req.content, req.format)
    except ValueError as exc:
        raise HTTPException(400, {'code':'import_invalid', 'message':str(exc), 'retryable':False}) from exc


@app.post('/api/import/feedback/confirm')
def import_confirm(req: ImportRequest):
    try:
        return confirm_feedback_import(store, req.content, req.format,
                                       expected_batch_id=req.batch_id or '', confirmed=req.confirmed)
    except Conflict as exc:
        err(exc)
    except ValueError as exc:
        raise HTTPException(400, {'code':'import_invalid', 'message':str(exc), 'retryable':False}) from exc


@app.get('/api/feedback/{ident}/training-adjustment')
def adjustment_preview(ident: str):
    try:
        row = store.get_feedback(ident)
        if row['status'] != 'confirmed':
            raise Conflict('请先确认反馈。')
        return LocalTools(store, knowledge_context_service, row,
                          today=_history_end_date(None)).call('adjust_today_training', {}).payload
    except (Conflict, NotFound) as exc:
        err(exc)


@app.post('/api/feedback/{ident}/training-adjustment/confirm')
def adjustment_confirm(ident: str, req: AdjustmentConfirm):
    if not req.confirmed:
        raise HTTPException(400, '需要明确确认局部调整。')
    proposal = adjustment_preview(ident)
    if not proposal.get('changes'):
        raise HTTPException(409, '当前没有适用的当日训练调整。')
    if proposal != req.proposal:
        err(Conflict('反馈或计划已有更新，请重新预览调整。'))
    try:
        return store.record_plan_change(**{k:v for k,v in proposal.items() if k != 'reason'})
    except (Conflict, NotFound) as exc:
        err(exc)
    except ValueError as exc:
        raise HTTPException(400, '局部调整不符合允许的字段范围。') from exc


@app.get('/api/plans/{ident}/changes')
def plan_changes(ident: str):
    return store.plan_changes(ident)


@app.get("/")
def index():
    return FileResponse(str(ROOT / "fitness/static/index.html"))


def err(e):
    if isinstance(e, Conflict):
        message = str(e)
        if "档案" in message:
            code = "profile_version_conflict"
        elif "反馈" in message:
            code = "feedback_revision_conflict"
        else:
            code = "request_conflict"
        raise HTTPException(409, {
            "code": code,
            "message": message,
            "retryable": True,
        })
    if isinstance(e, NotFound):
        raise HTTPException(404, {
            "code": "not_found",
            "message": str(e),
            "retryable": False,
        })
    raise e


@app.get("/api/state")
def state():
    record = store.profile()
    knowledge_status = "unknown"
    if record:
        try:
            context = knowledge_context_service.for_plan(Profile.model_validate(record["data"]))
            knowledge_status = context_persistence_status(context)
        except Exception as exc:
            if isinstance(exc, (OSError, ValueError, json.JSONDecodeError)):
                knowledge_status = "unavailable"
            else:
                raise
    return {
        "profile": record["data"] if record else None,
        "profile_version": record["version"] if record else 0,
        "plans": store.plans(),
        "feedback": _feedback_state(),
        "mode": "demo",
        "available_modes": ["demo", "live"] if settings.live_enabled and settings.api_key else ["demo"],
        "model": settings.model if settings.live_enabled and settings.api_key else None,
        "plan_changes": store.plan_changes(),
        "example_available": settings.example_path.exists(),
        "knowledge_status": knowledge_status,
        "today": datetime.now(ZoneInfo(settings.timezone)).date().isoformat(),
    }


def _feedback_state():
    rows = store.feedback()
    changes = store.plan_changes()
    for row in rows:
        preview = (row.get('trace') or {}).get('training_adjustment_preview')
        if preview and any(c['feedback_id'] == row['id'] and c['changes'] == preview.get('changes')
                           for c in changes):
            row['trace'].pop('training_adjustment_preview', None)
    return rows


def require_demo(mode):
    if mode != "demo" and not (settings.live_enabled and settings.api_key):
        raise HTTPException(503, {
            "code": "mode_unavailable",
            "message": "在线模型未启用或未配置密钥，请使用演示模式。",
            "retryable": False,
        })


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
    try:
        run = FitnessAgent(store, knowledge_context_service, settings, rules=agent).plan(
            profile_data, req.start_date, req.mode)
    except Conflict as exc:
        err(exc)
    return store.create_plan(run.data.model_dump(mode="json"), p["version"],
                             req.start_date.isoformat(), req.mode, run.trace)


@app.post("/api/plans/{ident}/confirm")
def confirm_plan(ident: str):
    try:
        return store.confirm_plan(ident)
    except (Conflict, NotFound) as e:
        err(e)


@app.post("/api/feedback/parse")
def parse(req: ParseRequest):
    require_demo(req.mode)
    run = FitnessAgent(store, knowledge_context_service, settings, rules=agent).parse(req.text, req.date, req.mode)
    return store.create_feedback(req.text, run.data.model_dump(mode='json'), req.mode, run.trace)


@app.post("/api/feedback/{ident}/confirm")
def confirm_feedback(ident: str, req: FeedbackConfirm):
    try:
        row = store.get_feedback(ident)
        parser_usage = (row.get('trace') or {}).get('parser_provider')
        if not parser_usage and row['status'] == 'draft':
            parser_usage = (row.get('trace') or {}).get('provider')
        trace = {'steps':['parser']}
        if parser_usage and parser_usage.get('status') != 'demo':
            trace['parser_provider'] = parser_usage
        return store.confirm_feedback(
            ident,
            req.data.model_dump(mode="json"),
            req.expected_revision,
            trace=trace,
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
        run = FitnessAgent(store, knowledge_context_service, settings, rules=agent).advise(
            row, req.mode, today=_history_end_date(None))
        a = run.data.model_dump(mode="json")
        advice_trace = run.trace
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


def _export_response(kind: str, export_format: str, rows: list[dict]):
    try:
        document = render_export(kind, rows, export_format)
    except ExportFormatError as exc:
        raise HTTPException(400, {
            "code": "export_format_invalid" if "格式" in str(exc) else "export_type_invalid",
            "message": str(exc),
            "retryable": False,
        }) from exc
    if not rows:
        raise HTTPException(404, {
            "code": "export_not_found",
            "message": "没有可导出的记录。",
            "retryable": False,
        })
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
    )


def _history_end_date(value: date | None) -> date:
    return value or datetime.now(ZoneInfo(settings.timezone)).date()


def _history_error(exc: HistoryQueryError):
    raise HTTPException(400, {
        "code": "history_query_invalid",
        "message": str(exc),
        "retryable": False,
    }) from exc


@app.get("/api/history/recent")
def history_recent(
    days: int = 7,
    end_date: date | None = None,
    issue: str | None = None,
    metric: str | None = None,
):
    try:
        return get_recent_feedback(
            store.feedback(limit=None),
            end_date=_history_end_date(end_date),
            days=days,
            issue=issue,
            metric=metric,
        )
    except HistoryQueryError as exc:
        _history_error(exc)


@app.get("/api/history/trends")
def history_trends(days: int = 7, end_date: date | None = None):
    try:
        return summarize_recent_trend(
            store.feedback(limit=None), end_date=_history_end_date(end_date), days=days
        )
    except HistoryQueryError as exc:
        _history_error(exc)


@app.get("/api/history/similar/{feedback_id}")
def history_similar(feedback_id: str, limit: int = 3):
    try:
        current = store.get_feedback(feedback_id)
        return explain_similar_feedback(store.feedback(limit=None), current, limit=limit)
    except HistoryQueryError as exc:
        _history_error(exc)
    except NotFound as exc:
        err(exc)


@app.get("/api/export/plan")
def export_plan(format: str = "json", plan_id: str | None = None):
    rows = store.plans()
    if plan_id:
        rows = [row for row in rows if row["id"] == plan_id]
    return _export_response("plan", format, rows)


@app.get("/api/export/feedback")
def export_feedback(format: str = "json", feedback_id: str | None = None):
    rows = store.feedback()
    if feedback_id:
        rows = [row for row in rows if row["id"] == feedback_id]
    return _export_response("feedback", format, rows)


@app.get("/api/export/advice")
def export_advice(format: str = "json", feedback_id: str | None = None):
    rows = [row for row in store.feedback() if row.get("advice") is not None]
    if feedback_id:
        rows = [row for row in rows if row["id"] == feedback_id]
    return _export_response("advice", format, rows)


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
