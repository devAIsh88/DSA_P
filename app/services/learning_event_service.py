"""Append and serialize immutable learner evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.attempt import Attempt
from app.models.learning_event import LearningEvent
from app.models.submission import Submission
from app.schemas.learning_event import LearningEventResponse, LearningEventType


class EventConflictError(Exception):
    """An idempotency key was reused for a different event."""


_LEARNER_EVIDENCE_KEYS: dict[LearningEventType, frozenset[str]] = {
    LearningEventType.ATTEMPT_STARTED: frozenset({"schema_version", "problem_id", "user_id", "started_at"}),
    LearningEventType.REASONING_RECORDED: frozenset({
        "schema_version", "reasoning_text", "word_count", "elapsed_ms_since_attempt_start",
    }),
    LearningEventType.SUBMISSION_EVALUATED: frozenset({
        "schema_version", "submission_id", "overall_status", "tests_passed", "tests_total",
        "edge_cases_failed", "execution_time_ms", "hint_count_at_submission", "max_hint_level_at_submission",
    }),
    LearningEventType.HINT_REQUESTED: frozenset({
        "schema_version", "hint_level_requested", "elapsed_ms_since_attempt_start", "submission_count_at_request",
    }),
    LearningEventType.HINT_DELIVERED: frozenset({"schema_version", "hint_level_delivered", "hint_content_id"}),
    LearningEventType.ATTEMPT_COMPLETED: frozenset({
        "schema_version", "status", "outcome", "final_submission_id", "total_duration_ms",
        "hint_count", "max_hint_level",
    }),
    LearningEventType.UNDERSTANDING_CHECK: frozenset({"schema_version", "learner_rating", "prompt_version"}),
}


def lock_attempt(db: Session, attempt_id: int) -> Attempt | None:
    """Serialize appends against the Attempt row in PostgreSQL."""

    return db.scalar(
        select(Attempt).where(Attempt.id == attempt_id).with_for_update().execution_options(populate_existing=True)
    )


def event_by_key(db: Session, attempt_id: int, key: str | None) -> LearningEvent | None:
    """Find an earlier event for a caller's retry key."""

    if key is None:
        return None
    return db.scalar(
        select(LearningEvent).where(LearningEvent.attempt_id == attempt_id, LearningEvent.idempotency_key == key)
    )


def event_for_submission(db: Session, submission_id: int) -> LearningEvent | None:
    """Find the unique evaluation event for a persisted Submission."""

    return db.scalar(select(LearningEvent).where(
        LearningEvent.submission_id == submission_id,
        LearningEvent.event_type == LearningEventType.SUBMISSION_EVALUATED.value,
    ))


def append_event(
    db: Session,
    attempt_id: int,
    event_type: LearningEventType,
    evidence: dict[str, Any],
    provenance: dict[str, Any],
    *,
    submission_id: int | None = None,
    skill_id: int | None = None,
    idempotency_key: str | None = None,
) -> LearningEvent:
    """Allocate the next sequence under a row lock and append within the caller's transaction."""

    attempt = lock_attempt(db, attempt_id)
    if attempt is None:
        raise ValueError("Attempt not found")
    existing = event_by_key(db, attempt_id, idempotency_key)
    if existing is not None:
        if (existing.event_type != event_type.value or existing.evidence != evidence
                or existing.submission_id != submission_id or existing.skill_id != skill_id):
            raise EventConflictError("Idempotency key already used for different evidence")
        return existing
    if submission_id is not None and event_type is LearningEventType.SUBMISSION_EVALUATED:
        submission = db.get(Submission, submission_id)
        if submission is None or submission.attempt_id != attempt_id or submission.problem_id != attempt.problem_id:
            raise ValueError("Submission does not belong to this Attempt")
        existing = event_for_submission(db, submission_id)
        if existing is not None:
            return existing
    next_sequence = db.scalar(
        select(func.coalesce(func.max(LearningEvent.attempt_sequence), 0)).where(LearningEvent.attempt_id == attempt_id)
    ) + 1
    event = LearningEvent(
        user_id=attempt.user_id,
        attempt_id=attempt.id,
        problem_id=attempt.problem_id,
        skill_id=skill_id,
        submission_id=submission_id,
        event_type=event_type.value,
        occurred_at=datetime.now(UTC),
        attempt_sequence=next_sequence,
        evidence=evidence,
        derived_labels=None,
        provenance=provenance,
        idempotency_key=idempotency_key,
    )
    db.add(event)
    db.flush()
    return event


def list_events(db: Session, attempt_id: int) -> list[LearningEvent]:
    """Return historical events in replay order."""

    return list(db.scalars(
        select(LearningEvent).where(LearningEvent.attempt_id == attempt_id)
        .order_by(LearningEvent.attempt_sequence)
    ))


def hint_summary(db: Session, attempt_id: int) -> tuple[int, int]:
    """Summarize recorded hint actions without inferring assistance from an LLM."""

    hints = list(db.scalars(select(LearningEvent).where(
        LearningEvent.attempt_id == attempt_id,
        LearningEvent.event_type.in_((LearningEventType.HINT_REQUESTED.value,
                                      LearningEventType.HINT_DELIVERED.value)),
    )))
    requested = sum(item.event_type == LearningEventType.HINT_REQUESTED.value for item in hints)
    delivered_levels = [item.evidence.get("hint_level_delivered") for item in hints
                        if item.event_type == LearningEventType.HINT_DELIVERED.value]
    valid_levels = [level for level in delivered_levels if isinstance(level, int) and 0 <= level <= 6]
    return requested, max(valid_levels, default=0)


def to_learner_event(event: LearningEvent) -> LearningEventResponse:
    """Allowlist event evidence; never expose labels, provenance, or private test details."""

    event_type = LearningEventType(event.event_type)
    allowed = _LEARNER_EVIDENCE_KEYS[event_type]
    return LearningEventResponse(
        id=event.id,
        attempt_id=event.attempt_id,
        problem_id=event.problem_id,
        submission_id=event.submission_id,
        event_type=event_type,
        occurred_at=event.occurred_at,
        attempt_sequence=event.attempt_sequence,
        evidence={key: value for key, value in event.evidence.items() if key in allowed},
    )
