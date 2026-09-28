"""Request and learner-facing response contracts for problem Attempts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AttemptStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class AttemptOutcome(str, Enum):
    SOLVED = "SOLVED"
    GAVE_UP = "GAVE_UP"


class AttemptStart(BaseModel):
    user_id: int = Field(gt=0)
    problem_id: int = Field(gt=0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ReasoningCreate(BaseModel):
    reasoning_text: str = Field(min_length=1, max_length=20000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class AttemptComplete(BaseModel):
    outcome: AttemptOutcome
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class AttemptAbandon(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class AttemptResponse(BaseModel):
    """Attempt metadata; detailed reasoning remains in its historical event."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    problem_id: int
    status: AttemptStatus
    outcome: AttemptOutcome | None
    started_at: datetime
    completed_at: datetime | None
    total_duration_ms: int | None
