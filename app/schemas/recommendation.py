"""Provider-neutral deterministic recommendation inputs and public contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.attempt import AttemptOutcome, AttemptStatus


class RecommendationAction(str, Enum):
    NEXT_PROBLEM = "NEXT_PROBLEM"
    REVISE_CONCEPT = "REVISE_CONCEPT"
    RETRY_SIMILAR_PROBLEM = "RETRY_SIMILAR_PROBLEM"
    INCREASE_DIFFICULTY = "INCREASE_DIFFICULTY"
    DECREASE_DIFFICULTY = "DECREASE_DIFFICULTY"


class RecommendationReasonCode(str, Enum):
    COLD_START = "COLD_START"
    UNPRACTICED_SKILL = "UNPRACTICED_SKILL"
    NEW_PROBLEM = "NEW_PROBLEM"
    UNATTRIBUTED_CATALOGUE = "UNATTRIBUTED_CATALOGUE"
    SCHEDULED_REVIEW_DUE = "SCHEDULED_REVIEW_DUE"
    EVALUATED_FAILURE_RETRY = "EVALUATED_FAILURE_RETRY"
    ASSISTED_SUCCESS_PRACTICE = "ASSISTED_SUCCESS_PRACTICE"
    ABANDONED_PROBLEM_RETRY = "ABANDONED_PROBLEM_RETRY"
    DECLARED_GIVE_UP_RETRY = "DECLARED_GIVE_UP_RETRY"
    INDEPENDENT_PRACTICE_PENDING = "INDEPENDENT_PRACTICE_PENDING"
    INDEPENDENT_SUCCESS_PROGRESSION = "INDEPENDENT_SUCCESS_PROGRESSION"
    CONSECUTIVE_EVALUATED_FAILURES = "CONSECUTIVE_EVALUATED_FAILURES"
    OBSERVED_LOW_MASTERY = "OBSERVED_LOW_MASTERY"


class RecommendationUnavailableReason(str, Enum):
    EMPTY_CATALOGUE = "EMPTY_CATALOGUE"
    NO_ELIGIBLE_PROBLEM = "NO_ELIGIBLE_PROBLEM"
    CATALOGUE_EXHAUSTED = "CATALOGUE_EXHAUSTED"


class RecommendationMappingStatus(str, Enum):
    SINGLE_SKILL = "single_skill"
    UNMAPPED = "unmapped"
    MULTIPLE_SKILLS = "multiple_skills_require_policy"
    NONUNIT_WEIGHT = "nonunit_weight_requires_policy"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RecommendationCandidate(_FrozenModel):
    problem_id: int = Field(gt=0)
    difficulty: str
    skill_id: int | None = Field(default=None, gt=0)
    mapping_status: RecommendationMappingStatus
    target_track: str | None = None

    @model_validator(mode="after")
    def validate_mapping(self) -> RecommendationCandidate:
        if (self.mapping_status == RecommendationMappingStatus.SINGLE_SKILL) != (self.skill_id is not None):
            raise ValueError("Only a single unit-weight mapping may supply a skill")
        return self


class TerminalEvidence(_FrozenModel):
    """Validated historical facts; binary eligibility is supplied by evidence loading."""

    event_id: int = Field(gt=0)
    attempt_id: int = Field(gt=0)
    problem_id: int = Field(gt=0)
    skill_id: int | None = Field(default=None, gt=0)
    occurred_at: datetime
    status: AttemptStatus
    outcome: AttemptOutcome | None = None
    final_status: str | None = None
    binary_correct: Annotated[int, Field(strict=True, ge=0, le=1)] | None = None
    max_hint_level: int = Field(default=0, ge=0, le=6)
    hint_requests: int = Field(default=0, ge=0)
    has_hint_action: bool = False

    @field_validator("occurred_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_terminal(self) -> TerminalEvidence:
        if self.status == AttemptStatus.ACTIVE:
            raise ValueError("Terminal evidence cannot describe an ACTIVE Attempt")
        if self.status == AttemptStatus.ABANDONED:
            if self.outcome is not None or self.binary_correct is not None:
                raise ValueError("Abandonment is not a binary outcome")
        elif self.outcome is None:
            raise ValueError("A completed Attempt requires an outcome")
        if self.binary_correct is not None:
            expected = 1 if self.outcome == AttemptOutcome.SOLVED else 0
            if (self.skill_id is None or self.binary_correct != expected or self.has_hint_action
                    or self.max_hint_level or self.hint_requests):
                raise ValueError("Binary evidence must be supported and independent")
        return self


class RecommendationSkillState(_FrozenModel):
    skill_id: int = Field(gt=0)
    mastery_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    attempt_count: int = Field(ge=0)
    successful_attempt_count: int = Field(ge=0)
    hint_dependent_count: int = Field(ge=0)
    last_attempt_at: datetime | None = None

    @field_validator("last_attempt_at")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_counts(self) -> RecommendationSkillState:
        if not self.hint_dependent_count <= self.successful_attempt_count <= self.attempt_count:
            raise ValueError("Skill reporting counts are inconsistent")
        return self


class RecommendationContext(_FrozenModel):
    evaluated_at: datetime
    candidates: tuple[RecommendationCandidate, ...]
    attempts: tuple[TerminalEvidence, ...]
    skills: tuple[RecommendationSkillState, ...]
    active_attempt_ids: tuple[int, ...] = ()

    @field_validator("evaluated_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @model_validator(mode="after")
    def unique_inputs(self) -> RecommendationContext:
        if len({item.problem_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("Duplicate catalogue Problem")
        if len({item.skill_id for item in self.skills}) != len(self.skills):
            raise ValueError("Duplicate SkillState")
        if len({item.event_id for item in self.attempts}) != len(self.attempts):
            raise ValueError("Duplicate historical event ID")
        return self


class RecommendationDecision(_FrozenModel):
    action_type: RecommendationAction
    problem_id: int = Field(gt=0)
    skill_id: int | None = Field(default=None, gt=0)
    reason_codes: tuple[RecommendationReasonCode, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def targeted_skill(self) -> RecommendationDecision:
        if (self.action_type != RecommendationAction.NEXT_PROBLEM and self.skill_id is None
                and not (self.action_type == RecommendationAction.RETRY_SIMILAR_PROBLEM
                         and RecommendationReasonCode.ABANDONED_PROBLEM_RETRY in self.reason_codes)):
            raise ValueError("A targeted recommendation requires a supported skill")
        return self


class RecommendationResult(_FrozenModel):
    decision: RecommendationDecision | None = None
    unavailable_reason: RecommendationUnavailableReason | None = None
    reevaluate_at: datetime | None = None

    @model_validator(mode="after")
    def one_outcome(self) -> RecommendationResult:
        if (self.decision is None) == (self.unavailable_reason is None):
            raise ValueError("Exactly one decision or empty reason is required")
        return self


class RecommendationPolicyConfig(_FrozenModel):
    """Versioned, uncalibrated MVP heuristics; not a mastery model."""

    version: str = Field(default="adaptive-rules-v1", min_length=1, max_length=60)
    difficulty_order: tuple[str, ...] = ("Easy", "Medium", "Hard")
    weak_min_observations: int = Field(default=2, ge=1)
    weak_mastery_threshold: float = Field(default=0.50, ge=0, le=1, allow_inf_nan=False)
    review_min_independent_successes: int = Field(default=1, ge=1)
    review_mastery_threshold: float = Field(default=0.60, ge=0, le=1, allow_inf_nan=False)
    review_interval_days: int = Field(default=7, ge=1)
    promotion_mastery_threshold: float = Field(default=0.70, ge=0, le=1, allow_inf_nan=False)
    promotion_consecutive_solves: int = Field(default=2, ge=2)
    demotion_consecutive_struggles: int = Field(default=2, ge=2)
    demotion_statuses: tuple[str, ...] = ("WRONG_ANSWER", "TIME_LIMIT_EXCEEDED", "MEMORY_LIMIT_EXCEEDED")
    assisted_success_hint_level: int = Field(default=4, ge=1, le=6)
    avoid_immediate_repetition: bool = True
    allow_unattributed_catalogue: bool = True
    target_track: str | None = None

    @model_validator(mode="after")
    def validate_order(self) -> RecommendationPolicyConfig:
        normalized = [value.strip().casefold() for value in self.difficulty_order]
        if not normalized or any(not value for value in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("Difficulty order must contain unique nonempty levels")
        allowed = {"WRONG_ANSWER", "TIME_LIMIT_EXCEEDED", "MEMORY_LIMIT_EXCEEDED"}
        if not self.demotion_statuses or any(value not in allowed for value in self.demotion_statuses):
            raise ValueError("Demotion statuses must remain authoritative evaluated failures")
        if self.target_track is not None and not self.target_track.strip():
            raise ValueError("Target filter cannot be empty")
        return self


class RecommendationResponse(BaseModel):
    """Public selection only; internal snapshots and evidence do not escape."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    action_type: RecommendationAction
    problem_id: int
    skill_id: int | None
    policy_version: str
    reason_codes: tuple[RecommendationReasonCode, ...]
    created_at: datetime


class NextRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: RecommendationResponse | None
    unavailable_reason: RecommendationUnavailableReason | None

    @model_validator(mode="after")
    def one_outcome(self) -> NextRecommendationResponse:
        if (self.recommendation is None) == (self.unavailable_reason is None):
            raise ValueError("Exactly one recommendation or empty reason is required")
        return self
