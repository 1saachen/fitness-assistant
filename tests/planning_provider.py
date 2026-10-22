"""Independent nutrition responses for tests focused on training orchestration."""
import json

from test_agent_runtime import ScriptProvider, final


def supplement_reply(messages):
    context = json.loads(messages[1]['content'])
    return final({'summary': '模拟模型评估，暂不新增补剂。', 'budget_note': '预算待核实', 'questions': [],
        'items': [{'name': name, 'current_product': name, 'priority': 'needs_review',
            'reason': '请核实产品成分', 'conditions': [], 'food_alternatives': [],
            'cautions': ['未确认适用性'], 'source_ids': []}
            for name in context['profile']['supplements']['current_products'] or []]})


class PlanningScriptProvider(ScriptProvider):
    def __init__(self, replies):
        super().__init__(replies)
        self.nutrition_messages = []

    def complete(self, messages, tools=None, **kwargs):
        if '你是补剂规划 Agent' in messages[0]['content']:
            return supplement_reply(messages)
        if '你是持续陪伴用户的训练和饮食教练' in messages[0]['content']:
            return final({'reply': '已记录本次补充。', 'suggestions': [], 'questions': [],
                'memory_updates': [], 'retire_keys': [], 'restriction_resolutions': {},
                'decision': {'action': 'keep', 'reason': '本次条件已另行用于规划。'}, 'facts': None})
        if '你是饮食规划 Agent' not in messages[0]['content']:
            return super().complete(messages, tools, **kwargs)
        self.nutrition_messages.append(messages)
        context = json.loads(messages[1]['content'])
        eaten = context.get('completed_meals', [])
        return final({'approach': '模拟模型餐单', 'daily_targets': context.get('daily_targets'),
            'budget_note': '价格待核实', 'questions': [],
            'meal_options': [*eaten, *[
                {'meal': name, 'suggestions': ['按已确认可耐受的食物搭配']}
                for name in ('早餐', '午餐', '晚餐') if name not in {m['meal'] for m in eaten}]]})


class ModelledTestProvider:
    def complete(self, messages, tools=None, **kwargs):
        from test_model_led_planning import food_candidate
        from test_training_live import day_candidate
        from test_training_live_service import cycle_candidate

        role = messages[0]['content']
        if '你是补剂规划 Agent' in role:
            return supplement_reply(messages)
        if '你是训练规划 Agent' in role:
            task = json.loads(messages[1]['content'])
            if task['kind'] == 'cycle':
                candidate = cycle_candidate()
                candidate['cycle'][0]['label'] = '推'
            else:
                candidate = day_candidate()
                candidate['training']['label'] = '推'
                if task['state'].get('current_fatigue_defer'):
                    candidate.update(action='defer', reasons=['今天反馈疲劳，本次安排休息。'],
                        training={'label': '按循环顺延', 'kind': 'rest', 'exercises': [], 'estimated_minutes': 0})
                elif task['state'].get('active_restrictions'):
                    candidate.update(action='pause', reasons=['先暂停训练，按限制情况恢复。'],
                        training={'label': '暂停训练', 'kind': 'rest', 'exercises': [], 'estimated_minutes': 0})
            return final(candidate)
        if '你是饮食规划 Agent' in role:
            return final(food_candidate())
        if '你是持续陪伴用户的训练和饮食教练' in role:
            return final({'reply': '已记录本次补充。', 'suggestions': [], 'questions': [],
                'memory_updates': [], 'retire_keys': [], 'restriction_resolutions': {},
                'decision': {'action': 'keep', 'reason': '本次信息已纳入安排。'}, 'facts': None})
        if '只输出FeedbackData的JSON补丁' in role:
            task = json.loads(messages[1]['content'])
            return type('Reply', (), {'content': json.dumps(task['baseline']),
                'tool_calls': [], 'usage': {}})()
        raise AssertionError('Unexpected model role in API test')
