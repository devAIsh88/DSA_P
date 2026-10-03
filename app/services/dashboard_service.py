"""Read-only aggregation; authoritative projections and decisions are never changed."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.attempt import Attempt
from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.recommendation import Recommendation
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.schemas.attempt import AttemptResponse
from app.schemas.dashboard import DashboardSummaryResponse, LearnerStateResponse, SkillProgressResponse
from app.schemas.learning_event import LearningEventType
from app.schemas.recommendation import RecommendationResponse
from app.schemas.skill_state import SkillStateResponse
from app.services.attempt_service import single_learner_id


def _skill_progress(db: Session, user_id: int) -> list[SkillProgressResponse]:
    """Label actual stored projections; unobserved skills never receive invented priors."""

    rows = db.execute(select(SkillState, Skill.name, Skill.description).join(
        Skill, Skill.id == SkillState.skill_id,
    ).where(SkillState.user_id == user_id).order_by(SkillState.skill_id))
    return [SkillProgressResponse(
        **SkillStateResponse.model_validate(state).model_dump(),
        skill_name=name, skill_description=description,
    ) for state, name, description in rows]


def _active_attempts(db: Session, user_id: int) -> list[AttemptResponse]:
    return [AttemptResponse.model_validate(attempt) for attempt in db.scalars(
        select(Attempt).where(Attempt.user_id == user_id, Attempt.status == "ACTIVE")
        .order_by(Attempt.id)
    )]


def get_learner_state(db: Session) -> LearnerStateResponse:
    """Expose identity and current stored reporting without persistence side effects."""

    user_id = single_learner_id(db)
    return LearnerStateResponse(
        user_id=user_id, active_attempts=_active_attempts(db, user_id),
        skills=_skill_progress(db, user_id),
    )


def get_dashboard_summary(db: Session) -> DashboardSummaryResponse:
    """Keep whole-learner activity distinct from supported skill solve denominators."""

    user_id = single_learner_id(db)
    attempts = list(db.scalars(select(Attempt).where(Attempt.user_id == user_id).order_by(Attempt.id)))
    skills = _skill_progress(db, user_id)
    solved = [attempt for attempt in attempts if attempt.status == "COMPLETED" and attempt.outcome == "SOLVED"]
    hint_counts = dict(db.execute(select(LearningEvent.event_type, func.count(LearningEvent.id)).where(
        LearningEvent.user_id == user_id,
        LearningEvent.event_type.in_((LearningEventType.HINT_REQUESTED.value, LearningEventType.HINT_DELIVERED.value)),
    ).group_by(LearningEvent.event_type)).all())
    successful_supported = sum(skill.successful_attempt_count for skill in skills)
    independent_solves = sum(skill.independent_solve_count for skill in skills)
    hint_dependent_solves = sum(skill.hint_dependent_count for skill in skills)
    recommendation = db.scalar(select(Recommendation).where(
        Recommendation.user_id == user_id, Recommendation.consumed_at.is_(None),
        Recommendation.superseded_at.is_(None),
    ))
    return DashboardSummaryResponse(
        user_id=user_id,
        catalogue_problem_count=db.scalar(select(func.count(Problem.id))) or 0,
        attempt_count=len(attempts),
        completed_attempt_count=sum(attempt.status == "COMPLETED" for attempt in attempts),
        solved_attempt_count=len(solved),
        abandoned_attempt_count=sum(attempt.status == "ABANDONED" for attempt in attempts),
        unique_solved_problem_count=len({attempt.problem_id for attempt in solved}),
        active_attempts=[AttemptResponse.model_validate(attempt) for attempt in attempts if attempt.status == "ACTIVE"],
        recent_attempts=[AttemptResponse.model_validate(attempt) for attempt in reversed(attempts[-10:])],
        skills=skills,
        hint_request_count=hint_counts.get(LearningEventType.HINT_REQUESTED.value, 0),
        hint_delivery_count=hint_counts.get(LearningEventType.HINT_DELIVERED.value, 0),
        independent_solve_count=independent_solves,
        hint_dependent_solve_count=hint_dependent_solves,
        successful_supported_attempt_count=successful_supported,
        independent_solve_share=independent_solves / successful_supported if successful_supported else None,
        hint_dependency_share=hint_dependent_solves / successful_supported if successful_supported else None,
        # This is only the persisted snapshot; /recommendations/next owns freshness.
        existing_recommendation=RecommendationResponse.model_validate(recommendation) if recommendation else None,
    )
