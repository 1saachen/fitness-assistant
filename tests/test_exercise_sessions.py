"""Actual training records retain set order and require local source evidence."""

from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from fitness.data_transfer import preview_feedback_import
from fitness.exporting import render_export
from fitness.models import Exercise, ExerciseResult, FeedbackData
from fitness.safety import SafetyError, validate_model_feedback

DAY = date(2026, 10, 21)
NAMES = {"bench": "卧推", "squat": "深蹲"}


def validate(results, text, names=NAMES):
    return validate_model_feedback({"exercise_results": results}, text, DAY,
                                   FeedbackData(date=DAY), exercise_names=names)


def bench_sets():
    return {"exercise_id": "bench", "weight_kg": 45,
            "sets": [{"reps": 8, "weight_kg": 45}, {"reps": 8, "weight_kg": 45},
                     {"reps": 7, "weight_kg": 45, "rpe": 9}]}


def test_reps_only_records_and_legacy_results_are_supported():
    assert ExerciseResult(exercise_id="bench", weight_kg=45, rpe=8).sets == []
    result = ExerciseResult(exercise_id="bench", session_id="evening-1",
                            sets=[{"reps": 8}, {"reps": 7, "completed": False}],
                            form_notes="最后一组动作不稳", goal_completed=False)
    assert result.sets[0].weight_kg is None
    assert result.sets[0].rpe is None
    assert result.sets[0].completed is None
    assert result.session_id == "evening-1"


@pytest.mark.parametrize("patch", [
    {"sets": [{"reps": 0}]}, {"sets": [{"reps": 8.5}]},
    {"sets": [{"reps": True}]}, {"sets": [{"reps": 8, "rpe": 8.2}]},
    {"sets": [{"reps": 8, "weight_kg": -1}]},
    {"sets": [{"reps": 8, "completed": "true"}]},
    {"goal_completed": "true"}, {"session_id": "  "}, {"exercise_id": " "},
])
def test_set_contract_rejects_invalid_or_coerced_facts(patch):
    with pytest.raises(ValidationError):
        ExerciseResult.model_validate({"exercise_id": "bench", "weight_kg": 45, **patch})


def test_grounded_rep_sequence_preserves_unknown_rpe_and_final_set_association():
    result = validate([bench_sets()], "卧推45kg，8/8/7次，末组RPE9")
    assert [item.reps for item in result.exercise_results[0].sets] == [8, 8, 7]
    assert [item.rpe for item in result.exercise_results[0].sets] == [None, None, 9]


def test_reps_only_and_custom_named_exercise_are_grounded_without_plan_identity():
    exercise = Exercise(name="反向卷腹", sets=3, reps_min=8, reps_max=12, rest_seconds=60)
    result = validate([{"exercise_id": exercise.exercise_id, "exercise_name": "反向卷腹",
                        "sets": [{"reps": 12}, {"reps": 10}]}], "反向卷腹12/10次", names={})
    assert result.exercise_results[0].weight_kg is None


def test_numbered_sets_support_different_weights_and_explicit_completion():
    candidate = {"exercise_id": "bench", "sets": [
        {"reps": 8, "weight_kg": 45, "rpe": 7, "completed": True},
        {"reps": 6, "weight_kg": 47.5, "rpe": 9, "completed": False}],
        "form_notes": "末组动作不稳", "goal_completed": False}
    text = "卧推第1组45kg8次RPE7，完成；第2组47.5kg6次RPE9，未完成；末组动作不稳，未完成目标"
    assert validate([candidate], text).exercise_results[0].sets[1].weight_kg == 47.5


@pytest.mark.parametrize("text", [
    "明天卧推45kg，8/8/7次，末组RPE9", "准备卧推45kg，8/8/7次，末组RPE9",
    "计划卧推45kg，8/8/7次，末组RPE9", "希望卧推45kg，8/8/7次，末组RPE9",
    "没有做卧推45kg，8/8/7次，末组RPE9",
])
def test_future_intention_and_negated_performance_are_rejected(text):
    with pytest.raises(SafetyError, match="ungrounded_fact"):
        validate([bench_sets()], text)


def test_plan_numbers_do_not_mask_the_distinct_actual_sequence():
    text = "计划卧推50kg，8/8/8次；实际卧推45kg，8/8/7次，末组RPE9"
    assert validate([bench_sets()], text).exercise_results[0].sets[-1].reps == 7
    wrong = bench_sets()
    wrong["sets"][-1]["reps"] = 8
    with pytest.raises(SafetyError, match="ungrounded_fact"):
        validate([wrong], text)


@pytest.mark.parametrize("change", ["reorder", "copy_rpe", "other_weight", "complete", "notes", "goal"])
def test_rejects_ungrounded_set_order_associations_and_additional_facts(change):
    item = deepcopy(bench_sets())
    if change == "reorder":
        item["sets"] = list(reversed(item["sets"]))
    elif change == "copy_rpe":
        for exercise_set in item["sets"]:
            exercise_set["rpe"] = 9
    elif change == "other_weight":
        item["weight_kg"] = 80
        item["sets"][0]["weight_kg"] = 80
    elif change == "complete":
        item["sets"][0]["completed"] = True
    elif change == "notes":
        item["form_notes"] = "动作稳定"
    else:
        item["goal_completed"] = True
    with pytest.raises(SafetyError, match="ungrounded_fact"):
        validate([item], "卧推45kg，8/8/7次，末组RPE9；深蹲80kg，动作稳定，完成目标")


def test_identity_mismatch_is_rejected_even_when_custom_name_occurs():
    with pytest.raises(SafetyError, match="ungrounded_fact"):
        validate([{"exercise_id": "invented", "exercise_name": "反向卷腹",
                   "sets": [{"reps": 12}]}], "反向卷腹12次", names={})


def test_adjacent_exercise_prefix_cannot_supply_another_exercises_weight():
    with pytest.raises(SafetyError, match="ungrounded_fact"):
        validate([{"exercise_id": "bench", "weight_kg": 80, "sets": [{"reps": 8, "weight_kg": 80}]}],
                 "深蹲80kg卧推8次")


def test_negative_form_description_cannot_be_trimmed_to_positive_phrase():
    with pytest.raises(SafetyError, match="ungrounded_fact"):
        validate([{"exercise_id": "bench", "sets": [{"reps": 8}], "form_notes": "动作稳定"}],
                 "卧推8次，并非动作稳定")


def test_explicit_rpe_sequence_retains_set_order():
    result = validate([{"exercise_id": "bench", "sets": [
        {"reps": 8, "rpe": 7}, {"reps": 8, "rpe": 8}, {"reps": 7, "rpe": 9}]}],
        "卧推8/8/7次，RPE7/8/9")
    assert [item.rpe for item in result.exercise_results[0].sets] == [7, 8, 9]


def test_unrelated_extra_rep_statement_makes_unnumbered_sets_ambiguous():
    with pytest.raises(SafetyError, match="ungrounded_fact"):
        validate([bench_sets()], "卧推45kg，8/8/7次，末组RPE9，后来又做了6次")


def test_goal_status_cannot_supply_set_completion_even_with_whitespace():
    with pytest.raises(SafetyError, match="ungrounded_fact"):
        validate([{"exercise_id": "bench", "sets": [{"reps": 8, "completed": False}]}],
                 "卧推第1组8次，未完成 目标")


@pytest.mark.parametrize("format", ["json", "csv", "markdown"])
def test_complete_training_and_other_feedback_facts_roundtrip(format):
    facts = FeedbackData(date=DAY, training_completed=False, meal_to_plan="晚餐",
                         meal_conditions="食堂", available_foods="鸡蛋", desired_foods="米饭",
                         already_eaten="牛奶", diet_followed_plan=False,
                         exercise_results=[{**bench_sets(), "session_id": "evening-1",
                                            "form_notes": "末组动作不稳", "goal_completed": False}])
    row = {"id": "row-1", "date": DAY.isoformat(), "status": "confirmed", "revision": 1,
           "data": facts.model_dump(mode="json"), "raw_text": "卧推45kg，8/8/7次，末组RPE9"}
    preview = preview_feedback_import(render_export("feedback", [row], format).content, format)
    assert preview["errors"] == []
    assert preview["items"][0]["data"] == facts.model_dump(mode="json")


def test_csv_invalid_exercise_json_is_reported_without_silently_discarding_records():
    preview = preview_feedback_import('date,exercise_results\n2026-10-21,"not json"\n', "csv")
    assert preview["errors"]
    assert preview["items"] == []
