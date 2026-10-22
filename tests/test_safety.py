from copy import deepcopy
from datetime import date

import pytest

from fitness.models import AdviceData, FeedbackData, Profile
from fitness.planning import generate_plan


def safety_module():
    from fitness import safety

    return safety


def test_medication_details_keep_guardrail_even_with_conflicting_negative_status():
    profile = Profile(health={'medications_status': 'none_known_self_reported', 'medications': '正在服用降压药'})
    assert any('用药' in message for message in safety_module().health_guardrails(profile))


def baseline_advice():
    return AdviceData(summary="本次反馈仅供短期观察。", suggestions=["优先保证规律睡眠"], source_ids=["source-1"])


def test_advice_wording_patch_preserves_sources():
    safety = safety_module()
    baseline = baseline_advice()
    validated = safety.validate_model_advice({"summary": "睡眠记录可用于观察近期恢复趋势。",
                                            "suggestions": ["记录后续几天的睡眠与疲劳感"]}, baseline)
    assert validated.source_ids == ["source-1"]
    assert baseline.summary == "本次反馈仅供短期观察。"
    assert validated.summary != baseline.summary


@pytest.mark.parametrize("patch,reason", [
    ({"source_ids": ["invented"]}, "immutable_field"),
    ({"diagnosis": "unknown"}, "invalid_schema"),
    ({"suggestions": ["每天服用肌酸5克"]}, "unsafe_content"),
    ({"suggestions": ["You have diabetes; stop your medication."]}, "unsafe_content"),
    ({"suggestions": ["胸痛时继续训练"]}, "unsafe_content"),
    ({"suggestions": ["深蹲5组，每组20次"]}, "unsafe_content"),
    ({"summary": "你患有糖尿病"}, "unsafe_content"),
    ({"suggestions": ["肌酸每天5克即可"]}, "unsafe_content"),
    ({"suggestions": ["降压药减半即可继续训练"]}, "unsafe_content"),
    ({"suggestions": ["每天禁食两天以快速减脂"]}, "unsafe_content"),
    ({"suggestions": ["Take five grams of creatine daily"]}, "unsafe_content"),
    ({"summary": "确诊糖尿病，需要治疗"}, "unsafe_content"),
    ({"summary": "You are diabetic"}, "unsafe_content"),
    ({"suggestions": ["Take creatine every day"]}, "unsafe_content"),
    ({"suggestions": ["建议肌酸用量为五克"]}, "unsafe_content"),
])
def test_advice_rejects_unsafe_and_untrusted_fields(patch, reason):
    safety = safety_module()
    with pytest.raises(safety.SafetyError, match=reason):
        safety.validate_model_advice(patch, baseline_advice())


def test_plan_allows_summary_but_no_prescription_changes(profile_data):
    safety = safety_module()
    baseline = generate_plan(Profile.model_validate(profile_data), date(2026, 10, 11))
    candidate = baseline.model_dump(mode="json")
    candidate["summary"] = "按已记录的时间与器械条件安排这一周，并持续记录恢复情况。"
    assert safety.validate_model_plan(candidate, baseline).days == baseline.days
    modified = deepcopy(candidate)
    modified["days"][0]["exercises"][0]["sets"] = 5
    with pytest.raises(safety.SafetyError, match="immutable_field"):
        safety.validate_model_plan(modified, baseline)
    with pytest.raises(safety.SafetyError, match="immutable_field"):
        safety.validate_model_plan({"nutrition": {"approach": "禁食"}}, baseline)


@pytest.mark.parametrize("field,value,needle", [
    ("exercise_limiting_conditions_details", "既往心脏病", "专业人员"),
    ("medications", "服用降压药", "用药"),
    ("exercise_limiting_conditions_details", "怀孕", "孕"),
])
def test_health_guardrails_always_apply_to_profile(profile_data, field, value, needle):
    safety = safety_module()
    profile_data["health"][field] = value
    profile = Profile.model_validate(profile_data)
    warnings = safety.health_guardrails(profile)
    assert any(needle in warning for warning in warnings)


def test_symptom_guardrails_work_without_provider(profile_data):
    safety = safety_module()
    warnings = safety.health_guardrails(Profile.model_validate(profile_data), {"training_summary": "训练时胸痛和晕厥"})
    assert any("停止" in warning and "就医" in warning for warning in warnings)


def test_feedback_chinese_sleep_measurement_is_grounded():
    safety = safety_module()
    day = date(2026, 10, 11)
    baseline = FeedbackData(date=day)
    result = safety.validate_model_feedback({"sleep_hours": 5}, "昨晚睡了五个小时", day, baseline)
    assert result.sleep_hours == 5
    assert baseline.sleep_hours is None


def test_feedback_extracts_named_exercise_weight_and_rpe_only_when_grounded():
    safety = safety_module()
    day = date(2026, 10, 11)
    baseline = FeedbackData(date=day)
    plan = {'squat': '深蹲'}
    result = safety.validate_model_feedback({'exercise_results': [
        {'exercise_id': 'squat', 'weight_kg': 80, 'rpe': 8},
    ]}, '今天深蹲80公斤，最后一组RPE 8', day, baseline, exercise_names=plan)
    assert result.exercise_results[0].weight_kg == 80
    assert result.exercise_results[0].rpe == 8
    with pytest.raises(safety.SafetyError, match='ungrounded_fact'):
        safety.validate_model_feedback({'exercise_results': [
            {'exercise_id': 'deadlift', 'weight_kg': 80, 'rpe': 8},
        ]}, '今天深蹲80公斤，最后一组RPE 8', day, baseline, exercise_names=plan)


@pytest.mark.parametrize("candidate,text", [
    ({"sleep_hours": 8}, "昨晚睡了五个小时"),
    ({"weight_kg": 70}, "今天觉得轻一点"),
    ({"intake_kcal": 2000}, "今天食堂吃了两顿饭"),
    ({"training_completed": True}, "今天准备训练"),
    ({"training_completed": True}, "未完成训练"),
    ({"diet_followed_plan": True}, "今天吃了鸡蛋"),
    ({"sleep_hours": 5}, "有时睡五小时，有时睡八小时"),
    ({"date": "2026-10-10"}, "昨天训练"),
    ({"confirmed": True}, "今天训练完成"),
    ({"training_completed": "true"}, "今天训练完成"),
    ({"training_summary": "诊断为糖尿病"}, "今天有点累"),
    ({"training_summary": "今天跑完十公里"}, "今天吃了鸡蛋"),
    ({"sleep_hours": 5}, "昨晚没睡五小时"),
    ({"sleep_hours": 5}, "我希望今晚睡五小时"),
])
def test_feedback_rejects_ungrounded_facts(candidate, text):
    safety = safety_module()
    day = date(2026, 10, 11)
    with pytest.raises(safety.SafetyError):
        safety.validate_model_feedback(candidate, text, day, FeedbackData(date=day))


def test_feedback_preserves_baseline_unknowns_and_grounded_explicit_boolean():
    safety = safety_module()
    day = date(2026, 10, 11)
    baseline = FeedbackData(date=day, uncertainties=["未提供份量"])
    result = safety.validate_model_feedback({"training_completed": False}, "今天未完成训练", day, baseline)
    assert result.training_completed is False
    assert result.weight_kg is None
    assert result.uncertainties == baseline.uncertainties


def test_raw_symptoms_are_guarded_even_when_parser_has_no_fields(profile_data):
    safety = safety_module()
    profile = Profile.model_validate(profile_data)
    assert safety.has_urgent_symptoms("训练时胸痛")
    assert safety.has_urgent_symptoms("shortness of breath during exercise")
    assert any("停止" in warning for warning in safety.health_guardrails(
        profile, FeedbackData(date=date(2026, 10, 11)), raw_text="训练时胸痛"))


@pytest.mark.parametrize("wording", [
    "上次我的建议让你一周减重5公斤，已经证明补剂很有效。",
    "你按建议服用补剂后恢复改善，证明这个方案适合你。",
    "Your weight loss was caused by my advice.",
    "你本周体重减少三公斤。",
    "最近平均睡眠8小时，恢复很好。",
])
def test_new_personal_outcome_or_measurement_claim_is_rejected(wording):
    safety = safety_module()
    with pytest.raises(safety.SafetyError, match="ungrounded_claim"):
        safety.validate_model_advice({"summary": wording}, baseline_advice())


def test_ordinary_rewording_and_unchanged_quantified_rule_are_allowed():
    safety = safety_module()
    baseline = AdviceData(summary="成人睡眠通常以7至9小时为参考。", suggestions=["记录恢复情况"])
    assert safety.validate_model_advice({"summary": "成人可参考7至9小时睡眠，并记录恢复情况。"}, baseline)


@pytest.mark.parametrize("wording", ["你正在服用华法林，建议关注运动风险。", "您有心脏病。",
                                      "You are taking warfarin."])
def test_fabricated_personal_health_fact_is_rejected(wording):
    safety = safety_module()
    with pytest.raises(safety.SafetyError):
        safety.validate_model_advice({"summary": wording}, baseline_advice())


def test_new_uncertainty_cannot_introduce_unrecorded_health_fact():
    safety = safety_module()
    day = date(2026, 10, 11)
    with pytest.raises(safety.SafetyError, match="ungrounded_fact"):
        safety.validate_model_feedback({"uncertainties": ["用户可能服用华法林"]}, "今天有点累", day,
                                       FeedbackData(date=day))


def test_generic_extraction_uncertainty_and_original_excerpt_are_allowed():
    safety = safety_module()
    day = date(2026, 10, 11)
    result = safety.validate_model_feedback({"uncertainties": ["睡眠时长不明确，需确认", "今天有点累"]},
                                            "今天有点累", day, FeedbackData(date=day))
    assert len(result.uncertainties) == 2
