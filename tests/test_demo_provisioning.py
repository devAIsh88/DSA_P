"""Explicit demo setup is idempotent, conflict-safe and never fabricates history."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from adaptive_fixtures import NOW, create_adaptive_database
from app.db.base import Base
from app.models import Attempt, LearningEvent, Problem, ProblemSkill, Recommendation, Skill, SkillState, Submission, User
from app.models.test_case import TestCase as ProblemTestCase
from scripts.demo_catalogue import DEMO_PROBLEMS, DEMO_SOURCE
from scripts.provision_demo import (
    DemoProvisioningError, main, provision_demo, synchronize_demo_sequences, validate_local_demo_database,
)


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


class SequenceResult:
    """Only the SQLAlchemy result methods used by the synchronization helper."""

    def __init__(self, value=None):
        self.value = value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value

    def one(self):
        return self.value


class PostgreSQLSequenceSession:
    """Record compiled statements; neither connect nor execute any SQL."""

    def __init__(self, *, maximum_id, last_value, is_called, schema="public", sequence="users_id_seq"):
        self.bind = SimpleNamespace(dialect=postgresql_dialect())
        self.state = (maximum_id, last_value, is_called)
        self.schema = schema
        self.sequence = sequence
        self.current_table = None
        self.calls = []

    def get_bind(self):
        return self.bind

    def execute(self, statement, parameters=None):
        sql = str(statement.compile(dialect=self.bind.dialect))
        self.calls.append((sql, parameters))
        if "pg_get_serial_sequence" in sql:
            self.current_table = parameters["table_name"]
            if self.current_table != "users":
                return SequenceResult(None)
            return SequenceResult({"schema_name": self.schema, "sequence_name": self.sequence, "sequence_oid": 100})
        if "last_value" in sql and "is_called" in sql:
            return SequenceResult(self.state[1:])
        return SequenceResult()

    def scalar(self, statement):
        sql = str(statement.compile(dialect=self.bind.dialect))
        self.calls.append((sql, None))
        assert self.current_table == "users"
        assert "max(users.id)" in sql
        return self.state[0]


@pytest.mark.parametrize("maximum,last,called,should_advance", [
    (7, 1, True, True),
    (7, 7, False, True),
    (7, 12, True, False),
    (7, 7, True, False),
    (None, 1, False, False),
])
def test_demo_sequence_alignment_advances_only_when_collision_is_possible(maximum, last, called, should_advance) -> None:
    session = PostgreSQLSequenceSession(maximum_id=maximum, last_value=last, is_called=called)
    synchronize_demo_sequences(session)
    advances = [(sql, params) for sql, params in session.calls if "setval" in sql]
    if should_advance:
        assert len(advances) == 1
        assert advances[0][1] == {"sequence_oid": 100, "maximum_id": maximum}
        assert "true" in advances[0][0]
    else:
        assert advances == []


def test_demo_sequence_alignment_locks_only_catalogue_tables_and_binds_lookup_values() -> None:
    session = PostgreSQLSequenceSession(maximum_id=7, last_value=1, is_called=True)
    synchronize_demo_sequences(session)
    lock = session.calls[0]
    assert lock == ("LOCK TABLE users, skills, problems, test_cases IN SHARE ROW EXCLUSIVE MODE", None)
    lookups = [(sql, params) for sql, params in session.calls if "pg_get_serial_sequence" in sql]
    assert [params for _sql, params in lookups] == [
        {"table_name": table, "column_name": "id"} for table in ("users", "skills", "problems", "test_cases")
    ]
    assert all("%(table_name)s" in sql and "%(column_name)s" in sql for sql, _params in lookups)
    assert not any(history in lock[0] for history in ("attempts", "submissions", "learning_events", "skill_states", "recommendations"))


def test_demo_sequence_identifiers_are_quoted_and_setval_uses_bound_oid() -> None:
    schema = 'odd"schema'
    sequence = 'sequence"; DROP TABLE users; --'
    session = PostgreSQLSequenceSession(maximum_id=9, last_value=1, is_called=False,
                                        schema=schema, sequence=sequence)
    synchronize_demo_sequences(session)
    reads = [sql for sql, _params in session.calls if "last_value" in sql]
    assert len(reads) == 1
    quoted = session.bind.dialect.identifier_preparer.quote_identifier
    assert f"{quoted(schema)}.{quoted(sequence)}" in reads[0]
    advances = [(sql, params) for sql, params in session.calls if "setval" in sql]
    assert advances[0][1] == {"sequence_oid": 100, "maximum_id": 9}
    assert schema not in advances[0][0]
    assert sequence not in advances[0][0]


def test_demo_sequence_alignment_is_a_sqlite_noop() -> None:
    class SQLiteSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def execute(self, *_args, **_kwargs):
            raise AssertionError("SQLite must not execute PostgreSQL synchronization SQL")

        def scalar(self, *_args, **_kwargs):
            raise AssertionError("SQLite must not query sequence state")

    synchronize_demo_sequences(SQLiteSession())
