"""Model feedback is interpretation; sources remain user reports."""

from datetime import date
from typing import Literal

from pydantic import Field

from .models import Contract, FeedbackData


class SourceRef(Contract):
    feedback_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1, strict=True)


class MemoryEntry(Contract):
    key: str = Field(min_length=1, max_length=100)
    category: Literal['fact', 'preference', 'restriction', 'question', 'pattern']
    text: str = Field(min_length=1, max_length=2000)
    sources: list[SourceRef] = Field(min_length=1, max_length=30)
    expires_on: date | None = None


class MemoryDocument(Contract):
    entries: list[MemoryEntry] = Field(default_factory=list, max_length=300)


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
