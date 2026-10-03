"""UI contracts/state are deterministic and require no running HTTP service."""

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from app.schemas.dashboard import LearnerStateResponse
from app.schemas.submission import SubmissionCreate
from frontend.api_client import APIClient, APIError
from frontend.config import UISettings
from frontend.state import finish_operation, operation_key, positive_id


def test_client_parses_learner_schema():
    client = APIClient("http://test", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"user_id": 7, "active_attempts": [], "skills": []})))
    assert client.learner().user_id == 7


def test_client_serializes_post_once_and_never_retries():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("provider-private-detail", request=request)

    client = APIClient("http://test", transport=httpx.MockTransport(handler))
    with pytest.raises(APIError) as error:
        client.submit(SubmissionCreate(problem_id=1, attempt_id=3, code="print(1)", idempotency_key="retry"))
    assert len(requests) == 1
    assert b'"idempotency_key":"retry"' in requests[0].content
    assert error.value.code == "NETWORK_UNAVAILABLE"
    assert "provider-private-detail" not in str(error.value)


@pytest.mark.parametrize("status", [404, 409, 422, 500, 503, 504])
def test_client_never_displays_private_error_body(status):
    client = APIClient("http://test", transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json={"detail": "SECRET hidden-input provider-token"})))
    with pytest.raises(APIError) as error:
        client.learner()
    assert error.value.status == status
    assert "SECRET" not in str(error.value)
    assert "hidden-input" not in str(error.value)


def test_active_conflict_only_exposes_safe_attempt_ids():
    client = APIClient("http://test", transport=httpx.MockTransport(lambda request: httpx.Response(
        409, json={"detail": {"code": "ACTIVE_ATTEMPT_EXISTS", "attempt_ids": [2, -1, "secret", True]}})))
    with pytest.raises(APIError) as error:
        client.recommendation()
    assert error.value.attempt_ids == (2,)


def test_bad_response_is_safe():
    client = APIClient("http://test", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"user_id": "SECRET"})))
    with pytest.raises(APIError) as error:
        client.learner()
    assert error.value.code == "INVALID_RESPONSE"
    assert "SECRET" not in str(error.value)


def test_operation_identity_survives_retry_and_changes_with_payload():
    state = {}
    first = operation_key(state, "submit", {"code": "one", "attempt_id": 1})
    assert operation_key(state, "submit", {"attempt_id": 1, "code": "one"}) == first
    assert "one" not in str(state)
    assert operation_key(state, "submit", {"code": "two", "attempt_id": 1}) != first
    finish_operation(state, "submit")
    assert not state["operations"]


@pytest.mark.parametrize("value,expected", [("4", 4), (None, None), ("-1", None), ("secret", None), ("0", None)])
def test_url_identifiers(value, expected):
    assert positive_id(value) == expected


def test_ui_config_contains_no_provider_or_database_fields(monkeypatch):
    settings = UISettings(_env_file=None, UI_LEARNER_ID=7)
    assert set(UISettings.model_fields) == {"api_base_url", "learner_id", "request_timeout_seconds"}
    assert settings.learner_id == 7
    with pytest.raises(ValidationError):
        UISettings(_env_file=None, UI_API_BASE_URL="http://user:secret@localhost")


def test_shell_connects_without_provider_calls(monkeypatch):
    monkeypatch.setenv("UI_LEARNER_ID", "7")
    monkeypatch.setattr(APIClient, "learner", lambda self: LearnerStateResponse(
        user_id=7, active_attempts=[], skills=[]))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "frontend/app.py").run()
    assert not app.exception
    assert any(header.value == "Home / Progress" for header in app.header)


def test_shell_fails_closed_on_configured_identity_mismatch(monkeypatch):
    monkeypatch.setenv("UI_LEARNER_ID", "8")
    monkeypatch.setattr(APIClient, "learner", lambda self: LearnerStateResponse(
        user_id=7, active_attempts=[], skills=[]))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "frontend/app.py").run()
    assert not app.exception
    assert "does not match" in app.error[0].value
