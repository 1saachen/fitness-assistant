from datetime import date
from types import SimpleNamespace

import pytest

from fitness.agent import DemoAgent
from fitness.config import ROOT, Settings
from fitness.knowledge_context import KnowledgeContextService
from fitness.models import Profile
from fitness.storage import Store


def setup_history(tmp_path, profile_data):
    store = Store(tmp_path / 'history.sqlite3')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    data = DemoAgent().parse_feedback('睡了5小时，累，没练', date(2026, 10, 11)).model_dump(mode='json')
    row = store.create_feedback('睡了5小时，累，没练', data, 'demo', {})
    row = store.confirm_feedback(row['id'], data, 0)
    service = KnowledgeContextService(ROOT / 'data/knowledge', ROOT / 'data/knowledge/baseline-strategies.json')
    return store, row, service


def test_demo_orchestration_reads_tools_and_never_calls_provider(tmp_path, profile_data):
    from fitness.orchestration import FitnessAgent
    store, row, service = setup_history(tmp_path, profile_data)
    class ForbiddenProvider:
        def complete(self, *a, **k):
            raise AssertionError('demo must not call network provider')
    result = FitnessAgent(store, service, Settings(), provider=ForbiddenProvider()).advise(row, 'demo')
    assert result.data.suggestions
    assert [t['name'] for t in result.trace['tool_calls']][:2] == ['get_profile', 'get_current_plan']
    assert 'summarize_recent_trend' in [t['name'] for t in result.trace['tool_calls']]
    assert result.trace['provider']['status'] == 'demo'
    assert result.data.explanations[0].facts


def test_urgent_profile_plan_withholds_training_and_skips_provider(tmp_path, profile_data):
    from fitness.orchestration import FitnessAgent
    profile_data['health'] = {'exercise_limiting_conditions_status':'has_conditions',
                             'exercise_limiting_conditions_details':'胸痛'}
    store, _row, service = setup_history(tmp_path, profile_data)
    class ForbiddenProvider:
        def complete(self, *a, **k):
            raise AssertionError('urgent profile must not call provider')
    result = FitnessAgent(store, service, Settings(live_enabled=True), provider=ForbiddenProvider()).plan(
        Profile.model_validate(profile_data), date(2026, 10, 11), 'live')
    assert all(day.kind == 'rest' and not day.exercises for day in result.data.days)
    assert '暂停' in result.data.summary
    assert result.trace['provider']['status'] == 'skipped_safety'


def test_model_can_select_read_tool_and_only_rephrase_advice(tmp_path, profile_data):
    from fitness.orchestration import FitnessAgent
    store, row, service = setup_history(tmp_path, profile_data)
    class Provider:
        count = 0
        def complete(self, messages, tools=None):
            self.count += 1
            if self.count == 1:
                return SimpleNamespace(content=None, tool_calls=[{'id':'one', 'name':'summarize_recent_trend',
                    'arguments':{'days':14}}], usage={'total_tokens':10})
            return SimpleNamespace(content='{"summary":"结合反馈，优先安排恢复。"}', tool_calls=[],
                                   usage={'total_tokens':15})
    result = FitnessAgent(store, service, Settings(live_enabled=True), provider=Provider()).advise(row, 'live')
    assert result.trace['provider']['status'] == 'ok'
    assert result.trace['provider']['usage']['total_tokens'] == 25
    assert result.data.summary == '结合反馈，优先安排恢复。'
    assert any(t['input'].get('days') == 14 for t in result.trace['tool_calls'])


def test_unknown_tool_or_unsafe_model_output_is_rejected(tmp_path, profile_data):
    from fitness.orchestration import FitnessAgent
    from fitness.provider import ProviderError
    store, row, service = setup_history(tmp_path, profile_data)
    class Provider:
        def complete(self, messages, tools=None):
            return SimpleNamespace(content=None, tool_calls=[{'id':'bad','name':'delete_database','arguments':{}}],
                                   usage={})
    with pytest.raises(ProviderError, match='tool_invalid'):
        FitnessAgent(store, service, Settings(live_enabled=True), provider=Provider()).advise(row, 'live')
    assert store.get_feedback(row['id'])['advice'] is None


def test_training_adjustment_preview_does_not_write_base_plan(tmp_path, profile_data):
    from fitness.tools import LocalTools
    store, row, service = setup_history(tmp_path, profile_data)
    profile = Profile.model_validate(profile_data)
    plan = store.create_plan(DemoAgent().generate_plan(profile, date(2026, 10, 11)).model_dump(mode='json'),
                             1, '2026-10-11', 'demo', {})
    store.confirm_plan(plan['id'])
    tools = LocalTools(store, service, row, today=date(2026, 10, 11))
    proposal = tools.call('adjust_today_training', {}).payload
    assert proposal['changes'][0]['old_value'] == 3
    assert proposal['changes'][0]['new_value'] == 2
    assert store.plans()[0]['data'] == plan['data']
    assert store.plan_changes() == []
    with pytest.raises(ValueError):
        tools.call('adjust_today_training', {'sets':10})


def test_live_parse_chinese_numeral_is_grounded_and_not_saved(tmp_path, profile_data):
    from fitness.orchestration import FitnessAgent
    store, _row, service = setup_history(tmp_path, profile_data)
    class Provider:
        def complete(self, messages, tools=None):
            return SimpleNamespace(content='{"sleep_hours":5}', tool_calls=[], usage={'total_tokens':4})
    before = len(store.feedback())
    result = FitnessAgent(store, service, Settings(live_enabled=True), provider=Provider()).parse(
        '昨晚睡了五个小时', date(2026, 10, 11), 'live')
    assert result.data.sleep_hours == 5
    assert result.trace['provider']['status'] == 'ok'
    assert len(store.feedback()) == before


def test_model_step_limit_cannot_loop_forever(tmp_path, profile_data):
    from fitness.orchestration import FitnessAgent
    from fitness.provider import ProviderError
    store, row, service = setup_history(tmp_path, profile_data)
    class Provider:
        count = 0
        def complete(self, messages, tools=None):
            self.count += 1
            return SimpleNamespace(content=None, tool_calls=[{'id':'one', 'name':'get_profile', 'arguments':{}}], usage={})
    provider = Provider()
    with pytest.raises(ProviderError, match='step_limit'):
        FitnessAgent(store, service, Settings(live_enabled=True, max_steps=2), provider=provider).advise(row, 'live')
    assert provider.count == 2


def test_live_timeout_counts_attempt_and_keeps_failed_tool_trace(tmp_path, profile_data):
    from fitness.orchestration import FitnessAgent
    from fitness.provider import ProviderError
    store, row, service = setup_history(tmp_path, profile_data)
    class Provider:
        def complete(self, messages, tools=None):
            raise ProviderError('timeout')
    with pytest.raises(ProviderError, match='timeout'):
        FitnessAgent(store, service, Settings(live_enabled=True), provider=Provider()).advise(row, 'live')
    assert store.get_feedback(row['id'])['advice'] is None


def test_multiple_adjustments_replay_chronologically(tmp_path, profile_data):
    from fitness.tools import LocalTools
    store, row, service = setup_history(tmp_path, profile_data)
    plan = store.create_plan(DemoAgent().generate_plan(Profile.model_validate(profile_data),
                             date(2026, 10, 11)).model_dump(mode='json'), 1, '2026-10-11', 'demo', {})
    store.confirm_plan(plan['id'])
    for _ in range(2):
        preview = LocalTools(store, service, row, today=date(2026, 10, 11)).training_preview()
        store.record_plan_change(**{k:v for k,v in preview.items() if k != 'reason'})
    assert LocalTools(store, service, row, today=date(2026, 10, 11)).training_preview()['changes'] == []


def test_plan_agent_uses_typed_tools_and_model_can_read_history(tmp_path, profile_data):
    from fitness.orchestration import FitnessAgent
    store, _row, service = setup_history(tmp_path, profile_data)
    class Provider:
        count = 0
        def complete(self, messages, tools=None):
            self.count += 1
            if self.count == 1:
                assert any(t['function']['name'] == 'summarize_recent_trend' for t in tools)
                return SimpleNamespace(content=None, tool_calls=[{'id':'one','name':'summarize_recent_trend',
                    'arguments':{'days':21}}], usage={})
            return SimpleNamespace(content='{"summary":"结合档案与近期记录安排本周训练。"}', tool_calls=[], usage={})
    result = FitnessAgent(store, service, Settings(live_enabled=True), provider=Provider()).plan(
        Profile.model_validate(profile_data), date(2026, 10, 11), 'live')
    assert result.trace['provider']['status'] == 'ok'
    assert [t['name'] for t in result.trace['tool_calls']][:3] == ['get_profile', 'get_current_plan', 'retrieve_baseline_strategies']
    assert result.trace['tool_calls'][-1]['input']['days'] == 21


def test_real_adapter_tool_roundtrip_uses_local_facts_and_validated_output(tmp_path, profile_data):
    import json

    import httpx

    from fitness.orchestration import FitnessAgent
    from fitness.provider import OpenAICompatibleProvider
    store, row, service = setup_history(tmp_path, profile_data)
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            message = {'role':'assistant', 'content':None, 'tool_calls':[
                {'id':'history', 'type':'function','function':{'name':'get_recent_feedback',
                    'arguments':'{"days":14,"metric":"sleep_hours","issue":null}'}}]}
            finish = 'tool_calls'
        else:
            assert body['messages'][-1]['role'] == 'tool'
            facts = json.loads(body['messages'][-1]['content'])['payload']['records']
            assert facts[0]['data']['sleep_hours'] == 5
            message = {'role':'assistant','content':'{"summary":"优先安排恢复，继续记录近期睡眠。"}'}
            finish = 'stop'
        return httpx.Response(200, json={'choices':[{'index':0,'message':message,'finish_reason':finish}],
                                         'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}})
    settings = Settings(live_enabled=True, api_key='synthetic-test-key')
    result = FitnessAgent(store, service, settings,
        provider=OpenAICompatibleProvider(settings, transport=httpx.MockTransport(handler))).advise(row, 'live')
    assert result.trace['provider']['status'] == 'ok'
    assert result.trace['provider']['usage']['total_tokens'] == 6
    assert len(calls) == 2


def test_edited_urgent_symptom_skips_provider_and_preview(tmp_path, profile_data):
    from fitness.orchestration import FitnessAgent
    store, row, service = setup_history(tmp_path, profile_data)
    row['raw_text'] = '累'
    row['data']['training_summary'] = '胸痛'
    class Forbidden:
        def complete(self, *args, **kwargs):
            raise AssertionError('urgent state must not call model')
    result = FitnessAgent(store, service, Settings(live_enabled=True), provider=Forbidden()).advise(row, 'live')
    assert result.trace['provider']['status'] == 'skipped_safety'
    assert '暂停训练' in result.data.summary
    assert result.trace['training_adjustment_preview']['changes'] == []
