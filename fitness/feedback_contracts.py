"""Model feedback is interpretation; sources remain user reports."""

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .models import Contract, FeedbackData


class SourceRef(Contract):
    feedback_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1, strict=True)


class MemoryEvidence(SourceRef):
    quote: str = Field(min_length=1, max_length=4000)


class MemoryEntry(Contract):
    key: str = Field(min_length=1, max_length=100)
    category: Literal['fact', 'preference', 'restriction', 'question', 'pattern']
    retention: Literal['temporary', 'long_term'] = 'temporary'
    text: str = Field(min_length=1, max_length=2000)
    sources: list[SourceRef] = Field(min_length=1, max_length=30)
    expires_on: date | None = None
    event_date: date | None = None
    evidence: list[MemoryEvidence] = Field(default_factory=list, max_length=30)
    supersedes: list[str] = Field(default_factory=list, max_length=30)
    confirmed_at: str | None = Field(default=None, max_length=100)


class MemoryDocument(Contract):
    entries: list[MemoryEntry] = Field(default_factory=list, max_length=300)


class ProfileFieldUpdate(Contract):
    path: Literal[
        'nutrition.primary_meal_source',
        'nutrition.food_budget.amount',
        'nutrition.food_budget.period',
        'nutrition.food_allergy_status',
        'nutrition.food_allergy_details',
        'nutrition.food_intolerances',
        'nutrition.other_dietary_restrictions',
        'nutrition.food_preferences',
        'nutrition.disliked_foods',
        'health.exercise_limiting_conditions_status',
        'health.exercise_limiting_conditions_details',
        'health.medications_status',
        'health.medications',
        'training.usual_training_time',
    ]
    value: str | int | float | None
    quote: str = Field(min_length=1, max_length=4000)


class PlanDecision(Contract):
    action: Literal['keep', 'adjust_next', 'propose_long_term', 'adjust_remaining']
    reason: str = Field(min_length=1, max_length=2000)
    conditions: str = Field(default='', max_length=4000)
    target_date: date | None = None


class EvidencedFacts(Contract):
    data: FeedbackData
    evidence: dict[str, str] = Field(default_factory=dict)


class FeedbackUnderstanding(Contract):
    reply: str = Field(min_length=1, max_length=6000)
    suggestions: list[str] = Field(default_factory=list, max_length=10)
    questions: list[str] = Field(default_factory=list, max_length=8)
    memory_updates: list[MemoryEntry] = Field(default_factory=list, max_length=30)
    profile_updates: list[ProfileFieldUpdate] = Field(default_factory=list, max_length=20)
    retire_keys: list[str] = Field(default_factory=list, max_length=30)
    restriction_resolutions: dict[str, str] = Field(default_factory=dict)
    decision: PlanDecision
    facts: EvidencedFacts | None = None


class FeedbackSubmit(Contract):
    text: str = Field(min_length=1, max_length=4000)
    date: date
    timing: Literal['review', 'remaining'] = 'review'
    parent_feedback_id: str | None = Field(default=None, max_length=100)
    request_key: str = Field(min_length=1, max_length=100)


class CriticalFactsConfirm(Contract):
    expected_revision: int = Field(ge=1, strict=True)
    training_completed: bool | None = Field(default=None, strict=True)
    diet_followed_plan: bool | None = Field(default=None, strict=True)

    @model_validator(mode='after')
    def nonempty(self):
        if self.training_completed is None and self.diet_followed_plan is None:
            raise ValueError('请明确选择训练或饮食执行状态。')
        return self


class PreferenceConfirm(Contract):
    expected_version: int = Field(ge=1, strict=True)
    action: Literal['confirm', 'retire']
