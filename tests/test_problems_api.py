from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import problems as problems_api
from app.db.base import Base
from app.main import app
from app.models.problem import Problem
from app.models.test_case import TestCase
from app.services.problem_service import ProblemNotFoundError, get_problem


def make_problem() -> Problem:
    return Problem(
        id=7,
        title="Two Sum",
        description="Find two values that add to a target.",
        difficulty="Easy",
        source="DEV Placement OS",
        topic="Arrays",
        subtopic="Hashing",
        constraints="2 <= n <= 10^4",
        input_format="Numbers then target",
        output_format="Two indices",
        expected_complexity="O(n)",
        target_track="Core DSA",
        created_at=datetime(2026, 8, 28, tzinfo=UTC),
    )


def make_sample_case() -> TestCase:
    return TestCase(
        id=11,
        problem_id=7,
        input="2 7 11 15\n9",
        expected_output="0 1",
        is_sample=True,
        is_hidden=False,
        weight=1,
    )


def test_list_problems_returns_learner_safe_catalogue(monkeypatch) -> None:
    monkeypatch.setattr(problems_api, "list_problems", lambda _db: [make_problem()])

    response = TestClient(app).get("/problems")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 7,
            "title": "Two Sum",
            "difficulty": "Easy",
            "source": "DEV Placement OS",
            "topic": "Arrays",
            "subtopic": "Hashing",
            "target_track": "Core DSA",
        }
    ]


def test_list_problems_returns_empty_list_when_catalogue_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(problems_api, "list_problems", lambda _db: [])

    response = TestClient(app).get("/problems")

    assert response.status_code == 200
    assert response.json() == []


def test_list_problems_returns_server_error_when_catalogue_lookup_fails(monkeypatch) -> None:
    def fail(_db):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(problems_api, "list_problems", fail)

    response = TestClient(app, raise_server_exceptions=False).get("/problems")

    assert response.status_code == 500


def test_get_problem_returns_details_and_only_visible_sample_case(monkeypatch) -> None:
    monkeypatch.setattr(
        problems_api,
        "get_problem",
        lambda _db, _problem_id: (make_problem(), [make_sample_case()]),
    )

    response = TestClient(app).get("/problems/7")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 7
    assert body["description"] == "Find two values that add to a target."
    assert body["sample_test_cases"] == [
        {"id": 11, "input": "2 7 11 15\n9", "expected_output": "0 1"}
    ]
    assert "is_hidden" not in body["sample_test_cases"][0]
    assert "weight" not in body["sample_test_cases"][0]


def test_problem_service_excludes_hidden_test_case_content() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    hidden_input = "PRIVATE INPUT"
    hidden_output = "PRIVATE EXPECTED OUTPUT"
    try:
        session.add(make_problem())
        session.add_all(
            [
                make_sample_case(),
                TestCase(
                    id=12,
                    problem_id=7,
                    input=hidden_input,
                    expected_output=hidden_output,
                    is_sample=False,
                    is_hidden=True,
                    weight=2,
                ),
            ]
        )
        session.commit()

        _problem, visible_cases = get_problem(session, 7)

        assert [test_case.id for test_case in visible_cases] == [11]
        assert hidden_input not in [test_case.input for test_case in visible_cases]
        assert hidden_output not in [test_case.expected_output for test_case in visible_cases]
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_get_problem_returns_not_found_for_unknown_id(monkeypatch) -> None:
    def not_found(_db, _problem_id):
        raise ProblemNotFoundError

    monkeypatch.setattr(problems_api, "get_problem", not_found)

    response = TestClient(app).get("/problems/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Problem not found"}
