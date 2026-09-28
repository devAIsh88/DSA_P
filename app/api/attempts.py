"""Learner-facing Phase 4A Attempt and Session Vault routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.attempt import AttemptAbandon, AttemptComplete, AttemptResponse, AttemptStart, ReasoningCreate
from app.schemas.learning_event import LearningEventResponse
from app.services.attempt_service import (
    AttemptConflictError, AttemptNotFoundError, AttemptProblemNotFoundError, LearnerIdentityError,
    LearnerNotFoundError,
    abandon_attempt, complete_attempt, get_attempt, record_reasoning, start_attempt,
)
from app.services.learning_event_service import list_events, to_learner_event


router = APIRouter(prefix="/attempts", tags=["attempts"])


def _attempt_error(error: Exception) -> HTTPException:
    if isinstance(error, (AttemptNotFoundError, AttemptProblemNotFoundError, LearnerNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt, learner, or problem not found")
    if isinstance(error, LearnerIdentityError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.post("/start", response_model=AttemptResponse, status_code=status.HTTP_201_CREATED)
def start(payload: AttemptStart, db: Session = Depends(get_db)) -> AttemptResponse:
    try:
        return AttemptResponse.model_validate(start_attempt(db, payload))
    except (AttemptConflictError, AttemptProblemNotFoundError, LearnerNotFoundError, LearnerIdentityError) as error:
        raise _attempt_error(error) from error


@router.get("/{attempt_id}", response_model=AttemptResponse)
def read_attempt(attempt_id: int, db: Session = Depends(get_db)) -> AttemptResponse:
    try:
        return AttemptResponse.model_validate(get_attempt(db, attempt_id))
    except (AttemptNotFoundError, LearnerNotFoundError, LearnerIdentityError) as error:
        raise _attempt_error(error) from error


@router.post("/{attempt_id}/reasoning", response_model=LearningEventResponse, status_code=status.HTTP_201_CREATED)
def add_reasoning(attempt_id: int, payload: ReasoningCreate, db: Session = Depends(get_db)) -> LearningEventResponse:
    try:
        return to_learner_event(record_reasoning(db, attempt_id, payload))
    except (AttemptConflictError, AttemptNotFoundError, LearnerNotFoundError, LearnerIdentityError) as error:
        raise _attempt_error(error) from error


@router.post("/{attempt_id}/complete", response_model=AttemptResponse)
def complete(attempt_id: int, payload: AttemptComplete, db: Session = Depends(get_db)) -> AttemptResponse:
    try:
        return AttemptResponse.model_validate(complete_attempt(db, attempt_id, payload))
    except (AttemptConflictError, AttemptNotFoundError, LearnerNotFoundError, LearnerIdentityError) as error:
        raise _attempt_error(error) from error


@router.post("/{attempt_id}/abandon", response_model=AttemptResponse)
def abandon(
    attempt_id: int, payload: AttemptAbandon | None = None, db: Session = Depends(get_db),
) -> AttemptResponse:
    try:
        return AttemptResponse.model_validate(abandon_attempt(db, attempt_id, payload.idempotency_key if payload else None))
    except (AttemptConflictError, AttemptNotFoundError, LearnerNotFoundError, LearnerIdentityError) as error:
        raise _attempt_error(error) from error


@router.get("/{attempt_id}/events", response_model=list[LearningEventResponse])
def read_events(attempt_id: int, db: Session = Depends(get_db)) -> list[LearningEventResponse]:
    try:
        get_attempt(db, attempt_id)
    except (AttemptNotFoundError, LearnerNotFoundError, LearnerIdentityError) as error:
        raise _attempt_error(error) from error
    return [to_learner_event(event) for event in list_events(db, attempt_id)]
