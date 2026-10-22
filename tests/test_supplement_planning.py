import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_agent_runtime import ScriptProvider, final
from test_model_led_planning import food_candidate, free_cycle

from fitness.agent_contracts import PlanningRunError
from fitness.config import Settings
from fitness.daily_planning import DailyPlanningService
from fitness.models import Profile
from fitness.provider import ProviderError, ProviderReply
from fitness.storage import Store


def candidate():
    return {'summary': '先保证饮食，再评估是否需要补充。', 'budget_note': '预算未知，不估算售价。',
        'items': [{'name': '维生素D', 'current_product': None, 'priority': 'conditional',
            'reason': '仅在饮食和日晒条件需要时评估。',
            'conditions': ['健康状况未知时先核实相关疾病和限制；用药情况未知时先核实当前用药'],
            'food_alternatives': ['先评估日常食物来源'], 'cautions': ['知识卡是创作者观点，证据有限。'],
            'source_ids': []}], 'questions': []}


def knowledge():
    return SimpleNamespace(knowledge_root=Path(__file__).resolve().parents[1] / 'data' / 'knowledge')


def sources():
    from fitness.knowledge import build_manifest
    return {r['id']: r for r in build_manifest(knowledge().knowledge_root) if r['collection'] == 'supplements'}


def test_default_plan_does_not_load_knowledge_cards(monkeypatch):
    from fitness.supplement_agent import SupplementPlannerAgent
    def unexpected_read(*args, **kwargs):
        pytest.fail('Default planning must not load the supplement library')
    monkeypatch.setattr('fitness.supplement_agent.build_manifest', unexpected_read)
    provider = ScriptProvider([final(candidate())])
    profile = Profile()
    profile.supplements.budget.amount = 200
    result = SupplementPlannerAgent(Settings(live_enabled=True), provider).plan_live(profile, knowledge(),
        nutrition=food_candidate(), training_cycle=free_cycle()['cycle'], conditions='希望控制预算',
        personal_memory={'entries': [{'text': '夜班作息'}]}, history=[])
    assert result.status == 'draft_ready'
    payload = json.loads(provider.messages[0][1]['content'])
    cards = payload['knowledge']['cards']
    assert cards == []
    assert payload['profile']['supplements']['budget']['amount'] == 200
    assert payload['nutrition'] == food_candidate()
    assert payload['personal_memory']['entries'][0]['text'] == '夜班作息'
    assert result.trace['source_snapshots'] == []
    assert result.trace['knowledge_status'] == 'not_requested'


def search_reply(query):
    return ProviderReply(tool_calls=[{'id': 'supplement-search', 'name': 'search_supplement_knowledge',
        'arguments': {'query': query, 'limit': 3}}])


def test_explicit_question_can_search_and_persist_only_retrieved_approved_cards():
    from fitness.supplement_agent import SupplementPlannerAgent
    plan = candidate()
    plan['items'][0].update(name='益生菌', source_ids=['mvp-supplements-004'])
    provider = ScriptProvider([search_reply('益生菌'), final(plan)])
    result = SupplementPlannerAgent(Settings(live_enabled=True), provider).plan_live(
        Profile(), knowledge(), conditions='我想了解益生菌')
    assert result.status == 'draft_ready'
    cards = json.loads(provider.messages[1][-1]['content'])['cards']
    assert 0 < len(cards) <= 3
    assert all('益生菌' in c['title'] for c in cards)
    assert all(c['metadata']['review_status'] == 'approved' and c['collection'] == 'supplements' for c in cards)
    assert all(c['source']['video_url'] and c['metadata']['evidence_level'] for c in cards)
    assert [s['id'] for s in result.trace['source_snapshots']] == ['mvp-supplements-004']
    assert result.trace['knowledge_status'] == 'ok'


@pytest.mark.parametrize('query', ['肌酸', '不存在的补剂', 'evidence-pilot-magnesium-20260919'])
def test_missing_or_pending_knowledge_does_not_produce_unrelated_sources(query):
    from fitness.supplement_agent import SupplementKnowledge
    tools = SupplementKnowledge(knowledge())
    assert tools.call('search_supplement_knowledge', {'query': query})['cards'] == []
    assert tools.retrieved_sources == {}


def test_search_normalizes_spaces_without_matching_other_vitamins():
    from fitness.supplement_agent import SupplementKnowledge
    tools = SupplementKnowledge(knowledge())
    cards = tools.call('search_supplement_knowledge', {'query': '维生素 D3', 'limit': 5})['cards']
    assert cards
    assert all('维生素d3' in ''.join(card['title'].casefold().split()) for card in cards)


def test_no_suitable_supplement_allows_an_empty_recommendation_list():
    from fitness.supplement_agent import SupplementPlannerAgent
    plan = candidate()
    plan['items'] = []
    result = SupplementPlannerAgent(Settings(), ScriptProvider([final(plan)])).plan_live(Profile(), knowledge())
    assert result.status == 'draft_ready'
    assert result.candidate['items'] == []


def test_prompt_sets_default_list_and_personalized_protein_powder_rule():
    from fitness.supplement_agent import SupplementPlannerAgent
    provider = ScriptProvider([final(candidate())])
    SupplementPlannerAgent(Settings(live_enabled=True), provider).plan_live(
        Profile(), knowledge(), nutrition=food_candidate())
    system = provider.messages[0][0]['content']
    assert '默认范围仅限' in system
    assert all(name in system for name in ('肌酸', '鱼油', '维生素D3/K2', '甘氨酸镁'))
    assert '蛋白质目标' in system and '蛋白粉' in system


@pytest.mark.parametrize('dose', ['每天补充维生素D 2000 IU', '鱼油每天2克', '镁每日二百毫克',
                                  '每日服用一粒', '每日2次', 'vitamin D 20 mcg', '鱼油２克', '补充铁10\u200bmg'])
def test_validator_preserves_model_dose_wording_without_local_filtering(dose):
    from fitness.supplement_agent import validate_supplement_candidate
    plan = candidate()
    plan['items'][0]['reason'] = dose
    assert not validate_supplement_candidate(plan, Profile(), sources())


def test_validator_checks_references_and_current_product_coverage():
    from fitness.supplement_agent import validate_supplement_candidate
    profile = Profile()
    profile.supplements.current_products = ['我的复合片']
    plan = candidate()
    assert any(i.code == 'current_products' for i in validate_supplement_candidate(plan, profile, sources()))
    item = plan['items'][0]
    item.update(name='我的复合片', current_product='我的复合片', priority='needs_review', source_ids=[])
    assert not validate_supplement_candidate(plan, profile, sources())
    item['source_ids'] = ['evidence-pilot-magnesium-20260919']  # pending card
    assert any(i.code == 'source' for i in validate_supplement_candidate(plan, profile, sources()))
    item.update(source_ids=['mvp-supplements-006'], priority='consider')
    assert not validate_supplement_candidate(plan, profile, sources())


def test_no_library_allows_no_new_product_and_preserves_unrecognized_current_product():
    from fitness.supplement_agent import SupplementPlannerAgent
    profile = Profile()
    profile.supplements.current_products = ['某品牌复合片']
    plan = candidate()
    plan['items'][0].update(name='某品牌复合片', current_product='某品牌复合片',
                            priority='needs_review', source_ids=[])
    result = SupplementPlannerAgent(Settings(live_enabled=True), ScriptProvider([final(plan)])).plan_live(profile, None)
    assert result.status == 'draft_ready'
    assert result.trace['knowledge_status'] == 'not_requested'
    assert result.trace['source_snapshots'] == []


def test_model_can_recommend_without_cards_but_conditional_items_still_require_conditions():
    from fitness.supplement_agent import validate_supplement_candidate
    plan = candidate()
    assert not validate_supplement_candidate(plan, Profile(), {})
    plan['items'][0]['conditions'] = []
    assert {i.code for i in validate_supplement_candidate(plan, Profile(), {})} == {'conditions'}


def test_runtime_repairs_fabricated_source():
    from fitness.supplement_agent import SupplementPlannerAgent
    bad = deepcopy(candidate())
    bad['items'][0]['source_ids'] = ['invented']
    result = SupplementPlannerAgent(Settings(live_enabled=True),
        ScriptProvider([final(bad), final(candidate())])).plan_live(Profile(), knowledge())
    assert result.status == 'draft_ready'
    assert result.trace['revisions'] == 1


@pytest.mark.parametrize('claim', ['你缺乏维生素D，必须补充', '你的疲劳证明缺铁',
                                   'You have vitamin D deficiency'])
def test_validator_does_not_filter_model_medical_wording(claim):
    from fitness.supplement_agent import validate_supplement_candidate
    plan = candidate()
    plan['items'][0]['reason'] = claim
    assert not validate_supplement_candidate(plan, Profile(), sources())


def test_existing_label_can_include_strength_without_turning_into_dosing_instruction():
    from fitness.supplement_agent import validate_supplement_candidate
    profile = Profile()
    profile.supplements.current_products = ['某品牌鱼油1000mg']
    plan = candidate()
    plan['items'][0].update(name='某品牌鱼油1000mg', current_product='某品牌鱼油1000mg',
                            priority='needs_review', source_ids=[])
    assert not validate_supplement_candidate(plan, profile, {})


@pytest.mark.parametrize('health_status,medication_status', [
    ('unknown', 'unknown'), ('has_conditions', 'taking'), ('none_known_self_reported', 'none_known_self_reported'),
])
@pytest.mark.parametrize('priority', ['consider', 'conditional', 'not_needed', 'needs_review'])
def test_model_assessment_is_not_blocked_by_local_health_or_memory_rules(health_status, medication_status, priority):
    from fitness.supplement_agent import SupplementPlannerAgent
    profile = Profile()
    profile.health.exercise_limiting_conditions_status = health_status
    profile.health.medications_status = medication_status
    plan = candidate()
    plan['summary'] = '优先正餐和每周4次力量训练；正餐蛋白质约150g。'
    plan['items'][0].update(priority=priority, conditions=['结合饮食情况评估'])
    provider = ScriptProvider([final(plan)])
    result = SupplementPlannerAgent(Settings(), provider).plan_live(profile, knowledge(),
        personal_memory={'entries': [{'category': 'restriction', 'text': '先核实相关限制'}]})
    assert result.status == 'draft_ready'
    assert result.candidate == plan
    assert result.trace['revisions'] == 0
    assert len(provider.messages) == 1


def service(tmp_path, profile_data, replies):
    store = Store(tmp_path / 'isolated.sqlite3')
    store.save_profile(Profile.model_validate(profile_data).model_dump(mode='json'), 0)
    planner = DailyPlanningService(store, Settings(live_enabled=True), provider=ScriptProvider(replies))
    planner.supplements.knowledge = knowledge()
    return planner


def test_long_term_saves_supplements_and_trusted_source_snapshot(tmp_path, profile_data):
    plan = candidate()
    plan['items'][0]['source_ids'] = ['mvp-supplements-006']
    planner = service(tmp_path, profile_data,
        [final(free_cycle()), final(food_candidate()), search_reply('维生素D'), final(plan)])
    saved = planner.create_long_term(date(2026, 10, 22), mode='live')
    assert saved['data']['supplements'] == plan
    assert saved['data']['supplement_sources'][0]['id'] == 'mvp-supplements-006'
    assert saved['trace']['supplement_provider']['status'] == 'ok'
    assert planner.confirm_long_term(saved['id'])['data']['supplements'] == plan


@pytest.mark.parametrize('reply', [ProviderError('timeout'), final(status='needs_input', questions=['产品成分是什么？'])])
def test_supplement_failure_does_not_save_partial_plan(tmp_path, profile_data, reply):
    planner = service(tmp_path, profile_data, [final(free_cycle()), final(food_candidate()), reply])
    old = planner.create_long_term(date(2026, 10, 21))
    with pytest.raises(PlanningRunError):
        planner.create_long_term(date(2026, 10, 22), mode='live')
    assert [p['id'] for p in planner.repo.long_terms()] == [old['id']]


def test_profile_change_during_supplement_run_prevents_stale_save(tmp_path, profile_data):
    from fitness.storage import Conflict
    planner = service(tmp_path, profile_data, [final(free_cycle()), final(food_candidate()), final(candidate())])
    original = planner.supplements.provider.complete

    def complete(messages, *args, **kwargs):
        if '你是补剂规划 Agent' in messages[0]['content']:
            row = planner.store.profile()
            planner.store.save_profile(row['data'], row['version'])
        return original(messages, *args, **kwargs)

    planner.supplements.provider.complete = complete
    with pytest.raises(Conflict):
        planner.create_long_term(date(2026, 10, 22), mode='live')
    assert planner.repo.long_terms() == []


def test_long_term_persists_model_prose_verbatim_without_content_filtering(tmp_path, profile_data):
    plan = candidate()
    plan['summary'] = '正餐蛋白质目标150g、每周4次力量训练，补剂按饮食情况评估。'
    plan['items'][0]['reason'] = '模型给出的原始评估，数字示例2000 IU。'
    plan['items'][0]['priority'] = 'consider'
    planner = service(tmp_path, profile_data, [final(free_cycle()), final(food_candidate()), final(plan)])
    saved = planner.create_long_term(date(2026, 10, 22), mode='live')
    assert saved['data']['supplements'] == plan
    assert saved['trace']['supplement_provider']['revisions'] == 0
    assert planner.confirm_long_term(saved['id'])['data']['supplements'] == plan
