from datetime import date

from fitness.models import Profile
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
    assert any('过敏' in q for q in plan.questions)
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
