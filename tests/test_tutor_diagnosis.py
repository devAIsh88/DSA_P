"""Diagnosis and reasoning use evaluated, learner-owned historical evidence."""

from sqlalchemy import select

from app.main import app
from app.models.learning_event import LearningEvent
from app.models.skill_state import SkillState
from app.schemas.learning_event import LearningEventType
from app.services.tutor_provider import MockTutorProvider, TutorProviderError
from app.services.tutor_provider_factory import get_tutor_provider
from test_learner_state_phase4b import learner_db, start, submit  # noqa: F401


class FailingTutor(MockTutorProvider):
    async def diagnose_attempt(self, request):
        raise TutorProviderError("offline")

    async def analyze_reasoning(self, request):
        raise TutorProviderError("offline")


def test_diagnosis_requires_evaluation_and_remains_idempotent(learner_db) -> None:
    client, factory, _ = learner_db
    tutor = MockTutorProvider()
    app.dependency_overrides[get_tutor_provider] = lambda: tutor
    attempt_id = start(client)
    submission_id = submit(client, attempt_id)
    payload = {"submission_id": submission_id, "idempotency_key": "diagnose-1"}
    response = client.post(f"/attempts/{attempt_id}/diagnose", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["deterministic_status"] == "ACCEPTED"
    assert client.post(f"/attempts/{attempt_id}/diagnose", json=payload).json() == response.json()
    assert len(tutor.calls) == 1
    context = tutor.calls[0][1].context.model_dump_json()
    for secret in ("PRIVATE HIDDEN INPUT", "PRIVATE HIDDEN OUTPUT", "PRIVATE STDERR"):
        assert secret not in context
        assert secret not in response.text
    with factory() as db:
        event = db.get(LearningEvent, response.json()["diagnosis_event_id"])
        assert event.evidence["diagnosis_summary"] == response.json()["diagnosis_summary"]
        assert event.provenance["source_event_ids"]
        assert "misconception_category" in event.derived_labels
        assert db.scalars(select(SkillState)).all() == []
    assert client.post(f"/attempts/{attempt_id}/diagnose", json={
        "submission_id": submission_id + 1, "idempotency_key": "different",
    }).status_code == 404
    other_attempt = start(client, 2)
    assert client.post(f"/attempts/{other_attempt}/diagnose", json=payload).status_code == 409


def test_failed_diagnosis_creates_no_synthetic_event_then_recovers(learner_db) -> None:
    client, factory, _ = learner_db
    attempt_id = start(client)
    submission_id = submit(client, attempt_id)
    app.dependency_overrides[get_tutor_provider] = lambda: FailingTutor()
    payload = {"submission_id": submission_id, "idempotency_key": "failure"}
    assert client.post(f"/attempts/{attempt_id}/diagnose", json=payload).status_code == 503
    with factory() as db:
        assert db.scalar(select(LearningEvent).where(
            LearningEvent.event_type == LearningEventType.TUTOR_DIAGNOSIS_GENERATED.value,
        )) is None
    app.dependency_overrides[get_tutor_provider] = lambda: MockTutorProvider()
    assert client.post(f"/attempts/{attempt_id}/diagnose", json=payload).status_code == 200


def test_reasoning_analysis_preserves_source_and_checks_lifecycle(learner_db) -> None:
    client, factory, _ = learner_db
    tutor = MockTutorProvider()
    app.dependency_overrides[get_tutor_provider] = lambda: tutor
    attempt_id = start(client)
    source = client.post(f"/attempts/{attempt_id}/reasoning", json={"reasoning_text": "Use a pointer."})
    source_id = source.json()["id"]
    payload = {"reasoning_event_id": source_id, "idempotency_key": "reason-1"}
    response = client.post(f"/attempts/{attempt_id}/reasoning-analysis", json=payload)
    assert response.status_code == 200, response.text
    assert client.post(f"/attempts/{attempt_id}/reasoning-analysis", json=payload).json() == response.json()
    with factory() as db:
        original = db.get(LearningEvent, source_id)
        analysis = db.get(LearningEvent, response.json()["analysis_event_id"])
        assert original.evidence["reasoning_text"] == "Use a pointer."
        assert original.derived_labels is None
        assert analysis.derived_labels["reasoning_quality"] == response.json()["reasoning_quality"]
        assert analysis.evidence["feedback_text"] == response.json()["feedback_text"]
    assert client.post(f"/attempts/{attempt_id}/abandon").status_code == 200
    assert client.post(f"/attempts/{attempt_id}/reasoning-analysis", json={
        "reasoning_event_id": source_id, "idempotency_key": "after-close",
    }).status_code == 409


def test_reasoning_failure_and_invalid_reference(learner_db) -> None:
    client, factory, _ = learner_db
    attempt_id = start(client)
    source = client.post(f"/attempts/{attempt_id}/reasoning", json={"reasoning_text": "Try all pairs."})
    source_id = source.json()["id"]
    app.dependency_overrides[get_tutor_provider] = lambda: FailingTutor()
    assert client.post(f"/attempts/{attempt_id}/reasoning-analysis", json={
        "reasoning_event_id": source_id, "idempotency_key": "failure",
    }).status_code == 503
    assert client.post(f"/attempts/{attempt_id}/reasoning-analysis", json={
        "reasoning_event_id": 9999, "idempotency_key": "unknown",
    }).status_code == 404
    with factory() as db:
        assert db.scalar(select(LearningEvent).where(
            LearningEvent.event_type == LearningEventType.TUTOR_REASONING_ANALYSIS_GENERATED.value,
        )) is None
