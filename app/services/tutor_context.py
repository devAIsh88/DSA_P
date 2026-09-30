"""Allowlisted tutor context built without hidden test or provider internals."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attempt import Attempt
from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.problem_skill import ProblemSkill
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.models.submission import Submission
from app.schemas.learning_event import LearningEventType
from app.schemas.tutor import TutorContext


def build_tutor_context(
    db: Session, attempt: Attempt, *, submission: Submission | None = None,
    reasoning_event: LearningEvent | None = None,
) -> TutorContext:
    """Select only learner-owned, public problem and aggregate evaluation fields."""

    problem = db.get(Problem, attempt.problem_id)
    if problem is None:
        raise ValueError("Attempt problem is missing")
    if submission is None:
        submission = db.scalar(select(Submission).where(Submission.attempt_id == attempt.id)
                               .order_by(Submission.id.desc()).limit(1))
    if reasoning_event is None:
        reasoning_event = db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == attempt.id,
            LearningEvent.event_type == LearningEventType.REASONING_RECORDED.value,
        ).order_by(LearningEvent.attempt_sequence.desc()).limit(1))
    skill_rows = list(db.execute(select(Skill.id, Skill.name).join(
        ProblemSkill, ProblemSkill.skill_id == Skill.id,
    ).where(ProblemSkill.problem_id == problem.id).order_by(Skill.id).limit(8)))
    skill_names = [row.name for row in skill_rows]
    mastery = None
    if len(skill_rows) == 1:
        state = db.get(SkillState, (attempt.user_id, skill_rows[0].id))
        mastery = state.mastery_probability if state is not None else None
    prior_levels = list(db.scalars(select(LearningEvent).where(
        LearningEvent.attempt_id == attempt.id,
        LearningEvent.event_type == LearningEventType.HINT_DELIVERED.value,
    ).order_by(LearningEvent.attempt_sequence.desc()).limit(20)))
    return TutorContext(
        problem_title=problem.title[:200], problem_description=problem.description[:6000],
        problem_constraints=problem.constraints[:2000] if problem.constraints else None,
        attempt_status=attempt.status, attempt_outcome=attempt.outcome,
        reasoning_text=(reasoning_event.evidence.get("reasoning_text") or "")[:10000]
        if reasoning_event is not None else None,
        source_code=submission.source_code[:12000] if submission is not None else None,
        deterministic_status=submission.overall_status if submission is not None else None,
        tests_passed=submission.tests_passed if submission is not None else None,
        tests_total=submission.tests_total if submission is not None else None,
        skill_names=skill_names, mastery_probability=mastery,
        prior_hint_levels=[int(item.evidence["hint_level_delivered"]) for item in reversed(prior_levels)
                           if type(item.evidence.get("hint_level_delivered")) is int],
    )
