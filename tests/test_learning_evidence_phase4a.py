"""Phase 4A evidence, lifecycle, API safety, and Phase 3 integration tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.submissions import get_execution_provider
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.attempt import Attempt
from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.test_case import TestCase as ProblemTestCase
from app.models.test_result import TestResult as StoredTestResult
from app.models.user import User
from app.schemas.execution import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.schemas.learning_event import LearningEventType
from app.services.execution_service import ExecutionProvider
from app.services.learning_event_service import append_event, event_for_submission


class MockExecutionProvider(ExecutionProvider):
    """Return deterministic results without executing learner code."""

    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []
        self.visible_output = "wrong"
        self.hidden_output = "SECRET HIDDEN STDOUT"

    async def execute_batch(self, request: ExecutionRequest) -> list[ExecutionResult]:
        self.requests.append(request)
        return [
            ExecutionResult(
                test_case_id=case.id,
                status=ExecutionStatus.ACCEPTED,
                stdout=self.visible_output if case.id == 1 else self.hidden_output,
                stderr="SECRET HIDDEN STDERR" if case.id == 2 else "",
                compile_output="SECRET HIDDEN COMPILE" if case.id == 2 else "",
            )
            for case in request.test_cases
        ]


@pytest.fixture
def phase4a_db() -> Iterator[tuple[TestClient, sessionmaker[Session], MockExecutionProvider]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(User(id=1))
        db.add_all([
            Problem(id=1, title="P1", description="d", difficulty="Easy", topic="Arrays"),
            Problem(id=2, title="P2", description="d", difficulty="Easy", topic="Arrays"),
        ])
        db.add_all([
            ProblemTestCase(id=1, problem_id=1, input="visible input", expected_output="yes", is_sample=True,
                     is_hidden=False, weight=1),
            ProblemTestCase(id=2, problem_id=1, input="SECRET HIDDEN INPUT", expected_output="SECRET EXPECTED",
                     is_sample=False, is_hidden=True, weight=1),
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


def start(client: TestClient, *, key: str | None = None, problem_id: int = 1) -> int:
    payload: dict[str, object] = {"user_id": 1, "problem_id": problem_id}
    if key is not None:
        payload["idempotency_key"] = key
    response = client.post("/attempts/start", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_attempt_creation_active_uniqueness_and_later_revisit(phase4a_db) -> None:
    client, factory, _provider = phase4a_db
    first = start(client, key="start-1")
    assert start(client, key="start-1") == first
    assert client.post("/attempts/start", json={"user_id": 1, "problem_id": 1}).status_code == 409
    assert client.get(f"/attempts/{first}").json()["status"] == "ACTIVE"
    opening = client.get(f"/attempts/{first}/events").json()
    assert [(item["event_type"], item["attempt_sequence"]) for item in opening] == [("ATTEMPT_STARTED", 1)]
    assert client.post(f"/attempts/{first}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    second = start(client, key="start-2")
    assert second != first
    assert client.post(f"/attempts/{second}/abandon").json()["status"] == "ABANDONED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Attempt)) == 2
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 4


def test_valid_and_invalid_terminal_transitions_and_solved_guard(phase4a_db) -> None:
    client, _factory, provider = phase4a_db
    attempt_id = start(client)
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "SOLVED"}).status_code == 409
    provider.visible_output = "yes"
    submitted = client.post("/submissions", json={
        "problem_id": 1, "attempt_id": attempt_id, "code": "print('yes')",
    })
    assert submitted.status_code == 201
    # The hidden case fails, so the aggregate result cannot support SOLVED.
    assert submitted.json()["overall_status"] == "WRONG_ANSWER"
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "SOLVED"}).status_code == 409
    provider.hidden_output = "SECRET EXPECTED"
    accepted = client.post("/submissions", json={
        "problem_id": 1, "attempt_id": attempt_id, "code": "print('fixed')",
    })
    assert accepted.json()["overall_status"] == "ACCEPTED"
    closed = client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "SOLVED", "idempotency_key": "close"})
    assert closed.status_code == 200
    assert closed.json()["status"] == "COMPLETED"
    assert closed.json()["outcome"] == "SOLVED"
    assert closed.json()["completed_at"] is not None
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "SOLVED", "idempotency_key": "close"}).status_code == 200
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "GAVE_UP", "idempotency_key": "close"}).status_code == 409
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "SOLVED"}).status_code == 409
    assert client.post(f"/attempts/{attempt_id}/abandon").status_code == 409
    assert client.post(f"/attempts/{attempt_id}/reasoning", json={"reasoning_text": "later"}).status_code == 409
    assert client.post("/submissions", json={"problem_id": 1, "attempt_id": attempt_id, "code": "print(1)"}).status_code == 409


def test_reasoning_is_canonical_event_evidence_with_distinct_labels_and_provenance(phase4a_db) -> None:
    client, factory, _provider = phase4a_db
    attempt_id = start(client)
    first = client.post(f"/attempts/{attempt_id}/reasoning", json={
        "reasoning_text": "Use a hash map.", "idempotency_key": "reason-1",
    })
    assert first.status_code == 201
    assert first.json()["evidence"]["reasoning_text"] == "Use a hash map."
    assert client.post(f"/attempts/{attempt_id}/reasoning", json={
        "reasoning_text": "Use a hash map.", "idempotency_key": "reason-1",
    }).json()["id"] == first.json()["id"]
    assert client.post(f"/attempts/{attempt_id}/reasoning", json={
        "reasoning_text": "Change to two pointers.", "idempotency_key": "reason-2",
    }).status_code == 201
    assert client.post(f"/attempts/{attempt_id}/reasoning", json={
        "reasoning_text": "Different text", "idempotency_key": "reason-1",
    }).status_code == 409
    events = client.get(f"/attempts/{attempt_id}/events").json()
    assert [item["attempt_sequence"] for item in events] == [1, 2, 3]
    assert [item["evidence"]["reasoning_text"] for item in events[1:]] == [
        "Use a hash map.", "Change to two pointers.",
    ]
    assert all("derived_labels" not in item and "provenance" not in item for item in events)
    assert "reasoning_text" not in Attempt.__table__.columns
    with factory() as db:
        row = db.get(LearningEvent, first.json()["id"])
        assert row.evidence["reasoning_text"] == "Use a hash map."
        assert row.derived_labels is None
        assert row.provenance == {"source": "learner", "user_id": 1}


def test_multiple_submissions_event_order_retry_and_hidden_redaction(phase4a_db) -> None:
    client, factory, provider = phase4a_db
    attempt_id = start(client)
    first = client.post("/submissions", json={
        "problem_id": 1, "attempt_id": attempt_id, "code": "print('wrong')", "idempotency_key": "submit-1",
    })
    assert first.status_code == 201
    assert first.json()["overall_status"] == "WRONG_ANSWER"
    retry = client.post("/submissions", json={
        "problem_id": 1, "attempt_id": attempt_id, "code": "print('wrong')", "idempotency_key": "submit-1",
    })
    assert retry.status_code == 201
    assert retry.json() == first.json()
    assert len(provider.requests) == 1
    assert client.post("/submissions", json={
        "problem_id": 1, "attempt_id": attempt_id, "code": "different", "idempotency_key": "submit-1",
    }).status_code == 409
    second = client.post("/submissions", json={
        "problem_id": 1, "attempt_id": attempt_id, "code": "print('still wrong')", "idempotency_key": "submit-2",
    })
    assert second.status_code == 201
    assert second.json()["submission_id"] != first.json()["submission_id"]
    assert len(provider.requests) == 2
    events_response = client.get(f"/attempts/{attempt_id}/events")
    events = events_response.json()
    assert [(item["event_type"], item["attempt_sequence"]) for item in events] == [
        ("ATTEMPT_STARTED", 1), ("SUBMISSION_EVALUATED", 2), ("SUBMISSION_EVALUATED", 3),
    ]
    assert [item["submission_id"] for item in events[1:]] == [
        first.json()["submission_id"], second.json()["submission_id"],
    ]
    for secret in ("SECRET HIDDEN INPUT", "SECRET EXPECTED", "SECRET HIDDEN STDOUT",
                   "SECRET HIDDEN STDERR", "SECRET HIDDEN COMPILE"):
        assert secret not in events_response.text
        assert secret not in first.text
    with factory() as db:
        submissions = list(db.scalars(select(Submission).where(Submission.attempt_id == attempt_id)))
        assert len(submissions) == 2
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.event_type == LearningEventType.SUBMISSION_EVALUATED.value,
        )) == 2
        event_row = event_for_submission(db, submissions[0].id)
        assert event_row.provenance["source"] == "execution_evaluation_engine"
        assert event_row.provenance["evaluation"]["source"] == "deterministic_rule"
        assert event_row.derived_labels is None
        hidden = db.scalar(select(StoredTestResult).where(StoredTestResult.submission_id == submissions[0].id,
                                                       StoredTestResult.is_hidden.is_(True)))
        assert hidden.stderr == "SECRET HIDDEN STDERR"
        assert "stderr" not in event_row.evidence


def test_invalid_attempt_relationships_and_phase3_unassociated_path(phase4a_db) -> None:
    client, factory, provider = phase4a_db
    attempt_id = start(client)
    assert client.post("/submissions", json={
        "problem_id": 2, "attempt_id": attempt_id, "code": "print(1)",
    }).status_code == 409
    assert client.post("/submissions", json={
        "problem_id": 1, "attempt_id": 999, "code": "print(1)",
    }).status_code == 404
    assert len(provider.requests) == 0
    response = client.post("/submissions", json={"problem_id": 1, "code": "print(1)"})
    assert response.status_code == 201
    with factory() as db:
        submission = db.get(Submission, response.json()["submission_id"])
        assert submission.attempt_id is None
        assert event_for_submission(db, submission.id) is None


def test_single_learner_boundary_rejects_ambiguous_ownership(phase4a_db) -> None:
    client, factory, provider = phase4a_db
    attempt_id = start(client)
    with factory() as db:
        db.add(User(id=2))
        db.commit()
    assert client.post("/attempts/start", json={"user_id": 2, "problem_id": 1}).status_code == 409
    assert client.get(f"/attempts/{attempt_id}").status_code == 409
    assert client.get(f"/attempts/{attempt_id}/events").status_code == 409
    assert client.post(f"/attempts/{attempt_id}/reasoning", json={"reasoning_text": "private"}).status_code == 409
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "GAVE_UP"}).status_code == 409
    assert client.post(f"/attempts/{attempt_id}/abandon").status_code == 409
    assert client.post("/submissions", json={
        "problem_id": 1, "attempt_id": attempt_id, "code": "print(1)",
    }).status_code == 409
    assert len(provider.requests) == 0


def test_db_uniqueness_and_append_only_service_surface(phase4a_db) -> None:
    client, factory, _provider = phase4a_db
    attempt_id = start(client)
    with factory() as db:
        attempt = db.get(Attempt, attempt_id)
        duplicate_sequence = LearningEvent(
            user_id=attempt.user_id, attempt_id=attempt.id, problem_id=attempt.problem_id,
            event_type=LearningEventType.REASONING_RECORDED.value,
            attempt_sequence=1, evidence={"schema_version": 1, "reasoning_text": "x"},
        )
        db.add(duplicate_sequence)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        append_event(
            db, attempt_id, LearningEventType.REASONING_RECORDED,
            {"schema_version": 1, "reasoning_text": "retained"}, {"source": "learner"},
            idempotency_key="append-key",
        )
        db.commit()
        opening = db.scalar(select(LearningEvent).where(LearningEvent.attempt_id == attempt_id,
                                                        LearningEvent.attempt_sequence == 1))
        assert opening.evidence["problem_id"] == 1
        assert opening.attempt_sequence == 1
    assert client.get(f"/attempts/{attempt_id}/events").json()[1]["evidence"]["reasoning_text"] == "retained"
    paths = {(route.path, method) for route in app.routes for method in getattr(route, "methods", ())}
    assert not any(method in {"PUT", "PATCH", "DELETE"} and path.startswith("/attempts") for path, method in paths)
    assert not any("hint" in path or "understanding-check" in path for path, _method in paths)


def test_database_rejects_duplicate_submission_event_and_retry_key(phase4a_db) -> None:
    client, factory, _provider = phase4a_db
    attempt_id = start(client)
    response = client.post("/submissions", json={
        "problem_id": 1, "attempt_id": attempt_id, "code": "print('wrong')", "idempotency_key": "submission-key",
    })
    assert response.status_code == 201
    submission_id = response.json()["submission_id"]
    with factory() as db:
        db.add(LearningEvent(
            user_id=1, attempt_id=attempt_id, problem_id=1, submission_id=submission_id,
            event_type=LearningEventType.SUBMISSION_EVALUATED.value, attempt_sequence=3,
            evidence={"schema_version": 1, "submission_id": submission_id},
            idempotency_key="different-key",
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(LearningEvent(
            user_id=1, attempt_id=attempt_id, problem_id=1,
            event_type=LearningEventType.REASONING_RECORDED.value, attempt_sequence=3,
            evidence={"schema_version": 1, "reasoning_text": "x"},
            idempotency_key="submission-key",
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.attempt_id == attempt_id,
        )) == 2
