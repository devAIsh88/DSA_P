"""Transactional adaptive recommendation issuance, reuse and lifecycle integration."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.attempt import Attempt
from app.models.recommendation import Recommendation
from app.models.user import User
from app.schemas.recommendation import NextRecommendationResponse, RecommendationPolicyConfig, RecommendationResponse
from app.services.attempt_service import LearnerIdentityError, LearnerNotFoundError, single_learner_id
from app.services.recommendation_context import AdaptiveInputs, LearnerStateNotReadyError, load_adaptive_inputs, utc_time
from app.services.recommendation_lifecycle import consume_recommendation, supersede_recommendation
from app.services.recommendation_policy import RecommendationPolicy, load_policy_config


class ActiveAttemptError(Exception):
    def __init__(self, attempt_ids: list[int]) -> None:
        self.attempt_ids = attempt_ids
        super().__init__("An active Attempt must finish before selecting another activity")


class RecommendationUnavailableError(Exception):
    """No persisted answer can be returned safely."""


class _InputsChangedError(Exception):
    pass


def lock_learner(db: Session, user_id: int) -> None:
    """Serialize recommendation issuance and new Attempt creation, not provider calls."""

    if db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        raise LearnerNotFoundError


def active_recommendation(db: Session, user_id: int) -> Recommendation | None:
    return db.scalar(select(Recommendation).where(
        Recommendation.user_id == user_id, Recommendation.consumed_at.is_(None),
        Recommendation.superseded_at.is_(None),
    ).execution_options(populate_existing=True))


def _fresh(recommendation: Recommendation, inputs: AdaptiveInputs, now: datetime) -> bool:
    return (recommendation.input_fingerprint == inputs.fingerprint
            and recommendation.evidence_through_event_id == inputs.through_event_id
            and recommendation.evidence_event_count == inputs.event_count
            and (recommendation.reevaluate_at is None or utc_time(now) < utc_time(recommendation.reevaluate_at)))


def _response(recommendation: Recommendation) -> NextRecommendationResponse:
    return NextRecommendationResponse(recommendation=RecommendationResponse.model_validate(recommendation),
                                      unavailable_reason=None)


def get_next_recommendation(
    db: Session, *, now: datetime | None = None, config: RecommendationPolicyConfig | None = None,
) -> NextRecommendationResponse:
    """Reuse or persist a deterministic decision; never return an uncommitted selection."""

    for _ in range(3):
        try:
            clock = utc_time(now or datetime.now(UTC))
            policy_config = config if config is not None else load_policy_config()
            user_id = single_learner_id(db)
            lock_learner(db, user_id)
            active_attempts = list(db.scalars(select(Attempt.id).where(
                Attempt.user_id == user_id, Attempt.status == "ACTIVE",
            ).order_by(Attempt.id)))
            if active_attempts:
                raise ActiveAttemptError(active_attempts)
            inputs = load_adaptive_inputs(db, user_id, clock, policy_config)
            current = active_recommendation(db, user_id)
            if current is not None and _fresh(current, inputs, clock):
                response = _response(current)
                # Validate reuse against changes that committed during input assembly too.
                if load_adaptive_inputs(db, user_id, clock, policy_config).fingerprint != inputs.fingerprint:
                    raise _InputsChangedError
                db.commit()
                return response
            result = RecommendationPolicy(policy_config).recommend(inputs.context)
            if load_adaptive_inputs(db, user_id, clock, policy_config).fingerprint != inputs.fingerprint:
                raise _InputsChangedError
            if current is not None:
                supersede_recommendation(current, clock)
                db.flush()  # Release the partial unique index slot before inserting its successor.
            if result.decision is None:
                db.commit()
                return NextRecommendationResponse(recommendation=None, unavailable_reason=result.unavailable_reason)
            decision = result.decision
            recommendation = Recommendation(
                user_id=user_id, action_type=decision.action_type.value, problem_id=decision.problem_id,
                skill_id=decision.skill_id, policy_version=policy_config.version,
                reason_codes=[reason.value for reason in decision.reason_codes],
                evidence_through_event_id=inputs.through_event_id, evidence_event_count=inputs.event_count,
                input_snapshot=inputs.snapshot, input_fingerprint=inputs.fingerprint,
                created_at=clock, reevaluate_at=result.reevaluate_at,
            )
            db.add(recommendation)
            db.flush()
            response = _response(recommendation)
            db.commit()
            return response
        except (_InputsChangedError, IntegrityError):
            db.rollback()
        except (LearnerNotFoundError, LearnerIdentityError, ActiveAttemptError, LearnerStateNotReadyError):
            db.rollback()
            raise
        except (SQLAlchemyError, ValueError, OSError) as error:
            db.rollback()
            raise RecommendationUnavailableError from error
    raise RecommendationUnavailableError("Concurrent input changes prevented a stable persisted decision")


def recommendation_for_new_attempt(
    db: Session, user_id: int, problem_id: int, now: datetime,
) -> Recommendation | None:
    """Check freshness before ATTEMPT_STARTED changes the evidence boundary."""

    current = active_recommendation(db, user_id)
    if current is None:
        return None
    try:
        inputs = load_adaptive_inputs(db, user_id, now, load_policy_config())
        fresh = _fresh(current, inputs, now)
    except (LearnerStateNotReadyError, ValueError, OSError):
        fresh = False
    if not fresh or current.problem_id != problem_id:
        supersede_recommendation(current, now)
        return None
    return current


def consume_for_new_attempt(recommendation: Recommendation | None, attempt: Attempt, now: datetime) -> None:
    if recommendation is not None:
        consume_recommendation(recommendation, attempt, now)
