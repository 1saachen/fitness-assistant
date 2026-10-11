import json

import pytest

from fitness.exporting import ExportFormatError, render_export


def sample_plan():
    return {
        "id": "plan-1",
        "version": 1,
        "status": "confirmed",
        "profile_version": 1,
        "start_date": "2026-09-22",
        "data": {
            "title": "减脂保力量 · 一周草案",
            "summary": "按反馈逐周调整。",
            "days": [
                {
                    "day_index": 0,
                    "label": "第1天 · 力量训练",
                    "kind": "training",
                    "estimated_minutes": 45,
                    "exercises": [
                        {
                            "name": "深蹲",
                            "sets": 3,
                            "reps_min": 5,
                            "reps_max": 8,
                            "rest_seconds": 120,
                        }
                    ],
                }
            ],
            "nutrition": {
                "approach": "优先蛋白质和蔬菜。",
                "meal_options": [],
                "budget_note": "记录实际花费。",
            },
            "source_ids": ["knowledge-1"],
        },
        "trace": {
            "steps": ["baseline_strategy_selection", "planner"],
            "knowledge_status": "ok",
            "knowledge_item_ids": ["knowledge-1"],
        },
    }


def sample_feedback():
    return {
        "id": "feedback-1",
        "date": "2026-09-22",
        "status": "confirmed",
        "revision": 1,
        "raw_text": "睡了6小时，完成训练",
        "data": {
            "date": "2026-09-22",
            "training_summary": "完成训练",
            "training_completed": True,
            "food_summary": None,
            "sleep_hours": 6,
            "sleep_date": None,
            "fatigue": "有点累",
            "weight_kg": 79.8,
            "intake_kcal": None,
            "uncertainties": [],
        },
        "advice": {
            "summary": "今天降低训练压力。",
            "suggestions": ["保证睡眠"],
            "source_ids": ["knowledge-1"],
        },
        "trace": {"steps": ["advisor"], "knowledge_status": "ok"},
    }


def test_json_export_keeps_structured_data_and_trace():
    document = render_export("plan", [sample_plan()], "json")

    payload = json.loads(document.content)
    assert payload["type"] == "plan"
    assert payload["items"][0]["data"]["days"][0]["exercises"][0]["name"] == "深蹲"
    assert payload["items"][0]["trace"]["knowledge_status"] == "ok"
    assert document.media_type == "application/json"
    assert document.filename.endswith(".json")


def test_markdown_feedback_roundtrip_preserves_all_explicit_facts():
    from fitness.data_transfer import preview_feedback_import
    from fitness.models import FeedbackData
    row = sample_feedback()
    row['data']['diet_followed_plan'] = False
    row['data']['intake_kcal'] = 2000
    content = render_export('feedback', [row], 'markdown').content
    preview = preview_feedback_import(content, 'markdown')
    assert preview['errors'] == []
    assert len(preview['items']) == 1
    assert preview['items'][0]['data'] == FeedbackData.model_validate(row['data']).model_dump(mode='json')


def test_csv_and_markdown_exports_are_readable():
    csv_document = render_export("feedback", [sample_feedback()], "csv")
    markdown_document = render_export("advice", [sample_feedback()], "markdown")

    assert "feedback_id,date,status,revision" in csv_document.content
    assert "feedback-1" in csv_document.content
    assert "睡了6小时，完成训练" in csv_document.content
    assert "# 健身助手建议导出" in markdown_document.content
    assert "保证睡眠" in markdown_document.content
    assert markdown_document.filename.endswith(".md")


def test_export_rejects_unknown_kind_or_format():
    with pytest.raises(ExportFormatError, match="导出格式"):
        render_export("plan", [sample_plan()], "xml")
    with pytest.raises(ExportFormatError, match="导出类型"):
        render_export("unknown", [], "json")
