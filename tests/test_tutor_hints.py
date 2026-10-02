"""Hint event causality, gates, retries, fallback, and safe tutor context."""

from sqlalchemy import select

from app.main import app
from app.models.learning_event import LearningEvent
from app.schemas.learning_event import LearningEventType
from app.services.tutor_provider import MockTutorProvider, TutorProviderError
from app.services.tutor_provider_factory import get_tutor_provider
from test_learner_state_phase4b import learner_db, start, submit  # noqa: F401


class FailingTutorProvider(MockTutorProvider):
    async def generate_hint(self, request):
        raise TutorProviderError("test failure")


def test_hint_levels_gate_and_idempotent_events(learner_db) -> None:
    client, factory, _ = learner_db
    tutor = MockTutorProvider()
    app.dependency_overrides[get_tutor_provider] = lambda: tutor
    attempt_id = start(client)
    for level in range(1, 6):
        payload = {"attempt_id": attempt_id, "requested_level": level, "idempotency_key": f"hint-{level}"}
        response = client.post("/hints/request", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["delivered_level"] == level
        assert client.post("/hints/request", json=payload).json() == response.json()
    sixth = client.post("/hints/request", json={
        "attempt_id": attempt_id, "requested_level": 6, "idempotency_key": "hint-6",
    })
    assert sixth.status_code == 200, sixth.text
    assert len(tutor.calls) == 6
    with factory() as db:
        rows = list(db.scalars(select(LearningEvent).where(LearningEvent.attempt_id == attempt_id)
                               .order_by(LearningEvent.attempt_sequence)))
        assert len(rows) == 13
        assert [row.attempt_sequence for row in rows] == list(range(1, 14))
        assert all(row.derived_labels is None for row in rows)
        assert rows[-1].provenance["provider"] == "mock"
    assert client.post("/hints/request", json={
        "attempt_id": attempt_id, "requested_level": 2, "idempotency_key": "hint-1",
    }).status_code == 409


def test_request_survives_gate_failure_and_provider_fallback(learner_db) -> None:
    client, factory, _ = learner_db
    attempt_id = start(client)
    app.dependency_overrides[get_tutor_provider] = lambda: FailingTutorProvider()
    gated = client.post("/hints/request", json={
        "attempt_id": attempt_id, "requested_level": 6, "idempotency_key": "gated",
    })
    assert gated.status_code == 409
    with factory() as db:
        assert db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == attempt_id,
            LearningEvent.event_type == LearningEventType.HINT_REQUESTED.value,
        )) is not None
    result = client.post("/hints/request", json={
        "attempt_id": attempt_id, "requested_level": 3, "idempotency_key": "fallback",
    })
    assert result.status_code == 200, result.text
    assert result.json()["source"] == "fallback"
    assert client.post("/hints/request", json={
        "attempt_id": attempt_id, "requested_level": 3, "idempotency_key": "fallback",
    }).json() == result.json()


def test_hint_context_excludes_hidden_test_material(learner_db) -> None:
    client, _, _ = learner_db
    tutor = MockTutorProvider()
    app.dependency_overrides[get_tutor_provider] = lambda: tutor
    attempt_id = start(client)
    submit(client, attempt_id)
    result = client.post("/hints/request", json={
        "attempt_id": attempt_id, "requested_level": 1, "idempotency_key": "after-submit",
    })
    assert result.status_code == 200, result.text
    context = tutor.calls[0][1].context.model_dump_json()
    for secret in ("PRIVATE HIDDEN INPUT", "PRIVATE HIDDEN OUTPUT", "PRIVATE STDERR"):
        assert secret not in context
        assert secret not in result.text
        assert secret not in client.get(f"/attempts/{attempt_id}/events").text


def test_level_six_provider_failure_keeps_request_without_fabricated_solution(learner_db) -> None:
    client, factory, _ = learner_db
    attempt_id = start(client)
    app.dependency_overrides[get_tutor_provider] = lambda: MockTutorProvider()
    assert client.post("/hints/request", json={
        "attempt_id": attempt_id, "requested_level": 5, "idempotency_key": "level-five",
    }).status_code == 200
    app.dependency_overrides[get_tutor_provider] = lambda: FailingTutorProvider()
    payload = {"attempt_id": attempt_id, "requested_level": 6, "idempotency_key": "level-six"}
    assert client.post("/hints/request", json=payload).status_code == 503
    assert client.post("/hints/request", json=payload).status_code == 503
    with factory() as db:
        events = list(db.scalars(select(LearningEvent).where(LearningEvent.attempt_id == attempt_id)))
        assert len([event for event in events if event.event_type == LearningEventType.HINT_REQUESTED.value]) == 2
        assert len([event for event in events if event.event_type == LearningEventType.HINT_DELIVERED.value]) == 1
    app.dependency_overrides[get_tutor_provider] = lambda: MockTutorProvider()
    assert client.post("/hints/request", json=payload).status_code == 200


def test_hint_validation_and_attempt_state(learner_db) -> None:
    client, _, _ = learner_db
    app.dependency_overrides[get_tutor_provider] = lambda: MockTutorProvider()
    attempt_id = start(client)
    assert client.post("/hints/request", json={
        "attempt_id": attempt_id, "requested_level": 0, "idempotency_key": "x",
    }).status_code == 422
    assert client.post("/hints/request", json={
        "attempt_id": 999, "requested_level": 1, "idempotency_key": "x",
    }).status_code == 404
    assert client.post(f"/attempts/{attempt_id}/abandon").status_code == 200
    assert client.post("/hints/request", json={
        "attempt_id": attempt_id, "requested_level": 1, "idempotency_key": "after-close",
    }).status_code == 409
