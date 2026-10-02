"""Recommendation orchestration over genuine, disposable learner evidence."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError

from adaptive_fixtures import FrozenClock, NOW, PRIVATE_MARKERS, create_adaptive_database
from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.problem_skill import ProblemSkill
from app.models.recommendation import Recommendation
from app.models.skill_state import SkillState
from app.models.user import User
from app.schemas.recommendation import RecommendationPolicyConfig
from app.services import recommendation_service
from app.services.attempt_service import LearnerIdentityError, LearnerNotFoundError
from app.services.recommendation_context import LearnerStateNotReadyError, load_adaptive_inputs
from app.services.recommendation_service import ActiveAttemptError, RecommendationUnavailableError, get_next_recommendation


@pytest.fixture
def adaptive_db(monkeypatch):
    harness, engine = create_adaptive_database(monkeypatch)
    try:
        yield harness
    finally:
        engine.dispose()


def next_result(harness, *, now=NOW, config=None):
    with harness.factory() as db:
        return get_next_recommendation(db, now=now, config=config)


def stored_rows(harness):
    with harness.factory() as db:
        return list(db.scalars(select(Recommendation).order_by(Recommendation.id)))


def source_snapshot(harness):
    with harness.factory() as db:
        events = [dict((column.name, getattr(row, column.name)) for column in LearningEvent.__table__.columns)
                  for row in db.scalars(select(LearningEvent).order_by(LearningEvent.id))]
        states = [dict((column.name, getattr(row, column.name)) for column in SkillState.__table__.columns)
                  for row in db.scalars(select(SkillState).order_by(SkillState.skill_id))]
        return json.dumps({"events": events, "states": states}, sort_keys=True, default=str)


def test_first_decision_persists_and_identical_evidence_reuses_active_record(adaptive_db) -> None:
    first = next_result(adaptive_db)
    second = next_result(adaptive_db, now=NOW + timedelta(hours=1))
    assert first.recommendation.id == second.recommendation.id
    assert first == second
    assert first.recommendation.problem_id == 1
    assert first.recommendation.reason_codes == ("COLD_START",)
    rows = stored_rows(adaptive_db)
    assert len(rows) == 1
    assert rows[0].evidence_through_event_id is None and rows[0].evidence_event_count == 0
    assert rows[0].policy_version == "adaptive-rules-v1"
    assert len(rows[0].input_fingerprint) == 64
    assert rows[0].input_snapshot["policy"]["weak_min_observations"] == 2


def test_new_committed_history_supersedes_previous_decision_atomically(adaptive_db) -> None:
    first = next_result(adaptive_db)
    adaptive_db.solve(1)
    second = next_result(adaptive_db)
    assert first.recommendation.id != second.recommendation.id
    assert second.recommendation.problem_id == 4
    rows = stored_rows(adaptive_db)
    # Attempt integration may consume the first row once the later stage is present.
    assert rows[0].consumed_at is not None or rows[0].superseded_at is not None
    assert rows[1].consumed_at is None and rows[1].superseded_at is None
    assert rows[1].evidence_event_count == 3
    assert rows[1].evidence_through_event_id == rows[1].input_snapshot["evidence"]["event_ids"][-1]


def test_later_lower_id_event_is_detected_even_when_maximum_id_is_unchanged(adaptive_db) -> None:
    attempt_id = adaptive_db.solve(1)
    # Explicit IDs emulate a PostgreSQL sequence value allocated before another
    # transaction committed. These are new rows, never edits to historical rows.
    with adaptive_db.factory() as db:
        db.add(LearningEvent(
            id=100, user_id=1, attempt_id=attempt_id, problem_id=1,
            event_type="UNDERSTANDING_CHECK", occurred_at=NOW, attempt_sequence=4,
            evidence={"stage": "PROMPTED", "question": "Explain it"},
            provenance={"source": "deterministic_rule"},
        ))
        db.commit()
    first = next_result(adaptive_db)
    with adaptive_db.factory() as db:
        db.add(LearningEvent(
            id=50, user_id=1, attempt_id=attempt_id, problem_id=1,
            event_type="UNDERSTANDING_CHECK", occurred_at=NOW, attempt_sequence=5,
            evidence={"stage": "ANSWERED", "answer_text": "learner answer"},
            provenance={"source": "learner"},
        ))
        db.commit()
    second = next_result(adaptive_db)
    assert first.recommendation.id != second.recommendation.id
    rows = stored_rows(adaptive_db)
    assert rows[0].evidence_through_event_id == rows[1].evidence_through_event_id == 100
    assert rows[1].evidence_event_count == rows[0].evidence_event_count + 1
    assert 50 in rows[1].input_snapshot["evidence"]["event_ids"]
    assert rows[0].superseded_at is not None


def test_scheduled_review_invalidates_without_any_new_learning_event(adaptive_db) -> None:
    FrozenClock.value = NOW - timedelta(days=6)
    adaptive_db.solve(1)
    adaptive_db.solve(2)
    first = next_result(adaptive_db)
    assert first.recommendation.action_type == "INCREASE_DIFFICULTY"
    first_sources = source_snapshot(adaptive_db)
    due = NOW + timedelta(days=1)
    before_due = next_result(adaptive_db, now=due - timedelta(seconds=1))
    assert before_due.recommendation.id == first.recommendation.id
    at_due = next_result(adaptive_db, now=due)
    assert at_due.recommendation.id != first.recommendation.id
    assert at_due.recommendation.action_type == "REVISE_CONCEPT"
    assert at_due.recommendation.problem_id == 2
    assert at_due.recommendation.reason_codes == ("SCHEDULED_REVIEW_DUE",)
    rows = stored_rows(adaptive_db)
    assert rows[0].reevaluate_at.replace(tzinfo=NOW.tzinfo) == due
    assert rows[0].evidence_event_count == rows[1].evidence_event_count
    assert source_snapshot(adaptive_db) == first_sources


def test_policy_version_and_config_changes_recompute(adaptive_db) -> None:
    first = next_result(adaptive_db)
    alternate = RecommendationPolicyConfig(version="adaptive-test-v2", target_track="placement")
    with adaptive_db.factory() as db:
        db.get(Problem, 2).target_track = "placement"
        db.commit()
    second = next_result(adaptive_db, config=alternate)
    assert second.recommendation.id != first.recommendation.id
    assert second.recommendation.problem_id == 2
    assert second.recommendation.policy_version == "adaptive-test-v2"
    assert stored_rows(adaptive_db)[0].superseded_at is not None


def test_policy_version_alone_invalidates_identical_evidence_and_catalogue(adaptive_db) -> None:
    first = next_result(adaptive_db)
    second = next_result(adaptive_db, config=RecommendationPolicyConfig(version="adaptive-test-v2"))
    assert second.recommendation.id != first.recommendation.id
    assert second.recommendation.problem_id == first.recommendation.problem_id
    assert second.recommendation.policy_version == "adaptive-test-v2"
    rows = stored_rows(adaptive_db)
    assert rows[0].evidence_event_count == rows[1].evidence_event_count == 0
    assert rows[0].superseded_at is not None


def test_catalogue_change_invalidates_even_without_new_learning_event(adaptive_db) -> None:
    first = next_result(adaptive_db)
    with adaptive_db.factory() as db:
        db.get(Problem, 1).difficulty = "Hard"
        db.commit()
    second = next_result(adaptive_db)
    assert first.recommendation.id != second.recommendation.id
    assert second.recommendation.problem_id == 2
    rows = stored_rows(adaptive_db)
    assert rows[0].evidence_event_count == rows[1].evidence_event_count == 0
    assert rows[0].input_snapshot["catalogue"][0]["difficulty"] == "Easy"
    assert rows[1].input_snapshot["catalogue"][0]["difficulty"] == "Hard"


def test_mapping_change_invalidates_without_normalization_or_historical_mutation(adaptive_db) -> None:
    first = next_result(adaptive_db)
    with adaptive_db.factory() as db:
        db.get(ProblemSkill, (1, 1)).weight = 0.5
        db.commit()
    second = next_result(adaptive_db)
    assert first.recommendation.id != second.recommendation.id
    assert second.recommendation.problem_id == 2
    assert stored_rows(adaptive_db)[1].input_snapshot["catalogue"][0]["mappings"] == [{"skill_id": 1, "weight": 0.5}]


@pytest.mark.parametrize("column,value", [
    ("model_version", "unknown"), ("param_version", "unknown"),
    ("observation_rule_version", "unknown"), ("attribution_rule_version", "unknown"),
    ("last_evidence_event_id", 1), ("attempt_count", 99),
])
def test_incompatible_or_stale_projection_is_rejected_without_rebuild(adaptive_db, column, value) -> None:
    adaptive_db.solve(1)
    with adaptive_db.factory() as db:
        setattr(db.get(SkillState, (1, 1)), column, value)
        db.commit()
    before = source_snapshot(adaptive_db)
    with pytest.raises(LearnerStateNotReadyError):
        next_result(adaptive_db)
    assert not stored_rows(adaptive_db)
    assert source_snapshot(adaptive_db) == before


def test_missing_projection_with_supported_history_is_not_silently_rebuilt(adaptive_db) -> None:
    adaptive_db.solve(1)
    with adaptive_db.factory() as db:
        db.delete(db.get(SkillState, (1, 1)))
        db.commit()
    with pytest.raises(LearnerStateNotReadyError):
        next_result(adaptive_db)
    with adaptive_db.factory() as db:
        assert db.get(SkillState, (1, 1)) is None
    assert not stored_rows(adaptive_db)


def test_active_attempt_gate_returns_sorted_ids_without_recommendation_mutation(adaptive_db) -> None:
    first = next_result(adaptive_db)
    second_attempt = adaptive_db.start(2)
    first_attempt = adaptive_db.start(1)
    rows_before = [(row.id, row.consumed_at, row.superseded_at) for row in stored_rows(adaptive_db)]
    with pytest.raises(ActiveAttemptError) as caught:
        next_result(adaptive_db)
    assert caught.value.attempt_ids == sorted([first_attempt, second_attempt])
    assert [(row.id, row.consumed_at, row.superseded_at) for row in stored_rows(adaptive_db)] == rows_before
    assert len(stored_rows(adaptive_db)) == 1


def test_unsupported_mapping_does_not_fabricate_skill_state(adaptive_db) -> None:
    with adaptive_db.factory() as db:
        db.add(ProblemSkill(problem_id=1, skill_id=2, weight=1.0))
        for problem in (2, 3, 4, 5):
            db.get(Problem, problem).difficulty = "Unknown"
        db.commit()
    adaptive_db.solve(1)
    result = next_result(adaptive_db)
    assert result.recommendation is None
    assert result.unavailable_reason == "CATALOGUE_EXHAUSTED"
    with adaptive_db.factory() as db:
        assert db.scalar(select(func.count()).select_from(SkillState)) == 0


def test_new_supported_mapping_does_not_reattribute_old_assisted_completion(adaptive_db) -> None:
    with adaptive_db.factory() as db:
        db.delete(db.get(ProblemSkill, (1, 1)))
        for problem in (2, 3, 4, 5):
            db.get(Problem, problem).difficulty = "Unknown"
        db.commit()
    adaptive_db.solve(1, hint_level=1)
    with adaptive_db.factory() as db:
        db.add(ProblemSkill(problem_id=1, skill_id=1, weight=1.0))
        db.commit()
    before = source_snapshot(adaptive_db)
    result = next_result(adaptive_db)
    assert result.recommendation is None
    assert result.unavailable_reason == "CATALOGUE_EXHAUSTED"
    assert source_snapshot(adaptive_db) == before
    with adaptive_db.factory() as db:
        assert db.scalar(select(func.count()).select_from(SkillState)) == 0


def test_supersession_to_empty_result_creates_no_fake_recommendation(adaptive_db) -> None:
    first = next_result(adaptive_db)
    with adaptive_db.factory() as db:
        for problem in db.scalars(select(Problem)):
            problem.difficulty = "Unknown"
        db.commit()
    result = next_result(adaptive_db)
    assert result.recommendation is None
    assert result.unavailable_reason == "NO_ELIGIBLE_PROBLEM"
    rows = stored_rows(adaptive_db)
    assert len(rows) == 1 and rows[0].id == first.recommendation.id
    assert rows[0].superseded_at is not None


def test_empty_catalogue_creates_no_recommendation(adaptive_db) -> None:
    with adaptive_db.factory() as db:
        for problem in list(db.scalars(select(Problem))):
            db.delete(problem)
        db.commit()
    result = next_result(adaptive_db)
    assert result.recommendation is None and result.unavailable_reason == "EMPTY_CATALOGUE"
    assert not stored_rows(adaptive_db)


def test_database_commit_failure_rolls_back_decision_and_prior_supersession(adaptive_db, monkeypatch) -> None:
    first = next_result(adaptive_db)
    with adaptive_db.factory() as db:
        db.get(Problem, 1).difficulty = "Hard"
        db.commit()
    with adaptive_db.factory() as db:
        def fail_commit():
            raise SQLAlchemyError("controlled persistence failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RecommendationUnavailableError):
            get_next_recommendation(db, now=NOW)
    rows = stored_rows(adaptive_db)
    assert len(rows) == 1 and rows[0].id == first.recommendation.id
    assert rows[0].superseded_at is None and rows[0].consumed_at is None


def test_unstable_input_boundary_retries_boundedly_without_persisted_answer(adaptive_db, monkeypatch) -> None:
    original = recommendation_service.load_adaptive_inputs
    calls = 0

    def changing_input(db, user_id, clock, config):
        nonlocal calls
        result = original(db, user_id, clock, config)
        calls += 1
        from dataclasses import replace
        return replace(result, fingerprint=f"{calls:064x}")

    monkeypatch.setattr(recommendation_service, "load_adaptive_inputs", changing_input)
    with pytest.raises(RecommendationUnavailableError):
        next_result(adaptive_db)
    assert calls == 6
    assert not stored_rows(adaptive_db)


def test_read_decisions_do_not_mutate_sources_or_leak_private_payloads(adaptive_db) -> None:
    adaptive_db.solve(1, hint_level=4, reasoning=True)
    before = source_snapshot(adaptive_db)
    response = next_result(adaptive_db)
    next_result(adaptive_db, now=NOW + timedelta(minutes=1))
    assert source_snapshot(adaptive_db) == before
    serialized = response.model_dump_json() + json.dumps(stored_rows(adaptive_db)[0].input_snapshot)
    assert all(marker not in serialized for marker in PRIVATE_MARKERS)
    assert set(response.recommendation.model_dump()) == {
        "id", "action_type", "problem_id", "skill_id", "policy_version", "reason_codes", "created_at",
    }


def test_snapshot_replays_with_exact_decision_and_versions(adaptive_db) -> None:
    adaptive_db.solve(1)
    response = next_result(adaptive_db)
    row = stored_rows(adaptive_db)[0]
    from app.schemas.recommendation import RecommendationContext
    from app.services.recommendation_policy import RecommendationPolicy

    context = RecommendationContext.model_validate(row.input_snapshot["context"])
    config = RecommendationPolicyConfig.model_validate(row.input_snapshot["policy"])
    replayed = RecommendationPolicy(config).recommend(context)
    assert replayed.decision.problem_id == response.recommendation.problem_id
    assert replayed.decision.action_type == response.recommendation.action_type
    assert replayed.decision.reason_codes == response.recommendation.reason_codes
    versions = row.input_snapshot["projection_versions"][0]
    assert versions["model_version"] == "bkt-v1"
    assert versions["observation_rule_version"] == "attempt-completion-binary-reporting-v1"
    assert versions["attribution_rule_version"] == "single-skill-v1"


def test_missing_or_ambiguous_learner_does_not_create_one(adaptive_db) -> None:
    with adaptive_db.factory() as db:
        db.add(User(id=2))
        db.commit()
    with pytest.raises(LearnerIdentityError):
        next_result(adaptive_db)
    with adaptive_db.factory() as db:
        db.delete(db.get(User, 1))
        db.delete(db.get(User, 2))
        db.commit()
    with pytest.raises(LearnerNotFoundError):
        next_result(adaptive_db)
    assert not stored_rows(adaptive_db)


@pytest.mark.parametrize("event_type", ["SUBMISSION_EVALUATED", "HINT_REQUESTED", "HINT_DELIVERED", "ATTEMPT_COMPLETED"])
@pytest.mark.parametrize("malformed", [[], "unstructured", None])
def test_corrupt_structured_history_fails_closed_without_mutation(adaptive_db, event_type, malformed) -> None:
    adaptive_db.solve(1, hint_level=4)
    # Core SQL represents external database corruption; normal application
    # services do not revise committed historical evidence.
    with adaptive_db.factory() as db:
        event_id = db.scalar(select(LearningEvent.id).where(LearningEvent.event_type == event_type))
        db.execute(update(LearningEvent).where(LearningEvent.id == event_id).values(evidence=malformed))
        db.commit()
    before = source_snapshot(adaptive_db)
    with pytest.raises(LearnerStateNotReadyError):
        next_result(adaptive_db)
    assert not stored_rows(adaptive_db)
    assert source_snapshot(adaptive_db) == before


@pytest.mark.parametrize("invalid_part", ["source", "validation_source", "validation_rule"])
def test_supported_completion_with_invalid_authority_fails_closed(adaptive_db, invalid_part) -> None:
    adaptive_db.solve(1)
    with adaptive_db.factory() as db:
        completion = db.scalar(select(LearningEvent).where(LearningEvent.event_type == "ATTEMPT_COMPLETED"))
        provenance = json.loads(json.dumps(completion.provenance))
        if invalid_part == "source":
            provenance["source"] = "llm_model"
        elif invalid_part == "validation_source":
            provenance["validation"]["source"] = "llm_model"
        else:
            provenance["validation"]["rule_id"] = "unknown_rule"
        db.execute(update(LearningEvent).where(LearningEvent.id == completion.id).values(provenance=provenance))
        db.commit()
    before = source_snapshot(adaptive_db)
    with pytest.raises(LearnerStateNotReadyError):
        next_result(adaptive_db)
    assert not stored_rows(adaptive_db)
    assert source_snapshot(adaptive_db) == before


@pytest.mark.parametrize("outcome", ["SOLVED", "GAVE_UP"])
@pytest.mark.parametrize("invalid_reference", [True, "1", -1])
def test_nonnull_malformed_submission_reference_fails_closed(adaptive_db, outcome, invalid_reference) -> None:
    if outcome == "SOLVED":
        adaptive_db.solve(1)
    else:
        adaptive_db.give_up(1)
    with adaptive_db.factory() as db:
        completion = db.scalar(select(LearningEvent).where(LearningEvent.event_type == "ATTEMPT_COMPLETED"))
        evidence = {**completion.evidence, "final_submission_id": invalid_reference}
        db.execute(update(LearningEvent).where(LearningEvent.id == completion.id).values(evidence=evidence))
        db.commit()
    before = source_snapshot(adaptive_db)
    with pytest.raises(LearnerStateNotReadyError):
        next_result(adaptive_db)
    assert not stored_rows(adaptive_db)
    assert source_snapshot(adaptive_db) == before


@pytest.mark.parametrize("outcome", ["SOLVED", "GAVE_UP"])
@pytest.mark.parametrize("broken_reference", ["missing_evaluation", "wrong_engine", "not_prior", "wrong_problem"])
def test_referenced_submission_needs_prior_matching_engine_evidence(adaptive_db, outcome, broken_reference) -> None:
    if outcome == "SOLVED":
        adaptive_db.solve(1)
    else:
        adaptive_db.give_up(1)
    with adaptive_db.factory() as db:
        evaluation = db.scalar(select(LearningEvent).where(LearningEvent.event_type == "SUBMISSION_EVALUATED"))
        if broken_reference == "missing_evaluation":
            db.execute(delete(LearningEvent).where(LearningEvent.id == evaluation.id))
        elif broken_reference == "wrong_engine":
            provenance = {**evaluation.provenance, "source": "llm_model"}
            db.execute(update(LearningEvent).where(LearningEvent.id == evaluation.id).values(provenance=provenance))
        elif broken_reference == "not_prior":
            db.execute(update(LearningEvent).where(LearningEvent.id == evaluation.id).values(attempt_sequence=4))
        else:
            db.execute(update(LearningEvent).where(LearningEvent.id == evaluation.id).values(problem_id=2))
        db.commit()
    before = source_snapshot(adaptive_db)
    with pytest.raises(LearnerStateNotReadyError):
        next_result(adaptive_db)
    assert not stored_rows(adaptive_db)
    assert source_snapshot(adaptive_db) == before


def test_boolean_passed_count_cannot_validate_solved_outcome(adaptive_db) -> None:
    adaptive_db.solve(1)
    with adaptive_db.factory() as db:
        evaluation = db.scalar(select(LearningEvent).where(LearningEvent.event_type == "SUBMISSION_EVALUATED"))
        # Python True == 1; an explicit integer check must distinguish this corruption.
        evidence = {**evaluation.evidence, "tests_total": 1, "tests_passed": True}
        db.execute(update(LearningEvent).where(LearningEvent.id == evaluation.id).values(evidence=evidence))
        db.commit()
    before = source_snapshot(adaptive_db)
    with pytest.raises(LearnerStateNotReadyError):
        next_result(adaptive_db)
    assert not stored_rows(adaptive_db)
    assert source_snapshot(adaptive_db) == before


def test_declared_give_up_without_submission_retains_valid_binary_evidence(adaptive_db) -> None:
    adaptive_db.give_up(1, evaluated=False)
    before = source_snapshot(adaptive_db)
    response = next_result(adaptive_db)
    assert response.recommendation is not None
    with adaptive_db.factory() as db:
        inputs = load_adaptive_inputs(db, 1, NOW, RecommendationPolicyConfig())
    terminal = inputs.context.attempts[0]
    assert terminal.final_status is None
    assert terminal.outcome == "GAVE_UP"
    assert terminal.binary_correct == 0
    assert source_snapshot(adaptive_db) == before


def test_loaded_abandonment_breaks_evaluated_demotion_run(adaptive_db) -> None:
    adaptive_db.give_up(3)
    abandoned_id = adaptive_db.abandon(3)
    adaptive_db.give_up(3)
    before = source_snapshot(adaptive_db)
    response = next_result(adaptive_db)
    assert response.recommendation.action_type == "RETRY_SIMILAR_PROBLEM"
    assert response.recommendation.reason_codes == ("EVALUATED_FAILURE_RETRY",)
    assert response.recommendation.problem_id == 3
    with adaptive_db.factory() as db:
        inputs = load_adaptive_inputs(db, 1, NOW, RecommendationPolicyConfig())
    abandoned = next(fact for fact in inputs.context.attempts if fact.attempt_id == abandoned_id)
    assert abandoned.status == "ABANDONED" and abandoned.skill_id == 1
    assert abandoned.binary_correct is None
    assert source_snapshot(adaptive_db) == before


def test_loaded_abandonment_breaks_independent_promotion_run(adaptive_db) -> None:
    adaptive_db.solve(1)
    abandoned_id = adaptive_db.abandon(1)
    adaptive_db.solve(2)
    with adaptive_db.factory() as db:
        assert db.get(SkillState, (1, 1)).mastery_probability >= 0.70
    before = source_snapshot(adaptive_db)
    response = next_result(adaptive_db)
    assert response.recommendation.action_type == "NEXT_PROBLEM"
    assert response.recommendation.reason_codes == ("UNPRACTICED_SKILL",)
    assert response.recommendation.problem_id == 4
    with adaptive_db.factory() as db:
        inputs = load_adaptive_inputs(db, 1, NOW, RecommendationPolicyConfig())
    abandoned = next(fact for fact in inputs.context.attempts if fact.attempt_id == abandoned_id)
    assert abandoned.status == "ABANDONED" and abandoned.skill_id == 1
    assert abandoned.binary_correct is None
    assert source_snapshot(adaptive_db) == before
