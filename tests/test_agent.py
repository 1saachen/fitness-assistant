from datetime import date

from fitness import planning
from fitness.agent import DemoAgent
from fitness.knowledge_context import KnowledgeContextResult, RetrievalIssue
from fitness.models import FeedbackData, KnowledgeCitation, Profile, StrategySnapshot


def test_feedback_parser_records_only_explicit_diet_adherence():
    agent = DemoAgent()

    assert agent.parse_feedback("饮食按计划执行，吃食堂", date(2026, 10, 1)).diet_followed_plan is True
    assert agent.parse_feedback("今天没按计划吃，点了外卖", date(2026, 10, 2)).diet_followed_plan is False
    assert agent.parse_feedback("今天吃食堂", date(2026, 10, 3)).diet_followed_plan is None


def test_parser_does_not_turn_negated_or_hypothetical_phrases_into_facts():
    agent = DemoAgent()
    for text in ('未完成训练', '没有完成训练', '今天还没练完'):
        assert agent.parse_feedback(text, date(2026, 10, 11)).training_completed is False
    for text in ('我希望今晚睡了5小时', '昨晚没睡了5小时', '计划明天体重80公斤'):
        parsed = agent.parse_feedback(text, date(2026, 10, 11))
        assert parsed.sleep_hours is None
        assert parsed.weight_kg is None


def citation(index, *issues, excerpt=None, collection="training"):
    return KnowledgeCitation(
        id=f"knowledge-{index:03d}",
        title=f"Knowledge {index}",
        excerpt=excerpt or f"Creator claim {index}",
        creator_name=f"Creator {index}",
        collection=collection,
        matched_issues=list(issues),
    )


def issue(index, label=None):
    return RetrievalIssue(
        id=f"issue-{index}",
        label=label or f"Issue {index}",
        terms=(f"term-{index}",),
        collections=("training",),
        knowledge_item_ids=(f"knowledge-{index:03d}",),
    )


def test_plan_keeps_complete_strategy_and_citation_snapshots(profile_data):
    profile = Profile.model_validate(profile_data)
    strategies = tuple(
        StrategySnapshot(
            id=f"strategy-{index}",
            title=f"Strategy {index}",
            summary=f"Summary {index}",
            action_rules=[f"Rule {index}"],
            knowledge_item_ids=[f"knowledge-{index:03d}"],
        )
        for index in range(7)
    )
    citations = tuple(citation(index) for index in range(74))
    context = KnowledgeContextResult(strategies=strategies, citations=citations)

    plan = DemoAgent().generate_plan(profile, date(2026, 9, 21), context)

    assert plan.strategy_context == list(strategies)
    assert plan.knowledge_context == list(citations)
    assert plan.source_ids == [item.id for item in citations]
    assert all(strategy.title not in plan.summary for strategy in strategies)
    assert "共7个模块" not in plan.summary


def test_plan_bounds_strategy_summary_without_dropping_snapshots(profile_data):
    profile = Profile.model_validate(profile_data)
    strategies = tuple(
        StrategySnapshot(
            id=f"long-strategy-{index}",
            title=f"{index:02d}-" + chr(65 + index) * 197,
            summary="S" * 300,
        )
        for index in range(20)
    )

    plan = DemoAgent().generate_plan(
        profile,
        date(2026, 9, 21),
        KnowledgeContextResult(strategies=strategies),
    )

    assert plan.strategy_context == list(strategies)
    assert len(plan.summary) <= 2000
    assert all(strategy.title not in plan.summary for strategy in strategies)


def test_creator_claims_do_not_change_rule_based_exercise_prescriptions(profile_data):
    profile = Profile.model_validate(profile_data)
    agent = DemoAgent()
    baseline = agent.generate_plan(profile, date(2026, 9, 21))
    context = KnowledgeContextResult(
        strategies=(
            StrategySnapshot(
                id="creator-program",
                title="Creator program",
                summary="Train six times per week",
                action_rules=["Use five sets of twenty repetitions for every exercise"],
                knowledge_item_ids=["knowledge-000"],
            ),
        ),
        citations=(citation(0, excerpt="Train six times weekly with five sets of twenty repetitions"),),
    )

    enriched = agent.generate_plan(profile, date(2026, 9, 21), context)

    assert enriched.days == baseline.days
    assert sum(day.kind == "training" for day in enriched.days) == 3


def test_advice_preserves_rule_safety_suggestions_and_adds_one_bounded_reference_per_issue(
    profile_data,
):
    profile = Profile.model_validate(profile_data)
    feedback = FeedbackData(date="2026-09-21", sleep_hours=5, fatigue="疲惫")
    issues = (
        RetrievalIssue(
            id="short_sleep",
            label="睡眠不足",
            terms=("睡眠",),
            collections=("sleep_recovery",),
            knowledge_item_ids=("knowledge-000",),
        ),
        RetrievalIssue(
            id="training_fatigue",
            label="训练疲劳",
            terms=("疲劳",),
            collections=("training",),
            knowledge_item_ids=("knowledge-000", "knowledge-001"),
        ),
        RetrievalIssue(
            id="supplement_question",
            label="补剂问题",
            terms=("肌酸",),
            collections=("supplements",),
            knowledge_item_ids=("knowledge-002",),
        ),
    )
    citations = (
        citation(0, "short_sleep", "training_fatigue", excerpt="先改善睡眠与恢复"),
        citation(1, "training_fatigue", excerpt="另一条疲劳观点"),
        citation(
            2,
            "supplement_question",
            excerpt="作者建议每天服用特定剂量并声称可以治疗疲劳" * 10,
            collection="supplements",
        ),
    )
    context = KnowledgeContextResult(citations=citations, issues=issues)

    advice = DemoAgent().advice(profile, feedback, [], context)

    assert advice.suggestions[:3] == [
        "保持训练动作质量和逐步增加重量",
        "优先保证规律睡眠与蛋白质来源",
        "今天感到疲劳时降低训练量，观察连续几天趋势",
    ]
    references = advice.suggestions[3:]
    assert len(references) == len(issues)
    assert all(text.startswith("知识库参考（视频观点）：") for text in references)
    assert all("仅作创作者参考" in text for text in references)
    assert all("不作为个体补剂剂量或医疗结论" in text for text in references)
    assert sum("训练疲劳" in text for text in references) == 1
    assert all(len(text) <= 200 for text in references)
    assert advice.knowledge_context == list(citations)
    assert advice.source_ids == [item.id for item in citations]


def test_advice_caps_suggestions_with_deterministic_rule_first_issue_order(profile_data):
    profile = Profile.model_validate(profile_data)
    feedback = FeedbackData(date="2026-09-21")
    issues = tuple(issue(index) for index in range(7))
    citations = tuple(citation(index, f"issue-{index}") for index in range(7))

    advice = DemoAgent().advice(
        profile,
        feedback,
        [],
        KnowledgeContextResult(citations=citations, issues=issues),
    )

    assert len(advice.suggestions) == 8
    assert advice.suggestions[:2] == [
        "保持训练动作质量和逐步增加重量",
        "优先保证规律睡眠与蛋白质来源",
    ]
    assert [label for label in (f"Issue {index}" for index in range(7)) if any(
        label in suggestion for suggestion in advice.suggestions
    )] == [f"Issue {index}" for index in range(6)]


def test_advice_deduplicates_issue_ids_without_displacing_later_issues(profile_data):
    profile = Profile.model_validate(profile_data)
    feedback = FeedbackData(date="2026-09-21")
    duplicate = RetrievalIssue(
        id="issue-0",
        label="Duplicate issue zero",
        terms=("duplicate",),
        collections=("training",),
        knowledge_item_ids=("knowledge-000",),
    )
    issues = (issue(0), duplicate, *(issue(index) for index in range(1, 6)))
    citations = tuple(citation(index, f"issue-{index}") for index in range(6))

    advice = DemoAgent().advice(
        profile,
        feedback,
        [],
        KnowledgeContextResult(citations=citations, issues=issues),
    )

    references = advice.suggestions[2:]
    assert len(references) == 6
    assert sum("Issue 0" in reference for reference in references) == 1
    assert not any("Duplicate issue zero" in reference for reference in references)
    assert any("Issue 5" in reference for reference in references)


def test_empty_or_unavailable_context_keeps_core_rules_available(profile_data):
    profile = Profile.model_validate(profile_data)
    feedback = FeedbackData(date="2026-09-21", fatigue="疲惫")
    agent = DemoAgent()

    legacy_plan = agent.generate_plan(profile, date(2026, 9, 21))
    unavailable_plan = agent.generate_plan(
        profile,
        date(2026, 9, 21),
        KnowledgeContextResult(status="unavailable"),
    )
    legacy_advice = agent.advice(profile, feedback, [])
    unavailable_advice = agent.advice(
        profile,
        feedback,
        [],
        KnowledgeContextResult(status="unavailable"),
    )

    assert legacy_plan.days == unavailable_plan.days
    assert legacy_plan.strategy_context == unavailable_plan.strategy_context == []
    assert legacy_plan.knowledge_context == unavailable_plan.knowledge_context == []
    assert legacy_advice.suggestions == unavailable_advice.suggestions
    assert legacy_advice.knowledge_context == unavailable_advice.knowledge_context == []


def test_unavailable_context_still_preserves_nonempty_snapshots(profile_data):
    profile = Profile.model_validate(profile_data)
    strategy = StrategySnapshot(
        id="strategy-unavailable",
        title="Unavailable strategy",
        summary="Context status does not erase snapshots",
    )
    knowledge = citation(0, "issue-0")
    context = KnowledgeContextResult(
        status="unavailable",
        strategies=(strategy,),
        citations=(knowledge,),
        issues=(issue(0),),
    )
    agent = DemoAgent()

    plan = agent.generate_plan(profile, date(2026, 9, 21), context)
    advice = agent.advice(profile, FeedbackData(date="2026-09-21"), [], context)

    assert plan.strategy_context == [strategy]
    assert plan.knowledge_context == [knowledge]
    assert plan.source_ids == [knowledge.id]
    assert advice.knowledge_context == [knowledge]
    assert advice.source_ids == [knowledge.id]


def test_oversized_context_degrades_as_a_whole_without_blocking_core_rules(profile_data):
    profile = Profile.model_validate(profile_data)
    feedback = FeedbackData(date="2026-09-21", fatigue="疲惫")
    citations = tuple(citation(index, "issue-0") for index in range(101))
    citation_context = KnowledgeContextResult(
        citations=citations,
        issues=(
            RetrievalIssue(
                id="issue-0",
                label="Oversized issue",
                terms=("oversized",),
                collections=("training",),
                knowledge_item_ids=(citations[0].id,),
            ),
        ),
    )
    agent = DemoAgent()

    plan = agent.generate_plan(profile, date(2026, 9, 21), citation_context)
    advice = agent.advice(profile, feedback, [], citation_context)

    assert plan.days
    assert plan.strategy_context == []
    assert plan.knowledge_context == []
    assert plan.source_ids == []
    assert advice.suggestions == [
        "保持训练动作质量和逐步增加重量",
        "优先保证规律睡眠与蛋白质来源",
        "今天感到疲劳时降低训练量，观察连续几天趋势",
    ]
    assert advice.knowledge_context == []
    assert advice.source_ids == []

    too_many_strategies = tuple(
        StrategySnapshot(id=f"strategy-{index}", title=f"Strategy {index}", summary="Summary")
        for index in range(21)
    )
    strategy_plan = agent.generate_plan(
        profile,
        date(2026, 9, 21),
        KnowledgeContextResult(strategies=too_many_strategies, citations=(citation(0),)),
    )
    assert strategy_plan.days
    assert strategy_plan.strategy_context == []
    assert strategy_plan.knowledge_context == []
    assert strategy_plan.source_ids == []


def test_context_persistence_status_distinguishes_capacity_from_valid_empty_context():
    strategies_at_limit = tuple(
        StrategySnapshot(id=f"strategy-{index}", title=f"Strategy {index}", summary="Summary")
        for index in range(20)
    )
    citations_at_limit = tuple(citation(index) for index in range(100))

    assert planning.context_persistence_status(KnowledgeContextResult()) == "ok"
    assert planning.context_persistence_status(
        KnowledgeContextResult(strategies=strategies_at_limit, citations=citations_at_limit)
    ) == "ok"
    assert planning.context_persistence_status(
        KnowledgeContextResult(
            strategies=(
                *strategies_at_limit,
                StrategySnapshot(id="strategy-20", title="Strategy 20", summary="Summary"),
            )
        )
    ) == "capacity_exceeded"
    assert planning.context_persistence_status(
        KnowledgeContextResult(citations=(*citations_at_limit, citation(100)))
    ) == "capacity_exceeded"
    assert planning.context_persistence_status(
        KnowledgeContextResult(status="unavailable")
    ) == "unavailable"
    assert planning.context_persistence_status(
        KnowledgeContextResult(
            status="unavailable",
            strategies=(
                *strategies_at_limit,
                StrategySnapshot(id="strategy-20", title="Strategy 20", summary="Summary"),
            ),
        )
    ) == "unavailable"
    assert planning.context_persistence_status(
        KnowledgeContextResult(
            status="unavailable",
            citations=(*citations_at_limit, citation(100)),
        )
    ) == "unavailable"
