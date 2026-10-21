from datetime import timedelta

from .catalog import available
from .knowledge_context import KnowledgeContextResult
from .models import PlanData
from .nutrition import nutrition_plan

STRATEGY_TITLE_PREVIEW_LENGTH = 40
MAX_STRATEGY_SNAPSHOTS = 20
MAX_CITATION_SNAPSHOTS = 100
CAPACITY_EXCEEDED_STATUS = "capacity_exceeded"


def _strategy_title_preview(title):
    if len(title) <= STRATEGY_TITLE_PREVIEW_LENGTH:
        return title
    return f"{title[: STRATEGY_TITLE_PREVIEW_LENGTH - 1]}…"


def _context_exceeds_persistence_capacity(context):
    return (
        len(context.strategies) > MAX_STRATEGY_SNAPSHOTS
        or len(context.citations) > MAX_CITATION_SNAPSHOTS
    )


def context_persistence_status(context):
    if context.status == "ok" and _context_exceeds_persistence_capacity(context):
        return CAPACITY_EXCEEDED_STATUS
    return context.status


def persistent_context_snapshots(context):
    if _context_exceeds_persistence_capacity(context):
        return [], []
    return list(context.strategies), list(context.citations)


def generate_plan(profile, start_date, context=None):
    context = context or KnowledgeContextResult()
    training = profile.training
    session_count = training.available_sessions_per_week or 3
    default_days = {
        1: [0], 2: [0, 3], 3: [0, 2, 4], 4: [0, 2, 4, 6],
        5: [0, 1, 2, 4, 5], 6: [0, 1, 2, 3, 4, 5],
    }[session_count]
    chosen_days = ([i for i in range(7)
                    if (start_date + timedelta(days=i)).weekday() in training.preferred_weekdays]
                   if training.preferred_weekdays is not None else default_days)
    exercise_pool = {item.id: item for item in available(training.available_equipment)}
    templates = [
        ["barbell_bench_press", "lat_pulldown", "plank"],
        ["squat", "dumbbell_bench_press", "seated_row"],
        ["deadlift", "dumbbell_row", "plank"],
        ["leg_press", "romanian_deadlift", "lat_pulldown"],
    ]
    days = []
    questions = []
    if training.session_duration_minutes is None:
        questions.append("请补充每次可训练时长，当前按约45分钟生成草案。")
    for day_index in range(7):
        if day_index in chosen_days:
            exercise_ids = [
                exercise_id
                for exercise_id in templates[chosen_days.index(day_index) % len(templates)]
                if exercise_id in exercise_pool
            ]
            if len(exercise_ids) < len(templates[chosen_days.index(day_index) % len(templates)]):
                questions.append("器械不足时仅使用可用动作作有限草案，无法替代完整模板；空动作日作恢复，请补充器械。")
            if not exercise_ids:
                exercise_ids = [item.id for item in exercise_pool.values()
                                if item.equipment != 'bodyweight'][:3]
            if not exercise_ids:
                days.append({"day_index": day_index, "label": f"第{day_index + 1}天 · 恢复",
                             "kind": "rest", "exercises": [], "estimated_minutes": 0})
                continue
            exercises = [
                {
                    "exercise_id": exercise_id,
                    "sets": 3,
                    "reps_min": 5 if exercise_id in ("squat", "deadlift") else 8,
                    "reps_max": 8 if exercise_id in ("squat", "deadlift") else 12,
                    "rest_seconds": 120 if exercise_id in ("squat", "deadlift") else 90,
                    "name": exercise_pool[exercise_id].name,
                }
                for exercise_id in exercise_ids
            ]
            days.append(
                {
                    "day_index": day_index,
                    "label": f"第{day_index + 1}天 · 力量训练",
                    "kind": "training",
                    "exercises": exercises,
                    "estimated_minutes": min(45, training.session_duration_minutes or 45),
                }
            )
        else:
            days.append(
                {
                    "day_index": day_index,
                    "label": f"第{day_index + 1}天 · 恢复",
                    "kind": "rest",
                    "exercises": [],
                    "estimated_minutes": 0,
                }
            )
    nutrition, nutrition_questions = nutrition_plan(profile)
    questions.extend(nutrition_questions)
    strategies, citations = persistent_context_snapshots(context)
    goal_title, goal_summary = {
        "fat_loss": ("减脂保力量", "减脂并维持力量，建立可持续的饮食与训练习惯。"),
        "muscle_gain": ("增肌与力量", "增肌并改善力量，结合饮食、训练和恢复反馈调整。"),
        "general_health": ("健康与体能", "维持基本健康，逐步建立规律运动、饮食和作息。"),
    }.get(profile.goals.primary, ("个性化训练", "根据已提供的档案与反馈生成保守起始安排。"))
    age_context = f"{profile.personal.age_years}岁，" if profile.personal.age_years is not None else ""
    return PlanData(
        title=f"{goal_title} · 一周草案",
        summary=(
            f"{age_context}{goal_summary}"
        ),
        days=days,
        nutrition=nutrition,
        questions=list(dict.fromkeys(questions)),
        source_ids=[citation.id for citation in citations],
        strategy_context=strategies,
        knowledge_context=citations,
        recovery_guidance=["优先建立规律作息，成年人通常以7至9小时睡眠为参考，按个人恢复反馈调整。",
                           "休息日安排轻活动；异常疼痛或持续不适时停止相关训练并咨询专业人员。"],
        supplement_guidance=["先保障正餐、训练和睡眠，再按明确需求讨论补剂；不把视频排名当作个体用量。",
                             "补剂花费单独记录；有疾病、用药或不良反应时先咨询医生或药师。"],
    )
