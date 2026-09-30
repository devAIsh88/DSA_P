"""Typed event categories and deliberately narrow learner-facing views."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class LearningEventType(str, Enum):
    ATTEMPT_STARTED = "ATTEMPT_STARTED"
    REASONING_RECORDED = "REASONING_RECORDED"
    SUBMISSION_EVALUATED = "SUBMISSION_EVALUATED"
    HINT_REQUESTED = "HINT_REQUESTED"
    HINT_DELIVERED = "HINT_DELIVERED"
    ATTEMPT_COMPLETED = "ATTEMPT_COMPLETED"
    UNDERSTANDING_CHECK = "UNDERSTANDING_CHECK"
    TUTOR_DIAGNOSIS_GENERATED = "TUTOR_DIAGNOSIS_GENERATED"
    TUTOR_REASONING_ANALYSIS_GENERATED = "TUTOR_REASONING_ANALYSIS_GENERATED"
    POST_ATTEMPT_EXPLANATION_GENERATED = "POST_ATTEMPT_EXPLANATION_GENERATED"
    TUTOR_UNDERSTANDING_EVALUATED = "TUTOR_UNDERSTANDING_EVALUATED"


class EvidenceSource(str, Enum):
    LEARNER = "learner"
    EXECUTION_EVALUATION_ENGINE = "execution_evaluation_engine"
    DETERMINISTIC_RULE = "deterministic_rule"
    MODEL = "model"


class LearningEventResponse(BaseModel):
    """An allowlisted event view without labels or internal provenance."""

    id: int
    attempt_id: int
    problem_id: int
    submission_id: int | None
    event_type: LearningEventType
    occurred_at: datetime
    attempt_sequence: int
    evidence: dict[str, Any]
