"""Profile-driven meal choices; estimates never claim cafeteria prices are known."""

from .models import NutritionPlan


def nutrition_plan(profile):
    n = profile.nutrition
    source = n.primary_meal_source or 'unknown'
    source_label = {'school_cafeteria': '学校食堂', 'cafeteria': '食堂',
                    'home_cooking': '自炊', 'takeaway': '外卖'}.get(source, source)
    restrictions = ' '.join(filter(None, [n.food_allergy_details, n.food_intolerances,
                                         n.other_dietary_restrictions]))
    uncertain = n.food_allergy_status == 'unknown' or (
        n.food_allergy_status == 'has_allergies' and not n.food_allergy_details)
    proteins = ['鸡蛋', '奶制品', '豆制品', '肉类']
    excluded = {
        '鸡蛋': ('蛋', 'egg', 'vegan', '纯素'), '奶制品': ('奶', '乳', 'milk', 'lactose', 'vegan', '纯素'),
        '豆制品': ('豆', 'soy'), '肉类': ('素食', '纯素', 'vegan', 'vegetarian', '肉'),
    }
    proteins = [p for p in proteins if not any(t in restrictions.lower() for t in excluded[p])]
    if uncertain or not proteins:
        protein_text = '先核实可耐受的蛋白质食材和交叉接触风险，再选择搭配'
    else:
        protein_text = '从' + '、'.join(proteins) + '中选择可耐受且符合饮食限制的蛋白质来源'
    approach = f'以{source_label}可获得的食物为基础，规律进餐，搭配蛋白质、蔬菜和主食。'
    if restrictions:
        approach += f'按记录的过敏/不耐受/饮食限制筛选：{restrictions[:500]}；核实配料及交叉接触。'
    if uncertain:
        approach += '过敏信息待确认，当前不承诺任何具体食材安全。'
    meals = [
        {'meal': '早餐', 'suggestions': [protein_text, '搭配适量主食，按饥饿程度记录实际份量']},
        {'meal': '午餐/晚餐', 'suggestions': [protein_text, '搭配蔬菜和主食，记录油、酱料及饮料']},
        {'meal': '训练后', 'suggestions': ['在接下来一餐补充适合自己的蛋白质和碳水', '饮水并观察恢复']},
    ]
    if 'home' in source or '自炊' in source:
        meals[1]['suggestions'].append('自炊时提前分装主食、蔬菜及可耐受的蛋白质食材')
    if any('takeaway' in s or '外卖' in s for s in [source, *n.occasional_meal_sources]):
        meals[1]['suggestions'].append('外卖先核实配料，酱料分装，保留可耐受的蛋白质和蔬菜')
    if any('速食' in s or 'instant' in s for s in n.occasional_meal_sources):
        meals[1]['suggestions'].append('速食核对配料与营养标签，搭配可耐受的蛋白质和蔬菜')
    budget = n.food_budget
    if budget.amount is None or budget.period is None:
        note = '未提供完整饮食预算和周期；请记录实际花费后核算。'
    else:
        divisor = {'day': 1, 'week': 7, 'month': 30}[budget.period]
        daily = budget.amount / divisor
        note = f'预算折算约 {daily:g} 元/天（按月时以30天估算）；当地价格未知，以实际账单核验。'
        if daily < 30:
            note += '优先基础食材与食堂套餐，补剂预算单独记录，避免挤占正餐。'
            meals[1]['suggestions'].append('低预算优先按份购买当季蔬菜、主食与可耐受的基础蛋白质食材，先核实套餐价格')
        else:
            note += '优先保障正餐蛋白质、蔬菜及主食，补剂预算单独记录。'
    questions = ['请补充食物过敏及不耐受信息，并核实实际食材。'] if uncertain else []
    return NutritionPlan(approach=approach, meal_options=meals, budget_note=note), questions
