"""Deterministic, local-only exports for plans, feedback and advice."""

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class ExportFormatError(ValueError):
    """Raised when an export type or format is not supported."""


SUPPORTED_TYPES = {"plan", "feedback", "advice"}
SUPPORTED_FORMATS = {"json", "csv", "markdown"}


@dataclass(frozen=True)
class ExportDocument:
    content: str
    media_type: str
    filename: str


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _trace_status(row: dict) -> str:
    trace = row.get("trace") or {}
    return str(trace.get("knowledge_status") or "unknown")


def _source_ids(row: dict) -> list[str]:
    data = row.get("data") or {}
    advice = row.get("advice") or {}
    return list(dict.fromkeys([*(data.get("source_ids") or []), *(advice.get("source_ids") or [])]))


def _plan_csv(rows: list[dict]) -> str:
    fields = [
        "plan_id", "version", "status", "profile_version", "start_date", "title", "summary",
        "day_index", "day_label", "day_kind", "estimated_minutes", "exercise", "sets",
        "reps_min", "reps_max", "rest_seconds", "nutrition_approach", "budget_note", "trace_json",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        data = row.get("data") or {}
        base = {
            "plan_id": row.get("id", ""),
            "version": row.get("version", ""),
            "status": row.get("status", ""),
            "profile_version": row.get("profile_version", ""),
            "start_date": row.get("start_date", ""),
            "title": data.get("title", ""),
            "summary": data.get("summary", ""),
            "nutrition_approach": (data.get("nutrition") or {}).get("approach", ""),
            "budget_note": (data.get("nutrition") or {}).get("budget_note", ""),
            "trace_json": _json_cell(row.get("trace") or {}),
        }
        days = data.get("days") or [{}]
        for day in days:
            exercises = day.get("exercises") or [{}]
            for exercise in exercises:
                writer.writerow({
                    **base,
                    "day_index": day.get("day_index", ""),
                    "day_label": day.get("label", ""),
                    "day_kind": day.get("kind", ""),
                    "estimated_minutes": day.get("estimated_minutes", ""),
                    "exercise": exercise.get("name", ""),
                    "sets": exercise.get("sets", ""),
                    "reps_min": exercise.get("reps_min", ""),
                    "reps_max": exercise.get("reps_max", ""),
                    "rest_seconds": exercise.get("rest_seconds", ""),
                })
    return output.getvalue()


def _feedback_csv(rows: list[dict]) -> str:
    fields = [
        "feedback_id", "date", "status", "revision", "raw_text", "training_summary",
        "training_completed", "food_summary", "diet_followed_plan", "sleep_hours", "sleep_date", "fatigue", "weight_kg",
        "intake_kcal", "exercise_results", "meal_to_plan", "meal_conditions", "available_foods",
        "desired_foods", "already_eaten", "uncertainties", "advice_summary", "advice_suggestions",
        "source_ids", "trace_json",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        data = row.get("data") or {}
        advice = row.get("advice") or {}
        writer.writerow({
            "feedback_id": row.get("id", ""),
            "date": row.get("date", ""),
            "status": row.get("status", ""),
            "revision": row.get("revision", ""),
            "raw_text": row.get("raw_text", ""),
            "training_summary": data.get("training_summary", ""),
            "training_completed": data.get("training_completed", ""),
            "food_summary": data.get("food_summary", ""),
            "diet_followed_plan": data.get("diet_followed_plan", ""),
            "sleep_hours": data.get("sleep_hours", ""),
            "sleep_date": data.get("sleep_date", ""),
            "fatigue": data.get("fatigue", ""),
            "weight_kg": data.get("weight_kg", ""),
            "intake_kcal": data.get("intake_kcal", ""),
            "exercise_results": _json_cell(data.get("exercise_results") or []),
            "meal_to_plan": data.get("meal_to_plan", ""),
            "meal_conditions": data.get("meal_conditions", ""),
            "available_foods": data.get("available_foods", ""),
            "desired_foods": data.get("desired_foods", ""),
            "already_eaten": data.get("already_eaten", ""),
            "uncertainties": _json_cell(data.get("uncertainties") or []),
            "advice_summary": advice.get("summary", ""),
            "advice_suggestions": _json_cell(advice.get("suggestions") or []),
            "source_ids": _json_cell(_source_ids(row)),
            "trace_json": _json_cell(row.get("trace") or {}),
        })
    return output.getvalue()


def _advice_csv(rows: list[dict]) -> str:
    fields = [
        "feedback_id", "date", "feedback_status", "advice_summary", "suggestion",
        "source_ids", "knowledge_status", "trace_json",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        advice = row.get("advice") or {}
        suggestions = advice.get("suggestions") or [""]
        for suggestion in suggestions:
            writer.writerow({
                "feedback_id": row.get("id", ""),
                "date": row.get("date", ""),
                "feedback_status": row.get("status", ""),
                "advice_summary": advice.get("summary", ""),
                "suggestion": suggestion,
                "source_ids": _json_cell(_source_ids(row)),
                "knowledge_status": _trace_status(row),
                "trace_json": _json_cell(row.get("trace") or {}),
            })
    return output.getvalue()


def _markdown_plan(rows: list[dict]) -> str:
    sections = ["# 健身助手计划导出", "", f"导出时间：{datetime.now(UTC).isoformat()}", ""]
    for row in rows:
        data = row.get("data") or {}
        sections.extend([
            f"## {data.get('title') or '未命名计划'}",
            f"- 计划日期：{row.get('start_date') or '未知'}",
            f"- 状态：{row.get('status') or '未知'}",
            f"- 摘要：{data.get('summary') or '无'}",
            "",
        ])
        for day in data.get("days") or []:
            sections.extend([f"### {day.get('label') or '训练日'}", ""])
            exercises = day.get("exercises") or []
            if not exercises:
                sections.append("- 恢复或轻松活动")
            for exercise in exercises:
                sections.append(
                    f"- {exercise.get('name') or '动作'}：{exercise.get('sets', '')} 组，"
                    f"{exercise.get('reps_min', '')}-{exercise.get('reps_max', '')} 次，"
                    f"休息 {exercise.get('rest_seconds', '')} 秒"
                )
            sections.append("")
        nutrition = data.get("nutrition") or {}
        sections.extend([
            "### 饮食安排",
            f"- 方式：{nutrition.get('approach') or '无'}",
            f"- 预算备注：{nutrition.get('budget_note') or '无'}",
            "",
            "### 生成轨迹",
            f"- 知识状态：{_trace_status(row)}",
            f"- 来源 ID：{', '.join(_source_ids(row)) or '无'}",
            "",
        ])
    return "\n".join(sections).rstrip() + "\n"


def _markdown_feedback(rows: list[dict], advice_only: bool = False) -> str:
    title = "建议" if advice_only else "反馈"
    sections = [f"# 健身助手{title}导出", "", f"导出时间：{datetime.now(UTC).isoformat()}", ""]
    for row in rows:
        advice = row.get("advice") or {}
        sections.extend([
            f"## {row.get('date') or '未知日期'} · {row.get('id') or '未知记录'}",
            f"- 反馈状态：{row.get('status') or '未知'}",
        ])
        if not advice_only:
            data = row.get("data") or {}
            sections.extend([
                f"- 原始记录：{row.get('raw_text') or '无'}",
                f"- 训练：{data.get('training_summary') or '未记录'}",
                f"- 睡眠：{data.get('sleep_hours') if data.get('sleep_hours') is not None else '未记录'} 小时",
                f"- 疲劳：{data.get('fatigue') or '未记录'}",
                "",
            ])
        if advice:
            sections.extend(["### 建议", f"{advice.get('summary') or '无'}", ""])
            sections.extend(f"- {suggestion}" for suggestion in advice.get("suggestions") or [])
            sections.append("")
        elif advice_only:
            sections.append("暂未生成建议。\n")
        sections.extend([
            "### 生成轨迹",
            f"- 知识状态：{_trace_status(row)}",
            f"- 来源 ID：{', '.join(_source_ids(row)) or '无'}",
            "",
        ])
    if not advice_only:
        sections.extend(['### 可重新导入的明确事实', '', '```json', _json_cell({
            'export_version':1, 'type':'feedback', 'items':[
                {'status':row.get('status', 'draft'), 'raw_text':row.get('raw_text', ''),
                 'data':row.get('data') or {}} for row in rows],
        }), '```', ''])
    return "\n".join(sections).rstrip() + "\n"


def render_export(kind: str, rows: list[dict], export_format: str) -> ExportDocument:
    """Render records without including local keys, cookies or runtime secrets."""
    if kind not in SUPPORTED_TYPES:
        raise ExportFormatError(f"导出类型不支持：{kind}")
    if export_format not in SUPPORTED_FORMATS:
        raise ExportFormatError(f"导出格式不支持：{export_format}")
    rows = list(rows)
    if export_format == "json":
        content = _json_cell({
            "export_version": 1,
            "type": kind,
            "exported_at": datetime.now(UTC).isoformat(),
            "items": rows,
        })
        media_type, suffix = "application/json", "json"
    elif export_format == "csv":
        content = {"plan": _plan_csv, "feedback": _feedback_csv, "advice": _advice_csv}[kind](rows)
        media_type, suffix = "text/csv", "csv"
    else:
        content = _markdown_plan(rows) if kind == "plan" else _markdown_feedback(rows, kind == "advice")
        media_type, suffix = "text/markdown", "md"
    stamp = datetime.now(UTC).date().isoformat()
    return ExportDocument(content, media_type, f"fitness-{kind}-{stamp}.{suffix}")
