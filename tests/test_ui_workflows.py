"""Streamlit interactions bridged to disposable FastAPI, never live providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from streamlit.testing.v1 import AppTest

from app.main import app as backend_app
from app.models.attempt import Attempt
from app.models.learning_event import LearningEvent
from app.models.recommendation import Recommendation
from app.models.submission import Submission
from app.schemas.execution import ExecutionStatus
from app.services.tutor_provider_factory import get_tutor_provider
from frontend.api_client import APIClient
from test_phase8_backend import Phase8Harness, UnavailableTutor, phase8_api  # noqa: F401


ENTRYPOINT = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


@dataclass
class UIHarness:
    backend: Phase8Harness
    calls: list[tuple[str, str]] = field(default_factory=list)
    lose_next_response: str | None = None
    overrides: dict[tuple[str, str], tuple[int, dict]] = field(default_factory=dict)

    def request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if (request.method, path) in self.overrides:
            status, payload = self.overrides[(request.method, path)]
            return httpx.Response(status, json=payload, request=request)
        result = self.backend.client.request(
            request.method, path, content=request.content,
            headers={"content-type": "application/json"},
        )
        if request.method == "POST" and path == self.lose_next_response:
            self.lose_next_response = None
            raise httpx.ReadTimeout("PRIVATE NETWORK DETAIL", request=request)
        return httpx.Response(result.status_code, content=result.content,
                              headers={"content-type": "application/json"}, request=request)

    def open(self, *, problem_id: int | None = None, attempt_id: int | None = None) -> AppTest:
        ui = AppTest.from_file(ENTRYPOINT, default_timeout=20)
        if problem_id is not None:
            ui.query_params["problem_id"] = str(problem_id)
        if attempt_id is not None:
            ui.query_params["attempt_id"] = str(attempt_id)
        ui.run()
        assert_clean(ui)
        return ui


@pytest.fixture
def ui_api(phase8_api, monkeypatch) -> UIHarness:
    harness = UIHarness(phase8_api)
    transport = httpx.MockTransport(harness.request)
    original_init = APIClient.__init__

    def bridged_init(self, base_url, timeout=90, transport=None):
        original_init(self, "http://isolated.test", timeout, transport=harness_transport)

    harness_transport = transport
    monkeypatch.setattr(APIClient, "__init__", bridged_init)
    monkeypatch.setenv("UI_LEARNER_ID", "1")
    monkeypatch.setenv("UI_API_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("GOOGLE_API_KEY", "PRIVATE_UI_API_KEY")
    return harness


def assert_clean(ui: AppTest) -> None:
    assert not ui.exception, [exception.value for exception in ui.exception]
    rendered = "\n".join(str(element.value) for kind in (
        "title", "header", "subheader", "caption", "markdown", "text", "code",
        "info", "warning", "error", "success", "metric",
    ) for element in ui.get(kind))
    for secret in ("PRIVATE HIDDEN INPUT", "PRIVATE HIDDEN OUTPUT", "PRIVATE STDERR", "PRIVATE COMPILE",
                   "PRIVATE_UI_API_KEY", "PRIVATE NETWORK DETAIL", "input_snapshot", "input_fingerprint"):
        assert secret not in rendered


def button(ui: AppTest, *, key: str | None = None, label: str | None = None):
    matches = [item for item in ui.button if (key is not None and item.key == key)
               or (label is not None and item.label == label)]
    assert len(matches) == 1, (key, label, [(item.key, item.label) for item in ui.button])
    return matches[0]


def click(ui: AppTest, *, key: str | None = None, label: str | None = None) -> AppTest:
    target = button(ui, key=key, label=label)
    assert not target.disabled, (target.key, target.label)
    target.click().run()
    assert_clean(ui)
    return ui


def text_area(ui: AppTest, key: str):
    matches = [item for item in ui.text_area if item.key == key]
    assert len(matches) == 1
    return matches[0]


def query_id(ui: AppTest, name: str) -> int:
    # AppTest represents query values as lists after Streamlit navigation.
    value = ui.query_params[name]
    return int(value[0] if isinstance(value, list) else value)


def start_workspace(h: UIHarness) -> tuple[AppTest, int]:
    ui = h.open(problem_id=1)
    click(ui, key="start:1")
    attempt_id = query_id(ui, "attempt_id")
    return ui, attempt_id


def test_ui_open_does_not_start_attempt_and_run_does_not_create_evidence(ui_api) -> None:
    h = ui_api
    ui = h.open()
    assert not any(method == "POST" for method, _path in h.calls)
    assert ("GET", "/recommendations/next") not in h.calls
    click(ui, key="catalogue_open_1")
    with h.backend.factory() as db:
        assert db.scalar(select(func.count()).select_from(Attempt)) == 0
    click(ui, key="start:1")
    attempt_id = query_id(ui, "attempt_id")
    assert button(ui, key=f"solved:{attempt_id}").disabled
    text_area(ui, f"code:{attempt_id}").set_value("accepted code").run()
    before = h.backend.snapshot()
    click(ui, key=f"run:{attempt_id}")
    assert h.backend.snapshot() == before
    assert button(ui, key=f"solved:{attempt_id}").disabled
    assert any(item.value == "Sample Run result" for item in ui.subheader)
    assert all(key in {"view", "problem_id", "attempt_id"} for key in ui.query_params)


def test_ui_primary_learning_loop_and_next_recommendation_consumption(ui_api) -> None:
    h = ui_api
    ui = h.open()
    click(ui, key="recommendation_refresh")
    issued_calls = h.calls.count(("GET", "/recommendations/next"))
    ui.run()
    assert h.calls.count(("GET", "/recommendations/next")) == issued_calls
    with h.backend.factory() as db:
        first_recommendation = db.scalar(select(Recommendation))
        first_id = first_recommendation.id
        problem_id = first_recommendation.problem_id
    click(ui, key="recommendation_open")
    click(ui, key=f"start:{problem_id}")
    attempt_id = query_id(ui, "attempt_id")
    text_area(ui, f"reasoning:{attempt_id}").set_value("The invariant explains each step.")
    click(ui, label="Save reasoning")
    text_area(ui, f"code:{attempt_id}").set_value("wrong code").run()
    before_run = h.backend.snapshot()
    click(ui, key=f"run:{attempt_id}")
    assert h.backend.snapshot() == before_run
    click(ui, key=f"submit:{attempt_id}")
    assert button(ui, key=f"solved:{attempt_id}").disabled
    submission = h.backend.client.get(f"/attempts/{attempt_id}/events").json()[-1]["submission_id"]
    click(ui, key=f"diagnose:{attempt_id}:{submission}")
    click(ui, label="Analyze saved reasoning")
    text_area(ui, f"code:{attempt_id}").set_value("accepted code").run()
    click(ui, key=f"run:{attempt_id}")
    assert button(ui, key=f"solved:{attempt_id}").disabled
    click(ui, key=f"submit:{attempt_id}")
    assert not button(ui, key=f"solved:{attempt_id}").disabled
    click(ui, key=f"solved:{attempt_id}")
    assert text_area(ui, f"code:{attempt_id}").disabled
    state = h.backend.client.get("/learner/state").json()["skills"][0]
    assert state["independent_solve_count"] == 1
    assert state["mastery_probability"] > 0.2
    click(ui, key=f"post_explanation:{attempt_id}")
    click(ui, key=f"understanding_check:{attempt_id}")
    events = h.backend.client.get(f"/attempts/{attempt_id}/events").json()
    check = next(event for event in reversed(events) if event["evidence"].get("stage") == "PROMPTED")
    text_area(ui, f"understanding_answer:{attempt_id}:{check['id']}").set_value("Invariant, O(n) time, empty input edge case.")
    click(ui, label="Save answer and request AI evaluation")
    assert button(ui, label="Answer already saved").disabled
    click(ui, label="Home / Progress")
    assert any(item.label == "Solved Attempts" and item.value == "1" for item in ui.metric)
    click(ui, key="recommendation_refresh")
    with h.backend.factory() as db:
        recommendation = db.scalar(select(Recommendation).where(
            Recommendation.consumed_at.is_(None), Recommendation.superseded_at.is_(None)))
        next_id, next_problem = recommendation.id, recommendation.problem_id
    click(ui, key="recommendation_open")
    click(ui, key=f"start:{next_problem}")
    with h.backend.factory() as db:
        assert db.get(Recommendation, first_id).consumed_at is not None
        assert db.get(Recommendation, next_id).consumed_at is not None


def test_full_new_ui_session_restores_attempt_code_result_and_reasoning(ui_api) -> None:
    h = ui_api
    attempt_id = h.backend.start()
    reasoning = h.backend.client.post(f"/attempts/{attempt_id}/reasoning", json={"reasoning_text": "Persisted reasoning"})
    assert reasoning.status_code == 201
    h.backend.submit(attempt_id)
    before = h.backend.snapshot()
    ui = h.open(attempt_id=attempt_id)
    assert text_area(ui, f"code:{attempt_id}").value == "accepted code"
    assert text_area(ui, f"reasoning:{attempt_id}").value == "Persisted reasoning"
    assert not button(ui, key=f"solved:{attempt_id}").disabled
    assert any(item.value == "Deterministic submission result" for item in ui.subheader)
    assert h.backend.snapshot() == before
    fresh = h.open(attempt_id=attempt_id)
    assert text_area(fresh, f"code:{attempt_id}").value == "accepted code"
    assert h.backend.snapshot() == before


def test_ui_assisted_activity_changes_reporting_without_mastery(ui_api) -> None:
    h = ui_api
    ui, attempt_id = start_workspace(h)
    click(ui, key=f"hint_request:{attempt_id}")
    text_area(ui, f"code:{attempt_id}").set_value("accepted code").run()
    click(ui, key=f"submit:{attempt_id}")
    click(ui, key=f"solved:{attempt_id}")
    skill = h.backend.client.get("/learner/state").json()["skills"][0]
    assert skill["mastery_probability"] == pytest.approx(0.2)
    assert skill["hint_dependent_count"] == skill["hint_count_total"] == 1
    assert skill["independent_solve_count"] == 0
    click(ui, label="Home / Progress")
    assert any(item.label == "Hint requests" and item.value == "1" for item in ui.metric)


def test_ui_provider_failure_preserves_answer_blocks_resubmission_and_core_flow(ui_api) -> None:
    h = ui_api
    backend_app.dependency_overrides[get_tutor_provider] = lambda: UnavailableTutor()
    ui, attempt_id = start_workspace(h)
    click(ui, key=f"hint_request:{attempt_id}")
    assert any("Safe static fallback" in item.value for item in ui.caption)
    text_area(ui, f"code:{attempt_id}").set_value("accepted code").run()
    click(ui, key=f"run:{attempt_id}")
    click(ui, key=f"submit:{attempt_id}")
    click(ui, label="Diagnose latest submission")
    assert any("temporarily unavailable" in item.value for item in ui.error)
    click(ui, key=f"solved:{attempt_id}")
    click(ui, key=f"understanding_check:{attempt_id}")
    events = h.backend.client.get(f"/attempts/{attempt_id}/events").json()
    check = next(event for event in events if event["evidence"].get("stage") == "PROMPTED")
    answer_path = f"/attempts/{attempt_id}/understanding-checks/{check['id']}/answer"
    text_area(ui, f"understanding_answer:{attempt_id}:{check['id']}").set_value("Saved despite unavailable model")
    click(ui, label="Save answer and request AI evaluation")
    assert any(item.value == "Answer saved; AI evaluation unavailable." for item in ui.info)
    assert button(ui, label="Answer already saved").disabled
    assert h.calls.count(("POST", answer_path)) == 1
    ui.run()
    refreshed = h.open(attempt_id=attempt_id)
    assert button(refreshed, label="Answer already saved").disabled
    assert any(item.value == "Answer saved; AI evaluation unavailable." for item in refreshed.info)
    assert h.calls.count(("POST", answer_path)) == 1
    click(refreshed, label="Home / Progress")
    click(refreshed, key="recommendation_refresh")
    assert any(item.key == "recommendation_open" for item in refreshed.button)


def test_ui_lost_submission_response_recovers_without_duplicate_grading(ui_api) -> None:
    h = ui_api
    ui, attempt_id = start_workspace(h)
    text_area(ui, f"code:{attempt_id}").set_value("accepted code").run()
    h.lose_next_response = "/submissions"
    click(ui, key=f"submit:{attempt_id}")
    assert not button(ui, key=f"solved:{attempt_id}").disabled
    assert h.calls.count(("POST", "/submissions")) == 1
    with h.backend.factory() as db:
        assert db.scalar(select(func.count()).select_from(Submission)) == 1
    ui.run()
    fresh = h.open(attempt_id=attempt_id)
    assert text_area(fresh, f"code:{attempt_id}").value == "accepted code"
    assert h.calls.count(("POST", "/submissions")) == 1
    click(ui, key=f"submit:{attempt_id}")  # Same-session explicit retry retains key.
    with h.backend.factory() as db:
        assert db.scalar(select(func.count()).select_from(Submission)) == 1
    assert len(h.backend.execution.requests) == 1


def test_ui_lost_start_response_offers_resume_without_parallel_attempt(ui_api) -> None:
    h = ui_api
    ui = h.open(problem_id=1)
    h.lose_next_response = "/attempts/start"
    click(ui, key="start:1")
    with h.backend.factory() as db:
        attempts = list(db.scalars(select(Attempt)))
        assert len(attempts) == 1
        attempt_id = attempts[0].id
    assert not any(item.key == "start:1" for item in ui.button)
    click(ui, key=f"resume:{attempt_id}")
    assert query_id(ui, "attempt_id") == attempt_id
    assert h.calls.count(("POST", "/attempts/start")) == 1


def test_ui_multiple_active_attempt_navigation_and_abandoned_revisit(ui_api) -> None:
    h = ui_api
    first = h.backend.start(1, "first")
    second = h.backend.start(2, "second")
    ui = h.open()
    assert [item.key for item in ui.button if str(item.key).startswith("active_resume_")] == [
        f"active_resume_{first}", f"active_resume_{second}",
    ]
    assert not any(item.key == "recommendation_refresh" for item in ui.button)
    click(ui, key=f"active_resume_{second}")
    assert query_id(ui, "attempt_id") == second
    click(ui, key=f"abandon:{second}")
    assert text_area(ui, f"code:{second}").disabled
    assert not any(item.key == f"revisit:{second}" for item in ui.button)
    assert h.backend.client.post(f"/attempts/{first}/abandon").status_code == 200
    ui.run()
    click(ui, key=f"revisit:{second}")
    new_id = query_id(ui, "attempt_id")
    assert new_id not in {first, second}
    assert h.backend.client.get(f"/attempts/{second}").json()["status"] == "ABANDONED"


def test_ui_infrastructure_result_is_not_incorrectness_and_latest_submit_controls_solved(ui_api) -> None:
    h = ui_api
    ui, attempt_id = start_workspace(h)
    text_area(ui, f"code:{attempt_id}").set_value("accepted code").run()
    click(ui, key=f"submit:{attempt_id}")
    assert not button(ui, key=f"solved:{attempt_id}").disabled
    h.backend.execution.status = ExecutionStatus.SYSTEM_ERROR
    before = h.backend.snapshot()
    click(ui, key=f"run:{attempt_id}")
    assert h.backend.snapshot() == before
    assert any("not evidence of learner incorrectness" in item.value for item in ui.warning)
    click(ui, key=f"submit:{attempt_id}")
    assert button(ui, key=f"solved:{attempt_id}").disabled
    assert any("Execution infrastructure unavailable" in item.value for item in ui.warning)
    assert h.backend.client.get("/learner/state").json()["skills"] == []


def test_ui_level_six_gate_records_request_and_backend_permits_after_level_five(ui_api) -> None:
    h = ui_api
    ui, attempt_id = start_workspace(h)
    level = next(item for item in ui.selectbox if item.key == f"hint_level:{attempt_id}")
    level.set_value(6).run()
    click(ui, key=f"hint_request:{attempt_id}")
    events = h.backend.client.get(f"/attempts/{attempt_id}/events").json()
    assert [event["event_type"] for event in events] == ["ATTEMPT_STARTED", "HINT_REQUESTED"]
    assert any("No delivered hint" in item.value for item in ui.caption)
    assert h.backend.tutor.calls == []
    level = next(item for item in ui.selectbox if item.key == f"hint_level:{attempt_id}")
    level.set_value(5).run()
    click(ui, key=f"hint_request:{attempt_id}")
    level = next(item for item in ui.selectbox if item.key == f"hint_level:{attempt_id}")
    level.set_value(6).run()
    click(ui, key=f"hint_request:{attempt_id}")
    events = h.backend.client.get(f"/attempts/{attempt_id}/events").json()
    delivered = [event for event in events if event["event_type"] == "HINT_DELIVERED"]
    assert [event["evidence"]["hint_level_delivered"] for event in delivered] == [5, 6]
    assert len(h.backend.tutor.calls) == 2


def test_ui_recommendation_failure_preserves_catalogue_and_problem_view(ui_api) -> None:
    h = ui_api
    h.overrides[("GET", "/recommendations/next")] = (
        503, {"detail": {"code": "LEARNER_STATE_NOT_READY", "private": "PRIVATE_UI_API_KEY"}},
    )
    ui = h.open()
    click(ui, key="recommendation_refresh")
    assert any("not ready" in item.value for item in ui.warning)
    assert any(item.key == "catalogue_open_1" for item in ui.button)
    click(ui, key="catalogue_open_1")
    assert any(item.key == "start:1" for item in ui.button)
    with h.backend.factory() as db:
        assert db.scalar(select(func.count()).select_from(Attempt)) == 0
