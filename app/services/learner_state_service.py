"""Project eligible historical Attempt evidence into single-skill learner state."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.learning_event import LearningEvent
from app.models.problem_skill import ProblemSkill
from app.models.skill_state import SkillState
from app.models.user import User
from app.schemas.learning_event import LearningEventType
from app.services.bkt_provider import BKTProvider, load_bkt_parameters
from app.services.knowledge_tracing import KnowledgeTracingProvider, TracingObservation


OBSERVATION_RULE_VERSION = "attempt-completion-binary-reporting-v1"
ATTRIBUTION_RULE_VERSION = "single-skill-v1"
_HINT_TYPES = (LearningEventType.HINT_REQUESTED.value, LearningEventType.HINT_DELIVERED.value)


def _utc_time(value: datetime) -> datetime:
    """SQLite drops timezone data in tests; persisted PostgreSQL timestamps retain it."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def single_skill_for_problem(db: Session, problem_id: int) -> tuple[int | None, str]:
    """Snapshot a skill only when the problem has exactly one mapping."""

    mappings = list(db.execute(
        select(ProblemSkill.skill_id, ProblemSkill.weight).where(ProblemSkill.problem_id == problem_id)
        .order_by(ProblemSkill.skill_id).limit(2)
    ))
    if not mappings:
        return None, "unmapped"
    if len(mappings) > 1:
        return None, "multiple_skills_require_policy"
    skill_id, weight = mappings[0]
    if weight != 1.0:
        return None, "nonunit_weight_requires_policy"
    return skill_id, "single_skill"


def _eligible_observation(db: Session, event: LearningEvent) -> TracingObservation | None:
    """Fail closed when history cannot support a binary, unassisted observation."""

    if event.event_type != LearningEventType.ATTEMPT_COMPLETED.value or event.skill_id is None:
        return None
    if event.evidence.get("status") != "COMPLETED":
        return None
    provenance = event.provenance if isinstance(event.provenance, dict) else {}
    attribution = provenance.get("attribution")
    if (not isinstance(attribution, dict) or attribution.get("rule_version") != ATTRIBUTION_RULE_VERSION
            or attribution.get("status") != "single_skill"):
        return None
    if event.evidence.get("hint_count") != 0 or event.evidence.get("max_hint_level") != 0:
        return None
    hint_event_id = db.scalar(
        select(LearningEvent.id).where(
            LearningEvent.attempt_id == event.attempt_id, LearningEvent.event_type.in_(_HINT_TYPES),
        ).limit(1)
    )
    if hint_event_id is not None:
        return None

    final_submission_id = event.evidence.get("final_submission_id")
    if final_submission_id is not None and (not isinstance(final_submission_id, int)
                                            or isinstance(final_submission_id, bool)):
        return None
    evaluation = None
    if isinstance(final_submission_id, int):
        evaluation = db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == event.attempt_id,
            LearningEvent.submission_id == final_submission_id,
            LearningEvent.event_type == LearningEventType.SUBMISSION_EVALUATED.value,
            LearningEvent.id < event.id,
        ))
        if (evaluation is None or evaluation.user_id != event.user_id
                or evaluation.problem_id != event.problem_id
                or not isinstance(evaluation.provenance, dict)
                or evaluation.provenance.get("source") != "execution_evaluation_engine"):
            return None
    outcome = event.evidence.get("outcome")
    if outcome == "SOLVED":
        tests_total = evaluation.evidence.get("tests_total") if evaluation is not None else None
        tests_passed = evaluation.evidence.get("tests_passed") if evaluation is not None else None
        if (evaluation is None or evaluation.evidence.get("overall_status") != "ACCEPTED"
                or not isinstance(tests_total, int) or isinstance(tests_total, bool) or tests_total <= 0
                or tests_passed != tests_total):
            return None
        correct = 1.0
    elif outcome == "GAVE_UP":
        if evaluation is not None and evaluation.evidence.get("overall_status") in (
            "SYSTEM_ERROR", "RUNNING", "QUEUED", "ACCEPTED",
        ):
            return None
        correct = 0.0
    else:
        return None
    return TracingObservation(correct=correct, hint_level=0, attempt_id=event.attempt_id,
                              occurred_at=event.occurred_at)


def _reportable_completion(event: LearningEvent) -> bool:
    """Accept terminal evidence captured under the single-skill v1 attribution rule."""

    if event.event_type != LearningEventType.ATTEMPT_COMPLETED.value or event.skill_id is None:
        return False
    provenance = event.provenance if isinstance(event.provenance, dict) else {}
    attribution = provenance.get("attribution")
    if (not isinstance(attribution, dict) or attribution.get("rule_version") != ATTRIBUTION_RULE_VERSION
            or attribution.get("status") != "single_skill"):
        return False
    status = event.evidence.get("status")
    outcome = event.evidence.get("outcome")
    return ((status == "COMPLETED" and outcome in ("SOLVED", "GAVE_UP"))
            or (status == "ABANDONED" and outcome is None))


def _hint_reporting(db: Session, completion: LearningEvent) -> tuple[int, list[int], bool]:
    """Count requests and delivered levels before closure as separate raw signals."""

    hints = list(db.scalars(select(LearningEvent).where(
        LearningEvent.attempt_id == completion.attempt_id,
        LearningEvent.user_id == completion.user_id,
        LearningEvent.problem_id == completion.problem_id,
        LearningEvent.attempt_sequence < completion.attempt_sequence,
        LearningEvent.event_type.in_(_HINT_TYPES),
    )))
    requests = sum(hint.event_type == LearningEventType.HINT_REQUESTED.value for hint in hints)
    levels = [level for hint in hints if hint.event_type == LearningEventType.HINT_DELIVERED.value
              for level in [hint.evidence.get("hint_level_delivered")]
              if type(level) is int and 1 <= level <= 6]
    return requests, levels, bool(hints)


def rebuild_skill_state(
    db: Session, user_id: int, skill_id: int, provider: KnowledgeTracingProvider | None = None,
) -> SkillState | None:
    """Replay terminal reporting and eligible binary observations independently."""

    db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    tracer = provider if provider is not None else BKTProvider(load_bkt_parameters())
    events = list(db.scalars(
        select(LearningEvent).where(
            LearningEvent.user_id == user_id,
            LearningEvent.skill_id == skill_id,
            LearningEvent.event_type == LearningEventType.ATTEMPT_COMPLETED.value,
        ).order_by(LearningEvent.id)
    ))
    observations: list[TracingObservation] = []
    reporting_events: list[LearningEvent] = []
    durations: list[int] = []
    delivered_levels: list[int] = []
    hint_count_total = 0
    successful_attempt_count = 0
    independent_solve_count = 0
    hint_dependent_count = 0
    seen_attempts: set[int] = set()
    for event in events:
        if event.attempt_id in seen_attempts or not _reportable_completion(event):
            continue
        seen_attempts.add(event.attempt_id)
        reporting_events.append(event)
        observation = _eligible_observation(db, event)
        if observation is not None:
            observations.append(observation)
        requests, levels, has_hint_action = _hint_reporting(db, event)
        hint_count_total += requests
        delivered_levels.extend(levels)
        if event.evidence.get("outcome") == "SOLVED":
            successful_attempt_count += 1
            if has_hint_action:
                hint_dependent_count += 1
            else:
                independent_solve_count += 1
        duration_ms = event.evidence.get("total_duration_ms")
        if isinstance(duration_ms, int) and not isinstance(duration_ms, bool) and duration_ms >= 0:
            durations.append(duration_ms)
    if not reporting_events:
        return None

    snapshot = tracer.replay_skill_state(observations)
    last_event = reporting_events[-1]
    last_successful = max((_utc_time(event.occurred_at) for event in reporting_events
                           if event.evidence["outcome"] == "SOLVED"), default=None)
    state = db.get(SkillState, (user_id, skill_id))
    if state is None:
        state = SkillState(user_id=user_id, skill_id=skill_id)
        db.add(state)
    state.mastery_probability = snapshot.mastery_probability
    state.mastery_uncertainty = snapshot.mastery_uncertainty
    state.attempt_count = len(reporting_events)
    state.successful_attempt_count = successful_attempt_count
    state.independent_solve_count = independent_solve_count
    state.hint_dependent_count = hint_dependent_count
    state.hint_count_total = hint_count_total
    state.average_hint_level = (sum(delivered_levels) / len(delivered_levels) if delivered_levels else None)
    state.average_duration_ms = sum(durations) / len(durations) if durations else None
    state.recent_error_types = None
    state.last_attempt_at = max(_utc_time(event.occurred_at) for event in reporting_events)
    state.last_successful_at = last_successful
    state.retention_signal = None
    state.last_evidence_event_id = last_event.id
    state.model_version = snapshot.model_version
    state.param_version = snapshot.param_version
    state.observation_rule_version = OBSERVATION_RULE_VERSION
    state.attribution_rule_version = ATTRIBUTION_RULE_VERSION
    db.flush()
    return state


def project_completion_event(db: Session, event: LearningEvent) -> SkillState | None:
    """Project the new event within the same transaction as Attempt closure."""

    if event.event_type != LearningEventType.ATTEMPT_COMPLETED.value or event.skill_id is None:
        return None
    return rebuild_skill_state(db, event.user_id, event.skill_id)


def list_skill_states(db: Session, user_id: int) -> list[SkillState]:
    """Return projections for the single authenticated-by-context MVP learner."""

    return list(db.scalars(select(SkillState).where(SkillState.user_id == user_id)
                           .order_by(SkillState.skill_id)))


def get_skill_state(db: Session, user_id: int, skill_id: int) -> SkillState | None:
    """Find one projection without exposing its internal provenance columns."""

    return db.get(SkillState, (user_id, skill_id))
