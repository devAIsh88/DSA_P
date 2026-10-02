"""Diagnosis and reasoning use evaluated, learner-owned historical evidence."""

from sqlalchemy import select

from app.main import app
from app.models.learning_event import LearningEvent
from app.models.skill_state import SkillState
from app.models.user import User
from app.schemas.learning_event import LearningEventType
from app.schemas.tutor import DiagnosisResult, MisconceptionCategory
from app.services.tutor_provider import MockTutorProvider, TutorProviderError
from app.services.tutor_provider_factory import get_tutor_provider
from test_learner_state_phase4b import learner_db, map_skill, start, submit  # noqa: F401


class FailingTutor(MockTutorProvider):
    async def diagnose_attempt(self, request):
        raise TutorProviderError("offline")

    async def analyze_reasoning(self, request):
        raise TutorProviderError("offline")


class MalformedTutor(MockTutorProvider):
    def __init__(self):
        super().__init__()
        self.calls_made = 0

    async def diagnose_attempt(self, request):
        self.calls_made += 1
        return {"diagnosis_summary": ""}


class ConfidentTutor(MockTutorProvider):
    async def diagnose_attempt(self, request):
        return DiagnosisResult(
            misconception_category=MisconceptionCategory.LOGICAL_ERROR,
            diagnosis_summary="Check the invariant.", confidence=0.75,
            provenance=self._provenance("diagnosis"),
        )


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


def test_malformed_provider_output_retries_then_returns_503(learner_db) -> None:
    client, factory, _ = learner_db
    attempt_id = start(client)
    submission_id = submit(client, attempt_id)
    tutor = MalformedTutor()
    app.dependency_overrides[get_tutor_provider] = lambda: tutor
    response = client.post(f"/attempts/{attempt_id}/diagnose", json={
        "submission_id": submission_id, "idempotency_key": "malformed",
    })
    assert response.status_code == 503
    assert tutor.calls_made == 3  # one initial call plus two configured retries
    with factory() as db:
        assert db.scalar(select(LearningEvent).where(
            LearningEvent.event_type == LearningEventType.TUTOR_DIAGNOSIS_GENERATED.value,
        )) is None


def test_tutor_routes_preserve_mastery_and_single_learner_boundary(learner_db) -> None:
    client, factory, _ = learner_db
    map_skill(factory, 1, 1)
    attempt_id = start(client)
    submission_id = submit(client, attempt_id)
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "SOLVED"}).status_code == 200
    with factory() as db:
        state = db.get(SkillState, (1, 1))
        original = (state.mastery_probability, state.last_evidence_event_id)
    app.dependency_overrides[get_tutor_provider] = lambda: MockTutorProvider()
    assert client.post(f"/attempts/{attempt_id}/diagnose", json={
        "submission_id": submission_id, "idempotency_key": "mastery-diagnosis",
    }).status_code == 200
    assert client.post(f"/attempts/{attempt_id}/post-explanation", json={
        "idempotency_key": "mastery-explanation",
    }).status_code == 200
    with factory() as db:
        state = db.get(SkillState, (1, 1))
        assert (state.mastery_probability, state.last_evidence_event_id) == original
        db.add(User(id=2))
        db.commit()
    assert client.post(f"/attempts/{attempt_id}/diagnose", json={
        "submission_id": submission_id, "idempotency_key": "other-learner",
    }).status_code == 409


def test_model_confidence_is_label_only_and_not_learner_event_payload(learner_db) -> None:
    client, factory, _ = learner_db
    attempt_id = start(client)
    submission_id = submit(client, attempt_id)
    app.dependency_overrides[get_tutor_provider] = lambda: ConfidentTutor()
    response = client.post(f"/attempts/{attempt_id}/diagnose", json={
        "submission_id": submission_id, "idempotency_key": "confidence",
    })
    assert response.status_code == 200
    assert "confidence" not in response.json()
    with factory() as db:
        row = db.get(LearningEvent, response.json()["diagnosis_event_id"])
        assert row.derived_labels["model_confidence"] == 0.75
        assert "confidence" not in row.provenance
        assert "confidence" not in row.evidence
    assert "confidence" not in client.get(f"/attempts/{attempt_id}/events").text


def test_tutor_path_ids_must_be_positive(learner_db) -> None:
    client, _, _ = learner_db
    app.dependency_overrides[get_tutor_provider] = lambda: MockTutorProvider()
    assert client.post("/attempts/0/diagnose", json={
        "submission_id": 1, "idempotency_key": "invalid-path",
    }).status_code == 422
    assert client.post("/attempts/-1/understanding-checks", json={
        "idempotency_key": "invalid-check",
    }).status_code == 422
