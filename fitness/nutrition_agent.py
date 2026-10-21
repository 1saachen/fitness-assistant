"""Nutrition planner: model-designed live meals and explicit deterministic demo.

Arithmetic remains available as a reference; live food choices belong to the model.
"""

import re
from dataclasses import dataclass

from .models import MealOption, NutritionPlan, NutritionTargets, Profile


@dataclass(frozen=True)
class FoodEstimate:
    kcal: int
    protein: int
    fat: int
    carbs: int
    cost: float


BASE_MEALS = {
    "早餐": FoodEstimate(480, 27, 14, 62, 6),
    "午餐": FoodEstimate(650, 45, 18, 72, 13),
    "晚餐": FoodEstimate(560, 40, 16, 58, 11),
    "训练后": FoodEstimate(230, 18, 5, 30, 5),
}


def _allocate(total: int, weights: list[int]) -> list[int]:
    denominator = sum(weights)
    exact = [total * weight / denominator for weight in weights]
    allocated = [int(value) for value in exact]
    for index in sorted(range(len(weights)), key=lambda i: exact[i] - allocated[i], reverse=True)[:total - sum(allocated)]:
        allocated[index] += 1
    return allocated


def _meal_macros(targets: NutritionTargets) -> dict[str, dict[str, int]]:
    keys = list(BASE_MEALS)
    values = {
        field: _allocate(getattr(targets, field), [getattr(BASE_MEALS[key], field.removesuffix('_g')) for key in keys])
        for field in ('protein_g', 'fat_g', 'carbs_g')
    }
    return {key: {field: values[field][index] for field in values} for index, key in enumerate(keys)}


def _contains(text: str, *terms: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _activity_factor(profile: Profile) -> tuple[float, str]:
    value = (profile.daily_activity_level or "").lower()
    if _contains(value, "久坐", "低", "sedentary"):
        return 1.35, "日常活动按低水平估计"
    if _contains(value, "高", "high", "体力"):
        return 1.65, "日常活动按较高水平估计"
    if _contains(value, "中", "moderate"):
        return 1.55, "日常活动按中等水平估计"
    sessions = profile.training.available_sessions_per_week or 3
    return (1.50 if sessions >= 4 else 1.45), "未提供日常活动量，按训练频率估计活动水平"


def calculate_targets(profile: Profile) -> NutritionTargets | None:
    personal = profile.personal
    if (personal.age_years is None or personal.height_cm is None or personal.weight_kg is None
            or profile.goals.primary is None):
        return None
    assumptions: list[str] = []
    if personal.body_fat_percent is not None and personal.weight_kg is not None:
        lean_mass = personal.weight_kg * (1 - personal.body_fat_percent / 100)
        bmr = 370 + 21.6 * lean_mass
        method = "Katch-McArdle起始估算"
    else:
        sex = (personal.sex or "").lower()
        sex_adjustment = 5 if _contains(sex, "男", "male") else -161 if _contains(sex, "女", "female") else -78
        bmr = 10 * personal.weight_kg + 6.25 * personal.height_cm - 5 * personal.age_years + sex_adjustment
        method = "Mifflin-St Jeor起始估算"
        if not personal.sex:
            assumptions.append("未提供性别，采用中性近似；结果置信度较低")
    factor, activity_note = _activity_factor(profile)
    assumptions.append(activity_note)
    maintenance = bmr * factor
    goal = profile.goals.primary
    if goal == "fat_loss":
        calories = maintenance * 0.85
        protein = round(personal.weight_kg * 1.8)
        assumptions.append("减脂先按约15%能量缺口起步，结合连续体重和训练反馈校准")
    elif goal == "muscle_gain":
        calories = maintenance * 1.08
        protein = round(personal.weight_kg * 1.6)
        assumptions.append("增肌先按小幅能量盈余起步，结合体重和力量反馈校准")
    else:
        calories = maintenance
        protein = round(personal.weight_kg * 1.4)
        assumptions.append("健康维持先按估算维持能量起步，结合饥饿和体重反馈校准")
    fat = max(round(personal.weight_kg * 0.7), 40)
    carbs = max(round((calories - protein * 4 - fat * 9) / 4), 20)
    total = round(protein * 4 + fat * 9 + carbs * 4)
    confidence = "high" if personal.body_fat_percent is not None and profile.daily_activity_level else "medium"
    if not personal.sex or not profile.daily_activity_level:
        confidence = "low"
    return NutritionTargets(
        calories_kcal=total, protein_g=protein, fat_g=fat, carbs_g=carbs,
        method=method, assumptions=assumptions, confidence=confidence,
    )


def _restrictions(profile: Profile) -> tuple[str, str, bool]:
    nutrition = profile.nutrition
    safety = " ".join(filter(None, [nutrition.food_allergy_details, nutrition.food_intolerances,
                                      nutrition.other_dietary_restrictions])).lower()
    disliked = " ".join(filter(None, [nutrition.disliked_foods])).lower()
    unknown = nutrition.food_allergy_status == "unknown" or (
        nutrition.food_allergy_status == "has_allergies" and not nutrition.food_allergy_details
    )
    return safety, disliked, unknown


def _protein_text(profile: Profile) -> str:
    safety, disliked, unknown = _restrictions(profile)
    if unknown:
        return "确认过敏和不耐受信息后再选蛋白质；当前不承诺具体食材安全"
    vegan = _contains(safety, "纯素", "vegan")
    vegetarian = vegan or _contains(safety, "素食", "vegetarian")
    candidates = ([('豆制品', ('大豆', '黄豆', '豆制品', '豆腐', '豆'))] if vegetarian else [
        ('鸡蛋', ('鸡蛋',)), ('鸡胸肉', ('鸡肉', '鸡胸', '禽肉')),
        ('鱼肉', ('鱼肉', '鱼类', '鱼')), ('瘦肉', ('肉类', '猪肉', '牛肉', '瘦肉')),
        ('豆制品', ('大豆', '黄豆', '豆制品', '豆腐', '豆')),
    ])
    allowed = [name for name, terms in candidates
               if not _contains(safety, *terms) and not _contains(disliked, *terms)]
    if allowed:
        return "、".join(allowed[:-1]) + ("或" if len(allowed) > 1 else "") + allowed[-1]
    return "其他已确认可耐受的植物蛋白质来源" if vegan else "已确认可耐受的蛋白质食材"


def _protein_portion(profile: Profile, protein_g: int) -> str:
    safety, disliked, unknown = _restrictions(profile)
    if unknown:
        return f"已确认可耐受的蛋白质来源约{max(50, round(protein_g / 0.2 / 10) * 10)}克（按标签调整）"
    vegetarian = _contains(safety, "素食", "纯素", "vegetarian", "vegan")
    vegan = _contains(safety, "纯素", "vegan")
    candidates = [
        ("豆制品", max(80, round(protein_g / 0.12 / 10) * 10), ("大豆", "黄豆", "豆制品", "豆腐"), 0.12),
    ] if vegetarian else [
        ("鱼肉熟重", max(50, round(protein_g / 0.22 / 10) * 10), ("鱼肉", "鱼类", "鱼"), 0.22),
        ("瘦肉熟重", max(50, round(protein_g / 0.23 / 10) * 10), ("肉类", "猪肉", "牛肉", "瘦肉"), 0.23),
        ("鸡胸肉熟重", max(50, round(protein_g / 0.23 / 10) * 10), ("鸡肉", "鸡胸", "禽肉"), 0.23),
        ("豆制品", max(80, round(protein_g / 0.12 / 10) * 10), ("大豆", "黄豆", "豆制品", "豆腐"), 0.12),
    ]
    if vegan:
        candidates = candidates[:1]
    for label, grams, terms, _protein_density in candidates:
        if not _contains(safety, *terms) and not _contains(disliked, *terms):
            return f"{label}约{grams}克（估算份量，按标签或菜单复核）"
    return f"其他已确认可耐受的蛋白质来源约{max(50, round(protein_g / 0.2 / 10) * 10)}克（按标签调整）"


def _provided_food_conflicts(profile: Profile, *food_texts: str) -> bool:
    nutrition = profile.nutrition
    if nutrition.food_allergy_status == 'unknown':
        return False
    restrictions = [nutrition.food_allergy_details, nutrition.food_intolerances,
                    nutrition.other_dietary_restrictions, nutrition.disliked_foods]
    supplied = " ".join(food_texts).lower()
    terms = [term.strip().lower() for value in restrictions if value
             for term in re.split(r"[,，、;；/\s]+", value) if len(term.strip()) >= 2]
    return any(term in supplied for term in terms)


def _meal_suggestions(profile: Profile, meal: str, *, protein_g: int, carbs_g: int,
                      conditions: str = "", available_foods: str = "", desired_foods: str = "",
                      budget: float | None = None) -> list[str]:
    source = profile.nutrition.primary_meal_source or ""
    protein = _protein_text(profile)
    if available_foods or desired_foods:
        unknown_allergy = _restrictions(profile)[2]
        conflict = unknown_allergy or _provided_food_conflicts(profile, available_foods, desired_foods)
        chosen = available_foods or desired_foods
        warning = ("食物过敏信息尚未确认，先不引用具体食材清单；补充过敏信息后再安排。" if unknown_allergy
                   else "当天提供的食物与档案限制有冲突，确认前不将该清单用于具体安排。")
        result = ([warning] if conflict else
                  [f"优先安排：{chosen[:180]}",
                   f"按可核对的包装/菜单份量组合，接近本餐蛋白质约{protein_g}克、碳水约{carbs_g}克；不确定时保留估算误差。"])
        normalized_available = re.sub(r"\s+", "", available_foods)
        normalized_desired = re.sub(r"\s+", "", desired_foods)
        if not conflict and desired_foods and available_foods and normalized_desired not in normalized_available:
            result.append(f"你想吃的内容：{desired_foods[:120]}；未在可用食物中确认，请先确认能否获得或选择替代。")
        elif desired_foods and not available_foods:
            result.append(f"按偏好考虑：{desired_foods[:120]}；当前未提供可用食物清单，实际可得性待确认。")
        if available_foods and not conflict:
            result.append(f"可用食材：{available_foods[:180]}")
        condition_budget = re.search(r"(\d+(?:\.\d+)?)\s*元", conditions)
        effective_budget = budget if budget is not None else (float(condition_budget.group(1)) if condition_budget else None)
        if effective_budget is not None:
            result.append(f"本餐预算约 {effective_budget:g} 元，价格以实际菜单为准")
        if _contains(conditions, "外卖", "点餐"):
            result.append("外卖备注少酱汁，保留一份蔬菜；实际份量和油量存在估算误差")
        return result
    rice_g = max(50, round(carbs_g / 0.28 / 10) * 10)
    oats_g = max(20, round(carbs_g / 0.65 / 5) * 5)
    protein_portion = _protein_portion(profile, protein_g)
    breakfast_protein_portion = _protein_portion(profile, protein_g)
    templates = {
        "早餐": [f"{protein}；{breakfast_protein_portion}，按标签配到本餐约{protein_g}克蛋白质",
                 f"主食：馒头约{max(40, round(carbs_g / 0.5 / 10) * 10)}克或干燕麦约{oats_g}克；水果1份，按本餐约{carbs_g}克碳水目标调整"],
        "午餐": [f"熟米饭约{rice_g}克 + {protein_portion} + 绿叶蔬菜约200克",
                 "食堂优先选择清蒸、白灼或少油炒菜，饮料选无糖水或茶"],
        "晚餐": [f"熟米饭约{rice_g}克 + {protein_portion} + 蔬菜约200克",
                 "若当天训练已完成，保留主食；若未训练也不跳餐，按饥饿程度调整份量"],
        "训练后": [f"训练后下一餐优先安排{protein}，按食材标签配到约{protein_g}克蛋白质",
                   f"搭配香蕉1根或熟米饭约{rice_g}克，按本餐约{carbs_g}克碳水目标调整；不把补剂当作正餐替代"],
    }
    rows = templates[meal]
    if _contains(source, "takeaway", "外卖") or _contains(conditions, "外卖", "点餐"):
        rows.append("外卖优先选有明确肉类/豆制品和蔬菜的套餐，酱汁分装，核对实际配料")
    if _contains(source, "instant", "速食") or _contains(conditions, "速食"):
        rows.append("速食核对营养标签，搭配已确认可耐受的蛋白质和蔬菜")
    if _contains(source, "takeaway", "外卖") or any(
        _contains(value, "takeaway", "外卖") for value in profile.nutrition.occasional_meal_sources
    ):
        rows.append("偶尔外卖：优先选择有蛋白质和蔬菜的套餐，酱汁分装并核对配料")
    return rows


def _general_meal_suggestions(profile: Profile, meal: str, *, available_foods: str = '',
                              desired_foods: str = '') -> list[str]:
    safety, disliked, unknown = _restrictions(profile)
    if unknown:
        rows = ['档案未记录已确认的过敏与不耐受信息，具体食材请按你已知情况核实。']
    elif available_foods:
        rows = [f'可从已提供的食物中选择：{available_foods[:180]}']
    else:
        rows = ['按已确认可耐受的食物和当下饥饿程度安排，不限定食材或份量。']
    if desired_foods:
        rows.append(f'已记录本次偏好：{desired_foods[:120]}。')
    if safety or disliked:
        rows.append('已按档案中明确记录的饮食限制和不喜欢项筛选。')
    rows.append('当前缺少个体化营养估算所需资料；本餐不推测热量、宏量或份量。')
    return rows


class NutritionPlannerAgent:
    """A narrow sub-agent interface; it plans food, not training or medical care."""

    def __init__(self, settings=None, provider=None):
        self.settings, self.provider = settings, provider

    def plan_live(self, profile: Profile, **context):
        from .config import Settings
        from .nutrition_live import plan_nutrition_live
        return plan_nutrition_live(profile, self.settings or Settings(), self.provider, **context)

    def calculate_targets(self, profile: Profile) -> NutritionTargets:
        return calculate_targets(profile)

    def plan(self, profile: Profile, *, meal: str | None = None, conditions: str | None = None,
             available_foods: str | None = None, desired_foods: str | None = None,
             already_eaten: str | None = None, budget_amount: float | None = None,
             daily_targets: dict | None = None, training: dict | None = None) -> NutritionPlan:
        targets = NutritionTargets.model_validate(daily_targets) if daily_targets else calculate_targets(profile)
        macro_calories = (targets.protein_g * 4 + targets.fat_g * 9 + targets.carbs_g * 4
                          if targets else None)
        if targets and targets.calories_kcal != macro_calories:
            targets = targets.model_copy(update={
                'calories_kcal': macro_calories,
                'assumptions': [*targets.assumptions, '每日热量按蛋白质、脂肪和碳水的估算值核算'],
            })
        _safety, _disliked, unknown = _restrictions(profile)
        selected = [meal] if meal in BASE_MEALS else list(BASE_MEALS)
        meal_macros = _meal_macros(targets) if targets else None
        base_total = sum(BASE_MEALS[key].kcal for key in BASE_MEALS)
        scale = targets.calories_kcal / base_total if targets else None
        rows: list[MealOption] = []
        condition_budget = re.search(r"(\d+(?:\.\d+)?)\s*元", conditions or "")
        parsed_budget = float(condition_budget.group(1)) if condition_budget else None
        for key in selected:
            base = BASE_MEALS[key]
            row_budget = ((budget_amount if budget_amount is not None else parsed_budget) if meal
                          else round(base.cost * scale, 2) if scale is not None else None)
            macros = meal_macros[key] if meal_macros else None
            rows.append(MealOption(
                meal=key,
                suggestions=(_meal_suggestions(profile, key, conditions=conditions or "",
                    protein_g=macros['protein_g'], carbs_g=macros['carbs_g'],
                    available_foods=available_foods or "", desired_foods=desired_foods or "", budget=row_budget)
                    if macros else _general_meal_suggestions(profile, key,
                        available_foods=available_foods or '', desired_foods=desired_foods or '')),
                estimated_kcal=(macros['protein_g'] * 4 + macros['fat_g'] * 9 + macros['carbs_g'] * 4)
                    if macros else None,
                protein_g=macros['protein_g'] if macros else None,
                fat_g=macros['fat_g'] if macros else None,
                carbs_g=macros['carbs_g'] if macros else None,
                estimated_cost_cny=row_budget,
                alternatives=(['同类可耐受食材按标签或菜单信息替换'] if macros
                              else ['按已确认可耐受的食物替换']),
            ))
        questions: list[str] = []
        if _provided_food_conflicts(profile, available_foods or '', desired_foods or ''):
            questions.append('当天提供的食物可能包含档案记录的过敏、不耐受或不喜欢项；请确认具体配料，确认前不要安排冲突食物。')
        if already_eaten:
            questions.append("已吃内容仅作为本次剩余安排参考；如果份量不确定，保留估算误差。")
            if not re.search(r"\d+(?:\.\d+)?\s*(?:克|g|毫升|ml|份|个|勺)", already_eaten, re.IGNORECASE):
                questions.append('已吃食物未提供份量或标签数据，不据此推算已摄入营养；如需细分剩余餐次，请补充份量，避免补偿性节食。')
        approach = ("这是起始估算，不是固定处方；连续记录体重、饥饿感、训练表现和执行情况后再校准。"
                    if targets else "档案资料不足以计算个体化热量与宏量目标；仅按已提供的信息给出不含份量估算的通用餐次建议。")
        if unknown:
            approach += ' 过敏与不耐受状态未确认；不会推定为没有过敏，也不根据空白档案选择具体食材。'
        if conditions:
            approach += f" 本次条件：{conditions[:300]}。"
        if already_eaten:
            approach += f" 已吃内容：{already_eaten[:300]}；剩余餐次不采用补偿性节食。"
        budget = profile.nutrition.food_budget
        daily_budget = None
        if budget.amount is not None and budget.period is not None:
            daily_budget = budget.amount / {"day": 1, "week": 7, "month": 30}[budget.period]
        if daily_budget is not None and daily_budget < 30:
            rows[min(1, len(rows) - 1)].suggestions.append(
                "低预算：优先购买食堂基础套餐、主食、当季蔬菜和可耐受蛋白质，先核实价格"
            )
        budget_note = (
            f"预算折算约 {daily_budget:g} 元/天（按月以30天估算）；" if daily_budget is not None
            else "未提供完整饮食预算和周期；"
        ) + "餐项费用为粗略估算，食堂和外卖价格、油量与份量以当天实际为准。"
        source = profile.nutrition.primary_meal_source or ""
        source_label = {"school_cafeteria": "学校食堂", "cafeteria": "食堂",
                        "home_cooking": "自炊", "takeaway": "外卖"}.get(source, source)
        if source_label:
            approach = f"按{source_label}可获得的食物生成具体起始餐单；" + approach
        restrictions = " ".join(filter(None, [profile.nutrition.food_allergy_details,
                                                profile.nutrition.food_intolerances,
                                                profile.nutrition.other_dietary_restrictions]))
        if restrictions:
            approach += f"已按记录的饮食限制筛选：{restrictions[:300]}；仍需核实配料和交叉接触。"
        if profile.nutrition.food_allergy_status == "has_allergies":
            approach += "已知过敏源不会被主动安排；仍需核对商家配料和交叉接触。"
        if training is not None:
            if training.get('kind') == 'rest':
                approach += ' 今天按休息日安排，长期能量与蛋白质目标保持；训练后补充改为日常加餐。'
                for row in rows:
                    if row.meal == '训练后':
                        row.meal = '加餐'
                        row.suggestions = [text.replace('训练后下一餐', '加餐').replace('训练后', '加餐')
                                           for text in row.suggestions]
            else:
                approach += ' 今天结合训练安排分配餐次，训练前后按消化耐受安排正餐或加餐。'
        return NutritionPlan(approach=approach, meal_options=rows, budget_note=budget_note,
                             daily_targets=targets, questions=questions)

    def memory_preview(self, profile: Profile, text: str) -> list[dict]:
        """Return candidates only; the caller must ask the user before saving them."""
        result = []
        if re.search(r"(以后|长期|今后|都不要|一直不要).{0,20}(不吃|不要|避免|别放)([^，。；]+)", text):
            value = re.search(r"(不吃|不要|避免|别放)([^，。；]+)", text).group(2).strip()
            value = re.sub(r"^(?:安排|放入|放|添加|加入)\s*", "", value)
            result.append({"kind": "disliked_food", "value": value[:100],
                           "source_text": text[:300], "requires_confirmation": True})
        allergy = re.search(r"(?:我对|对|有)([^，。；]+)(?:过敏|不耐受)", text)
        if allergy:
            kind = "intolerance" if "不耐受" in text else "allergy"
            result.append({"kind": kind, "value": allergy.group(1).strip()[:100],
                           "source_text": text[:300], "requires_confirmation": True})
        return result
