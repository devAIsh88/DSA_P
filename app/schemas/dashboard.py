"""Learner-safe read facades for the local single-learner prototype."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.attempt import AttemptResponse
from app.schemas.recommendation import RecommendationResponse
from app.schemas.skill_state import SkillStateResponse


class SkillProgressResponse(SkillStateResponse):
    """Existing derived reporting with public concept labels, never private provenance."""

    skill_name: str
    skill_description: str | None


class LearnerStateResponse(BaseModel):
    """Read current identity/activity without generating or rebuilding any state."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)
    active_attempts: list[AttemptResponse]
    skills: list[SkillProgressResponse]


class DashboardSummaryResponse(BaseModel):
    """Explicit global activity counts and separately scoped supported-skill reporting."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)
    catalogue_problem_count: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    completed_attempt_count: int = Field(ge=0)
    solved_attempt_count: int = Field(ge=0)
    abandoned_attempt_count: int = Field(ge=0)
    unique_solved_problem_count: int = Field(ge=0)
    active_attempts: list[AttemptResponse]
    recent_attempts: list[AttemptResponse]
    skills: list[SkillProgressResponse]
    hint_request_count: int = Field(ge=0)
    hint_delivery_count: int = Field(ge=0)
    independent_solve_count: int = Field(ge=0)
    hint_dependent_solve_count: int = Field(ge=0)
    successful_supported_attempt_count: int = Field(ge=0)
    independent_solve_share: float | None = Field(ge=0, le=1)
    hint_dependency_share: float | None = Field(ge=0, le=1)
    existing_recommendation: RecommendationResponse | None
