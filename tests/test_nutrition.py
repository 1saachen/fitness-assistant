from datetime import date

from fitness.models import Profile
from fitness.nutrition_agent import NutritionPlannerAgent, calculate_targets
from fitness.planning import generate_plan


def test_nutrition_uses_real_budget_and_sources(profile_data):
    profile_data['nutrition']['food_budget'] = {'amount': 210, 'period': 'week'}
    profile_data['nutrition']['primary_meal_source'] = 'home_cooking'
    profile_data['nutrition']['occasional_meal_sources'] = ['takeaway']
    plan = generate_plan(Profile.model_validate(profile_data), date(2026, 10, 11))
    assert '30' in plan.nutrition.budget_note
    assert '40元' not in plan.nutrition.budget_note
    assert '自炊' in plan.nutrition.approach
    assert '外卖' in str(plan.nutrition.meal_options)


def test_nutrition_allergy_does_not_recommend_known_allergen(profile_data):
    profile_data['nutrition'].update(food_allergy_status='has_allergies',
                                    food_allergy_details='鸡蛋、牛奶、花生',
                                    other_dietary_restrictions='素食')
    plan = generate_plan(Profile.model_validate(profile_data), date(2026, 10, 11))
    choices = ' '.join(s for m in plan.nutrition.meal_options for s in m.suggestions)
    assert '鸡蛋' not in choices and '奶制品' not in choices and '肉类' not in choices
    assert '过敏' in plan.nutrition.approach
    assert '素食' in plan.nutrition.approach


def test_unknown_allergy_and_budget_are_explicit_questions(profile_data):
    profile_data['nutrition'] = {}
    plan = generate_plan(Profile.model_validate(profile_data), date(2026, 10, 11))
    assert not any('过敏' in q for q in plan.questions)
    assert '过敏与不耐受状态未确认' in plan.nutrition.approach
    assert '未提供' in plan.nutrition.budget_note


def test_six_sessions_are_not_silently_reduced_to_four(profile_data):
    profile_data['training']['available_sessions_per_week'] = 6
    plan = generate_plan(Profile.model_validate(profile_data), date(2026, 10, 11))
    assert sum(d.kind == 'training' for d in plan.days) == 6


def test_plan_title_and_summary_follow_each_supported_goal(profile_data):
    for goal, label in [('fat_loss', '减脂'), ('muscle_gain', '增肌'),
                        ('general_health', '健康')]:
        profile_data['goals']['primary'] = goal
        plan = generate_plan(Profile.model_validate(profile_data), date(2026, 10, 11))
        assert label in plan.title
        assert label in plan.summary
        if goal != 'fat_loss':
            assert '减脂保力量' not in plan.title


def test_preferred_monday_is_calendar_monday_when_plan_starts_sunday(profile_data):
    profile_data['training'].update(available_sessions_per_week=1, preferred_weekdays=[0])
    plan = generate_plan(Profile.model_validate(profile_data), date(2026, 10, 11))
    assert plan.days[0].kind == 'rest'
    assert plan.days[1].kind == 'training'


def test_limited_equipment_never_creates_empty_training_days(profile_data):
    profile_data['training'].update(available_sessions_per_week=6, available_equipment=['bodyweight'])
    plan = generate_plan(Profile.model_validate(profile_data), date(2026, 10, 11))
    assert all(day.exercises for day in plan.days if day.kind == 'training')
    assert all(e.exercise_id == 'plank' for day in plan.days for e in day.exercises)
    assert any('器械' in q for q in plan.questions)


def test_vegan_restriction_and_low_budget_change_meal_choices(profile_data):
    profile_data['nutrition'].update(other_dietary_restrictions='纯素',
                                     food_budget={'amount':100, 'period':'week'})
    plan = generate_plan(Profile.model_validate(profile_data), date(2026, 10, 11))
    options = str(plan.nutrition.meal_options)
    assert '鸡蛋' not in options and '奶制品' not in options and '肉类' not in options
    assert '低预算' in options


def test_nutrition_plan_has_calculated_targets_and_concrete_portions(profile_data):
    profile_data['personal']['body_fat_percent'] = 20
    profile_data['training']['available_sessions_per_week'] = 4
    profile_data['daily_activity_level'] = '低到中等'
    profile = Profile.model_validate(profile_data)
    plan = NutritionPlannerAgent().plan(profile)
    assert plan.daily_targets is not None
    assert 120 <= plan.daily_targets.protein_g <= 180
    assert plan.daily_targets.carbs_g > 0
    assert plan.daily_targets.calories_kcal == round(
        plan.daily_targets.protein_g * 4
        + plan.daily_targets.carbs_g * 4
        + plan.daily_targets.fat_g * 9
    )
    assert any('克' in row for meal in plan.meal_options for row in meal.suggestions)
    assert any(meal.estimated_kcal is not None for meal in plan.meal_options)
    assert sum(meal.protein_g for meal in plan.meal_options) == plan.daily_targets.protein_g
    assert sum(meal.fat_g for meal in plan.meal_options) == plan.daily_targets.fat_g
    assert sum(meal.carbs_g for meal in plan.meal_options) == plan.daily_targets.carbs_g
    assert plan.meal_options[0].estimated_kcal < plan.daily_targets.calories_kcal


def test_missing_profile_facts_do_not_produce_personalized_nutrition_estimates():
    plan = NutritionPlannerAgent().plan(Profile.model_validate({}))
    assert plan.daily_targets is None
    assert all(meal.estimated_kcal is None for meal in plan.meal_options)
    assert all(meal.protein_g is None and meal.fat_g is None and meal.carbs_g is None
               for meal in plan.meal_options)
    assert '个体化热量与宏量目标' in plan.approach


def test_goal_changes_initial_calorie_direction(profile_data):
    targets = {}
    for goal in ('fat_loss', 'general_health', 'muscle_gain'):
        profile_data['goals']['primary'] = goal
        targets[goal] = calculate_targets(Profile.model_validate(profile_data)).calories_kcal
    assert targets['fat_loss'] < targets['general_health'] < targets['muscle_gain']


def test_individual_meal_target_is_a_share_of_daily_target(profile_data):
    plan = NutritionPlannerAgent().plan(Profile.model_validate(profile_data), meal='午餐')
    assert plan.meal_options[0].estimated_kcal < plan.daily_targets.calories_kcal
    row = plan.meal_options[0]
    assert row.estimated_kcal == row.protein_g * 4 + row.carbs_g * 4 + row.fat_g * 9


def test_meal_portions_scale_with_macro_targets_and_match_estimates(profile_data):
    profile_data['nutrition']['food_allergy_status'] = 'none_known_self_reported'
    profile_data['daily_activity_level'] = '中等'
    profile = Profile.model_validate(profile_data)
    planner = NutritionPlannerAgent()
    low = planner.plan(profile, daily_targets={
        'calories_kcal': 1800, 'protein_g': 130, 'fat_g': 55, 'carbs_g': 211,
        'method': 'test', 'assumptions': [], 'confidence': 'medium'})
    high = planner.plan(profile, daily_targets={
        'calories_kcal': 2400, 'protein_g': 160, 'fat_g': 70, 'carbs_g': 298,
        'method': 'test', 'assumptions': [], 'confidence': 'medium'})
    for plan in (low, high):
        assert sum(meal.estimated_kcal for meal in plan.meal_options) == plan.daily_targets.calories_kcal
        for meal in plan.meal_options:
            assert meal.estimated_kcal == meal.protein_g * 4 + meal.carbs_g * 4 + meal.fat_g * 9
            assert any('克' in suggestion for suggestion in meal.suggestions)
        assert any('熟米饭' in suggestion for meal in plan.meal_options for suggestion in meal.suggestions)
    assert high.meal_options[1].protein_g > low.meal_options[1].protein_g
    assert high.meal_options[1].carbs_g > low.meal_options[1].carbs_g


def test_daily_conditions_override_base_meal_and_return_one_meal(profile_data):
    profile = Profile.model_validate(profile_data)
    plan = NutritionPlannerAgent().plan(
        profile, meal='午餐', conditions='只能点外卖，预算18元',
        available_foods='黄焖鸡、米饭、青菜', desired_foods='想吃黄焖鸡',
    )
    assert len(plan.meal_options) == 1
    assert plan.meal_options[0].meal == '午餐'
    assert '黄焖鸡' in str(plan.meal_options[0].suggestions)
    assert any('18' in row for row in plan.meal_options[0].suggestions)
    assert plan.meal_options[0].estimated_cost_cny == 18


def test_allergy_and_unknown_status_are_safe(profile_data):
    profile_data['nutrition'].update(
        food_allergy_status='has_allergies', food_allergy_details='花生',
        food_preferences='喜欢米饭', disliked_foods='香菜',
    )
    plan = NutritionPlannerAgent().plan(Profile.model_validate(profile_data))
    assert '花生' not in str(plan.meal_options)
    assert '香菜' not in str(plan.meal_options)
    profile_data['nutrition'] = {}
    unknown = NutritionPlannerAgent().plan(Profile.model_validate(profile_data))
    assert not any('过敏' in question for question in unknown.questions)
    assert '鸡胸肉' not in str(unknown.meal_options)
    assert '豆腐' not in str(unknown.meal_options)


def test_meal_plan_respects_specific_protein_allergies_and_dislikes(profile_data):
    profile_data['nutrition'].update(food_allergy_details='鸡肉', disliked_foods='鱼肉')
    plan = NutritionPlannerAgent().plan(Profile.model_validate(profile_data))
    suggestions = str([meal.suggestions for meal in plan.meal_options])
    assert '鸡胸肉' not in suggestions
    assert '鱼肉' not in suggestions
    assert '瘦肉' in suggestions or '豆制品' in suggestions


def test_desired_food_not_confirmed_available_is_not_treated_as_stock(profile_data):
    plan = NutritionPlannerAgent().plan(Profile.model_validate(profile_data), meal='午餐',
        available_foods='米饭和青菜', desired_foods='想吃鸡肉')
    text = ' '.join(plan.meal_options[0].suggestions)
    assert '米饭和青菜' in text
    assert '未在可用食物中确认' in text


def test_available_food_matching_known_allergy_is_held_for_confirmation(profile_data):
    profile_data['nutrition'].update(food_allergy_details='花生')
    plan = NutritionPlannerAgent().plan(Profile.model_validate(profile_data), meal='午餐',
        available_foods='米饭、青菜、花生酱鸡肉')
    text = ' '.join(plan.meal_options[0].suggestions)
    assert '花生酱鸡肉' not in text
    assert any('过敏' in question and '确认' in question for question in plan.questions)


def test_already_eaten_food_without_portions_is_not_counted_as_macros(profile_data):
    plan = NutritionPlannerAgent().plan(Profile.model_validate(profile_data),
        already_eaten='吃了米饭和鸡肉，但没称份量')
    assert any('份量' in question and '估算' in question for question in plan.questions)
    assert '不采用补偿性节食' in plan.approach


def test_unknown_allergy_does_not_echo_a_specific_available_food_list(profile_data):
    profile_data['nutrition']['food_allergy_status'] = 'unknown'
    plan = NutritionPlannerAgent().plan(Profile.model_validate(profile_data), meal='午餐',
        available_foods='鸡蛋、米饭、花生酱')
    text = ' '.join(plan.meal_options[0].suggestions)
    assert '花生酱' not in text
    assert '过敏' in text and plan.questions == []


def test_memory_preview_only_extracts_explicit_long_term_preferences(profile_data):
    profile = Profile.model_validate(profile_data)
    result = NutritionPlannerAgent().memory_preview(profile, '以后都不要安排香菜，我对花生过敏')
    assert {item['kind'] for item in result} == {'disliked_food', 'allergy'}
    assert next(item['value'] for item in result if item['kind'] == 'disliked_food') == '香菜'
    assert all(item['requires_confirmation'] for item in result)
    assert NutritionPlannerAgent().memory_preview(profile, '今天不想吃鸡蛋') == []
