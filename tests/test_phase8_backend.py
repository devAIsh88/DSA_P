"""Independent Phase 8 HTTP contracts and complete offline learning loops."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from adaptive_fixtures import create_adaptive_database
from app.api.submissions import get_execution_provider
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.attempt import Attempt
from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.problem_skill import ProblemSkill
from app.models.recommendation import Recommendation
from app.models.skill_state import SkillState
from app.models.submission import Submission
from app.models.test_case import TestCase as ProblemTestCase
from app.models.user import User
from app.schemas.execution import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.services.execution_service import ExecutionProvider, Judge0ExecutionService
from app.services.gemini_tutor_provider import GeminiTutorProvider
from app.services.tutor_provider import MockTutorProvider, TutorProviderError
from app.services.tutor_provider_factory import get_tutor_provider


PRIVATE_MARKERS = (
    "PRIVATE HIDDEN INPUT", "PRIVATE HIDDEN OUTPUT", "PRIVATE STDERR", "PRIVATE COMPILE",
)


class ControlledExecution(ExecutionProvider):
    """Return fixture output without executing, importing or evaluating code."""

    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []
        self.status = ExecutionStatus.ACCEPTED
        self.fail = False

    async def execute_batch(self, request: ExecutionRequest) -> list[ExecutionResult]:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("PRIVATE PROVIDER CONNECTION DETAIL")
        return [ExecutionResult(
            test_case_id=case.id,
            status=self.status,
            stdout=("PRIVATE HIDDEN OUTPUT" if case.id % 2 == 0 else "1")
            if request.code == "accepted code" else "wrong",
            stderr="PRIVATE STDERR",
            compile_output="PRIVATE COMPILE",
            time_ms=3.0,
            memory_kb=128.0,
        ) for case in request.test_cases]


class UnavailableTutor(MockTutorProvider):
    async def generate_hint(self, request):
        raise TutorProviderError("PRIVATE PROVIDER FAILURE")

    async def diagnose_attempt(self, request):
        raise TutorProviderError("PRIVATE PROVIDER FAILURE")

    async def analyze_reasoning(self, request):
        raise TutorProviderError("PRIVATE PROVIDER FAILURE")

    async def generate_post_attempt_explanation(self, request):
        raise TutorProviderError("PRIVATE PROVIDER FAILURE")

    async def evaluate_understanding(self, request):
        raise TutorProviderError("PRIVATE PROVIDER FAILURE")


@dataclass
class Phase8Harness:
    client: TestClient
    factory: sessionmaker[Session]
    execution: ControlledExecution
    tutor: MockTutorProvider

    def start(self, problem_id: int = 1, key: str = "start") -> int:
        response = self.client.post("/attempts/start", json={
            "user_id": 1, "problem_id": problem_id, "idempotency_key": key,
        })
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def submit(self, attempt_id: int, *, problem_id: int = 1, code: str = "accepted code",
               key: str = "submit") -> dict:
        response = self.client.post("/submissions", json={
            "problem_id": problem_id, "attempt_id": attempt_id, "code": code,
            "language": "python3", "idempotency_key": key,
        })
        assert response.status_code == 201, response.text
        return response.json()

    def complete(self, attempt_id: int, outcome: str = "SOLVED") -> None:
        response = self.client.post(f"/attempts/{attempt_id}/complete", json={
            "outcome": outcome, "idempotency_key": f"close-{attempt_id}",
        })
        assert response.status_code == 200, response.text

    def snapshot(self) -> dict:
        """Capture all table content to detect even lifecycle-only mutations."""
        with self.factory() as db:
            return {table.name: [tuple(row) for row in db.execute(select(table))]
                    for table in Base.metadata.sorted_tables}


@pytest.fixture
def phase8_api(monkeypatch) -> Iterator[Phase8Harness]:
    data, engine = create_adaptive_database(monkeypatch)
    execution = ControlledExecution()
    tutor = MockTutorProvider()

    def test_db():
        with data.factory() as db:
            yield db

    async def forbidden_live_call(*_args, **_kwargs):
        raise AssertionError("Phase 8 tests must not call Gemini or Judge0")

    monkeypatch.setattr(GeminiTutorProvider, "_generate", forbidden_live_call)
    monkeypatch.setattr(Judge0ExecutionService, "execute_batch", forbidden_live_call)
    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_execution_provider] = lambda: execution
    app.dependency_overrides[get_tutor_provider] = lambda: tutor
    try:
        with TestClient(app) as client:
            yield Phase8Harness(client, data.factory, execution, tutor)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def assert_public(response, *, allow_code: bool = False) -> None:
    assert all(marker not in response.text for marker in PRIVATE_MARKERS), response.text
    for private_field in ("input_snapshot", "input_fingerprint", "provenance", "compile_output", "stderr"):
        assert private_field not in response.text
    if not allow_code:
        assert "accepted code" not in response.text


def test_sample_run_uses_only_public_samples_and_mutates_nothing(phase8_api) -> None:
    h = phase8_api
    attempt = h.start()
    h.submit(attempt)
    h.complete(attempt)
    assert h.client.get("/recommendations/next").status_code == 200
    before = h.snapshot()
    first = h.client.post("/runs", json={"problem_id": 1, "code": "accepted code", "language": "python3"})
    second = h.client.post("/runs", json={"problem_id": 1, "code": "accepted code", "language": "python"})
    assert first.status_code == second.status_code == 200, first.text
    assert first.json() == second.json()
    payload = first.json()
    assert payload["problem_id"] == 1
    assert payload["overall_status"] == "ACCEPTED"
    assert payload["tests_total"] == payload["tests_passed"] == 1
    assert payload["edge_cases_failed"] == 0
    assert all(not result["is_hidden"] for result in payload["test_results"])
    assert all([case.id for case in request.test_cases] == [1] for request in h.execution.requests[-2:])
    assert all(case.input_data == "public" for request in h.execution.requests[-2:] for case in request.test_cases)
    assert all(case.time_limit_secs == 2.0 and case.memory_limit_kb == 256000
               for request in h.execution.requests[-2:] for case in request.test_cases)
    assert h.tutor.calls == []
    assert h.snapshot() == before
    assert_public(first)


def test_sample_run_pass_does_not_authorize_solved_completion(phase8_api) -> None:
    h = phase8_api
    attempt = h.start()
    assert h.client.post("/runs", json={"problem_id": 1, "code": "accepted code"}).status_code == 200
    assert h.client.post(f"/attempts/{attempt}/complete", json={"outcome": "SOLVED"}).status_code == 409
    with h.factory() as db:
        assert db.scalar(select(func.count()).select_from(Submission)) == 0
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 1
        assert db.scalar(select(func.count()).select_from(SkillState)) == 0


@pytest.mark.parametrize("status", [
    ExecutionStatus.RUNTIME_ERROR, ExecutionStatus.COMPILATION_ERROR,
    ExecutionStatus.TIME_LIMIT_EXCEEDED, ExecutionStatus.MEMORY_LIMIT_EXCEEDED,
    ExecutionStatus.SYSTEM_ERROR,
])
def test_run_statuses_are_safe_non_authoritative_results(phase8_api, status) -> None:
    h = phase8_api
    h.execution.status = status
    before = h.snapshot()
    response = h.client.post("/runs", json={"problem_id": 1, "code": "wrong code"})
    assert response.status_code == 200, response.text
    assert response.json()["overall_status"] == status.value
    assert response.json()["tests_passed"] == 0
    assert h.snapshot() == before
    assert_public(response)


def test_run_rejects_missing_problem_no_samples_and_invalid_requests(phase8_api) -> None:
    h = phase8_api
    assert h.client.post("/runs", json={"problem_id": 999, "code": "accepted code"}).status_code == 404
    with h.factory() as db:
        # Hidden material marked sample still must not become eligible Run input.
        db.get(ProblemTestCase, 1).is_sample = False
        db.get(ProblemTestCase, 2).is_sample = True
        db.commit()
    response = h.client.post("/runs", json={"problem_id": 1, "code": "accepted code"})
    assert response.status_code == 409
    assert "NO_PUBLIC_SAMPLE_TESTS" in response.text
    assert not h.execution.requests
    for payload in ({"problem_id": 0, "code": "x"}, {"problem_id": 1, "code": ""},
                    {"problem_id": 1, "code": "x", "language": "javascript"}):
        assert h.client.post("/runs", json=payload).status_code == 422


def test_run_unexpected_provider_failure_returns_private_safe_system_error(phase8_api) -> None:
    h = phase8_api
    h.execution.fail = True
    before = h.snapshot()
    response = h.client.post("/runs", json={"problem_id": 1, "code": "x"})
    assert response.status_code == 200, response.text
    assert response.json()["overall_status"] == "SYSTEM_ERROR"
    assert "PRIVATE PROVIDER" not in response.text
    assert_public(response)
    assert h.snapshot() == before


@pytest.mark.parametrize("status", [
    ExecutionStatus.ACCEPTED, ExecutionStatus.WRONG_ANSWER, ExecutionStatus.RUNTIME_ERROR, ExecutionStatus.COMPILATION_ERROR,
    ExecutionStatus.TIME_LIMIT_EXCEEDED, ExecutionStatus.MEMORY_LIMIT_EXCEEDED,
    ExecutionStatus.SYSTEM_ERROR,
])
def test_submission_read_recovers_owned_code_and_safe_terminal_result(phase8_api, status) -> None:
    h = phase8_api
    attempt = h.start()
    h.execution.status = status
    submitted = h.submit(attempt)
    before = h.snapshot()
    response = h.client.get(f"/submissions/{submitted['submission_id']}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["submission_id"] == submitted["submission_id"]
    assert payload["problem_id"] == 1
    assert payload["attempt_id"] == attempt
    assert payload["code"] == "accepted code"
    assert payload["language"] == "python3"
    assert payload["created_at"]
    for field in ("overall_status", "tests_passed", "tests_total", "edge_cases_failed", "test_results"):
        assert payload[field] == submitted[field]
    assert all(result["stdout"] is None for result in payload["test_results"] if result["is_hidden"])
    assert h.snapshot() == before
    assert_public(response, allow_code=True)


def test_submission_read_rejects_unowned_unlinked_missing_or_ambiguous_records(phase8_api) -> None:
    h = phase8_api
    assert h.client.get("/submissions/999").status_code == 404
    unlinked = h.client.post("/submissions", json={"problem_id": 1, "code": "accepted code"})
    assert unlinked.status_code == 201
    assert h.client.get(f"/submissions/{unlinked.json()['submission_id']}").status_code == 409
    attempt = h.start()
    submission = h.submit(attempt)
    with h.factory() as db:
        db.add(User(id=2))
        db.commit()
    denied = h.client.get(f"/submissions/{submission['submission_id']}")
    assert denied.status_code == 409
    assert "accepted code" not in denied.text


def test_empty_learner_facade_and_dashboard_are_truthful_read_only_summaries(phase8_api) -> None:
    h = phase8_api
    before = h.snapshot()
    learner = h.client.get("/learner/state")
    dashboard = h.client.get("/dashboard/summary")
    assert learner.status_code == dashboard.status_code == 200
    assert learner.json() == {"user_id": 1, "active_attempts": [], "skills": []}
    payload = dashboard.json()
    assert payload["user_id"] == 1
    assert payload["catalogue_problem_count"] == 5
    for field in ("attempt_count", "completed_attempt_count", "solved_attempt_count", "abandoned_attempt_count",
                  "unique_solved_problem_count", "hint_request_count", "hint_delivery_count",
                  "independent_solve_count", "hint_dependent_solve_count", "successful_supported_attempt_count"):
        assert payload[field] == 0
    assert payload["independent_solve_share"] is None
    assert payload["hint_dependency_share"] is None
    assert payload["active_attempts"] == payload["recent_attempts"] == payload["skills"] == []
    assert payload["existing_recommendation"] is None
    for unavailable in ("readiness", "accuracy", "retention_loss", "confidence_interval"):
        assert unavailable not in payload
    assert h.snapshot() == before
    assert_public(dashboard)


def test_dashboard_distinguishes_global_repeats_from_supported_solve_denominators(phase8_api) -> None:
    h = phase8_api
    first = h.start(key="independent")
    h.submit(first)
    h.complete(first)
    assisted = h.start(key="assisted")
    for level in (1, 3):
        delivered = h.client.post("/hints/request", json={
            "attempt_id": assisted, "requested_level": level, "idempotency_key": f"hint-{level}",
        })
        assert delivered.status_code == 200
    h.submit(assisted)
    h.complete(assisted)
    abandoned = h.start(2, "abandoned")
    assert h.client.post(f"/attempts/{abandoned}/abandon").status_code == 200
    with h.factory() as db:
        db.delete(db.get(ProblemSkill, (4, 2)))
        db.commit()
    unmapped = h.start(4, "unmapped")
    h.submit(unmapped, problem_id=4)
    h.complete(unmapped)
    active = h.start(3, "active")
    before = h.snapshot()
    response = h.client.get("/dashboard/summary")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["attempt_count"] == 5
    assert payload["completed_attempt_count"] == 3
    assert payload["solved_attempt_count"] == 3
    assert payload["abandoned_attempt_count"] == 1
    assert payload["unique_solved_problem_count"] == 2
    assert payload["successful_supported_attempt_count"] == 2
    assert payload["independent_solve_count"] == payload["hint_dependent_solve_count"] == 1
    assert payload["independent_solve_share"] == payload["hint_dependency_share"] == pytest.approx(0.5)
    assert payload["hint_request_count"] == payload["hint_delivery_count"] == 2
    assert [attempt["id"] for attempt in payload["active_attempts"]] == [active]
    assert [attempt["id"] for attempt in payload["recent_attempts"]] == [active, unmapped, abandoned, assisted, first]
    assert payload["skills"][0]["skill_name"] == "Arrays"
    assert payload["skills"][0]["hint_count_total"] == 2
    assert payload["skills"][0]["average_hint_level"] == 2
    assert h.client.get("/learner/state").json()["skills"] == payload["skills"]
    assert h.snapshot() == before
    assert_public(response)


def test_hint_requests_without_delivery_are_counted_separately(phase8_api) -> None:
    h = phase8_api
    attempt = h.start()
    assert h.client.post("/hints/request", json={
        "attempt_id": attempt, "requested_level": 6, "idempotency_key": "gated",
    }).status_code == 409
    h.submit(attempt)
    h.complete(attempt)
    payload = h.client.get("/dashboard/summary").json()
    assert payload["hint_request_count"] == 1
    assert payload["hint_delivery_count"] == 0
    assert payload["independent_solve_count"] == 0
    assert payload["hint_dependent_solve_count"] == 1
    assert payload["skills"][0]["mastery_probability"] == pytest.approx(0.2)
    assert payload["skills"][0]["average_hint_level"] is None


def test_summaries_return_existing_recommendation_without_issuing_or_consuming(phase8_api) -> None:
    h = phase8_api
    recommendation = h.client.get("/recommendations/next").json()["recommendation"]
    before = h.snapshot()
    response = h.client.get("/dashboard/summary")
    assert response.status_code == 200
    assert response.json()["existing_recommendation"] == recommendation
    assert h.client.get("/learner/state").status_code == 200
    assert h.snapshot() == before
    assert_public(response)


def test_summaries_reject_missing_or_ambiguous_learner_without_provisioning(phase8_api) -> None:
    h = phase8_api
    with h.factory() as db:
        db.add(User(id=2))
        db.commit()
    for route in ("/learner/state", "/dashboard/summary"):
        assert h.client.get(route).status_code == 409
    with h.factory() as db:
        db.delete(db.get(User, 1))
        db.delete(db.get(User, 2))
        db.commit()
    for route in ("/learner/state", "/dashboard/summary"):
        assert h.client.get(route).status_code == 404
    with h.factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0


def test_summaries_preserve_stale_projection_and_limit_recent_history(phase8_api) -> None:
    h = phase8_api
    solved = h.start(key="solved")
    h.submit(solved)
    h.complete(solved)
    for index in range(11):
        closed = h.start(2, key=f"gave-up-{index}")
        h.complete(closed, "GAVE_UP")
    second_active = h.start(3, key="second-active")
    first_active = h.start(1, key="first-active")
    with h.factory() as db:
        db.get(SkillState, (1, 1)).model_version = "unrecognized-model"
        db.commit()
    before = h.snapshot()
    response = h.client.get("/dashboard/summary")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["recent_attempts"]) == 10
    assert [attempt["id"] for attempt in payload["active_attempts"]] == sorted([first_active, second_active])
    assert [attempt["id"] for attempt in payload["recent_attempts"]] == sorted(
        [attempt["id"] for attempt in payload["recent_attempts"]], reverse=True,
    )
    assert payload["skills"][0]["model_version"] == "unrecognized-model"
    assert h.client.get("/learner/state").json()["skills"][0]["model_version"] == "unrecognized-model"
    assert h.snapshot() == before


def test_primary_offline_learning_loop_recovers_results_and_consumes_next_activity(phase8_api) -> None:
    h = phase8_api
    assert h.client.get("/dashboard/summary").status_code == 200
    initial = h.client.get("/recommendations/next").json()["recommendation"]
    problem_id = initial["problem_id"]
    assert h.client.get(f"/problems/{problem_id}").status_code == 200
    attempt = h.start(problem_id)
    reasoning = h.client.post(f"/attempts/{attempt}/reasoning", json={
        "reasoning_text": "Maintain the loop invariant.", "idempotency_key": "reasoning",
    })
    assert reasoning.status_code == 201
    before_run = h.snapshot()
    run = h.client.post("/runs", json={"problem_id": problem_id, "code": "wrong code"})
    assert run.json()["overall_status"] == "WRONG_ANSWER"
    assert h.snapshot() == before_run
    wrong = h.submit(attempt, problem_id=problem_id, code="wrong code", key="wrong")
    assert wrong["overall_status"] == "WRONG_ANSWER"
    diagnosis = h.client.post(f"/attempts/{attempt}/diagnose", json={
        "submission_id": wrong["submission_id"], "idempotency_key": "diagnosis",
    })
    assert diagnosis.status_code == 200
    analysis = h.client.post(f"/attempts/{attempt}/reasoning-analysis", json={
        "reasoning_event_id": reasoning.json()["id"], "idempotency_key": "analysis",
    })
    assert analysis.status_code == 200
    assert h.client.post("/runs", json={"problem_id": problem_id, "code": "accepted code"}).json()["overall_status"] == "ACCEPTED"
    accepted = h.submit(attempt, problem_id=problem_id, key="accepted")
    assert accepted["overall_status"] == "ACCEPTED"
    recovered = h.client.get(f"/submissions/{accepted['submission_id']}")
    assert recovered.json()["code"] == "accepted code"
    h.complete(attempt)
    learner = h.client.get("/learner/state").json()
    assert learner["active_attempts"] == []
    assert learner["skills"][0]["independent_solve_count"] == 1
    assert learner["skills"][0]["mastery_probability"] > 0.2
    check = h.client.post(f"/attempts/{attempt}/understanding-checks", json={"idempotency_key": "check"})
    assert check.status_code == 200
    answer = h.client.post(f"/attempts/{attempt}/understanding-checks/{check.json()['check_event_id']}/answer", json={
        "answer_text": "The invariant establishes the result; O(n) time and O(1) space.", "idempotency_key": "answer",
    })
    assert answer.status_code == 200
    next_activity = h.client.get("/recommendations/next").json()["recommendation"]
    assert next_activity["problem_id"] != problem_id
    h.start(next_activity["problem_id"], key="next-start")
    with h.factory() as db:
        assert db.get(Recommendation, initial["id"]).consumed_at is not None
        assert db.get(Recommendation, next_activity["id"]).consumed_at is not None
    for response in (diagnosis, analysis, answer, h.client.get("/dashboard/summary")):
        assert_public(response)


def test_assisted_loop_reports_activity_without_independent_mastery_update(phase8_api) -> None:
    h = phase8_api
    attempt = h.start()
    hint = h.client.post("/hints/request", json={
        "attempt_id": attempt, "requested_level": 4, "idempotency_key": "assisted-hint",
    })
    assert hint.status_code == 200
    h.submit(attempt)
    h.complete(attempt)
    skill = h.client.get("/learner/state").json()["skills"][0]
    assert skill["mastery_probability"] == pytest.approx(0.2)
    assert skill["independent_solve_count"] == 0
    assert skill["hint_dependent_count"] == skill["hint_count_total"] == 1
    assert skill["successful_attempt_count"] == 1
    next_activity = h.client.get("/recommendations/next")
    assert next_activity.status_code == 200
    assert next_activity.json()["recommendation"]["action_type"] == "RETRY_SIMILAR_PROBLEM"


def test_model_failure_preserves_answer_and_does_not_break_core_learning_loop(phase8_api) -> None:
    h = phase8_api
    app.dependency_overrides[get_tutor_provider] = lambda: UnavailableTutor()
    attempt = h.start()
    fallback = h.client.post("/hints/request", json={
        "attempt_id": attempt, "requested_level": 1, "idempotency_key": "fallback",
    })
    assert fallback.status_code == 200 and fallback.json()["source"] == "fallback"
    assert h.client.post("/runs", json={"problem_id": 1, "code": "accepted code"}).json()["overall_status"] == "ACCEPTED"
    submitted = h.submit(attempt)
    failed_diagnosis = h.client.post(f"/attempts/{attempt}/diagnose", json={
        "submission_id": submitted["submission_id"], "idempotency_key": "failed-diagnosis",
    })
    assert failed_diagnosis.status_code == 503
    h.complete(attempt)
    question = h.client.post(f"/attempts/{attempt}/understanding-checks", json={"idempotency_key": "check"})
    assert question.status_code == 200
    answer_url = f"/attempts/{attempt}/understanding-checks/{question.json()['check_event_id']}/answer"
    unavailable = h.client.post(answer_url, json={"answer_text": "My saved answer", "idempotency_key": "answer"})
    assert unavailable.status_code == 503
    events = h.client.get(f"/attempts/{attempt}/events").json()
    assert any(event["evidence"].get("answer_text") == "My saved answer" for event in events)
    assert not any(event["event_type"] == "TUTOR_DIAGNOSIS_GENERATED" for event in events)
    assert not any(event["event_type"] == "TUTOR_UNDERSTANDING_EVALUATED" for event in events)
    assert h.client.get("/learner/state").status_code == 200
    assert h.client.get("/dashboard/summary").status_code == 200
    assert h.client.get("/recommendations/next").status_code == 200
    assert_public(unavailable)
