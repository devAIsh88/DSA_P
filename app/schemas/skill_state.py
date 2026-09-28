"""Allowlisted learner-facing view of derived skill state."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SkillStateResponse(BaseModel):
    """Projection fields useful to the learner, excluding evidence provenance."""

    model_config = ConfigDict(from_attributes=True)

    skill_id: int
    mastery_probability: float
    mastery_uncertainty: float
    attempt_count: int
    successful_attempt_count: int
    independent_solve_count: int
    hint_dependent_count: int
    hint_count_total: int
    average_hint_level: float | None
    average_duration_ms: float | None
    recent_error_types: list[str] | None
    last_attempt_at: datetime | None
    last_successful_at: datetime | None
    retention_signal: float | None
    model_version: str
    param_version: str
