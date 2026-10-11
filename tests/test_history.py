from datetime import date

from fitness.history import find_similar_feedback, get_recent_feedback, summarize_recent_trend


def feedback(
    ident,
    day,
    *,
    status="confirmed",
    sleep=None,
    weight=None,
    fatigue=None,
    training=None,
    diet=None,
    food=None,
    raw_text="",
    advice=None,
    issues=None,
):
    return {
        "id": ident,
        "date": day,
        "status": status,
        "raw_text": raw_text,
        "data": {
            "date": day,
            "sleep_hours": sleep,
            "weight_kg": weight,
            "fatigue": fatigue,
            "training_completed": training,
            "diet_followed_plan": diet,
            "food_summary": food,
        },
        "advice": advice,
        "trace": {"issues": issues or []},
    }


def history_rows():
    return [
        feedback(
            "latest",
            "2026-10-11",
            sleep=6,
            weight=79.0,
            fatigue="很累",
            training=False,
            diet=False,
            food="外卖",
            raw_text="睡了6小时，很累，没按计划吃",
            advice={"summary": "降低训练压力", "suggestions": ["早点睡"]},
            issues=["short_sleep", "training_fatigue", "diet_adherence"],
        ),
        feedback(
            "mid",
            "2026-10-08",
            sleep=7,
            weight=79.5,
            training=True,
            diet=True,
            food="食堂",
            raw_text="完成训练，饮食按计划",
            issues=["diet_adherence"],
        ),
        feedback(
            "start",
            "2026-10-05",
            sleep=5,
            weight=80.0,
            fatigue="疲惫",
            training=True,
            food="食堂",
            raw_text="睡了5小时，疲惫",
            issues=["short_sleep", "training_fatigue"],
        ),
        feedback("outside", "2026-10-04", sleep=9, weight=81.0, training=True, diet=True),
        feedback("draft", "2026-10-10", status="draft", sleep=3, weight=90.0),
        feedback("future", "2026-10-12", sleep=4, weight=78.0),
    ]


def test_recent_feedback_uses_confirmed_inclusive_window_and_newest_order():
    result = get_recent_feedback(history_rows(), end_date=date(2026, 10, 11), days=7)

    assert result["window"] == {
        "days": 7,
        "start_date": "2026-10-05",
        "end_date": "2026-10-11",
    }
    assert result["count"] == 3
    assert [row["id"] for row in result["records"]] == ["latest", "mid", "start"]


def test_recent_feedback_filters_by_issue_and_explicit_metric():
    rows = history_rows()

    tired = get_recent_feedback(
        rows, end_date=date(2026, 10, 11), days=7, issue="training_fatigue"
    )
    diet = get_recent_feedback(
        rows, end_date=date(2026, 10, 11), days=7, metric="diet_followed_plan"
    )

    assert [row["id"] for row in tired["records"]] == ["latest", "start"]
    assert [row["id"] for row in diet["records"]] == ["latest", "mid"]
    assert diet["filters"] == {"issue": None, "metric": "diet_followed_plan"}


def test_trend_summary_reports_numeric_ranges_rates_and_missing_counts():
    result = summarize_recent_trend(history_rows(), end_date=date(2026, 10, 11), days=7)

    assert result["record_count"] == 3
    assert result["metrics"]["sleep_hours"] == {
        "valid_count": 3,
        "average": 6.0,
        "minimum": 5.0,
        "maximum": 7.0,
        "range": 2.0,
        "insufficient_data": False,
    }
    assert result["metrics"]["weight_kg"] == {
        "valid_count": 3,
        "average": 79.5,
        "minimum": 79.0,
        "maximum": 80.0,
        "range": 1.0,
        "change": -1.0,
        "insufficient_data": False,
    }
    assert result["metrics"]["training_completion"] == {
        "valid_count": 3,
        "completed_count": 2,
        "rate": 2 / 3,
        "insufficient_data": False,
    }
    assert result["metrics"]["diet_execution"] == {
        "valid_count": 2,
        "followed_count": 1,
        "rate": 0.5,
        "insufficient_data": False,
    }
    assert result["metrics"]["fatigue_reports"] == {
        "record_count": 3,
        "reported_count": 2,
        "rate": 2 / 3,
        "insufficient_data": False,
        "meaning": "有疲劳描述的记录占确认反馈的比例；未描述不等于没有疲劳。",
    }


def test_trend_summary_marks_single_or_missing_samples_insufficient():
    result = summarize_recent_trend(
        [feedback("one", "2026-10-11", sleep=6, training=True)],
        end_date=date(2026, 10, 11),
        days=7,
    )

    assert result["metrics"]["sleep_hours"]["valid_count"] == 1
    assert result["metrics"]["sleep_hours"]["insufficient_data"] is True
    assert result["metrics"]["weight_kg"] == {
        "valid_count": 0,
        "average": None,
        "minimum": None,
        "maximum": None,
        "range": None,
        "change": None,
        "insufficient_data": True,
    }
    assert result["metrics"]["diet_execution"]["rate"] is None
    assert result["metrics"]["diet_execution"]["valid_count"] == 0


def test_trend_summary_supports_only_product_windows():
    for days in (7, 14, 21):
        assert summarize_recent_trend([], end_date=date(2026, 10, 11), days=days)["window"]["days"] == days


def test_similar_feedback_ranks_shared_issues_and_explains_matches():
    current = feedback(
        "current",
        "2026-10-11",
        sleep=6,
        fatigue="累",
        training=False,
        diet=False,
        issues=["short_sleep", "training_fatigue", "diet_adherence"],
    )
    records = [
        current,
        feedback(
            "strong",
            "2026-10-01",
            sleep=5.5,
            fatigue="很累",
            training=False,
            diet=False,
            issues=["short_sleep", "training_fatigue", "diet_adherence"],
            advice={"summary": "过去建议减少训练量", "suggestions": ["早睡"]},
        ),
        feedback(
            "partial",
            "2026-10-05",
            sleep=6.5,
            training=True,
            issues=["short_sleep"],
        ),
        feedback("unrelated", "2026-10-10", weight=79.5, issues=["weight_trend"]),
    ]

    result = find_similar_feedback(records, current, limit=2)

    assert result["comparable_count"] == 2
    assert [row["id"] for row in result["matches"]] == ["strong", "partial"]
    assert result["matches"][0]["shared_issues"] == [
        "short_sleep",
        "training_fatigue",
        "diet_adherence",
    ]
    assert "睡眠同为不足7小时" in result["matches"][0]["matched_signals"]
    assert result["matches"][0]["previous_advice_summary"] == "过去建议减少训练量"
    assert "outcome" not in result["matches"][0]


def test_similar_feedback_reports_no_comparable_history_without_fabrication():
    current = feedback("current", "2026-10-11", sleep=8)

    result = find_similar_feedback([current], current, limit=3)

    assert result == {
        "current_feedback_id": "current",
        "comparable_count": 0,
        "matches": [],
        "message": "没有足够的可比历史反馈。",
    }
