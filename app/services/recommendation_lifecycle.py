"""Controlled lifecycle transitions; freshness is owned by the orchestration service."""

from datetime import datetime

from app.models.attempt import Attempt
from app.models.recommendation import Recommendation


def supersede_recommendation(recommendation: Recommendation, now: datetime) -> None:
    """Close an active decision without rewriting its original content."""

    if recommendation.consumed_at is not None or recommendation.superseded_at is not None:
        raise ValueError("Recommendation is already terminal")
    recommendation.superseded_at = now


def consume_recommendation(recommendation: Recommendation, attempt: Attempt, now: datetime) -> None:
    """Record exact matching new Attempt consumption inside the caller's transaction."""

    if recommendation.consumed_at is not None or recommendation.superseded_at is not None:
        raise ValueError("Recommendation is already terminal")
    if (attempt.user_id != recommendation.user_id or attempt.problem_id != recommendation.problem_id
            or attempt.status != "ACTIVE" or attempt.id is None):
        raise ValueError("Attempt does not match recommendation")
    recommendation.consumed_at = now
    recommendation.consumed_attempt_id = attempt.id
