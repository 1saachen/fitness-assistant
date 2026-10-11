"""Deterministic local tools for personal feedback history."""

from datetime import date, timedelta
from typing import Any

SUPPORTED_WINDOWS = (7, 14, 21)
SUPPORTED_METRICS = {
    "sleep_hours",
    "weight_kg",
    "fatigue",
    "training_completed",
    "diet_followed_plan",
}


class HistoryQueryError(ValueError):
    """Raised when a local history query is outside the supported contract."""


def _record_date(record: dict) -> date | None:
    value = record.get("date") or (record.get("data") or {}).get("date")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _window(end_date: date, days: int) -> tuple[date, date]:
    if days not in SUPPORTED_WINDOWS:
        raise HistoryQueryError("历史窗口只支持 7、14 或 21 天。")
    return end_date - timedelta(days=days - 1), end_date


def _issues(record: dict) -> tuple[str, ...]:
    trace_issues = (record.get("trace") or {}).get("issues")
    if isinstance(trace_issues, list):
        cleaned = tuple(dict.fromkeys(value for value in trace_issues if isinstance(value, str) and value))
        if cleaned:
            return cleaned
    data = record.get("data") or {}
    raw_text = str(record.get("raw_text") or "")
    issues = []
    if data.get("sleep_hours") is not None and data["sleep_hours"] < 7:
        issues.append("short_sleep")
    if data.get("fatigue"):
        issues.append("training_fatigue")
    if data.get("food_summary") or data.get("diet_followed_plan") is not None:
        issues.append("diet_adherence")
    if data.get("weight_kg") is not None:
        issues.append("weight_trend")
    if any(term in raw_text for term in ("补剂", "肌酸", "蛋白粉", "维生素", "镁")):
        issues.append("supplement_question")
    return tuple(issues)


def get_recent_feedback(
    records: list[dict],
    *,
    end_date: date,
    days: int,
    issue: str | None = None,
    metric: str | None = None,
) -> dict:
    """Return confirmed feedback in an inclusive calendar window."""
    start_date, end_date = _window(end_date, days)
    if metric is not None and metric not in SUPPORTED_METRICS:
        raise HistoryQueryError(f"不支持的历史指标：{metric}")
    selected = []
    for record in records:
        record_date = _record_date(record)
        if record.get("status") != "confirmed" or record_date is None:
            continue
        if not start_date <= record_date <= end_date:
            continue
        if issue is not None and issue not in _issues(record):
            continue
        if metric is not None and (record.get("data") or {}).get(metric) is None:
            continue
        selected.append(record)
    selected.sort(
        key=lambda row: (_record_date(row) or date.min, str(row.get("created_at") or "")),
        reverse=True,
    )
    return {
        "window": {
            "days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "filters": {"issue": issue, "metric": metric},
        "count": len(selected),
        "records": selected,
    }


def _rounded(value: float) -> float:
    return round(value, 3)


def _numeric_summary(records: list[dict], field: str, *, include_change: bool = False) -> dict:
    values = [
        float((record.get("data") or {})[field])
        for record in records
        if (record.get("data") or {}).get(field) is not None
    ]
    result = {
        "valid_count": len(values),
        "average": _rounded(sum(values) / len(values)) if values else None,
        "minimum": _rounded(min(values)) if values else None,
        "maximum": _rounded(max(values)) if values else None,
        "range": _rounded(max(values) - min(values)) if values else None,
    }
    if include_change:
        chronological = list(reversed(values))
        result["change"] = (
            _rounded(chronological[-1] - chronological[0]) if len(chronological) >= 2 else None
        )
    result["insufficient_data"] = len(values) < 2
    return result


def _boolean_rate(records: list[dict], field: str, positive_label: str) -> dict:
    values = [
        (record.get("data") or {})[field]
        for record in records
        if (record.get("data") or {}).get(field) is not None
    ]
    positive_count = sum(value is True for value in values)
    return {
        "valid_count": len(values),
        positive_label: positive_count,
        "rate": positive_count / len(values) if values else None,
        "insufficient_data": len(values) < 2,
    }


def summarize_recent_trend(records: list[dict], *, end_date: date, days: int) -> dict:
    """Summarize explicit measurements; a single point never establishes a trend."""
    recent = get_recent_feedback(records, end_date=end_date, days=days)
    rows = recent["records"]
    fatigue_count = sum(bool((record.get("data") or {}).get("fatigue")) for record in rows)
    return {
        "window": recent["window"],
        "record_count": len(rows),
        "metrics": {
            "sleep_hours": _numeric_summary(rows, "sleep_hours"),
            "weight_kg": _numeric_summary(rows, "weight_kg", include_change=True),
            "training_completion": _boolean_rate(rows, "training_completed", "completed_count"),
            "diet_execution": _boolean_rate(rows, "diet_followed_plan", "followed_count"),
            "fatigue_reports": {
                "record_count": len(rows),
                "reported_count": fatigue_count,
                "rate": fatigue_count / len(rows) if rows else None,
                "insufficient_data": len(rows) < 2,
                "meaning": "有疲劳描述的记录占确认反馈的比例；未描述不等于没有疲劳。",
            },
        },
    }


def _sleep_bucket(value: Any) -> str | None:
    if value is None:
        return None
    if value < 7:
        return "short"
    if value <= 9:
        return "usual"
    return "long"


def find_similar_feedback(records: list[dict], current: dict, *, limit: int = 3) -> dict:
    """Rank comparable history and explain explicit matches without inferring outcomes."""
    if limit < 1 or limit > 20:
        raise HistoryQueryError("相似历史数量必须在 1 到 20 之间。")
    current_data = current.get("data") or {}
    current_issues = _issues(current)
    candidates = []
    for record in records:
        if record.get("status") != "confirmed" or record.get("id") == current.get("id"):
            continue
        candidate_data = record.get("data") or {}
        candidate_issues = _issues(record)
        shared_issues = [issue for issue in current_issues if issue in candidate_issues]
        score = 4 * len(shared_issues)
        signals = []

        current_sleep = _sleep_bucket(current_data.get("sleep_hours"))
        candidate_sleep = _sleep_bucket(candidate_data.get("sleep_hours"))
        if current_sleep is not None and current_sleep == candidate_sleep:
            sleep_labels = {
                "short": "睡眠同为不足7小时",
                "usual": "睡眠同在7至9小时",
                "long": "睡眠同为超过9小时",
            }
            signals.append(sleep_labels[current_sleep])
            score += 2
        for field, label in (
            ("training_completed", "训练完成状态相同"),
            ("diet_followed_plan", "饮食执行状态相同"),
        ):
            current_value = current_data.get(field)
            candidate_value = candidate_data.get(field)
            if current_value is not None and current_value == candidate_value:
                signals.append(label)
                score += 1
        if current_data.get("fatigue") and candidate_data.get("fatigue"):
            signals.append("都明确记录了疲劳")
            score += 1
        current_weight = current_data.get("weight_kg")
        candidate_weight = candidate_data.get("weight_kg")
        if (
            current_weight is not None
            and candidate_weight is not None
            and abs(current_weight - candidate_weight) <= 1
        ):
            signals.append("体重记录相差不超过1kg")
            score += 1
        if score == 0:
            continue
        advice = record.get("advice") or {}
        candidates.append({
            "id": record.get("id"),
            "date": str(record.get("date") or ""),
            "score": score,
            "shared_issues": shared_issues,
            "matched_signals": signals,
            "previous_advice_summary": advice.get("summary"),
        })
    candidates.sort(key=lambda row: (-row["score"], row["date"], str(row["id"])), reverse=False)
    matches = candidates[:limit]
    return {
        "current_feedback_id": current.get("id"),
        "comparable_count": len(candidates),
        "matches": matches,
        "message": None if matches else "没有足够的可比历史反馈。",
    }
