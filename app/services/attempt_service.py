"""Attempt lifecycle and learner action capture."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.attempt import Attempt
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.schemas.attempt import AttemptComplete, AttemptOutcome, AttemptStart, ReasoningCreate
from app.schemas.learning_event import EvidenceSource, LearningEventType
from app.services.learning_event_service import append_event, event_by_key, lock_attempt


class AttemptNotFoundError(Exception):
    """The requested Attempt does not exist."""


class AttemptConflictError(Exception):
    """The requested operation conflicts with an Attempt's lifecycle or identity."""


class LearnerNotFoundError(Exception):
    """The requested learner does not exist."""


class LearnerIdentityError(Exception):
    """The single-learner MVP cannot establish an unambiguous learner identity."""


class AttemptProblemNotFoundError(Exception):
    """The requested problem does not exist."""


def single_learner_id(db: Session) -> int:
    """Require exactly one learner until authentication is introduced in a later phase."""

    learner_ids = list(db.scalars(select(User.id).order_by(User.id).limit(2)))
    if not learner_ids:
        raise LearnerNotFoundError
    if len(learner_ids) != 1:
        raise LearnerIdentityError("Single-learner identity is ambiguous")
    return learner_ids[0]


def ensure_attempt_owner(db: Session, attempt: Attempt) -> Attempt:
    """Prevent cross-learner access if extra User rows appear in the MVP database."""

    if attempt.user_id != single_learner_id(db):
        raise LearnerIdentityError("Attempt does not belong to the active learner")
    return attempt


def get_attempt(db: Session, attempt_id: int) -> Attempt:
    """Load one Attempt or raise a domain error."""

    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise AttemptNotFoundError
    return ensure_attempt_owner(db, attempt)


def _locked_attempt(db: Session, attempt_id: int) -> Attempt:
    attempt = lock_attempt(db, attempt_id)
    if attempt is None:
        raise AttemptNotFoundError
    return ensure_attempt_owner(db, attempt)


def _elapsed_ms(started_at: datetime, now: datetime) -> int:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return max(0, int((now - started_at).total_seconds() * 1000))


def _prior_event(db: Session, attempt_id: int, key: str | None, expected: LearningEventType):
    event = event_by_key(db, attempt_id, key)
    if event is not None and event.event_type != expected.value:
        raise AttemptConflictError("Idempotency key was used for another action")
    return event


def start_attempt(db: Session, payload: AttemptStart) -> Attempt:
    """Start one active engagement and append its opening event atomically."""

    if payload.user_id != single_learner_id(db):
        raise LearnerIdentityError("Requested learner is not the active learner")
    if db.get(Problem, payload.problem_id) is None:
        raise AttemptProblemNotFoundError
    if payload.idempotency_key is not None:
        earlier = db.scalar(select(Attempt).where(
            Attempt.user_id == payload.user_id, Attempt.idempotency_key == payload.idempotency_key,
        ))
        if earlier is not None:
            if earlier.problem_id != payload.problem_id:
                raise AttemptConflictError("Idempotency key was used for another problem")
            return earlier
    active = db.scalar(select(Attempt).where(
        Attempt.user_id == payload.user_id,
        Attempt.problem_id == payload.problem_id,
        Attempt.status == "ACTIVE",
    ))
    if active is not None:
        raise AttemptConflictError("An active Attempt already exists for this problem")
    now = datetime.now(UTC)
    attempt = Attempt(
        user_id=payload.user_id, problem_id=payload.problem_id, status="ACTIVE",
        outcome=None, started_at=now, idempotency_key=payload.idempotency_key,
    )
    try:
        db.add(attempt)
        db.flush()
        append_event(
            db, attempt.id, LearningEventType.ATTEMPT_STARTED,
            {"schema_version": 1, "problem_id": payload.problem_id, "user_id": payload.user_id,
             "started_at": now.isoformat()},
            {"source": EvidenceSource.LEARNER.value, "user_id": payload.user_id},
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if payload.idempotency_key is not None:
            earlier = db.scalar(select(Attempt).where(
                Attempt.user_id == payload.user_id, Attempt.idempotency_key == payload.idempotency_key,
            ))
            if earlier is not None and earlier.problem_id == payload.problem_id:
                return earlier
        raise AttemptConflictError("An active Attempt already exists for this problem") from error
    db.refresh(attempt)
    return attempt


def record_reasoning(db: Session, attempt_id: int, payload: ReasoningCreate):
    """Store each submitted reasoning text in an immutable event, including later revisions."""

    attempt = _locked_attempt(db, attempt_id)
    prior = _prior_event(db, attempt.id, payload.idempotency_key, LearningEventType.REASONING_RECORDED)
    if prior is not None:
        if prior.evidence.get("reasoning_text") != payload.reasoning_text:
            raise AttemptConflictError("Idempotency key was used for different reasoning")
        return prior
    if attempt.status != "ACTIVE":
        raise AttemptConflictError("Closed Attempts cannot accept reasoning")
    now = datetime.now(UTC)
    event = append_event(
        db, attempt.id, LearningEventType.REASONING_RECORDED,
        {"schema_version": 1, "reasoning_text": payload.reasoning_text,
         "word_count": len(payload.reasoning_text.split()),
         "elapsed_ms_since_attempt_start": _elapsed_ms(attempt.started_at, now)},
        {"source": EvidenceSource.LEARNER.value, "user_id": attempt.user_id},
        idempotency_key=payload.idempotency_key,
    )
    db.commit()
    return event


def _close_attempt(db: Session, attempt_id: int, status: str, outcome: AttemptOutcome | None, key: str | None) -> Attempt:
    attempt = _locked_attempt(db, attempt_id)
    prior = _prior_event(db, attempt.id, key, LearningEventType.ATTEMPT_COMPLETED)
    if prior is not None:
        if prior.evidence.get("status") != status or prior.evidence.get("outcome") != (outcome.value if outcome else None):
            raise AttemptConflictError("Idempotency key was used for a different outcome")
        return attempt
    if attempt.status != "ACTIVE":
        raise AttemptConflictError("Closed Attempts cannot change status")
    submissions = list(db.scalars(
        select(Submission).where(Submission.attempt_id == attempt.id).order_by(Submission.id)
    ))
    final_submission = submissions[-1] if submissions else None
    if outcome is AttemptOutcome.SOLVED and (
        final_submission is None or final_submission.overall_status != "ACCEPTED"
    ):
        raise AttemptConflictError("SOLVED requires a final accepted Submission in this Attempt")
    now = datetime.now(UTC)
    attempt.status = status
    attempt.outcome = outcome.value if outcome is not None else None
    attempt.completed_at = now
    attempt.total_duration_ms = _elapsed_ms(attempt.started_at, now)
    db.flush()
    append_event(
        db, attempt.id, LearningEventType.ATTEMPT_COMPLETED,
        {"schema_version": 1, "status": status, "outcome": attempt.outcome,
         "final_submission_id": final_submission.id if final_submission else None,
         "total_duration_ms": attempt.total_duration_ms, "hint_count": 0, "max_hint_level": 0},
        {"source": EvidenceSource.LEARNER.value, "user_id": attempt.user_id,
         "validation": {"source": EvidenceSource.DETERMINISTIC_RULE.value,
                        "rule_id": "attempt_close_v1"}},
        idempotency_key=key,
    )
    db.commit()
    return attempt


def complete_attempt(db: Session, attempt_id: int, payload: AttemptComplete) -> Attempt:
    """Close an active Attempt with a conclusive outcome."""

    return _close_attempt(db, attempt_id, "COMPLETED", payload.outcome, payload.idempotency_key)


def abandon_attempt(db: Session, attempt_id: int, key: str | None = None) -> Attempt:
    """Close an active Attempt without a conclusive outcome."""

    return _close_attempt(db, attempt_id, "ABANDONED", None, key)
