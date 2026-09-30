"""Phase 6 tutor workflows over immutable learner evidence."""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.learning_event import LearningEvent
from app.schemas.learning_event import EvidenceSource, LearningEventType
from app.schemas.tutor import HintRequest, HintResponse, HintTask
from app.services.attempt_service import ensure_attempt_owner, get_attempt
from app.services.learning_event_service import append_event, event_by_key, lock_attempt
from app.services.tutor_context import build_tutor_context
from app.services.tutor_prompts import HINT_GATE_VERSION
from app.services.tutor_provider import FallbackHintProvider, TutorProvider, TutorProviderError


class TutorConflictError(Exception):
    """State, ownership, evidence, or retry payload conflicts with a tutor action."""


def _key(action: str, client_key: str, part: str = "") -> str:
    digest = sha256(f"{action}\0{client_key}".encode()).hexdigest()
    return f"t:{digest}:{part}" if part else f"t:{digest}"


def _locked_owned_attempt(db: Session, attempt_id: int):
    attempt = lock_attempt(db, attempt_id)
    if attempt is None:
        return get_attempt(db, attempt_id)
    return ensure_attempt_owner(db, attempt)


def _hint_delivery(db: Session, attempt_id: int, client_key: str) -> LearningEvent | None:
    return event_by_key(db, attempt_id, _key("hint", client_key, "delivery"))


def _hint_response(attempt_id: int, request: LearningEvent, delivery: LearningEvent) -> HintResponse:
    return HintResponse(
        attempt_id=attempt_id, request_event_id=request.id, delivery_event_id=delivery.id,
        requested_level=request.evidence["hint_level_requested"],
        delivered_level=delivery.evidence["hint_level_delivered"],
        hint_text=delivery.evidence["hint_text"],
        hint_content_id=delivery.evidence["hint_content_id"],
        source=delivery.provenance["source"],
    )


async def request_hint(
    db: Session, payload: HintRequest, provider: TutorProvider,
    fallback: FallbackHintProvider, settings: Settings,
) -> HintResponse:
    """Persist request first, then deliver only validated content under a second lock."""

    attempt = _locked_owned_attempt(db, payload.attempt_id)
    key = _key("hint", payload.idempotency_key)
    request_event = event_by_key(db, attempt.id, key)
    if request_event is not None:
        if (request_event.event_type != LearningEventType.HINT_REQUESTED.value
                or request_event.evidence.get("hint_level_requested") != payload.requested_level):
            raise TutorConflictError("Idempotency key was used for a different hint")
        delivery = _hint_delivery(db, attempt.id, payload.idempotency_key)
        if delivery is not None:
            return _hint_response(attempt.id, request_event, delivery)
    else:
        if attempt.status != "ACTIVE":
            raise TutorConflictError("Hint requests require an ACTIVE Attempt")
        count = len(list(db.scalars(select(LearningEvent.id).where(
            LearningEvent.attempt_id == attempt.id,
            LearningEvent.event_type == LearningEventType.SUBMISSION_EVALUATED.value,
        ))))
        request_event = append_event(
            db, attempt.id, LearningEventType.HINT_REQUESTED,
            {"schema_version": 1, "hint_level_requested": payload.requested_level,
             "submission_count_at_request": count},
            {"source": EvidenceSource.LEARNER.value, "policy_version": HINT_GATE_VERSION},
            idempotency_key=key,
        )
        db.commit()
    if attempt.status != "ACTIVE":
        raise TutorConflictError("Closed Attempts cannot receive new hints")
    if payload.requested_level == 6 and settings.hint_level_6_requires_level_5:
        prior_five = db.scalar(select(LearningEvent.id).where(
            LearningEvent.attempt_id == attempt.id,
            LearningEvent.event_type == LearningEventType.HINT_DELIVERED.value,
            LearningEvent.evidence["hint_level_delivered"].as_integer() == 5,
        ).limit(1))
        if prior_five is None:
            raise TutorConflictError("Level 6 requires a delivered Level 5 hint")
    context = build_tutor_context(db, attempt)
    task = HintTask(context=context, level=payload.requested_level)
    try:
        result = await provider.generate_hint(task)
    except (TutorProviderError, ValueError):
        result = None
    if result is None:
        result = await fallback.generate_hint(task)
    if result is None:
        raise TutorProviderError("No safe hint is available")
    # A remote call may have overlapped another delivery or Attempt closure.
    attempt = _locked_owned_attempt(db, payload.attempt_id)
    delivery = _hint_delivery(db, attempt.id, payload.idempotency_key)
    if delivery is not None:
        db.rollback()
        return _hint_response(attempt.id, request_event, delivery)
    if attempt.status != "ACTIVE":
        raise TutorConflictError("Attempt closed during hint generation")
    delivery = append_event(
        db, attempt.id, LearningEventType.HINT_DELIVERED,
        {"schema_version": 1, "request_event_id": request_event.id,
         "hint_level_delivered": payload.requested_level,
         "hint_content_id": result.hint_content_id, "hint_text": result.hint_text},
        {**result.provenance.model_dump(exclude_none=True), "gate_policy_version": HINT_GATE_VERSION},
        idempotency_key=_key("hint", payload.idempotency_key, "delivery"),
    )
    db.commit()
    return _hint_response(attempt.id, request_event, delivery)
