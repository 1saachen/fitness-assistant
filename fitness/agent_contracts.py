"""Bounded agent results; candidates never imply confirmed writes."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field

from .models import Contract


class RunLimits(Contract):
    max_calls: int = Field(default=12, ge=1, le=30, strict=True)
    max_tools: int = Field(default=20, ge=1, le=60, strict=True)
    max_revisions: int = Field(default=2, ge=0, le=5, strict=True)
    timeout_seconds: float = Field(default=180, gt=0, le=600)
    max_output_tokens: int = Field(default=4096, ge=256, le=16384, strict=True)


@dataclass
class ValidationIssue:
    path: str
    code: str
    message: str


@dataclass
class RunResult:
    run_id: str
    status: Literal['draft_ready', 'needs_input', 'failed']
    candidate: dict | None = None
    questions: list[str] = field(default_factory=list)
    reason_code: str | None = None
    trace: dict = field(default_factory=dict)


class PlanningRunError(Exception):
    def __init__(self, result: RunResult, snapshot_token: str):
        self.result = result
        self.snapshot_token = snapshot_token
        super().__init__(result.reason_code or result.status)
