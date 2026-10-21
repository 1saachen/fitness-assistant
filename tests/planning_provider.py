"""Independent nutrition responses for tests focused on training orchestration."""
import json

from test_agent_runtime import ScriptProvider, final


class PlanningScriptProvider(ScriptProvider):
    def __init__(self, replies):
        super().__init__(replies)
        self.nutrition_messages = []

    def complete(self, messages, tools=None, **kwargs):
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
