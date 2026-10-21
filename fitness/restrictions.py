"""Conservative subject matching for reported restrictions and food checks."""

import re


def explicit_allergens(text, *, bare=False):
    terms = set()
    for clause in re.split(r'[，,；;。.!！\n]', text or ''):
        match = re.search(r'(.+?)(?:严重)?(?:过敏|不耐受)', clause)
        subject = match[1] if match else (clause if bare else '')
        subject = re.sub(r'^(?:(?:用户|本人|自己|我|自述|报告|表示|有|对|的|是|明确|已知|确认|存在|食物)\s*)+', '', subject.strip())
        for term in re.split(r'[、和及/()（）\s]+', subject):
            if len(term) >= 2:
                terms.add(term.lower())
        english = re.search(r'(?:allergic to|allergy to|intolerant to)\s+([a-z -]+)', clause, re.IGNORECASE)
        if english:
            terms.add(english[1].strip().lower())
    return terms


def resolution_matches(old_text, quote):
    if not re.search(r'更正|纠正|说错|误|解除|恢复|好了|不疼|无痛|不再|不是|没有|可以|允许|cleared|incorrect|recovered', quote, re.IGNORECASE):
        return False
    if re.search(r'尚未|仍然|还没|(?:没有|未|没)(?:恢复|解除|痊愈|消失|好)|不能|not recovered|still allergic', quote, re.IGNORECASE):
        return False
    groups = [('花生', 'peanut'), ('牛奶', '乳糖', 'milk', 'lactose'), ('鸡蛋', 'egg'),
              ('大豆', '豆腐', 'soy'), ('虾', '蟹', 'shellfish'), ('小麦', 'wheat'),
              ('鱼', 'fish'), ('坚果', 'nuts'), ('芝麻', 'sesame'),
              ('肩', 'shoulder'), ('膝', 'knee'), ('腰', '背', 'back'),
              ('腕', 'wrist'), ('肘', 'elbow'), ('髋', 'hip')]
    topics = [group for group in groups if any(term in old_text.lower() for term in group)]
    allergens = explicit_allergens(old_text)
    for allergen in allergens:
        if not any(any(term in allergen for term in group) for group in topics):
            topics.append((allergen,))
    return (all(any(term in quote.lower() for term in group) for group in topics)
            if topics else old_text in quote)


def actionable_food(text):
    # Explicit avoidance clauses are notes, not food being offered. "无糖花生酱" remains food.
    return re.sub(r'(?:不含|不使用|不添加|不安排|不要加|不要用|不要吃|不加|不用|避开|避免|排除)[^，,；;。.!！\n的]*', '', text).lower()
