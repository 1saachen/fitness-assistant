from .catalog import available
from .knowledge_context import KnowledgeContextResult
from .models import PlanData

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
    chosen_days = training.preferred_weekdays or [0, 2, 4, 6][:session_count]
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
    nutrition = {
        "approach": "以食堂可获得的蛋白质、蔬菜和主食为基础，保持规律进餐。",
        "meal_options": [
            {
                "meal": "早餐",
                "suggestions": ["鸡蛋或奶制品搭配主食", "按饥饿程度调整份量"],
            },
            {
                "meal": "午餐/晚餐",
                "suggestions": ["优先选择肉/蛋/豆制品、蔬菜和米饭", "外卖时选择少油并保留蛋白质"],
            },
            {
                "meal": "训练后",
                "suggestions": ["在接下来一餐补充蛋白质和碳水", "饮水并观察恢复"],
            },
        ],
        "budget_note": "学校食堂价格未知，需记录实际花费后再核算40元/天预算。",
    }
    strategies, citations = persistent_context_snapshots(context)
    strategy_summary = (
        f" 方案依据（共{len(strategies)}个模块）："
        f"{'、'.join(_strategy_title_preview(strategy.title) for strategy in strategies)}。"
        if strategies
        else ""
    )
    return PlanData(
        title="减脂保力量 · 一周草案",
        summary=(
            f"{profile.personal.age_years}岁，目标为{profile.goals.primary}。"
            "使用中等训练量维持力量，按反馈逐周调整。"
            f"{strategy_summary}"
        ),
        days=days,
        nutrition=nutrition,
        questions=questions,
        source_ids=[citation.id for citation in citations],
        strategy_context=strategies,
        knowledge_context=citations,
    )
