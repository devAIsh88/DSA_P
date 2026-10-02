"""Independent persistence and lifecycle checks for adaptive decision history."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # Register the existing foreign-key targets.
from app.db.base import Base
from app.models.attempt import Attempt
from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.recommendation import Recommendation
from app.models.skill import Skill
from app.models.user import User
from app.services.recommendation_lifecycle import consume_recommendation, supersede_recommendation


NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def recommendation_db() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite://", poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([User(id=1), User(id=2), Skill(id=1, name="Arrays")])
        db.add_all([
            Problem(id=1, title="First", description="d", difficulty="Easy", topic="Arrays"),
            Problem(id=2, title="Second", description="d", difficulty="Medium", topic="Arrays"),
        ])
        db.flush()
        db.add_all([
            Attempt(id=1, user_id=1, problem_id=1, status="COMPLETED", outcome="SOLVED"),
            Attempt(id=2, user_id=1, problem_id=1, status="ACTIVE"),
            Attempt(id=3, user_id=2, problem_id=1, status="ACTIVE"),
            Attempt(id=4, user_id=1, problem_id=2, status="ACTIVE"),
        ])
        db.flush()
        db.add(LearningEvent(id=1, user_id=1, attempt_id=1, problem_id=1, skill_id=1,
                             event_type="ATTEMPT_COMPLETED", occurred_at=NOW, attempt_sequence=1,
                             evidence={"outcome": "SOLVED"}, provenance={"source": "deterministic_rule"}))
        db.commit()
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def decision(**overrides) -> Recommendation:
    values = {
        "user_id": 1,
        "action_type": "NEXT_PROBLEM",
        "problem_id": 1,
        "skill_id": 1,
        "policy_version": "adaptive-rules-v1",
        "reason_codes": ["NEW_PROBLEM"],
        "evidence_through_event_id": 1,
        "evidence_event_count": 1,
        "input_snapshot": {"event_ids": [1], "policy": {"version": "adaptive-rules-v1"},
                           "model_version": "bkt-v1", "candidates": [{"problem_id": 1, "skill_id": 1}]},
        "input_fingerprint": "a" * 64,
        "created_at": NOW,
        "reevaluate_at": NOW + timedelta(days=7),
    }
    return Recommendation(**(values | overrides))


def test_decision_round_trip_preserves_evidence_snapshot_and_versions(recommendation_db):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        record_id = record.id
    with recommendation_db() as db:
        stored = db.get(Recommendation, record_id)
        assert stored.action_type == "NEXT_PROBLEM"
        assert stored.reason_codes == ["NEW_PROBLEM"]
        assert stored.policy_version == "adaptive-rules-v1"
        assert (stored.evidence_through_event_id, stored.evidence_event_count) == (1, 1)
        assert stored.input_snapshot == decision().input_snapshot
        assert stored.input_fingerprint == "a" * 64
        assert stored.reevaluate_at == (NOW + timedelta(days=7)).replace(tzinfo=None)
        assert stored.consumed_at is None and stored.superseded_at is None


def test_only_one_active_recommendation_per_learner(recommendation_db):
    with recommendation_db() as db:
        db.add(decision())
        db.commit()
        db.add(decision(problem_id=2))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 1
        db.add(decision(user_id=2))
        db.commit()
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 2


def test_cold_start_can_persist_empty_cursor_without_skill_attribution(recommendation_db):
    with recommendation_db() as db:
        record = decision(skill_id=None, evidence_through_event_id=None, evidence_event_count=0,
                          reason_codes=["COLD_START", "UNATTRIBUTED_CATALOGUE"])
        db.add(record)
        db.commit()
        db.refresh(record)
        assert record.skill_id is None
        assert (record.evidence_through_event_id, record.evidence_event_count) == (None, 0)


def test_explicit_abandoned_problem_retry_can_omit_skill(recommendation_db):
    with recommendation_db() as db:
        record = decision(action_type="RETRY_SIMILAR_PROBLEM", skill_id=None,
                          reason_codes=["ABANDONED_PROBLEM_RETRY"])
        db.add(record)
        db.commit()
        db.refresh(record)
        assert record.action_type == "RETRY_SIMILAR_PROBLEM"
        assert record.skill_id is None
        assert record.reason_codes == ["ABANDONED_PROBLEM_RETRY"]


def test_generic_null_skill_retry_is_rejected(recommendation_db):
    with recommendation_db() as db:
        db.add(decision(action_type="RETRY_SIMILAR_PROBLEM", skill_id=None,
                        reason_codes=["EVALUATED_FAILURE_RETRY"]))
        with pytest.raises(ValueError):
            db.flush()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 0


@pytest.mark.parametrize("transition", ["consume", "supersede"])
def test_terminal_history_allows_new_active_decision(recommendation_db, transition):
    with recommendation_db() as db:
        old = decision()
        db.add(old)
        db.commit()
        if transition == "consume":
            consume_recommendation(old, db.get(Attempt, 2), NOW + timedelta(seconds=1))
        else:
            supersede_recommendation(old, NOW + timedelta(seconds=1))
        db.flush()
        replacement = decision(problem_id=2)
        db.add(replacement)
        db.commit()
        records = db.scalars(select(Recommendation).order_by(Recommendation.id)).all()
        assert len(records) == 2
        assert records[1].consumed_at is None and records[1].superseded_at is None
        if transition == "consume":
            assert records[0].consumed_attempt_id == 2
        else:
            assert records[0].superseded_at is not None


@pytest.mark.parametrize("changes", [
    {"action_type": "RESUME"},
    {"evidence_event_count": -1},
    {"consumed_at": NOW},
    {"consumed_attempt_id": 2},
    {"consumed_at": NOW, "consumed_attempt_id": 2, "superseded_at": NOW},
    {"consumed_at": NOW - timedelta(seconds=1), "consumed_attempt_id": 2},
    {"superseded_at": NOW - timedelta(seconds=1)},
    {"action_type": "REVISE_CONCEPT", "skill_id": None},
    {"action_type": "INCREASE_DIFFICULTY", "skill_id": None},
    {"action_type": "DECREASE_DIFFICULTY", "skill_id": None},
])
def test_database_rejects_invalid_action_or_lifecycle(recommendation_db, changes):
    with recommendation_db() as db:
        db.add(decision(**changes))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 0


@pytest.mark.parametrize("field", ["user_id", "problem_id", "skill_id", "evidence_through_event_id",
                                  "consumed_attempt_id"])
def test_foreign_keys_reject_nonexistent_references(recommendation_db, field):
    changes = {field: 999}
    if field == "consumed_attempt_id":
        changes["consumed_at"] = NOW
    with recommendation_db() as db:
        db.add(decision(**changes))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("attempt_id", [1, 3, 4])
def test_consumption_rejects_closed_other_learner_or_other_problem(recommendation_db, attempt_id):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        with pytest.raises(ValueError, match="does not match"):
            consume_recommendation(record, db.get(Attempt, attempt_id), NOW)
        assert record.consumed_at is None and record.consumed_attempt_id is None


def test_consumption_rejects_attempt_without_persisted_identity(recommendation_db):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        transient = Attempt(user_id=1, problem_id=1, status="ACTIVE")
        with pytest.raises(ValueError, match="does not match"):
            consume_recommendation(record, transient, NOW)


@pytest.mark.parametrize("terminal", ["consumed", "superseded"])
def test_terminal_transition_cannot_repeat_or_change(recommendation_db, terminal):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        if terminal == "consumed":
            consume_recommendation(record, db.get(Attempt, 2), NOW)
        else:
            supersede_recommendation(record, NOW)
        db.commit()
        with pytest.raises(ValueError, match="already terminal"):
            supersede_recommendation(record, NOW)
        with pytest.raises(ValueError, match="already terminal"):
            consume_recommendation(record, db.get(Attempt, 2), NOW)


def test_rollback_restores_active_lifecycle_without_duplicate_history(recommendation_db):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        consume_recommendation(record, db.get(Attempt, 2), NOW)
        db.flush()
        db.rollback()
        db.refresh(record)
        assert record.consumed_at is None and record.consumed_attempt_id is None
        supersede_recommendation(record, NOW)
        db.flush()
        db.rollback()
        db.refresh(record)
        assert record.superseded_at is None
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 1


@pytest.mark.parametrize("field,value", [
    ("user_id", 2), ("action_type", "REVISE_CONCEPT"), ("problem_id", 2), ("skill_id", None),
    ("policy_version", "adaptive-rules-v2"), ("reason_codes", ["SCHEDULED_REVIEW_DUE"]),
    ("evidence_through_event_id", None), ("evidence_event_count", 2),
    ("input_snapshot", {"event_ids": []}), ("input_fingerprint", "b" * 64),
    ("created_at", NOW + timedelta(seconds=1)), ("reevaluate_at", None),
])
def test_committed_decision_fields_cannot_be_rewritten(recommendation_db, field, value):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        setattr(record, field, value)
        with pytest.raises(ValueError, match="decisions are immutable"):
            db.flush()
        db.rollback()


def test_committed_decision_cannot_be_deleted(recommendation_db):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        db.delete(record)
        with pytest.raises(ValueError, match="history cannot be deleted"):
            db.flush()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 1


def test_in_place_json_edits_do_not_persist_with_lifecycle_transition(recommendation_db):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        record.input_snapshot["event_ids"].append(999)
        record.reason_codes.append("SCHEDULED_REVIEW_DUE")
        supersede_recommendation(record, NOW)
        db.commit()
        db.refresh(record)
        assert record.input_snapshot["event_ids"] == [1]
        assert record.reason_codes == ["NEW_PROBLEM"]


@pytest.mark.parametrize("terminal", ["consumed", "superseded"])
def test_expired_terminal_record_cannot_be_reopened(recommendation_db, terminal):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        if terminal == "consumed":
            consume_recommendation(record, db.get(Attempt, 2), NOW)
        else:
            supersede_recommendation(record, NOW)
        db.commit()
        # No read of the expired terminal columns before assignment: protection
        # must still use the committed state rather than the new null values.
        record.consumed_at = None
        record.consumed_attempt_id = None
        record.superseded_at = None
        with pytest.raises(ValueError, match="Terminal recommendation"):
            db.flush()
        db.rollback()


def test_consumed_attempt_reference_cannot_be_changed(recommendation_db):
    with recommendation_db() as db:
        record = decision()
        db.add(record)
        db.commit()
        consume_recommendation(record, db.get(Attempt, 2), NOW)
        db.commit()
        record.consumed_attempt_id = 4
        with pytest.raises(ValueError, match="Terminal recommendation"):
            db.flush()
        db.rollback()
