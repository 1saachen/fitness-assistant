import pytest
from pydantic import ValidationError


def test_unknown_body_fat_and_supplements_stay_unknown(profile_data):
    from fitness.models import Profile
    p = Profile.model_validate(profile_data)
    assert p.personal.body_fat_percent is None
    assert p.supplements.current_products is None
    assert p.supplements.budget.amount is None


@pytest.mark.parametrize("value", [-5, 101, float("nan")])
def test_impossible_body_fat_rejected(profile_data, value):
    from fitness.models import Profile
    profile_data["personal"]["body_fat_percent"] = value
    with pytest.raises(ValidationError):
        Profile.model_validate(profile_data)


def test_incomplete_profile_can_be_saved(profile_data):
    from fitness.models import Profile
    profile_data["training"]["session_duration_minutes"] = None
    assert Profile.model_validate(profile_data).training.session_duration_minutes is None


def test_feedback_does_not_invent_intake():
    from fitness.models import FeedbackData
    p = FeedbackData(date="2026-09-10", food_summary="学校食堂")
    assert p.intake_kcal is None
    assert p.sleep_date is None
    assert p.diet_followed_plan is None
    with pytest.raises(ValidationError):
        FeedbackData(date="2026-09-10", sleep_hours=25)


@pytest.mark.parametrize("value", [True, False, None])
def test_feedback_accepts_explicit_diet_adherence(value):
    from fitness.models import FeedbackData

    assert FeedbackData(date="2026-09-10", diet_followed_plan=value).diet_followed_plan is value


def test_unexpected_model_fields_are_rejected():
    from fitness.models import FeedbackData
    with pytest.raises(ValidationError):
        FeedbackData(date="2026-09-10", execute_sql="DROP TABLE profiles")


@pytest.fixture
def legacy_plan_data():
    return {
        "title": "Weekly plan",
        "summary": "Start gradually",
        "days": [
            {"day_index": day, "label": "Rest", "kind": "rest"} for day in range(7)
        ],
        "nutrition": {
            "approach": "Regular meals",
            "meal_options": [{"meal": "Lunch", "suggestions": ["Rice and vegetables"]}],
            "budget_note": "Within budget",
        },
    }


def test_knowledge_citation_retains_multiple_videos_and_issues():
    from fitness.models import KnowledgeCitation
    citation = KnowledgeCitation(
        id="training-1", title="Training basics", excerpt="Progress gradually",
        creator_name="Coach", collection="training",
        videos=[
            {"bvid": "BV1", "title": "First", "url": "https://example.com/1",
             "published_at": "2026-09-01"},
            {"title": "Second", "url": "https://example.com/2"},
        ],
        matched_issues=["training_frequency", "progression"],
    )
    assert [video.title for video in citation.videos] == ["First", "Second"]
    assert citation.videos[0].bvid == "BV1"
    assert citation.videos[0].published_at == "2026-09-01"
    assert citation.videos[1].bvid is None
    assert citation.videos[1].published_at is None
    assert citation.matched_issues == ["training_frequency", "progression"]


def test_legacy_plan_and_advice_default_new_contexts_to_empty(legacy_plan_data):
    from fitness.models import AdviceData, PlanData
    plan = PlanData.model_validate(legacy_plan_data)
    advice = AdviceData(summary="Keep going", suggestions=["Rest well"])
    assert plan.strategy_context == []
    assert plan.knowledge_context == []
    assert advice.knowledge_context == []


@pytest.mark.parametrize("count", [74, 100])
def test_plan_and_advice_accept_large_source_lists(legacy_plan_data, count):
    from fitness.models import AdviceData, PlanData
    source_ids = [f"source-{index}" for index in range(count)]
    assert PlanData(**legacy_plan_data, source_ids=source_ids).source_ids == source_ids
    advice = AdviceData(summary="Keep going", suggestions=["Rest well"], source_ids=source_ids)
    assert advice.source_ids == source_ids


@pytest.mark.parametrize("collection", ["training", "fat_loss", "supplements", "sleep_recovery"])
def test_supported_knowledge_collections(collection):
    from fitness.models import KnowledgeCitation
    citation = KnowledgeCitation(
        id="item", title="Title", excerpt="Excerpt", creator_name="Creator",
        collection=collection,
    )
    assert citation.collection == collection


def test_invalid_knowledge_collection_rejected():
    from fitness.models import KnowledgeCitation
    with pytest.raises(ValidationError):
        KnowledgeCitation(
            id="item", title="Title", excerpt="Excerpt", creator_name="Creator",
            collection="unsupported",
        )


def test_context_round_trip_and_independent_defaults(legacy_plan_data):
    from fitness.models import (
        AdviceData,
        KnowledgeCitation,
        KnowledgeVideo,
        PlanData,
        StrategySnapshot,
    )
    citation_data = {
        "id": "item", "title": "Title", "excerpt": "Excerpt", "creator_name": "Creator",
        "collection": "training",
    }
    first = KnowledgeCitation(**citation_data)
    second = KnowledgeCitation(**citation_data)
    first.matched_issues.append("progression")
    first.videos.append(KnowledgeVideo(title="Video", url="https://example.com"))
    assert second.matched_issues == []
    assert second.videos == []
    strategy = StrategySnapshot(id="strategy", title="Title", summary="Summary")
    strategy.action_rules.append("Train regularly")
    strategy.knowledge_item_ids.append("item")
    other_strategy = StrategySnapshot(id="other", title="Title", summary="Summary")
    assert other_strategy.action_rules == []
    assert other_strategy.knowledge_item_ids == []
    plan = PlanData(**legacy_plan_data)
    plan.strategy_context.append(strategy)
    plan.knowledge_context.append(second)
    other_plan = PlanData(**legacy_plan_data)
    assert other_plan.strategy_context == []
    assert other_plan.knowledge_context == []
    assert PlanData.model_validate(plan.model_dump()) == plan
    advice = AdviceData(summary="Summary", suggestions=["Rest"])
    advice.knowledge_context.append(second)
    assert AdviceData(summary="Summary", suggestions=["Rest"]).knowledge_context == []
    assert AdviceData.model_validate(advice.model_dump()) == advice


@pytest.mark.parametrize("model_name,field,limit", [
    ("KnowledgeCitation", "videos", 20),
    ("KnowledgeCitation", "matched_issues", 20),
    ("StrategySnapshot", "action_rules", 20),
    ("StrategySnapshot", "knowledge_item_ids", 100),
    ("PlanData", "strategy_context", 20),
    ("PlanData", "knowledge_context", 100),
    ("PlanData", "source_ids", 100),
    ("AdviceData", "knowledge_context", 100),
    ("AdviceData", "source_ids", 100),
])
def test_context_list_limits(legacy_plan_data, model_name, field, limit):
    from fitness import models
    citation = {
        "id": "item", "title": "Title", "excerpt": "Excerpt", "creator_name": "Creator",
        "collection": "training",
    }
    strategy = {"id": "strategy", "title": "Title", "summary": "Summary"}
    payload = {
        "KnowledgeCitation": citation,
        "StrategySnapshot": strategy,
        "PlanData": legacy_plan_data,
        "AdviceData": {"summary": "Summary", "suggestions": ["Rest"]},
    }[model_name].copy()
    value = {
        "videos": {"title": "Video", "url": "https://example.com"},
        "knowledge_context": citation,
        "strategy_context": strategy,
    }.get(field, "value")
    model = getattr(models, model_name)
    payload[field] = [value] * limit
    assert len(getattr(model.model_validate(payload), field)) == limit
    payload[field] = [value] * (limit + 1)
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model_name,payload", [
    ("KnowledgeVideo", {"title": "Video", "url": "https://example.com"}),
    ("KnowledgeCitation", {"id": "item", "title": "Title", "excerpt": "Excerpt",
                           "creator_name": "Creator", "collection": "training"}),
    ("StrategySnapshot", {"id": "strategy", "title": "Title", "summary": "Summary"}),
])
def test_new_contracts_reject_extra_fields(model_name, payload):
    from fitness import models
    with pytest.raises(ValidationError):
        getattr(models, model_name)(**payload, unexpected="value")


@pytest.mark.parametrize("length,accepted", [(500, True), (501, False)])
def test_knowledge_video_title_matches_source_limit(length, accepted):
    from fitness.models import KnowledgeVideo
    title = "V" * length
    if accepted:
        assert KnowledgeVideo(title=title, url="https://example.com").title == title
    else:
        with pytest.raises(ValidationError):
            KnowledgeVideo(title=title, url="https://example.com")


@pytest.mark.parametrize("length,accepted", [(300, True), (301, False)])
def test_knowledge_citation_title_matches_item_limit(length, accepted):
    from fitness.models import KnowledgeCitation
    payload = {
        "id": "item", "title": "K" * length, "excerpt": "Excerpt",
        "creator_name": "Creator", "collection": "training",
    }
    if accepted:
        assert KnowledgeCitation(**payload).title == payload["title"]
    else:
        with pytest.raises(ValidationError):
            KnowledgeCitation(**payload)
