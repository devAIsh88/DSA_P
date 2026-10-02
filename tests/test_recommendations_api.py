"""Learner-safe adaptive API checks without live tutor or execution access."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from adaptive_fixtures import FrozenClock, NOW, PRIVATE_MARKERS, create_adaptive_database
from app.api import recommendations
from app.db.session import get_db
from app.main import app
from app.models.learning_event import LearningEvent
from app.models.problem import Problem
from app.models.problem_skill import ProblemSkill
from app.models.recommendation import Recommendation
from app.models.skill_state import SkillState
from app.models.user import User
from app.schemas.recommendation import RecommendationPolicyConfig
from app.services.execution_service import Judge0ExecutionService
from app.services.gemini_tutor_provider import GeminiTutorProvider
from app.services.recommendation_service import RecommendationUnavailableError, get_next_recommendation


@pytest.fixture
def adaptive_api(monkeypatch):
    harness, engine = create_adaptive_database(monkeypatch)
    options = {"now": NOW, "config": None}

    def test_db():
        with harness.factory() as db:
            yield db

    def fixed_clock_next(db):
        return get_next_recommendation(db, **options)

    async def forbidden_provider_call(*_args, **_kwargs):
        raise AssertionError("Recommendations must not invoke a model or execution provider")

    monkeypatch.setattr(recommendations, "get_next_recommendation", fixed_clock_next)
    monkeypatch.setattr(GeminiTutorProvider, "_generate", forbidden_provider_call)
    monkeypatch.setattr(Judge0ExecutionService, "execute_batch", forbidden_provider_call)
    app.dependency_overrides[get_db] = test_db
    try:
        with TestClient(app) as client:
            yield client, harness, options
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_authorized_route_exposes_exact_allowlisted_cold_start_contract(adaptive_api) -> None:
    client, harness, _ = adaptive_api
    response = client.get("/recommendations/next")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"recommendation", "unavailable_reason"}
    assert payload["unavailable_reason"] is None
    assert set(payload["recommendation"]) == {
        "id", "action_type", "problem_id", "skill_id", "policy_version", "reason_codes", "created_at",
    }
    assert payload["recommendation"]["action_type"] == "NEXT_PROBLEM"
    assert payload["recommendation"]["problem_id"] == 1
    assert payload["recommendation"]["reason_codes"] == ["COLD_START"]
    assert payload["recommendation"]["created_at"].endswith("Z")
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 1
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 0
        assert db.scalar(select(func.count()).select_from(SkillState)) == 0


def test_repeated_get_reuses_identical_persisted_response(adaptive_api) -> None:
    client, harness, options = adaptive_api
    first = client.get("/recommendations/next")
    options["now"] += timedelta(hours=1)
    second = client.get("/recommendations/next")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 1


def test_completed_history_changes_recommendation_without_mutating_mastery(adaptive_api) -> None:
    client, harness, _ = adaptive_api
    initial = client.get("/recommendations/next").json()["recommendation"]
    harness.solve(1)
    state = client.get("/learner/skills/1").json()
    response = client.get("/recommendations/next")
    assert response.status_code == 200
    result = response.json()["recommendation"]
    assert result["id"] != initial["id"]
    assert result["problem_id"] == 4
    assert client.get("/learner/skills/1").json() == state


def test_active_attempt_returns_defined_conflict_and_no_new_recommendation(adaptive_api) -> None:
    client, harness, _ = adaptive_api
    second = harness.start(2)
    first = harness.start(1)
    response = client.get("/recommendations/next")
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "ACTIVE_ATTEMPT_EXISTS", "attempt_ids": sorted([first, second])}}
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 0


def test_revision_deadline_invalidates_without_new_learning_event(adaptive_api) -> None:
    client, harness, options = adaptive_api
    FrozenClock.value = NOW - timedelta(days=6)
    harness.solve(1)
    harness.solve(2)
    first = client.get("/recommendations/next").json()["recommendation"]
    assert first["action_type"] == "INCREASE_DIFFICULTY"
    with harness.factory() as db:
        count = db.scalar(select(func.count()).select_from(LearningEvent))
    options["now"] = NOW + timedelta(days=1)
    second = client.get("/recommendations/next").json()["recommendation"]
    assert second["id"] != first["id"]
    assert second["action_type"] == "REVISE_CONCEPT"
    assert second["reason_codes"] == ["SCHEDULED_REVIEW_DUE"]
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == count


def test_empty_catalogue_returns_explicit_empty_200_without_fake_record(adaptive_api) -> None:
    client, harness, _ = adaptive_api
    with harness.factory() as db:
        for problem in list(db.scalars(select(Problem))):
            db.delete(problem)
        db.commit()
    response = client.get("/recommendations/next")
    assert response.status_code == 200
    assert response.json() == {"recommendation": None, "unavailable_reason": "EMPTY_CATALOGUE"}
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 0


def test_unknown_difficulty_returns_no_eligible_candidate(adaptive_api) -> None:
    client, harness, _ = adaptive_api
    with harness.factory() as db:
        for problem in db.scalars(select(Problem)):
            problem.difficulty = "Unknown"
        db.commit()
    response = client.get("/recommendations/next")
    assert response.status_code == 200
    assert response.json() == {"recommendation": None, "unavailable_reason": "NO_ELIGIBLE_PROBLEM"}


def test_unsupported_catalogue_can_be_excluded_by_versioned_policy(adaptive_api) -> None:
    client, harness, options = adaptive_api
    with harness.factory() as db:
        for mapping in list(db.scalars(select(ProblemSkill))):
            db.delete(mapping)
        db.commit()
    options["config"] = RecommendationPolicyConfig(version="adaptive-test-v2", allow_unattributed_catalogue=False)
    response = client.get("/recommendations/next")
    assert response.status_code == 200
    assert response.json() == {"recommendation": None, "unavailable_reason": "NO_ELIGIBLE_PROBLEM"}


@pytest.mark.parametrize("mapping_kind", ["unmapped", "multiple", "nonunit"])
def test_supported_baseline_fallback_reports_no_false_skill(adaptive_api, mapping_kind: str) -> None:
    client, harness, _ = adaptive_api
    with harness.factory() as db:
        for problem in (2, 3, 4, 5):
            db.get(Problem, problem).difficulty = "Unknown"
        if mapping_kind == "unmapped":
            db.delete(db.get(ProblemSkill, (1, 1)))
        elif mapping_kind == "multiple":
            db.add(ProblemSkill(problem_id=1, skill_id=2, weight=1.0))
        else:
            db.get(ProblemSkill, (1, 1)).weight = 0.5
        db.commit()
    response = client.get("/recommendations/next")
    assert response.status_code == 200
    result = response.json()["recommendation"]
    assert result["skill_id"] is None
    assert result["reason_codes"] == ["COLD_START", "UNATTRIBUTED_CATALOGUE"]


def test_stale_projection_returns_service_unavailable_without_rebuilding(adaptive_api) -> None:
    client, harness, _ = adaptive_api
    harness.solve(1)
    with harness.factory() as db:
        db.get(SkillState, (1, 1)).model_version = "unknown"
        db.commit()
    response = client.get("/recommendations/next")
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "LEARNER_STATE_NOT_READY"}}
    with harness.factory() as db:
        assert db.get(SkillState, (1, 1)).model_version == "unknown"
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 0


def test_persistence_failure_has_no_synthetic_success_or_private_error(adaptive_api, monkeypatch) -> None:
    client, harness, _ = adaptive_api

    def fail(_db):
        raise RecommendationUnavailableError("PRIVATE INTERNAL DATABASE DETAILS")

    monkeypatch.setattr(recommendations, "get_next_recommendation", fail)
    response = client.get("/recommendations/next")
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "RECOMMENDATION_UNAVAILABLE"}}
    assert "PRIVATE" not in response.text
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 0


def test_missing_and_ambiguous_learner_are_not_implicitly_provisioned(adaptive_api) -> None:
    client, harness, _ = adaptive_api
    with harness.factory() as db:
        db.add(User(id=2))
        db.commit()
    assert client.get("/recommendations/next").status_code == 409
    with harness.factory() as db:
        db.delete(db.get(User, 1))
        db.delete(db.get(User, 2))
        db.commit()
    assert client.get("/recommendations/next").status_code == 404
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 0


def test_recommendation_json_omits_all_private_execution_and_learner_content(adaptive_api) -> None:
    client, harness, _ = adaptive_api
    attempt_id = harness.solve(1, hint_level=4, reasoning=True)
    events_before = client.get(f"/attempts/{attempt_id}/events").json()
    skills_before = client.get("/learner/skills").json()
    response = client.get("/recommendations/next")
    assert response.status_code == 200
    assert response.json()["recommendation"]["action_type"] == "RETRY_SIMILAR_PROBLEM"
    assert all(marker not in response.text for marker in PRIVATE_MARKERS)
    for field in ("input_snapshot", "input_fingerprint", "evidence_through_event_id", "provenance"):
        assert field not in response.text
    assert client.get(f"/attempts/{attempt_id}/events").json() == events_before
    assert client.get("/learner/skills").json() == skills_before


def test_only_authorized_endpoint_is_present_without_request_parameters(adaptive_api) -> None:
    client, _, _ = adaptive_api
    openapi = client.get("/openapi.json").json()
    recommendation_paths = [path for path in openapi["paths"] if path.startswith("/recommendations")]
    assert recommendation_paths == ["/recommendations/next"]
    operation = openapi["paths"]["/recommendations/next"]["get"]
    assert not operation.get("parameters") and "requestBody" not in operation
    assert client.post("/recommendations/next").status_code == 405
