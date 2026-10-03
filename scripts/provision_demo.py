"""Explicit, idempotent local demo provisioning without learner history."""

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import BigInteger, Boolean, Column, MetaData, Table, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.problem import Problem
from app.models.problem_skill import ProblemSkill
from app.models.skill import Skill
from app.models.test_case import TestCase
from app.models.user import User
from scripts.demo_catalogue import DEMO_PROBLEMS, DEMO_SKILLS, DEMO_SOURCE, DemoProblem


class DemoProvisioningError(Exception):
    """Provisioning cannot safely identify or reuse local demo records."""


@dataclass(frozen=True)
class DemoProvisioningSummary:
    user_id: int
    skill_ids: tuple[int, ...]
    problem_ids: tuple[int, ...]
    users_created: int
    skills_created: int
    problems_created: int
    test_cases_created: int
    mappings_created: int


def synchronize_demo_sequences(db: Session) -> None:
    """Advance local catalogue ID sequences past legacy manually assigned IDs."""

    if db.get_bind().dialect.name != "postgresql":
        return
    models = (User, Skill, Problem, TestCase)
    preparer = db.get_bind().dialect.identifier_preparer
    table_names = ", ".join(preparer.format_table(model.__table__) for model in models)
    # Prevent catalogue/User inserts between MAX(id) and sequence synchronization.
    db.execute(text(f"LOCK TABLE {table_names} IN SHARE ROW EXCLUSIVE MODE"))
    for model in models:
        sequence = db.execute(text(
            "SELECT ns.nspname AS schema_name, seq.relname AS sequence_name, seq.oid AS sequence_oid "
            "FROM pg_class AS seq JOIN pg_namespace AS ns ON ns.oid = seq.relnamespace "
            "WHERE seq.oid = CAST(pg_get_serial_sequence(:table_name, :column_name) AS regclass)"
        ), {"table_name": model.__table__.fullname, "column_name": "id"}).mappings().one_or_none()
        if sequence is None:
            continue
        sequence_table = Table(
            sequence["sequence_name"], MetaData(), Column("last_value", BigInteger),
            Column("is_called", Boolean), schema=sequence["schema_name"],
            quote=True, quote_schema=True,
        )
        last_value, is_called = db.execute(select(
            sequence_table.c.last_value, sequence_table.c.is_called,
        )).one()
        maximum_id = db.scalar(select(func.max(model.id)))
        if maximum_id is not None and (
                maximum_id > last_value or (maximum_id == last_value and not is_called)):
            # PostgreSQL sequence advances survive rollback; harmless gaps are preferable
            # to collisions. Never decrease a sequence or change an existing row.
            db.execute(text("SELECT setval(CAST(:sequence_oid AS regclass), :maximum_id, true)"),
                       {"sequence_oid": sequence["sequence_oid"], "maximum_id": maximum_id})


def _problem_fields(spec: DemoProblem) -> dict[str, str]:
    return {
        "title": spec.title, "description": spec.description, "difficulty": spec.difficulty,
        "source": DEMO_SOURCE, "topic": spec.skill, "constraints": spec.constraints,
        "input_format": spec.input_format, "output_format": spec.output_format,
        "expected_complexity": spec.expected_complexity,
    }


def _validate_existing(db: Session, problem: Problem, spec: DemoProblem, skill_id: int) -> None:
    if any(getattr(problem, field) != value for field, value in _problem_fields(spec).items()):
        raise DemoProvisioningError(f"Existing demo problem conflicts with catalogue: {spec.title}")
    mappings = list(db.scalars(select(ProblemSkill).where(ProblemSkill.problem_id == problem.id)))
    if len(mappings) != 1 or mappings[0].skill_id != skill_id or mappings[0].weight != 1.0:
        raise DemoProvisioningError(f"Existing demo problem has conflicting skill mappings: {spec.title}")
    cases = list(db.scalars(select(TestCase).where(TestCase.problem_id == problem.id)))
    actual = Counter((case.input, case.expected_output, case.is_sample, case.is_hidden, case.weight)
                     for case in cases)
    expected = Counter((case.input, case.expected_output, case.is_sample, not case.is_sample, 1)
                       for case in spec.cases)
    if actual != expected:
        raise DemoProvisioningError(f"Existing demo problem has conflicting test cases: {spec.title}")


def provision_demo(db: Session) -> DemoProvisioningSummary:
    """Provision a small catalogue atomically; refuse conflicts instead of overwriting."""

    try:
        synchronize_demo_sequences(db)
        users = list(db.scalars(select(User).order_by(User.id)))
        if len(users) > 1:
            raise DemoProvisioningError("Demo provisioning requires at most one existing learner")
        users_created = int(not users)
        learner = users[0] if users else User()
        if users_created:
            db.add(learner)
            db.flush()

        skills: dict[str, Skill] = {}
        skills_created = 0
        for name, description in DEMO_SKILLS.items():
            skill = db.scalar(select(Skill).where(Skill.name == name))
            if skill is None:
                skill = Skill(name=name, description=description, difficulty_range="Easy-Hard")
                db.add(skill)
                db.flush()
                skills_created += 1
            skills[name] = skill

        problem_ids: list[int] = []
        problems_created = test_cases_created = mappings_created = 0
        for spec in DEMO_PROBLEMS:
            existing = list(db.scalars(select(Problem).where(
                Problem.source == DEMO_SOURCE, Problem.title == spec.title,
            )))
            if len(existing) > 1:
                raise DemoProvisioningError(f"Duplicate demo problem identity: {spec.title}")
            if existing:
                problem = existing[0]
                _validate_existing(db, problem, spec, skills[spec.skill].id)
            else:
                problem = Problem(**_problem_fields(spec))
                db.add(problem)
                db.flush()
                db.add(ProblemSkill(problem_id=problem.id, skill_id=skills[spec.skill].id, weight=1.0))
                db.add_all(TestCase(
                    problem_id=problem.id, input=case.input, expected_output=case.expected_output,
                    is_sample=case.is_sample, is_hidden=not case.is_sample, weight=1,
                ) for case in spec.cases)
                problems_created += 1
                test_cases_created += len(spec.cases)
                mappings_created += 1
            problem_ids.append(problem.id)
        summary = DemoProvisioningSummary(
            user_id=learner.id, skill_ids=tuple(skill.id for skill in skills.values()),
            problem_ids=tuple(problem_ids), users_created=users_created,
            skills_created=skills_created, problems_created=problems_created,
            test_cases_created=test_cases_created, mappings_created=mappings_created,
        )
        db.commit()
        return summary
    except Exception:
        db.rollback()
        raise


def main() -> int:
    """Run only against an explicitly configured development/test/demo environment."""

    from app.config import get_settings

    settings = get_settings()
    if settings.app_env.lower() not in {"development", "test", "demo"}:
        print("Demo provisioning refused: APP_ENV must be development, test or demo.")
        return 1
    try:
        validate_local_demo_database(settings.app_env, settings.database_url)
    except DemoProvisioningError as error:
        print(f"Demo provisioning refused: {error}")
        return 1
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        try:
            summary = provision_demo(db)
        except DemoProvisioningError as error:
            print(f"Demo provisioning refused: {error}")
            return 1
        except SQLAlchemyError:
            print("Demo provisioning failed safely. Check the local database and migration head; no private connection details are displayed.")
            return 1
    print(f"Demo catalogue ready. Set UI_LEARNER_ID={summary.user_id} in the local environment.")
    print(f"Created users={summary.users_created}, skills={summary.skills_created}, "
          f"problems={summary.problems_created}, tests={summary.test_cases_created}, "
          f"mappings={summary.mappings_created}.")
    print("No learner activity, events, submissions, mastery or recommendations were created.")
    return 0


def validate_local_demo_database(app_env: str, database_url: str) -> None:
    """Refuse remote databases before importing or connecting a configured session."""

    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError):
        raise DemoProvisioningError("DATABASE_URL must identify a supported local database") from None
    backend = url.get_backend_name()
    if backend == "sqlite" and app_env.lower() == "test" and url.host is None:
        return
    if backend != "postgresql" or (url.host or "").lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise DemoProvisioningError("Only loopback PostgreSQL is allowed; SQLite is restricted to APP_ENV=test")
    # libpq query parameters can override the URL host or select a remote service.
    if {key.lower() for key in url.query} & {"host", "hostaddr", "service", "servicefile"}:
        raise DemoProvisioningError("DATABASE_URL cannot override the loopback host through connection parameters")


if __name__ == "__main__":
    raise SystemExit(main())
