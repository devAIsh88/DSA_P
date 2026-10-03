"""Explicit demo setup is idempotent, conflict-safe and never fabricates history."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from adaptive_fixtures import NOW, create_adaptive_database
from app.db.base import Base
from app.models import Attempt, LearningEvent, Problem, ProblemSkill, Recommendation, Skill, SkillState, Submission, User
from app.models.test_case import TestCase as ProblemTestCase
from scripts.demo_catalogue import DEMO_PROBLEMS, DEMO_SOURCE
from scripts.provision_demo import DemoProvisioningError, main, provision_demo, validate_local_demo_database


@pytest.fixture
def demo_db() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    try:
        yield factory
    finally:
        engine.dispose()


def snapshot(factory) -> dict:
    with factory() as db:
        return {table.name: [tuple(row) for row in db.execute(select(table))]
                for table in Base.metadata.sorted_tables}


def assert_no_history(factory) -> None:
    with factory() as db:
        for model in (Attempt, Submission, LearningEvent, SkillState, Recommendation):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_demo_provisions_small_supported_catalogue_without_learner_history(demo_db) -> None:
    with demo_db() as db:
        result = provision_demo(db)
    assert result.user_id > 0
    assert result.users_created == 1
    assert result.skills_created == 2
    assert result.problems_created == result.mappings_created == 6
    assert result.test_cases_created == 25
    assert len(set(result.problem_ids)) == 6
    assert len(set(result.skill_ids)) == 2
    with demo_db() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert {skill.name for skill in db.scalars(select(Skill))} == {"Arrays", "Hashing"}
        assert {problem.difficulty for problem in db.scalars(select(Problem))} == {"Easy", "Medium", "Hard"}
        assert db.scalar(select(func.count()).select_from(ProblemTestCase).where(
            ProblemTestCase.is_sample.is_(True), ProblemTestCase.is_hidden.is_(False),
        )) == 12
        assert db.scalar(select(func.count()).select_from(ProblemTestCase).where(
            ProblemTestCase.is_hidden.is_(True),
        )) == 13
        for problem_id in result.problem_ids:
            problem = db.get(Problem, problem_id)
            assert problem.source == DEMO_SOURCE
            assert problem.description and problem.constraints and problem.input_format and problem.output_format
            mapping = list(db.scalars(select(ProblemSkill).where(ProblemSkill.problem_id == problem_id)))
            assert len(mapping) == 1
            assert mapping[0].weight == 1.0
            assert mapping[0].skill_id in result.skill_ids
    assert_no_history(demo_db)


def test_demo_rerun_reuses_identical_records_and_creates_nothing(demo_db) -> None:
    with demo_db() as db:
        initial = provision_demo(db)
    before = snapshot(demo_db)
    with demo_db() as db:
        repeated = provision_demo(db)
    assert repeated.user_id == initial.user_id
    assert repeated.problem_ids == initial.problem_ids
    assert repeated.skill_ids == initial.skill_ids
    for field in ("users_created", "skills_created", "problems_created", "test_cases_created", "mappings_created"):
        assert getattr(repeated, field) == 0
    assert snapshot(demo_db) == before
    assert_no_history(demo_db)


def test_demo_reuses_existing_learner_and_public_skill_without_overwriting(demo_db) -> None:
    with demo_db() as db:
        db.add(User(id=19))
        db.add(Skill(id=37, name="Arrays", description="Existing accepted description", difficulty_range="Easy"))
        db.add(Problem(id=41, title="Legitimate existing problem", description="Keep", topic="Other",
                       difficulty="Easy", source="user-catalogue"))
        db.commit()
        result = provision_demo(db)
    assert result.user_id == 19
    assert result.users_created == 0
    assert result.skills_created == 1
    assert 37 in result.skill_ids
    with demo_db() as db:
        assert db.get(Skill, 37).description == "Existing accepted description"
        assert db.get(Skill, 37).difficulty_range == "Easy"
        assert db.get(Problem, 41).description == "Keep"
        assert db.scalar(select(func.count()).select_from(Problem)) == 7
    assert_no_history(demo_db)


def test_demo_preserves_existing_real_service_activity_state_and_recommendations(monkeypatch) -> None:
    from app.services.recommendation_service import get_next_recommendation

    data, engine = create_adaptive_database(monkeypatch)
    try:
        data.solve(1, reasoning=True)
        with data.factory() as db:
            get_next_recommendation(db, now=NOW)
        history_tables = {"attempts", "submissions", "test_results", "learning_events", "skill_states", "recommendations"}
        before = {table: rows for table, rows in snapshot(data.factory).items() if table in history_tables}
        assert all(before[table] for table in history_tables)
        with data.factory() as db:
            result = provision_demo(db)
        assert result.users_created == 0
        assert result.problems_created == 6
        after = {table: rows for table, rows in snapshot(data.factory).items() if table in history_tables}
        assert after == before
    finally:
        engine.dispose()


def test_demo_refuses_ambiguous_learner_without_any_partial_catalogue(demo_db) -> None:
    with demo_db() as db:
        db.add_all([User(id=1), User(id=2)])
        db.commit()
    before = snapshot(demo_db)
    with demo_db() as db, pytest.raises(DemoProvisioningError):
        provision_demo(db)
    assert snapshot(demo_db) == before


@pytest.mark.parametrize("conflict", ["problem", "mapping", "test_case", "duplicate"])
def test_demo_refuses_conflicts_without_rewriting_or_leaving_partial_work(demo_db, conflict) -> None:
    with demo_db() as db:
        provision_demo(db)
        problem = db.scalar(select(Problem).where(Problem.title == DEMO_PROBLEMS[-1].title,
                                                  Problem.source == DEMO_SOURCE))
        if conflict == "problem":
            problem.description = "Legitimate changed description"
        elif conflict == "mapping":
            db.scalar(select(ProblemSkill).where(ProblemSkill.problem_id == problem.id)).weight = 0.5
        elif conflict == "test_case":
            db.scalar(select(ProblemTestCase).where(ProblemTestCase.problem_id == problem.id)).expected_output = "changed"
        else:
            db.add(Problem(title=problem.title, source=DEMO_SOURCE, description=problem.description,
                           difficulty=problem.difficulty, topic=problem.topic))
        # Earlier missing demo rows would be recreated before the last conflict.
        first = db.scalar(select(Problem).where(Problem.title == DEMO_PROBLEMS[0].title,
                                                Problem.source == DEMO_SOURCE))
        db.delete(first)
        db.commit()
    before = snapshot(demo_db)
    with demo_db() as db, pytest.raises(DemoProvisioningError):
        provision_demo(db)
    assert snapshot(demo_db) == before
    assert_no_history(demo_db)


def test_demo_cli_refuses_production_configuration_before_database_access(monkeypatch, capsys) -> None:
    from app import config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(app_env="production"))
    assert main() == 1
    output = capsys.readouterr().out
    assert "refused" in output
    assert "APP_ENV" in output


@pytest.mark.parametrize("host", ["db.example.invalid", "10.4.5.6", "production-db"])
def test_demo_cli_refuses_remote_database_even_in_development(monkeypatch, capsys, host) -> None:
    from app import config
    from app.db import session

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        app_env="development", database_url=f"postgresql+psycopg://fixture_user:PRIVATE_DUMMY_PASSWORD@{host}:5432/dev",
    ))

    def forbidden_database_access():
        raise AssertionError("Remote demo configuration must be rejected before opening a session")

    monkeypatch.setattr(session, "SessionLocal", forbidden_database_access)
    assert main() == 1
    output = capsys.readouterr().out
    assert "refused" in output
    assert host not in output
    assert "PRIVATE_DUMMY_PASSWORD" not in output


@pytest.mark.parametrize("database_url", [
    "postgresql+psycopg://fixture_user@localhost/dev",
    "postgresql+psycopg://fixture_user@127.0.0.1/dev",
    "postgresql+psycopg://fixture_user@[::1]/dev",
])
def test_demo_database_guard_accepts_explicit_loopback_postgresql(database_url) -> None:
    validate_local_demo_database("development", database_url)


@pytest.mark.parametrize("database_url", [
    "postgresql+psycopg://fixture_user@localhost/dev?host=remote.invalid",
    "postgresql+psycopg://fixture_user@localhost/dev?hostaddr=10.4.5.6",
    "postgresql+psycopg://fixture_user@localhost/dev?service=production",
    "postgresql+psycopg://fixture_user@localhost/dev?servicefile=private.conf",
    "postgresql+psycopg:///dev",
    "sqlite://",
    "PRIVATE_INVALID_URL",
])
def test_demo_database_guard_refuses_overrides_implicit_hosts_and_invalid_urls(database_url) -> None:
    with pytest.raises(DemoProvisioningError) as failure:
        validate_local_demo_database("development", database_url)
    assert database_url not in str(failure.value)


def test_demo_database_guard_allows_sqlite_only_in_test_environment() -> None:
    validate_local_demo_database("test", "sqlite://")
