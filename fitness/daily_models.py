"""Contracts for versioned long-term strategies and daily execution."""

from datetime import date

from pydantic import Field

from .models import Contract, Mode, Short, Text


class LongTermRequest(Contract):
    start_date: date | None = None
    cycle_labels: list[Short] | None = Field(default=None, min_length=1, max_length=14)
    mode: Mode = 'demo'
    conditions: Text | None = None
    expected_snapshot_token: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class DailyRequest(Contract):
    date: date
    conditions: Text | None = None
    mode: Mode = 'demo'
    expected_snapshot_token: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class MealCompleteRequest(Contract):
    meal: Short
    expected_revision: int = Field(ge=1)
