"""Atomic recommendation consumption through the existing Attempt lifecycle."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from adaptive_fixtures import FrozenClock, NOW, create_adaptive_database
from app.models.attempt import Attempt
from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.recommendation import Recommendation
from app.models.skill_state import SkillState
from app.models.user import User
from app.schemas.attempt import AttemptStart
from app.schemas.learning_event import LearningEventType
from app.schemas.recommendation import RecommendationPolicyConfig
from app.services import attempt_service, learning_event_service, recommendation_service
from app.services.attempt_service import AttemptConflictError, LearnerIdentityError
from app.services.recommendation_service import ActiveAttemptError, get_next_recommendation


@pytest.fixture
def adaptive_db(monkeypatch):
    harness, engine = create_adaptive_database(monkeypatch)
    try:
        yield harness
    finally:
        engine.dispose()


def issue(harness, *, now=NOW):
    with harness.factory() as db:
        return get_next_recommendation(db, now=now).recommendation


def record(harness, record_id):
    with harness.factory() as db:
        return db.get(Recommendation, record_id)


def counts(harness):
    with harness.factory() as db:
        return tuple(db.scalar(select(func.count()).select_from(model))
                     for model in (Attempt, LearningEvent, Recommendation))


def learner_states(harness):
    with harness.factory() as db:
        return [tuple(getattr(row, column.name) for column in SkillState.__table__.columns)
                for row in db.scalars(select(SkillState).order_by(SkillState.user_id, SkillState.skill_id))]


def test_fresh_matching_problem_consumes_with_opening_evidence(adaptive_db):
    chosen = issue(adaptive_db)
    attempt_id = adaptive_db.start(chosen.problem_id, key="following-recommendation")
    stored = record(adaptive_db, chosen.id)
    assert stored.consumed_attempt_id == attempt_id
    assert stored.consumed_at is not None and stored.superseded_at is None
    assert stored.reason_codes == ["COLD_START"]
    assert stored.evidence_event_count == 0 and stored.evidence_through_event_id is None
    assert counts(adaptive_db) == (1, 1, 1)
    with adaptive_db.factory() as db:
        opening = db.scalar(select(LearningEvent).where(LearningEvent.attempt_id == attempt_id))
        assert opening.event_type == "ATTEMPT_STARTED"
        assert opening.evidence["problem_id"] == chosen.problem_id
        assert db.get(Attempt, attempt_id).status == "ACTIVE"
        assert db.scalar(select(func.count()).select_from(SkillState)) == 0


def test_starting_different_problem_supersedes_without_claiming_consumption(adaptive_db):
    chosen = issue(adaptive_db)
    different = 2 if chosen.problem_id != 2 else 1
    adaptive_db.start(different)
    stored = record(adaptive_db, chosen.id)
    assert stored.superseded_at is not None
    assert stored.consumed_at is None and stored.consumed_attempt_id is None


@pytest.mark.parametrize("change", ["policy", "catalogue", "evidence"])
def test_changed_inputs_make_matching_problem_stale(adaptive_db, monkeypatch, change):
    solved = adaptive_db.solve(1)
    chosen = issue(adaptive_db)
    before_states = learner_states(adaptive_db)
    if change == "policy":
        monkeypatch.setattr(recommendation_service, "load_policy_config",
                            lambda: RecommendationPolicyConfig(version="adaptive-test-v2"))
    elif change == "catalogue":
        with adaptive_db.factory() as db:
            db.get(Problem, chosen.problem_id).difficulty = "Medium"
            db.commit()
    else:
        with adaptive_db.factory() as db:
            learning_event_service.append_event(
                db, solved, LearningEventType.UNDERSTANDING_CHECK,
                {"stage": "PROMPTED", "question": "Explain why it works"},
                {"source": "deterministic_rule"},
            )
            db.commit()
    adaptive_db.start(chosen.problem_id)
    stored = record(adaptive_db, chosen.id)
    assert stored.superseded_at is not None
    assert stored.consumed_at is None and stored.consumed_attempt_id is None
    assert learner_states(adaptive_db) == before_states


def test_reached_review_deadline_makes_matching_problem_stale(adaptive_db):
    FrozenClock.value = NOW - timedelta(days=6)
    adaptive_db.solve(1)
    adaptive_db.solve(2)
    chosen = issue(adaptive_db)
    assert chosen.action_type == "INCREASE_DIFFICULTY"
    before_states = learner_states(adaptive_db)
    FrozenClock.value = NOW + timedelta(days=1)
    adaptive_db.start(chosen.problem_id)
    stored = record(adaptive_db, chosen.id)
    assert stored.superseded_at is not None and stored.consumed_at is None
    assert learner_states(adaptive_db) == before_states


def test_inputs_changing_during_freshness_check_supersede_instead_of_consume(adaptive_db, monkeypatch):
    chosen = issue(adaptive_db)
    original = recommendation_service.load_adaptive_inputs
    calls = 0

    def changed_inputs(*args, **kwargs):
        nonlocal calls
        calls += 1
        inputs = original(*args, **kwargs)
        # Emulate a committed catalogue/evidence change between input assembly
        # and its validation. The recommendation must not be credited as followed.
        return replace(inputs, fingerprint="d" * 64) if calls == 2 else inputs

    monkeypatch.setattr(recommendation_service, "load_adaptive_inputs", changed_inputs)
    adaptive_db.start(chosen.problem_id)
    stored = record(adaptive_db, chosen.id)
    assert calls == 2
    assert stored.superseded_at is not None
    assert stored.consumed_at is None and stored.consumed_attempt_id is None
    assert counts(adaptive_db) == (1, 1, 1)


def test_idempotent_existing_attempt_does_not_consume_newer_recommendation(adaptive_db):
    earlier = adaptive_db.start(1, key="old-start")
    adaptive_db.submit(earlier)
    adaptive_db.complete(earlier)
    chosen = issue(adaptive_db)
    before = counts(adaptive_db)
    retried = adaptive_db.start(1, key="old-start")
    assert retried == earlier
    stored = record(adaptive_db, chosen.id)
    assert stored.consumed_at is None and stored.superseded_at is None
    assert counts(adaptive_db) == before


@pytest.mark.parametrize("failure", ["opening_event", "commit"])
@pytest.mark.parametrize("matching", [True, False])
def test_failed_creation_rolls_back_attempt_event_and_recommendation(adaptive_db, monkeypatch, failure, matching):
    chosen = issue(adaptive_db)
    before = counts(adaptive_db)
    problem_id = chosen.problem_id if matching else 2
    with adaptive_db.factory() as db:
        if failure == "opening_event":
            def fail_event(*_args, **_kwargs):
                raise RuntimeError("controlled opening event failure")
            monkeypatch.setattr(attempt_service, "append_event", fail_event)
            expected = RuntimeError
        else:
            def fail_commit():
                raise SQLAlchemyError("controlled commit failure")
            monkeypatch.setattr(db, "commit", fail_commit)
            expected = SQLAlchemyError
        with pytest.raises(expected):
            attempt_service.start_attempt(db, AttemptStart(user_id=1, problem_id=problem_id))
        # The service must roll back immediately, rather than depending on the
        # caller closing its Session to erase partial writes.
        stored = db.get(Recommendation, chosen.id)
        assert stored.consumed_at is None and stored.superseded_at is None
        assert db.scalar(select(func.count()).select_from(Attempt)) == before[0]
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == before[1]
    assert counts(adaptive_db) == before


def test_no_recommendation_preserves_ordinary_attempt_behavior(adaptive_db):
    first = adaptive_db.start(1)
    with pytest.raises(AttemptConflictError):
        adaptive_db.start(1)
    second = adaptive_db.start(2)
    assert first != second
    assert counts(adaptive_db) == (2, 2, 0)
    with adaptive_db.factory() as db:
        with pytest.raises(ActiveAttemptError) as error:
            get_next_recommendation(db, now=NOW)
        assert error.value.attempt_ids == sorted([first, second])
    assert counts(adaptive_db) == (2, 2, 0)


@pytest.mark.parametrize("terminal", ["consumed", "superseded"])
def test_start_does_not_rewrite_terminal_recommendation(adaptive_db, terminal):
    chosen = issue(adaptive_db)
    problem_id = chosen.problem_id if terminal == "consumed" else 2
    earlier = adaptive_db.start(problem_id)
    before = record(adaptive_db, chosen.id)
    with adaptive_db.factory() as db:
        attempt_service.abandon_attempt(db, earlier)
    later = adaptive_db.start(chosen.problem_id)
    assert later != earlier
    after = record(adaptive_db, chosen.id)
    assert after.consumed_at == before.consumed_at
    assert after.consumed_attempt_id == before.consumed_attempt_id
    assert after.superseded_at == before.superseded_at


def test_wrong_learner_identity_cannot_change_recommendation(adaptive_db):
    chosen = issue(adaptive_db)
    with adaptive_db.factory() as db:
        with pytest.raises(LearnerIdentityError):
            attempt_service.start_attempt(db, AttemptStart(user_id=999, problem_id=chosen.problem_id))
    stored = record(adaptive_db, chosen.id)
    assert stored.consumed_at is None and stored.superseded_at is None
    assert counts(adaptive_db) == (0, 0, 1)


def test_ambiguous_learner_identity_cannot_change_recommendation(adaptive_db):
    chosen = issue(adaptive_db)
    with adaptive_db.factory() as db:
        db.add(User(id=2))
        db.commit()
        with pytest.raises(LearnerIdentityError):
            attempt_service.start_attempt(db, AttemptStart(user_id=1, problem_id=chosen.problem_id))
    stored = record(adaptive_db, chosen.id)
    assert stored.consumed_at is None and stored.superseded_at is None
    assert counts(adaptive_db) == (0, 0, 1)
