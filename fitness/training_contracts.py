"""Training candidates express proposals, never execution facts."""

from datetime import date as Date
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .models import Contract, Exercise, Profile, Short, Text


class StrictExercise(Exercise):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class TrainingStep(Contract):
    label: Short = Field(min_length=1)
    kind: Literal['training', 'rest']
    exercises: list[StrictExercise] = Field(default_factory=list, max_length=8)
    estimated_minutes: int = Field(ge=0, le=180, strict=True)

    @model_validator(mode='after')
    def valid_content(self):
        if self.kind == 'rest' and (self.exercises or self.estimated_minutes):
            raise ValueError('休息步骤不能包含训练动作或时长')
        if self.kind == 'training' and (not self.exercises or not self.estimated_minutes):
            raise ValueError('训练步骤需要动作和时长')
        return self


class Candidate(Contract):
    summary: Text = Field(min_length=1)
    assumptions: list[Text] = Field(default_factory=list, max_length=10)
    source_ids: list[Short] = Field(default_factory=list, max_length=20)
    questions: list[Text] = Field(default_factory=list, max_length=10)


class CycleCandidate(Candidate):
    cycle: list[TrainingStep] = Field(min_length=1, max_length=14)


class DayCandidate(Candidate):
    action: Literal['train', 'rest', 'defer', 'skip', 'pause']
    training: TrainingStep
    reasons: list[Text] = Field(default_factory=list, max_length=10)
    scheduled_time: Short | None = None
    load_description: Text = ''

    @model_validator(mode='after')
    def valid_action(self):
        if (self.action == 'train') != (self.training.kind == 'training'):
            raise ValueError('训练状态和动作不一致')
        return self


class TrainingTask(Contract):
    kind: Literal['cycle', 'day']
    date: Date
    profile: Profile
    profile_version: int
    cycle: list[dict] = Field(default_factory=list)
    cycle_index: int = 0
    long_term: dict | None = None
    history: list[dict] = Field(default_factory=list)
    personal_memory: dict = Field(default_factory=dict)
    state: dict = Field(default_factory=dict)
    conditions: str = Field(default='', max_length=10000)
    cycle_labels: list[Short] | None = None
    time_limit_minutes: int | None = Field(default=None, ge=1, le=180)
    completed_training: dict | None = None
    snapshot_token: str = ''
