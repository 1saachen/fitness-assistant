from datetime import date

import pytest
from test_agent_runtime import ScriptProvider, final
from test_training_live import task

from fitness.agent_contracts import PlanningRunError
from fitness.config import Settings
from fitness.daily_planning import DailyPlanningService
from fitness.models import Profile
from fitness.nutrition_agent import NutritionPlannerAgent
from fitness.provider import ProviderError
from fitness.storage import Store
from fitness.training_agent import TrainingPlannerAgent


def food_candidate():
    return {'approach': '模型按自炊条件设计，份量仅为起始估算。',
            'meal_options': [{'meal': '早餐', 'suggestions': ['燕麦配豆腐炒蔬菜'],
                             'alternatives': ['换为可耐受的同类食物']}],
            'budget_note': '价格按实际采购核实', 'daily_targets': None, 'questions': []}


def free_cycle():
    return {'summary': '模型自由选择动作', 'cycle': [
        {'label': '下肢', 'kind': 'training', 'estimated_minutes': 20, 'exercises': [
            {'name': '哑铃保加利亚分腿蹲', 'sets': 2, 'reps_min': 8, 'reps_max': 10,
             'rest_seconds': 90, 'weight_kg': None, 'target_rpe': 7,
             'equipment': ['dumbbell'], 'notes': '每侧完成，首次根据RPE选重'}]}]}


def test_live_accepts_model_named_exercise_without_catalog_or_id(profile_data):
    planner = TrainingPlannerAgent(Settings(live_enabled=True), ScriptProvider([final(free_cycle())]))
    result = planner.plan_cycle_live(task(profile_data, 'cycle'))
    assert result.status == 'draft_ready'
    exercise = result.candidate['cycle'][0]['exercises'][0]
    assert exercise['name'] == '哑铃保加利亚分腿蹲'
    assert exercise['exercise_id']
    assert exercise['target_rpe'] == 7
    assert exercise['notes'].startswith('每侧')
    again = TrainingPlannerAgent(Settings(live_enabled=True), ScriptProvider([final(free_cycle())]))
    assert again.plan_cycle_live(task(profile_data, 'cycle')).candidate['cycle'][0]['exercises'][0]['exercise_id'] == exercise['exercise_id']


def test_free_exercise_still_checks_declared_equipment(profile_data):
    from fitness.training_validation import validate_training_candidate
    candidate = free_cycle()
    candidate['cycle'][0]['exercises'][0]['equipment'] = ['barbell']
    issues = validate_training_candidate(candidate, task(profile_data, 'cycle'), {})
    assert any(issue.code == 'equipment' for issue in issues)


def test_nutrition_live_is_model_designed_and_receives_conditions():
    provider = ScriptProvider([final(food_candidate())])
    agent = NutritionPlannerAgent(Settings(live_enabled=True), provider)
    result = agent.plan_live(Profile(), conditions='只有微波炉', already_eaten='午餐已吃',
                             available_foods='燕麦和豆腐')
    assert result.status == 'draft_ready'
    assert result.candidate['meal_options'][0]['suggestions'] == ['燕麦配豆腐炒蔬菜']
    sent = provider.messages[0][1]['content']
    assert '只有微波炉' in sent and '午餐已吃' in sent and '燕麦和豆腐' in sent


def test_model_meals_cannot_override_confirmed_daily_target(profile_data):
    from fitness.nutrition_agent import calculate_targets
    from fitness.nutrition_live import validate_nutrition_candidate
    profile = Profile.model_validate(profile_data)
    target = calculate_targets(profile).model_dump(mode='json')
    candidate = food_candidate()
    candidate['daily_targets'] = {**target, 'calories_kcal': target['calories_kcal'] + 500}
    issues = validate_nutrition_candidate(candidate, profile, daily_targets=target)
    assert any(issue.code == 'confirmed_target' for issue in issues)


def test_live_nutrition_failure_does_not_save_training_only_plan(tmp_path, profile_data):
    store = Store(tmp_path / 'isolated.sqlite3')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    provider = ScriptProvider([final(free_cycle()), ProviderError('timeout')])
    svc = DailyPlanningService(store, Settings(live_enabled=True), provider=provider)
    with pytest.raises(PlanningRunError) as exc:
        svc.create_long_term(date(2026, 10, 20), mode='live')
    assert exc.value.result.reason_code == 'timeout'
    assert svc.repo.long_terms() == []


def test_live_training_and_nutrition_are_saved_together(tmp_path, profile_data):
    store = Store(tmp_path / 'isolated.sqlite3')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    food = food_candidate()
    provider = ScriptProvider([final(free_cycle()), final(food), final({
        'summary': '暂不新增补剂', 'budget_note': '预算待核实', 'items': [], 'questions': []})])
    svc = DailyPlanningService(store, Settings(live_enabled=True), provider=provider)
    result = svc.create_long_term(date(2026, 10, 20), mode='live')
    assert result['data']['nutrition']['meal_options'][0]['suggestions'] == ['燕麦配豆腐炒蔬菜']
    assert result['trace']['nutrition_source'] == 'model'
    assert result['trace']['nutrition_provider']['status'] == 'ok'


def test_model_nutrition_preserves_eaten_meals_and_rejects_allergens(profile_data):
    from fitness.nutrition_live import validate_nutrition_candidate
    profile = Profile.model_validate(profile_data)
    profile.nutrition.food_allergy_status = 'has_allergies'
    profile.nutrition.food_allergy_details = '花生过敏'
    eaten = food_candidate()['meal_options'][0]
    candidate = food_candidate()
    candidate['meal_options'] = [{'meal': '午餐', 'suggestions': ['花生拌饭']}]
    issues = validate_nutrition_candidate(candidate, profile, completed_meals=[eaten])
    assert {'food_restriction', 'completed_immutable'} <= {i.code for i in issues}


def test_free_exercise_is_matched_in_actual_feedback_for_next_live_day(profile_data):
    import json
    cycle = free_cycle()
    first = TrainingPlannerAgent(Settings(live_enabled=True), ScriptProvider([final(cycle)])).plan_cycle_live(task(profile_data, 'cycle'))
    exercise = first.candidate['cycle'][0]['exercises'][0]
    day = {'summary': '按真实反馈下调负荷', 'action': 'train',
           'training': first.candidate['cycle'][0], 'load_description': '目标RPE7'}
    day['training']['exercises'][0]['weight_kg'] = 8
    provider = ScriptProvider([final(day)])
    current = task(profile_data, history=[{'date': '2026-10-19', 'status': 'confirmed', 'data': {
        'exercise_results': [{'exercise_id': exercise['exercise_id'], 'weight_kg': 10, 'rpe': 9}]}}])
    result = TrainingPlannerAgent(Settings(live_enabled=True), provider).plan_day_live(current)
    assert result.candidate['training']['exercises'][0]['exercise_id'] == exercise['exercise_id']
    # The matching record remains available through the existing read-only history tool.
    from fitness.training_tools import TrainingTools
    history = TrainingTools(current, None).call('get_training_history', {'days': 7})
    assert json.loads(json.dumps(history))['records'][0]['data']['exercise_results'][0]['rpe'] == 9


def test_daily_model_context_omits_persisted_knowledge_and_provider_trace(profile_data):
    import json

    from test_training_live import day_candidate
    long_term = {'id': 'long-test', 'data': {'summary': '增肌长期目标', 'review_rules': ['两周复盘'],
        'supplements': {'summary': '现有产品需要核对标签', 'items': []},
        'knowledge_context': ['large archive' * 2000], 'strategy_context': ['large archive' * 2000]},
        'trace': {'provider': 'unneeded past call trace' * 2000}}
    provider = ScriptProvider([final(day_candidate())])
    result = TrainingPlannerAgent(Settings(live_enabled=True), provider).plan_day_live(task(profile_data, long_term=long_term))
    assert result.status == 'draft_ready'
    sent = json.loads(provider.messages[0][1]['content'])
    assert sent['long_term']['data']['summary'] == '增肌长期目标'
    assert sent['long_term']['data']['supplements']['summary'] == '现有产品需要核对标签'
    assert 'knowledge_context' not in sent['long_term']['data']
    assert 'trace' not in sent['long_term']


def test_daily_nutrition_can_explain_targets_without_changing_confirmed_metadata(profile_data):
    from fitness.nutrition_agent import calculate_targets
    profile = Profile.model_validate(profile_data)
    target = calculate_targets(profile).model_dump(mode='json')
    candidate = food_candidate()
    candidate['daily_targets'] = {**target, 'method': '遵循已确认目标'}
    provider = ScriptProvider([final(candidate)])
    result = NutritionPlannerAgent(Settings(live_enabled=True), provider).plan_live(profile,
        daily_targets=target, lock_daily_targets=True)
    assert result.status == 'draft_ready'
    assert result.candidate['daily_targets'] == target


def test_whole_day_menu_must_approximately_cover_target_but_single_meal_is_partial(profile_data):
    from fitness.nutrition_agent import calculate_targets
    from fitness.nutrition_live import validate_nutrition_candidate
    profile = Profile.model_validate(profile_data)
    target = calculate_targets(profile).model_dump(mode='json')
    candidate = food_candidate()
    candidate['daily_targets'] = target
    candidate['meal_options'][0].update(estimated_kcal=120, protein_g=10, fat_g=0, carbs_g=20)
    issues = validate_nutrition_candidate(candidate, profile, daily_targets=target)
    assert any(i.code == 'daily_totals' for i in issues)
    assert not validate_nutrition_candidate(candidate, profile, daily_targets=target, meal='早餐')


def test_new_action_requires_equipment_declaration_when_catalog_cannot_check(profile_data):
    from fitness.training_validation import validate_training_candidate
    candidate = free_cycle()
    candidate['cycle'][0]['exercises'][0].pop('equipment')
    assert any(i.code == 'equipment_unknown' for i in validate_training_candidate(candidate, task(profile_data, 'cycle'), {}))


@pytest.mark.parametrize('allergy,food', [('鱼肉过敏', '清蒸鱼肉200克'), ('鸡肉过敏', '鸡胸肉150克'),
                                      ('芒果过敏', '芒果切块100克')])
def test_live_food_checks_explicit_allergens_beyond_common_groups(profile_data, allergy, food):
    from fitness.nutrition_live import validate_nutrition_candidate
    profile = Profile.model_validate(profile_data)
    profile.nutrition.food_allergy_status = 'has_allergies'
    profile.nutrition.food_allergy_details = allergy
    candidate = food_candidate()
    candidate['meal_options'][0]['suggestions'] = [food]
    assert any(i.code == 'food_restriction' for i in validate_nutrition_candidate(candidate, profile))


def test_nutrition_uses_recent_feedback_instead_of_oldest_rows(tmp_path, profile_data):
    import json
    from datetime import timedelta

    from fitness.models import FeedbackData
    store = Store(tmp_path / 'recent.sqlite3')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    day = date(2026, 10, 20)
    for days_ago in range(25, 0, -1):
        data = FeedbackData(date=day - timedelta(days=days_ago), weight_kg=70 + days_ago / 10).model_dump(mode='json')
        row = store.create_feedback('合成体重记录', data, 'demo', {})
        store.confirm_feedback(row['id'], data, 0)
    provider = ScriptProvider([final(free_cycle()), final(food_candidate()), final({
        'summary': '暂不新增补剂', 'budget_note': '预算待核实', 'items': [], 'questions': []})])
    svc = DailyPlanningService(store, Settings(live_enabled=True), provider=provider)
    svc.create_long_term(day, mode='live')
    history = json.loads(provider.messages[1][1]['content'])['history']
    assert len(history) == 13
    assert history[0]['date'] == (day - timedelta(days=13)).isoformat()
    assert history[-1]['date'] == (day - timedelta(days=1)).isoformat()
