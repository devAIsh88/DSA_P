"""Phase 6 tutor workflows over immutable learner evidence."""

from __future__ import annotations

from hashlib import sha256
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.learning_event import LearningEvent
from app.models.submission import Submission
from app.schemas.learning_event import EvidenceSource, LearningEventType
from app.schemas.tutor import (
    DiagnoseRequest, DiagnoseResponse, DiagnosisResult, HintRequest, HintResponse, HintResult, HintTask,
    ExplanationResult, PostExplanationRequest, PostExplanationResponse,
    ReasoningAnalysisRequest, ReasoningAnalysisResponse, ReasoningResult, ReasoningTask, TutorRequest,
    UnderstandingAnswerRequest, UnderstandingAnswerResponse, UnderstandingCheckRequest,
    UnderstandingCheckResponse, UnderstandingResult, UnderstandingTask,
)
from app.services.attempt_service import ensure_attempt_owner, get_attempt
from app.services.learning_event_service import append_event, event_by_key, lock_attempt
from app.services.tutor_context import build_tutor_context
from app.services.tutor_prompts import HINT_GATE_VERSION, UNDERSTANDING_QUESTION_VERSION
from app.services.tutor_provider import FallbackHintProvider, TutorProvider, TutorProviderError


class TutorConflictError(Exception):
    """State, ownership, evidence, or retry payload conflicts with a tutor action."""


class TutorNotFoundError(Exception):
    """A referenced Submission or event is absent."""


_Result = TypeVar("_Result", bound=BaseModel)


async def _invoke(call: Callable[[], Awaitable[object]], retries: int, schema: type[_Result]) -> _Result:
    """Retry only failed model output, with a configured finite bound."""

    for attempt in range(retries + 1):
        try:
            return schema.model_validate(await call())
        except (TutorProviderError, ValueError, TypeError) as error:
            if attempt == retries:
                raise TutorProviderError("Tutor provider unavailable") from error
    raise AssertionError("Retry loop must return or raise")


def _prior_action(db: Session, attempt_id: int, action: str, key: str,
                  expected: LearningEventType, target_field: str, target_id: int) -> LearningEvent | None:
    prior = event_by_key(db, attempt_id, _key(action, key))
    if prior is not None and (prior.event_type != expected.value or prior.evidence.get(target_field) != target_id):
        raise TutorConflictError("Idempotency key was used for different tutor evidence")
    return prior


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
        source="fallback" if delivery.provenance.get("provider") == "fallback" else "model",
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
        result = HintResult.model_validate(await provider.generate_hint(task))
    except (TutorProviderError, ValueError, TypeError):
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


def _diagnosis_response(event: LearningEvent) -> DiagnoseResponse:
    labels = event.derived_labels or {}
    return DiagnoseResponse(
        diagnosis_event_id=event.id, submission_id=event.evidence["submission_id"],
        deterministic_status=event.evidence["deterministic_status"],
        misconception_category=labels.get("misconception_category"),
        misconception_label=labels.get("misconception_label"),
        diagnosis_summary=event.evidence["diagnosis_summary"],
    )


async def diagnose_attempt(
    db: Session, attempt_id: int, payload: DiagnoseRequest,
    provider: TutorProvider, settings: Settings,
) -> DiagnoseResponse:
    """Diagnose a persisted, deterministically evaluated Submission."""

    attempt = _locked_owned_attempt(db, attempt_id)
    submission = db.get(Submission, payload.submission_id)
    if submission is None:
        raise TutorNotFoundError
    if submission.attempt_id != attempt.id or submission.problem_id != attempt.problem_id:
        raise TutorConflictError("Submission does not belong to Attempt")
    evaluation = db.scalar(select(LearningEvent).where(
        LearningEvent.attempt_id == attempt.id,
        LearningEvent.submission_id == submission.id,
        LearningEvent.event_type == LearningEventType.SUBMISSION_EVALUATED.value,
    ))
    if evaluation is None:
        raise TutorConflictError("Submission lacks deterministic evaluation evidence")
    prior = _prior_action(db, attempt.id, "diagnosis", payload.idempotency_key,
                          LearningEventType.TUTOR_DIAGNOSIS_GENERATED, "submission_id", submission.id)
    if prior is not None:
        return _diagnosis_response(prior)
    if attempt.status not in ("ACTIVE", "COMPLETED"):
        raise TutorConflictError("Diagnosis requires an ACTIVE or COMPLETED Attempt")
    context = build_tutor_context(db, attempt, submission=submission)
    result: DiagnosisResult = await _invoke(
        lambda: provider.diagnose_attempt(TutorRequest(context=context)), settings.tutor_max_retries,
        DiagnosisResult,
    )
    attempt = _locked_owned_attempt(db, attempt_id)
    prior = _prior_action(db, attempt.id, "diagnosis", payload.idempotency_key,
                          LearningEventType.TUTOR_DIAGNOSIS_GENERATED, "submission_id", submission.id)
    if prior is not None:
        db.rollback()
        return _diagnosis_response(prior)
    if attempt.status not in ("ACTIVE", "COMPLETED"):
        raise TutorConflictError("Attempt closed during diagnosis")
    labels = {"misconception_category": result.misconception_category.value
              if result.misconception_category else None,
              "misconception_label": result.misconception_label}
    if result.confidence is not None:
        labels["model_confidence"] = result.confidence
    event = append_event(
        db, attempt.id, LearningEventType.TUTOR_DIAGNOSIS_GENERATED,
        {"schema_version": 1, "submission_id": submission.id,
         "deterministic_status": evaluation.evidence["overall_status"],
         "diagnosis_summary": result.diagnosis_summary},
        {**result.provenance.model_dump(exclude_none=True), "source_event_ids": [evaluation.id]},
        submission_id=submission.id, derived_labels=labels,
        idempotency_key=_key("diagnosis", payload.idempotency_key),
    )
    db.commit()
    return _diagnosis_response(event)


def _reasoning_response(event: LearningEvent) -> ReasoningAnalysisResponse:
    return ReasoningAnalysisResponse(
        analysis_event_id=event.id, reasoning_event_id=event.evidence["reasoning_event_id"],
        reasoning_quality=event.derived_labels["reasoning_quality"],
        feedback_text=event.evidence["feedback_text"],
    )


async def analyze_reasoning(
    db: Session, attempt_id: int, payload: ReasoningAnalysisRequest,
    provider: TutorProvider, settings: Settings,
) -> ReasoningAnalysisResponse:
    """Analyze a specific immutable reasoning event without replacing it."""

    attempt = _locked_owned_attempt(db, attempt_id)
    source = db.get(LearningEvent, payload.reasoning_event_id)
    if source is None:
        raise TutorNotFoundError
    if source.attempt_id != attempt.id or source.event_type != LearningEventType.REASONING_RECORDED.value:
        raise TutorConflictError("Referenced event is not Attempt reasoning")
    prior = _prior_action(db, attempt.id, "reasoning", payload.idempotency_key,
                          LearningEventType.TUTOR_REASONING_ANALYSIS_GENERATED, "reasoning_event_id", source.id)
    if prior is not None:
        return _reasoning_response(prior)
    if attempt.status != "ACTIVE":
        raise TutorConflictError("Reasoning analysis requires an ACTIVE Attempt")
    context = build_tutor_context(db, attempt, reasoning_event=source)
    result: ReasoningResult = await _invoke(
        lambda: provider.analyze_reasoning(ReasoningTask(
            context=context, reasoning_text=source.evidence["reasoning_text"][:10000],
        )), settings.tutor_max_retries, ReasoningResult,
    )
    attempt = _locked_owned_attempt(db, attempt_id)
    prior = _prior_action(db, attempt.id, "reasoning", payload.idempotency_key,
                          LearningEventType.TUTOR_REASONING_ANALYSIS_GENERATED, "reasoning_event_id", source.id)
    if prior is not None:
        db.rollback()
        return _reasoning_response(prior)
    if attempt.status != "ACTIVE":
        raise TutorConflictError("Attempt closed during reasoning analysis")
    labels = {"reasoning_quality": result.reasoning_quality.value}
    if result.confidence is not None:
        labels["model_confidence"] = result.confidence
    event = append_event(
        db, attempt.id, LearningEventType.TUTOR_REASONING_ANALYSIS_GENERATED,
        {"schema_version": 1, "reasoning_event_id": source.id, "feedback_text": result.feedback_text},
        {**result.provenance.model_dump(exclude_none=True), "source_event_ids": [source.id]},
        derived_labels=labels, idempotency_key=_key("reasoning", payload.idempotency_key),
    )
    db.commit()
    return _reasoning_response(event)


def _explanation_response(event: LearningEvent) -> PostExplanationResponse:
    return PostExplanationResponse(
        explanation_event_id=event.id, explanation_text=event.evidence["explanation_text"],
        key_insight=event.evidence["key_insight"],
    )


async def post_attempt_explanation(
    db: Session, attempt_id: int, payload: PostExplanationRequest,
    provider: TutorProvider, settings: Settings,
) -> PostExplanationResponse:
    """Deliver an explanation only after a completed Attempt."""

    attempt = _locked_owned_attempt(db, attempt_id)
    prior = event_by_key(db, attempt.id, _key("explanation", payload.idempotency_key))
    if prior is not None:
        if prior.event_type != LearningEventType.POST_ATTEMPT_EXPLANATION_GENERATED.value:
            raise TutorConflictError("Idempotency key was used for another action")
        return _explanation_response(prior)
    if attempt.status != "COMPLETED":
        raise TutorConflictError("Post-attempt explanation requires a COMPLETED Attempt")
    context = build_tutor_context(db, attempt)
    result: ExplanationResult = await _invoke(
        lambda: provider.generate_post_attempt_explanation(TutorRequest(context=context)),
        settings.tutor_max_retries, ExplanationResult,
    )
    attempt = _locked_owned_attempt(db, attempt_id)
    prior = event_by_key(db, attempt.id, _key("explanation", payload.idempotency_key))
    if prior is not None:
        db.rollback()
        return _explanation_response(prior)
    if attempt.status != "COMPLETED":
        raise TutorConflictError("Attempt status changed during explanation")
    event = append_event(
        db, attempt.id, LearningEventType.POST_ATTEMPT_EXPLANATION_GENERATED,
        {"schema_version": 1, "explanation_text": result.explanation_text,
         "key_insight": result.key_insight},
        result.provenance.model_dump(exclude_none=True),
        idempotency_key=_key("explanation", payload.idempotency_key),
    )
    db.commit()
    return _explanation_response(event)


def _question(outcome: str | None) -> str:
    if outcome == "GAVE_UP":
        return ("Explain what would need to change in your attempted approach, "
                "its time and space complexity, and one important edge case.")
    return ("Explain why your final approach works, its time and space complexity, "
            "and one important edge case.")


def _check_response(event: LearningEvent) -> UnderstandingCheckResponse:
    return UnderstandingCheckResponse(
        check_event_id=event.id, question=event.evidence["question"],
        question_version=event.evidence["question_version"],
    )


def request_understanding_check(
    db: Session, attempt_id: int, payload: UnderstandingCheckRequest,
) -> UnderstandingCheckResponse:
    """Append a deterministic, versioned post-attempt question."""

    attempt = _locked_owned_attempt(db, attempt_id)
    prior = event_by_key(db, attempt.id, _key("understanding-prompt", payload.idempotency_key))
    if prior is not None:
        if (prior.event_type != LearningEventType.UNDERSTANDING_CHECK.value
                or prior.evidence.get("stage") != "PROMPTED"):
            raise TutorConflictError("Idempotency key was used for another action")
        return _check_response(prior)
    if attempt.status != "COMPLETED":
        raise TutorConflictError("Understanding checks require a COMPLETED Attempt")
    event = append_event(
        db, attempt.id, LearningEventType.UNDERSTANDING_CHECK,
        {"schema_version": 1, "stage": "PROMPTED", "question": _question(attempt.outcome),
         "question_version": UNDERSTANDING_QUESTION_VERSION},
        {"source": EvidenceSource.DETERMINISTIC_RULE.value,
         "rule_version": UNDERSTANDING_QUESTION_VERSION},
        idempotency_key=_key("understanding-prompt", payload.idempotency_key),
    )
    db.commit()
    return _check_response(event)


def _answer_response(answer: LearningEvent, evaluation: LearningEvent) -> UnderstandingAnswerResponse:
    return UnderstandingAnswerResponse(
        answer_event_id=answer.id, evaluation_event_id=evaluation.id,
        answer_quality=evaluation.derived_labels["answer_quality"],
        feedback_text=evaluation.evidence["feedback_text"],
    )


def _evaluation_for_answer(db: Session, attempt_id: int, answer_id: int) -> LearningEvent | None:
    return db.scalar(select(LearningEvent).where(
        LearningEvent.attempt_id == attempt_id,
        LearningEvent.event_type == LearningEventType.TUTOR_UNDERSTANDING_EVALUATED.value,
        LearningEvent.evidence["answer_event_id"].as_integer() == answer_id,
    ).limit(1))


async def answer_understanding_check(
    db: Session, attempt_id: int, check_event_id: int, payload: UnderstandingAnswerRequest,
    provider: TutorProvider, settings: Settings,
) -> UnderstandingAnswerResponse:
    """Commit the learner answer before optional provider evaluation."""

    attempt = _locked_owned_attempt(db, attempt_id)
    check = db.get(LearningEvent, check_event_id)
    if check is None:
        raise TutorNotFoundError
    if (check.attempt_id != attempt.id or check.event_type != LearningEventType.UNDERSTANDING_CHECK.value
            or check.evidence.get("stage") != "PROMPTED"):
        raise TutorConflictError("Referenced event is not a prompted check in this Attempt")
    answer = event_by_key(db, attempt.id, _key("understanding-answer", payload.idempotency_key))
    if answer is not None:
        if (answer.event_type != LearningEventType.UNDERSTANDING_CHECK.value
                or answer.evidence.get("stage") != "ANSWERED"
                or answer.evidence.get("check_event_id") != check.id
                or answer.evidence.get("answer_text") != payload.answer_text):
            raise TutorConflictError("Idempotency key was used for another answer")
        prior_evaluation = _evaluation_for_answer(db, attempt.id, answer.id)
        if prior_evaluation is not None:
            return _answer_response(answer, prior_evaluation)
    else:
        if attempt.status != "COMPLETED":
            raise TutorConflictError("Answer requires a COMPLETED Attempt")
        existing_answer = db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == attempt.id,
            LearningEvent.event_type == LearningEventType.UNDERSTANDING_CHECK.value,
            LearningEvent.evidence["stage"].as_string() == "ANSWERED",
            LearningEvent.evidence["check_event_id"].as_integer() == check.id,
        ).limit(1))
        if existing_answer is not None:
            raise TutorConflictError("This check already has an answer")
        answer = append_event(
            db, attempt.id, LearningEventType.UNDERSTANDING_CHECK,
            {"schema_version": 1, "stage": "ANSWERED", "check_event_id": check.id,
             "answer_text": payload.answer_text},
            {"source": EvidenceSource.LEARNER.value, "question_version": UNDERSTANDING_QUESTION_VERSION},
            idempotency_key=_key("understanding-answer", payload.idempotency_key),
        )
        db.commit()
    context = build_tutor_context(db, attempt)
    result: UnderstandingResult = await _invoke(
        lambda: provider.evaluate_understanding(UnderstandingTask(
            context=context, question=check.evidence["question"], answer_text=payload.answer_text,
        )), settings.tutor_max_retries, UnderstandingResult,
    )
    attempt = _locked_owned_attempt(db, attempt_id)
    prior_evaluation = _evaluation_for_answer(db, attempt.id, answer.id)
    if prior_evaluation is not None:
        db.rollback()
        return _answer_response(answer, prior_evaluation)
    if attempt.status != "COMPLETED":
        raise TutorConflictError("Attempt status changed during understanding evaluation")
    labels = {"answer_quality": result.answer_quality.value}
    if result.confidence is not None:
        labels["model_confidence"] = result.confidence
    evaluation = append_event(
        db, attempt.id, LearningEventType.TUTOR_UNDERSTANDING_EVALUATED,
        {"schema_version": 1, "check_event_id": check.id, "answer_event_id": answer.id,
         "feedback_text": result.feedback_text},
        {**result.provenance.model_dump(exclude_none=True), "source_event_ids": [check.id, answer.id]},
        derived_labels=labels,
        idempotency_key=_key("understanding-answer", payload.idempotency_key, "evaluation"),
    )
    db.commit()
    return _answer_response(answer, evaluation)
