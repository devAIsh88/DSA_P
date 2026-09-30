"""Post-attempt explanation and preserved understanding-check evidence."""

from sqlalchemy import select

from app.main import app
from app.models.learning_event import LearningEvent
from app.schemas.learning_event import LearningEventType
from app.services.tutor_provider import MockTutorProvider, TutorProviderError
from app.services.tutor_provider_factory import get_tutor_provider
from test_learner_state_phase4b import learner_db, start, submit  # noqa: F401


class FailingPostTutor(MockTutorProvider):
    async def generate_post_attempt_explanation(self, request):
        raise TutorProviderError("offline")

    async def evaluate_understanding(self, request):
        raise TutorProviderError("offline")


def completed(client) -> int:
    attempt_id = start(client)
    submit(client, attempt_id)
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "SOLVED"}).status_code == 200
    return attempt_id


def test_completed_gates_and_idempotent_post_explanation(learner_db) -> None:
    client, factory, _ = learner_db
    tutor = MockTutorProvider()
    app.dependency_overrides[get_tutor_provider] = lambda: tutor
    attempt_id = start(client)
    payload = {"idempotency_key": "post-1"}
    assert client.post(f"/attempts/{attempt_id}/post-explanation", json=payload).status_code == 409
    assert client.post(f"/attempts/{attempt_id}/understanding-checks", json=payload).status_code == 409
    submit(client, attempt_id)
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "SOLVED"}).status_code == 200
    response = client.post(f"/attempts/{attempt_id}/post-explanation", json=payload)
    assert response.status_code == 200, response.text
    assert client.post(f"/attempts/{attempt_id}/post-explanation", json=payload).json() == response.json()
    assert len(tutor.calls) == 1
    with factory() as db:
        row = db.get(LearningEvent, response.json()["explanation_event_id"])
        assert row.evidence["explanation_text"] == response.json()["explanation_text"]
        assert row.derived_labels is None
        assert row.provenance["model_id"] == "mock-v1"


def test_understanding_answer_survives_provider_failure_and_retry(learner_db) -> None:
    client, factory, _ = learner_db
    attempt_id = completed(client)
    prompt_payload = {"idempotency_key": "check-1"}
    prompt = client.post(f"/attempts/{attempt_id}/understanding-checks", json=prompt_payload)
    assert prompt.status_code == 200, prompt.text
    assert client.post(f"/attempts/{attempt_id}/understanding-checks", json=prompt_payload).json() == prompt.json()
    assert prompt.json()["question_version"] == "understanding-check-v1"
    check_id = prompt.json()["check_event_id"]
    url = f"/attempts/{attempt_id}/understanding-checks/{check_id}/answer"
    answer_payload = {"answer_text": "Invariant holds after every step.", "idempotency_key": "answer-1"}
    app.dependency_overrides[get_tutor_provider] = lambda: FailingPostTutor()
    assert client.post(url, json=answer_payload).status_code == 503
    with factory() as db:
        answer = db.scalar(select(LearningEvent).where(
            LearningEvent.attempt_id == attempt_id,
            LearningEvent.event_type == LearningEventType.UNDERSTANDING_CHECK.value,
            LearningEvent.evidence["stage"].as_string() == "ANSWERED",
        ))
        assert answer.evidence["answer_text"] == answer_payload["answer_text"]
        answer_id = answer.id
        assert answer.provenance["source"] == "learner"
    app.dependency_overrides[get_tutor_provider] = lambda: MockTutorProvider()
    result = client.post(url, json=answer_payload)
    assert result.status_code == 200, result.text
    assert result.json()["answer_event_id"] == answer_id
    assert client.post(url, json=answer_payload).json() == result.json()
    assert client.post(url, json={"answer_text": "different", "idempotency_key": "answer-2"}).status_code == 409
    with factory() as db:
        evaluation = db.get(LearningEvent, result.json()["evaluation_event_id"])
        assert evaluation.evidence["feedback_text"] == result.json()["feedback_text"]
        assert evaluation.derived_labels["answer_quality"] == result.json()["answer_quality"]
        assert evaluation.provenance["source_event_ids"] == [check_id, answer_id]
    visible = client.get(f"/attempts/{attempt_id}/events")
    assert visible.status_code == 200, visible.text
    assert "Invariant holds after every step." in visible.text
    assert "model_confidence" not in visible.text


def test_post_explanation_failure_has_no_fake_event_and_gave_up_question(learner_db) -> None:
    client, factory, _ = learner_db
    attempt_id = start(client)
    assert client.post(f"/attempts/{attempt_id}/complete", json={"outcome": "GAVE_UP"}).status_code == 200
    app.dependency_overrides[get_tutor_provider] = lambda: FailingPostTutor()
    assert client.post(f"/attempts/{attempt_id}/post-explanation", json={
        "idempotency_key": "failed-post",
    }).status_code == 503
    prompt = client.post(f"/attempts/{attempt_id}/understanding-checks", json={
        "idempotency_key": "check-gave-up",
    })
    assert prompt.status_code == 200
    assert "what would need to change" in prompt.json()["question"]
    with factory() as db:
        assert db.scalar(select(LearningEvent).where(
            LearningEvent.event_type == LearningEventType.POST_ATTEMPT_EXPLANATION_GENERATED.value,
        )) is None
