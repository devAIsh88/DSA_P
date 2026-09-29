"""Single-skill evidence projection, persistence, and API boundaries."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.submissions import get_execution_provider
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.attempt import Attempt
from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.problem_skill import ProblemSkill
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.models.submission import Submission
from app.models.test_case import TestCase as ProblemTestCase
from app.models.user import User
from app.schemas.execution import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.schemas.learning_event import LearningEventType
from app.services.bkt_provider import BKTParameters, BKTProvider
from app.services.execution_service import ExecutionProvider
from app.services.learner_state_service import rebuild_skill_state
from app.services.learning_event_service import append_event


class MockExecutionProvider(ExecutionProvider):
    """Produce deterministic public and hidden results without a network call."""

    def __init__(self) -> None:
        self.mode = "accepted"
        self.calls = 0

    async def execute_batch(self, request: ExecutionRequest) -> list[ExecutionResult]:
        self.calls += 1
        expected = {1: "yes", 2: "PRIVATE HIDDEN OUTPUT", 3: "other"}
        return [ExecutionResult(
            test_case_id=case.id,
            status=ExecutionStatus.SYSTEM_ERROR if self.mode == "system_error" else ExecutionStatus.ACCEPTED,
            stdout=expected[case.id] if self.mode == "accepted" else "wrong",
            stderr="PRIVATE STDERR" if case.id == 2 else "",
        ) for case in request.test_cases]


@pytest.fixture
def learner_db() -> Iterator[tuple[TestClient, sessionmaker[Session], MockExecutionProvider]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(User(id=1))
        db.add_all([Skill(id=1, name="Arrays"), Skill(id=2, name="Hashing")])
        db.add_all([
            Problem(id=1, title="P1", description="d", difficulty="Easy", topic="Arrays"),
            Problem(id=2, title="P2", description="d", difficulty="Easy", topic="Hashing"),
            Problem(id=3, title="P3", description="d", difficulty="Easy", topic="Unknown"),
        ])
        db.add_all([
            ProblemTestCase(id=1, problem_id=1, input="public", expected_output="yes", is_sample=True,
                            is_hidden=False, weight=1),
            ProblemTestCase(id=2, problem_id=1, input="PRIVATE HIDDEN INPUT", expected_output="PRIVATE HIDDEN OUTPUT",
                            is_sample=False, is_hidden=True, weight=1),
            ProblemTestCase(id=3, problem_id=2, input="public", expected_output="other", is_sample=True,
                            is_hidden=False, weight=1),
        ])
        db.commit()

    provider = MockExecutionProvider()

    def test_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_execution_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            yield client, factory, provider
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def map_skill(factory: sessionmaker[Session], problem_id: int, skill_id: int, *, weight: float = 1.0) -> None:
    with factory() as db:
        db.add(ProblemSkill(problem_id=problem_id, skill_id=skill_id, weight=weight))
        db.commit()


def start(client: TestClient, problem_id: int = 1) -> int:
    response = client.post("/attempts/start", json={"user_id": 1, "problem_id": problem_id})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def submit(client: TestClient, attempt_id: int, problem_id: int = 1, *, key: str | None = None) -> int:
    payload: dict[str, object] = {"problem_id": problem_id, "attempt_id": attempt_id, "code": "print('answer')"}
    if key is not None:
        payload["idempotency_key"] = key
    response = client.post("/submissions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["submission_id"]


def record_hint(factory: sessionmaker[Session], attempt_id: int, event_type: LearningEventType,
                level: int) -> None:
    evidence_key = ("hint_level_requested" if event_type is LearningEventType.HINT_REQUESTED
                    else "hint_level_delivered")
    source = "learner" if event_type is LearningEventType.HINT_REQUESTED else "deterministic_rule"
    with factory() as db:
        append_event(db, attempt_id, event_type,
                     {"schema_version": 1, evidence_key: level}, {"source": source})
        db.commit()


def test_submission_waits_for_completion_then_projects_once(learner_db) -> None:
    client, factory, provider = learner_db
    map_skill(factory, 1, 1)
    attempt_id = start(client)
    client.post(f"/attempts/{attempt_id}/reasoning", json={"reasoning_text": "Try arrays first"})
    provider.mode = "wrong"
    submit(client, attempt_id)
    assert client.get("/learner/skills").json() == []
    provider.mode = "accepted"
    accepted_id = submit(client, attempt_id, key="accepted-submission")
    assert client.get("/learner/skills").json() == []

    closed = client.post(f"/attempts/{attempt_id}/complete", json={
        "outcome": "SOLVED", "idempotency_key": "closed-once",
    })
    assert closed.status_code == 200
    state_response = client.get("/learner/skills/1")
    assert state_response.status_code == 200
    state = state_response.json()
    assert state["attempt_count"] == 1
    assert state["successful_attempt_count"] == 1
    assert state["independent_solve_count"] == 1
    assert state["hint_count_total"] == 0
    assert state["average_hint_level"] is None
    assert state["mastery_probability"] == pytest.approx(0.5135135135)
    assert state["model_version"] == "bkt-v1"
    assert state["param_version"] == "experimental-v1"
    assert client.get("/learner/skills").json() == [state]
    for private in ("PRIVATE HIDDEN INPUT", "PRIVATE HIDDEN OUTPUT", "PRIVATE STDERR"):
        assert private not in state_response.text
        assert private not in client.get(f"/attempts/{attempt_id}/events").text
    assert "provenance" not in state and "last_evidence_event_id" not in state

    with factory() as db:
        completion = db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == attempt_id,
            LearningEvent.event_type == LearningEventType.ATTEMPT_COMPLETED.value,
        ))
        stored = db.get(SkillState, (1, 1))
        assert completion.skill_id == 1
        assert completion.evidence["final_submission_id"] == accepted_id
        assert completion.provenance["attribution"]["status"] == "single_skill"
        assert stored.last_evidence_event_id == completion.id
        original_provenance = completion.provenance.copy()
        before = (stored.mastery_probability, stored.attempt_count, stored.last_evidence_event_id)
        rebuild_skill_state(db, 1, 1)
        rebuild_skill_state(db, 1, 1)
        db.commit()
        db.refresh(stored)
        assert before == (stored.mastery_probability, stored.attempt_count, stored.last_evidence_event_id)
        assert completion.provenance == original_provenance

    assert client.post(f"/attempts/{attempt_id}/complete", json={
        "outcome": "SOLVED", "idempotency_key": "closed-once",
    }).status_code == 200
    assert client.get("/learner/skills/1").json()["attempt_count"] == 1
    assert provider.calls == 2

    # Projection is reproducible from the event ledger even if a relational row is edited outside services.
    with factory() as db:
        db.get(Attempt, attempt_id).outcome = "GAVE_UP"
        db.get(Submission, accepted_id).overall_status = "WRONG_ANSWER"
        db.commit()
        before = db.get(SkillState, (1, 1)).mastery_probability
        rebuild_skill_state(db, 1, 1)
        db.commit()
        assert db.get(SkillState, (1, 1)).mastery_probability == before


def test_revisit_and_skill_isolation_with_incorrect_observation(learner_db) -> None:
    client, factory, _provider = learner_db
    map_skill(factory, 1, 1)
    map_skill(factory, 2, 2)
    first = start(client)
    submit(client, first)
    assert client.post(f"/attempts/{first}/complete", json={"outcome": "SOLVED"}).status_code == 200
    first_state = client.get("/learner/skills/1").json()

    revisit = start(client)
    assert revisit != first
    assert client.post(f"/attempts/{revisit}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    updated = client.get("/learner/skills/1").json()
    assert updated["attempt_count"] == 2
    assert updated["successful_attempt_count"] == 1
    assert updated["mastery_probability"] < first_state["mastery_probability"]

    other = start(client, problem_id=2)
    assert client.post(f"/attempts/{other}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    assert client.get("/learner/skills/2").json()["attempt_count"] == 1
    assert client.get("/learner/skills/1").json() == updated
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(SkillState)) == 2


def test_ambiguous_mappings_defer_projection_but_assisted_and_abandoned_report(learner_db) -> None:
    client, factory, _provider = learner_db
    unmapped = start(client, problem_id=3)
    assert client.post(f"/attempts/{unmapped}/complete", json={"outcome": "GAVE_UP"}).status_code == 200

    map_skill(factory, 3, 1, weight=0.5)
    weighted = start(client, problem_id=3)
    assert client.post(f"/attempts/{weighted}/complete", json={"outcome": "GAVE_UP"}).status_code == 200

    map_skill(factory, 2, 1)
    map_skill(factory, 2, 2)
    ambiguous = start(client, problem_id=2)
    assert client.post(f"/attempts/{ambiguous}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    assert client.get("/learner/skills").json() == []

    map_skill(factory, 1, 1)
    abandoned = start(client)
    assert client.post(f"/attempts/{abandoned}/abandon").status_code == 200
    assisted = start(client)
    record_hint(factory, assisted, LearningEventType.HINT_REQUESTED, 1)
    assert client.post(f"/attempts/{assisted}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    state = client.get("/learner/skills/1").json()
    assert state["mastery_probability"] == pytest.approx(0.2)
    assert state["attempt_count"] == 2
    assert state["successful_attempt_count"] == 0
    assert state["hint_count_total"] == 1
    assert state["average_hint_level"] is None
    with factory() as db:
        completion = db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == ambiguous,
            LearningEvent.event_type == LearningEventType.ATTEMPT_COMPLETED.value,
        ))
        assert completion.skill_id is None
        assert completion.provenance["attribution"]["status"] == "multiple_skills_require_policy"
        weighted_completion = db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == weighted,
            LearningEvent.event_type == LearningEventType.ATTEMPT_COMPLETED.value,
        ))
        assert weighted_completion.provenance["attribution"]["status"] == "nonunit_weight_requires_policy"
        assisted_completion = db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == assisted,
            LearningEvent.event_type == LearningEventType.ATTEMPT_COMPLETED.value,
        ))
        assert assisted_completion.evidence["hint_count"] == 1
        assert db.scalar(select(func.count()).select_from(SkillState)) == 1


def test_system_error_and_invalid_solved_attempt_do_not_update_mastery(learner_db) -> None:
    client, factory, provider = learner_db
    map_skill(factory, 1, 1)
    attempt_id = start(client)
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "SOLVED"}).status_code == 409
    provider.mode = "system_error"
    submit(client, attempt_id)
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    state = client.get("/learner/skills/1").json()
    assert state["mastery_probability"] == pytest.approx(0.2)
    assert state["attempt_count"] == 1


def test_assisted_only_reporting_replays_requests_deliveries_and_outcomes(learner_db) -> None:
    client, factory, _provider = learner_db
    map_skill(factory, 1, 1)
    solved = start(client)
    record_hint(factory, solved, LearningEventType.HINT_REQUESTED, 1)
    record_hint(factory, solved, LearningEventType.HINT_REQUESTED, 2)
    record_hint(factory, solved, LearningEventType.HINT_REQUESTED, 4)
    record_hint(factory, solved, LearningEventType.HINT_DELIVERED, 1)
    record_hint(factory, solved, LearningEventType.HINT_DELIVERED, 4)
    submit(client, solved)
    assert client.post(f"/attempts/{solved}/complete", json={"outcome": "SOLVED"}).status_code == 200

    first = client.get("/learner/skills/1").json()
    assert first["mastery_probability"] == pytest.approx(0.2)
    assert first["attempt_count"] == 1
    assert first["successful_attempt_count"] == 1
    assert first["independent_solve_count"] == 0
    assert first["hint_dependent_count"] == 1
    assert first["hint_count_total"] == 3
    assert first["average_hint_level"] == pytest.approx(2.5)
    with factory() as db:
        completion = db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == solved,
            LearningEvent.event_type == LearningEventType.ATTEMPT_COMPLETED.value,
        ))
        assert completion.evidence["hint_count"] == 3
        assert completion.evidence["max_hint_level"] == 4

    gave_up = start(client)
    record_hint(factory, gave_up, LearningEventType.HINT_DELIVERED, 6)
    assert client.post(f"/attempts/{gave_up}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    second = client.get("/learner/skills/1").json()
    assert second["mastery_probability"] == pytest.approx(0.2)
    assert second["attempt_count"] == 2
    assert second["successful_attempt_count"] == 1
    assert second["hint_dependent_count"] == 1
    assert second["hint_count_total"] == 3
    assert second["average_hint_level"] == pytest.approx(11 / 3)

    with factory() as db:
        events = list(db.scalars(select(LearningEvent).where(
            LearningEvent.attempt_id.in_((solved, gave_up)),
        ).order_by(LearningEvent.id)))
        history = [(item.id, item.evidence.copy(), item.provenance.copy()) for item in events]
        state = db.get(SkillState, (1, 1))
        before = (state.mastery_probability, state.attempt_count, state.hint_count_total,
                  state.average_hint_level, state.observation_rule_version)
        assert state.observation_rule_version == "attempt-completion-binary-reporting-v1"
        assert state.attribution_rule_version == "single-skill-v1"
        rebuild_skill_state(db, 1, 1)
        rebuild_skill_state(db, 1, 1)
        db.commit()
        db.refresh(state)
        assert before == (state.mastery_probability, state.attempt_count, state.hint_count_total,
                          state.average_hint_level, state.observation_rule_version)
        assert history == [(item.id, item.evidence, item.provenance) for item in events]


def test_assisted_revisit_does_not_change_independent_mastery(learner_db) -> None:
    client, factory, _provider = learner_db
    map_skill(factory, 1, 1)
    independent = start(client)
    submit(client, independent)
    assert client.post(f"/attempts/{independent}/complete", json={"outcome": "SOLVED"}).status_code == 200
    prior = client.get("/learner/skills/1").json()["mastery_probability"]

    assisted = start(client)
    record_hint(factory, assisted, LearningEventType.HINT_REQUESTED, 2)
    assert client.post(f"/attempts/{assisted}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    state = client.get("/learner/skills/1").json()
    assert state["mastery_probability"] == prior
    assert state["attempt_count"] == 2
    assert state["independent_solve_count"] == 1
    assert state["hint_count_total"] == 1


def test_projection_failure_rolls_back_attempt_and_event(learner_db, monkeypatch) -> None:
    client, factory, _provider = learner_db
    map_skill(factory, 1, 1)
    attempt_id = start(client)

    def fail_projection(_db, _event):
        raise RuntimeError("projection failed")

    monkeypatch.setattr("app.services.attempt_service.project_completion_event", fail_projection)
    with pytest.raises(RuntimeError, match="projection failed"):
        client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "GAVE_UP"})
    with factory() as db:
        assert db.get(Attempt, attempt_id).status == "ACTIVE"
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.attempt_id == attempt_id,
        )) == 1
        assert db.scalar(select(func.count()).select_from(SkillState)) == 0


def test_replay_with_new_parameter_version_keeps_event_immutable(learner_db) -> None:
    client, factory, _provider = learner_db
    map_skill(factory, 1, 1)
    attempt_id = start(client)
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    with factory() as db:
        state = db.get(SkillState, (1, 1))
        old_mastery = state.mastery_probability
        completion = db.get(LearningEvent, state.last_evidence_event_id)
        old_provenance = completion.provenance.copy()
        tracer = BKTProvider(BKTParameters(0.4, 0.2, 0.1, 0.3, "replay-v2"))
        rebuild_skill_state(db, 1, 1, provider=tracer)
        db.commit()
        db.refresh(state)
        assert state.mastery_probability != old_mastery
        assert state.param_version == "replay-v2"
        assert completion.provenance == old_provenance


def test_learner_api_rejects_ambiguous_ownership(learner_db) -> None:
    client, factory, _provider = learner_db
    with factory() as db:
        db.add(User(id=2))
        db.commit()
    assert client.get("/learner/skills").status_code == 409
    assert client.get("/learner/skills/1").status_code == 409
