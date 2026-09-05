"""Provider-independent Phase 3 execution and evaluation coverage."""

import asyncio
import os

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.submissions import get_execution_provider
from app.db.base import Base
from app.main import app
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.test_case import TestCase
from app.models.test_result import TestResult
from app.schemas.execution import ExecutionRequest, ExecutionResult, ExecutionStatus, TestCaseExecution
from app.schemas.submission import TestResultResponse
from app.services.evaluation_service import EvaluationService
from app.services.execution_service import ExecutionProvider, Judge0ExecutionService


class MockExecutionProvider(ExecutionProvider):
    """A provider boundary fake; it never runs student code."""

    def __init__(self, results: list[ExecutionResult]) -> None:
        self.results = results
        self.requests: list[ExecutionRequest] = []

    async def execute_batch(self, request: ExecutionRequest) -> list[ExecutionResult]:
        self.requests.append(request)
        return self.results


def case(case_id: int, expected: str, *, hidden: bool = False) -> TestCase:
    return TestCase(id=case_id, problem_id=1, input="private input", expected_output=expected, is_hidden=hidden)


def request() -> ExecutionRequest:
    return ExecutionRequest(code="print('x')", test_cases=[TestCaseExecution(id=1, input_data="1\n")])


def test_evaluation_normalizes_crlf_and_whitespace() -> None:
    summary = EvaluationService().evaluate(
        [case(1, "answer\n")],
        [ExecutionResult(test_case_id=1, status=ExecutionStatus.ACCEPTED, stdout="  answer\r\n  ")],
    )

    assert summary.overall_status is ExecutionStatus.ACCEPTED
    assert summary.tests_passed == 1


def test_evaluation_aggregates_timeout_over_accepted_and_wrong_answer() -> None:
    summary = EvaluationService().evaluate(
        [case(1, "ok"), case(2, "expected"), case(3, "ok")],
        [
            ExecutionResult(test_case_id=1, status=ExecutionStatus.ACCEPTED, stdout="ok"),
            ExecutionResult(test_case_id=2, status=ExecutionStatus.ACCEPTED, stdout="wrong"),
            ExecutionResult(test_case_id=3, status=ExecutionStatus.TIME_LIMIT_EXCEEDED),
        ],
    )

    assert [result.status for result in summary.results] == [
        ExecutionStatus.ACCEPTED,
        ExecutionStatus.WRONG_ANSWER,
        ExecutionStatus.TIME_LIMIT_EXCEEDED,
    ]
    assert summary.overall_status is ExecutionStatus.TIME_LIMIT_EXCEEDED
    assert summary.tests_passed == 1


def test_hidden_response_schema_redacts_stdout_and_has_no_private_fields() -> None:
    response = TestResultResponse(
        test_case_id=9,
        is_hidden=True,
        status=ExecutionStatus.WRONG_ANSWER,
        stdout="secret output",
    )

    assert response.model_dump() == {
        "test_case_id": 9,
        "is_hidden": True,
        "status": "WRONG_ANSWER",
        "stdout": None,
    }
    assert not ({"input", "expected_output", "stderr", "compile_output"} & response.model_dump().keys())


class _FakeClient:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def run_adapter(monkeypatch, response: httpx.Response | Exception):
    fake_client = _FakeClient(response)
    monkeypatch.setattr("app.services.execution_service.httpx.AsyncClient", lambda **_kwargs: fake_client)
    result = asyncio.run(Judge0ExecutionService("http://judge0").execute_batch(request()))
    return result, fake_client


def test_judge0_adapter_maps_status_and_enforces_safe_limited_payload(monkeypatch) -> None:
    results, client = run_adapter(
        monkeypatch,
        httpx.Response(200, json=[{"status": {"id": 3}, "stdout": "x" * (11 * 1024), "time": "0.2", "memory": 22}]),
    )

    assert results[0].status is ExecutionStatus.ACCEPTED
    assert len(results[0].stdout) == 10 * 1024
    assert results[0].time_ms == 200
    payload = client.calls[0]["json"]["submissions"][0]
    assert payload == {
        "source_code": "print('x')",
        "language_id": 71,
        "stdin": "1\n",
        "cpu_time_limit": 2.0,
        "wall_time_limit": 5.0,
        "memory_limit": 256000,
        "enable_network": False,
    }
    assert "expected_output" not in payload
    assert client.calls[0]["params"] == {"base64_encoded": "false", "wait": "true"}


@pytest.mark.parametrize(
    "response",
    [
        httpx.ReadTimeout("timed out"),
        httpx.Response(502, json={}),
        httpx.Response(200, json={"not": "a batch"}),
        httpx.Response(200, json=[{"status": {"id": 3}, "time": "not-a-number"}]),
    ],
)
def test_judge0_adapter_converts_provider_failures_to_system_errors(monkeypatch, response) -> None:
    results, _client = run_adapter(monkeypatch, response)

    assert [result.status for result in results] == [ExecutionStatus.SYSTEM_ERROR]


def test_judge0_adapter_maps_timeout_compilation_and_runtime_statuses(monkeypatch) -> None:
    for status_id, expected in [(5, ExecutionStatus.TIME_LIMIT_EXCEEDED), (6, ExecutionStatus.COMPILATION_ERROR), (7, ExecutionStatus.RUNTIME_ERROR)]:
        results, _client = run_adapter(monkeypatch, httpx.Response(200, json=[{"status": {"id": status_id}}]))
        assert results[0].status is expected


def test_post_submissions_uses_provider_boundary_and_redacts_hidden_evidence() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    session.add(Problem(id=1, title="P", description="d", difficulty="Easy", source="test", topic="A", subtopic="B", constraints="", input_format="", output_format="", expected_complexity="", target_track=""))
    session.add_all([
        TestCase(id=1, problem_id=1, input="visible", expected_output="yes", is_sample=True, is_hidden=False, weight=1),
        TestCase(id=2, problem_id=1, input="DO NOT LEAK", expected_output="SECRET", is_sample=False, is_hidden=True, weight=1),
    ])
    session.commit()
    session.close()
    provider = MockExecutionProvider([
        ExecutionResult(test_case_id=1, status=ExecutionStatus.ACCEPTED, stdout="yes"),
        ExecutionResult(test_case_id=2, status=ExecutionStatus.ACCEPTED, stdout="wrong", stderr="private stderr"),
    ])

    def get_test_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    from app.db.session import get_db

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_execution_provider] = lambda: provider
    try:
        response = TestClient(app).post("/submissions", json={"problem_id": 1, "code": "print('yes')"})
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)

    assert response.status_code == 201
    body = response.json()
    assert len(provider.requests) == 1
    assert len(provider.requests[0].test_cases) == 2
    assert body["overall_status"] == "WRONG_ANSWER"
    hidden = body["test_results"][1]
    assert hidden == {"test_case_id": 2, "is_hidden": True, "status": "WRONG_ANSWER", "stdout": None}
    assert "DO NOT LEAK" not in response.text
    assert "SECRET" not in response.text
    assert "private stderr" not in response.text


@pytest.mark.integration
def test_judge0_local_integration_is_opt_in() -> None:
    """Run only with RUN_JUDGE0_INTEGRATION=1 and a local Judge0 service."""
    if os.getenv("RUN_JUDGE0_INTEGRATION") != "1":
        pytest.skip("set RUN_JUDGE0_INTEGRATION=1 to test a local Judge0 service")
    base_url = os.getenv("JUDGE0_BASE_URL", "http://localhost:2358")
    results = asyncio.run(Judge0ExecutionService(base_url).execute_batch(request()))
    assert results[0].status is ExecutionStatus.ACCEPTED
