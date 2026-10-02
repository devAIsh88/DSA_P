"""Materialize allowlisted adaptive inputs without projecting learner state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.problem_skill import ProblemSkill
from app.models.skill_state import SkillState
from app.schemas.recommendation import (
    RecommendationCandidate, RecommendationContext, RecommendationPolicyConfig,
    RecommendationSkillState, TerminalEvidence,
)
from app.services.bkt_provider import MODEL_VERSION, load_bkt_parameters
from app.services.learner_state_service import (
    ATTRIBUTION_RULE_VERSION, OBSERVATION_RULE_VERSION, eligible_binary_observation, reportable_completion,
)


class LearnerStateNotReadyError(Exception):
    """A supported projection does not match its immutable source history."""


def utc_time(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class AdaptiveInputs:
    context: RecommendationContext
    snapshot: dict[str, Any]
    fingerprint: str
    through_event_id: int | None
    event_count: int


def _catalogue(db: Session) -> tuple[tuple[RecommendationCandidate, ...], list[dict[str, Any]]]:
    """Load candidate metadata and every mapping, not arbitrary first/primary skills."""

    rows = list(db.execute(select(
        Problem.id, Problem.difficulty, Problem.target_track, ProblemSkill.skill_id, ProblemSkill.weight,
    ).outerjoin(ProblemSkill, ProblemSkill.problem_id == Problem.id).order_by(Problem.id, ProblemSkill.skill_id)))
    grouped: dict[int, dict[str, Any]] = {}
    for problem_id, difficulty, target_track, skill_id, weight in rows:
        item = grouped.setdefault(problem_id, {
            "problem_id": problem_id, "difficulty": difficulty, "target_track": target_track, "mappings": [],
        })
        if skill_id is not None:
            item["mappings"].append({"skill_id": skill_id, "weight": weight})
    candidates = []
    for item in grouped.values():
        mappings = item["mappings"]
        skill_id = None
        if not mappings:
            status = "unmapped"
        elif len(mappings) > 1:
            status = "multiple_skills_require_policy"
        elif mappings[0]["weight"] != 1.0:
            status = "nonunit_weight_requires_policy"
        else:
            status, skill_id = "single_skill", mappings[0]["skill_id"]
        candidates.append(RecommendationCandidate(
            problem_id=item["problem_id"], difficulty=item["difficulty"], target_track=item["target_track"],
            mapping_status=status, skill_id=skill_id,
        ))
    return tuple(candidates), list(grouped.values())


def _terminal_facts(db: Session, events: list[LearningEvent]) -> tuple[TerminalEvidence, ...]:
    """Validate lifecycle, source, evaluation and hints; retain no private payload text."""

    facts = []
    seen: set[int] = set()
    by_attempt: dict[int, list[LearningEvent]] = {}
    for event in events:
        by_attempt.setdefault(event.attempt_id, []).append(event)
    for event in events:
        if event.event_type != "ATTEMPT_COMPLETED" or event.attempt_id in seen:
            continue
        provenance = event.provenance or {}
        evidence = event.evidence
        if (not isinstance(provenance, dict) or not isinstance(evidence, dict)
                or provenance.get("source") != "learner"
                or not isinstance(provenance.get("validation"), dict)
                or provenance["validation"].get("source") != "deterministic_rule"
                or provenance["validation"].get("rule_id") != "attempt_close_v1"):
            continue
        status, outcome = evidence.get("status"), evidence.get("outcome")
        if not ((status == "COMPLETED" and outcome in ("SOLVED", "GAVE_UP"))
                or (status == "ABANDONED" and outcome is None)):
            continue
        prior = [item for item in by_attempt[event.attempt_id]
                 if item.attempt_sequence < event.attempt_sequence and item.id < event.id
                 and item.problem_id == event.problem_id and item.user_id == event.user_id]
        final_id = evidence.get("final_submission_id")
        evaluation = next((item for item in prior if item.event_type == "SUBMISSION_EVALUATED"
                           and type(final_id) is int and item.submission_id == final_id
                           and isinstance(item.provenance, dict)
                           and item.provenance.get("source") == "execution_evaluation_engine"), None)
        final_status = evaluation.evidence.get("overall_status") if evaluation is not None else None
        if outcome == "SOLVED":
            total = evaluation.evidence.get("tests_total") if evaluation is not None else None
            passed = evaluation.evidence.get("tests_passed") if evaluation is not None else None
            if final_status != "ACCEPTED" or type(total) is not int or total <= 0 or passed != total:
                continue
        hints = [item for item in prior if item.event_type in ("HINT_REQUESTED", "HINT_DELIVERED")]
        levels = [item.evidence.get("hint_level_delivered") for item in hints
                  if item.event_type == "HINT_DELIVERED"]
        max_level = max((level for level in levels if type(level) is int and 1 <= level <= 6), default=0)
        observation = eligible_binary_observation(db, event)
        supported = reportable_completion(event)
        seen.add(event.attempt_id)
        facts.append(TerminalEvidence(
            event_id=event.id, attempt_id=event.attempt_id, problem_id=event.problem_id,
            skill_id=event.skill_id if supported else None, occurred_at=event.occurred_at,
            status=status, outcome=outcome, final_status=final_status,
            binary_correct=int(observation.correct) if observation is not None else None,
            max_hint_level=max_level, hint_requests=sum(item.event_type == "HINT_REQUESTED" for item in hints),
            has_hint_action=bool(hints),
        ))
    return tuple(facts)


def load_adaptive_inputs(
    db: Session, user_id: int, now: datetime, config: RecommendationPolicyConfig,
) -> AdaptiveInputs:
    """Read a complete explicit snapshot; never call learner-state rebuilding."""

    events = list(db.scalars(select(LearningEvent).where(LearningEvent.user_id == user_id)
                           .order_by(LearningEvent.id).execution_options(populate_existing=True)))
    through = events[-1].id if events else None
    candidates, catalogue = _catalogue(db)
    facts = _terminal_facts(db, events)
    states = list(db.scalars(select(SkillState).where(SkillState.user_id == user_id)
                           .order_by(SkillState.skill_id).execution_options(populate_existing=True)))
    expected: dict[int, list[LearningEvent]] = {}
    seen: set[int] = set()
    for event in events:
        if event.attempt_id not in seen and reportable_completion(event):
            expected.setdefault(event.skill_id, []).append(event)
            seen.add(event.attempt_id)
    by_skill = {state.skill_id: state for state in states}
    param_version = load_bkt_parameters().version
    for skill_id, history in expected.items():
        state = by_skill.get(skill_id)
        if (state is None or state.last_evidence_event_id != history[-1].id
                or state.attempt_count != len(history)
                or state.model_version != MODEL_VERSION or state.param_version != param_version
                or state.observation_rule_version != OBSERVATION_RULE_VERSION
                or state.attribution_rule_version != ATTRIBUTION_RULE_VERSION):
            raise LearnerStateNotReadyError
    if set(by_skill) - set(expected):
        raise LearnerStateNotReadyError
    projections = tuple(RecommendationSkillState(
        skill_id=state.skill_id, mastery_probability=state.mastery_probability,
        attempt_count=state.attempt_count, successful_attempt_count=state.successful_attempt_count,
        hint_dependent_count=state.hint_dependent_count, last_attempt_at=state.last_attempt_at,
    ) for state in states)
    context = RecommendationContext(evaluated_at=utc_time(now), candidates=candidates, attempts=facts, skills=projections)
    metadata = [{"skill_id": state.skill_id, "last_evidence_event_id": state.last_evidence_event_id,
                 "model_version": state.model_version, "param_version": state.param_version,
                 "observation_rule_version": state.observation_rule_version,
                 "attribution_rule_version": state.attribution_rule_version} for state in states]
    snapshot = {"context": context.model_dump(mode="json"), "policy": config.model_dump(mode="json"),
                "evidence": {"through_event_id": through, "event_count": len(events),
                             "event_ids": [item.id for item in events]},
                "catalogue": catalogue, "projection_versions": metadata}
    # Time invalidates through an explicit review boundary, not every GET microsecond.
    identity = {**snapshot, "context": {key: value for key, value in snapshot["context"].items()
                                       if key != "evaluated_at"}}
    digest = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return AdaptiveInputs(context, snapshot, digest, through, len(events))
