"""Disposable adaptive-engine data built through existing evidence services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.problem import Problem
from app.models.problem_skill import ProblemSkill
from app.models.recommendation import Recommendation  # Register the new table for isolated metadata.
from app.models.skill import Skill
from app.models.test_case import TestCase as ProblemTestCase
from app.models.user import User
from app.schemas.attempt import AttemptComplete, AttemptStart, ReasoningCreate
from app.schemas.execution import ExecutionRequest, ExecutionResult, ExecutionStatus
from app.schemas.learning_event import LearningEventType
from app.schemas.submission import SubmissionCreate
from app.services import attempt_service, learning_event_service, recommendation_service
from app.services.execution_service import ExecutionProvider
from app.services.submission_service import create_submission


NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)
PRIVATE_MARKERS = ("PRIVATE LEARNER CODE", "PRIVATE LEARNER REASONING", "PRIVATE HIDDEN INPUT",
                   "PRIVATE HIDDEN OUTPUT", "PRIVATE STDERR", "PRIVATE COMPILE")


class FrozenClock(datetime):
    value = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.value if tz is not None else cls.value.replace(tzinfo=None)


class FixtureExecutionProvider(ExecutionProvider):
    """Supply controlled execution output; learner code is never executed."""

    def __init__(self, accepted: bool = True, status: ExecutionStatus = ExecutionStatus.ACCEPTED) -> None:
        self.accepted = accepted
        self.status = status

    async def execute_batch(self, request: ExecutionRequest) -> list[ExecutionResult]:
        return [ExecutionResult(
            test_case_id=case.id, status=self.status,
            stdout=("PRIVATE HIDDEN OUTPUT" if case.id % 2 == 0 else "1") if self.accepted else "wrong",
            stderr="PRIVATE STDERR", compile_output="PRIVATE COMPILE",
        ) for case in request.test_cases]


@dataclass
class AdaptiveDatabase:
    factory: sessionmaker[Session]

    def start(self, problem_id: int = 1, key: str | None = None) -> int:
        with self.factory() as db:
            return attempt_service.start_attempt(
                db, AttemptStart(user_id=1, problem_id=problem_id, idempotency_key=key),
            ).id

    def reasoning(self, attempt_id: int) -> None:
        with self.factory() as db:
            attempt_service.record_reasoning(db, attempt_id, ReasoningCreate(reasoning_text="PRIVATE LEARNER REASONING"))

    def submit(self, attempt_id: int, problem_id: int = 1, *, accepted: bool = True,
               status: ExecutionStatus = ExecutionStatus.ACCEPTED) -> int:
        with self.factory() as db:
            result = asyncio.run(create_submission(
                db, SubmissionCreate(problem_id=problem_id, attempt_id=attempt_id, code="PRIVATE LEARNER CODE"),
                FixtureExecutionProvider(accepted, status),
            ))
            return result.submission_id

    def hint(self, attempt_id: int, *, delivered: bool = False, level: int = 4) -> None:
        with self.factory() as db:
            event_type = LearningEventType.HINT_DELIVERED if delivered else LearningEventType.HINT_REQUESTED
            key = "hint_level_delivered" if delivered else "hint_level_requested"
            source = "deterministic_rule" if delivered else "learner"
            learning_event_service.append_event(db, attempt_id, event_type,
                                                {"schema_version": 1, key: level}, {"source": source})
            db.commit()

    def complete(self, attempt_id: int, outcome: str = "SOLVED") -> None:
        with self.factory() as db:
            attempt_service.complete_attempt(db, attempt_id, AttemptComplete(outcome=outcome))

    def solve(self, problem_id: int = 1, *, hint_level: int = 0, reasoning: bool = False) -> int:
        attempt_id = self.start(problem_id)
        if reasoning:
            self.reasoning(attempt_id)
        if hint_level:
            self.hint(attempt_id, level=hint_level)
            self.hint(attempt_id, delivered=True, level=hint_level)
        self.submit(attempt_id, problem_id)
        self.complete(attempt_id)
        return attempt_id

    def give_up(self, problem_id: int = 1, *, evaluated: bool = True,
                status: ExecutionStatus = ExecutionStatus.ACCEPTED) -> int:
        attempt_id = self.start(problem_id)
        if evaluated:
            self.submit(attempt_id, problem_id, accepted=False, status=status)
        self.complete(attempt_id, "GAVE_UP")
        return attempt_id

    def abandon(self, problem_id: int = 1) -> int:
        attempt_id = self.start(problem_id)
        with self.factory() as db:
            attempt_service.abandon_attempt(db, attempt_id)
        return attempt_id


def create_adaptive_database(monkeypatch) -> tuple[AdaptiveDatabase, object]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(User(id=1))
        db.add_all([Skill(id=1, name="Arrays"), Skill(id=2, name="Hashing")])
        db.add_all([
            Problem(id=1, title="Easy A1", description="public", difficulty="Easy", topic="Arrays"),
            Problem(id=2, title="Easy A2", description="public", difficulty="Easy", topic="Arrays"),
            Problem(id=3, title="Medium A", description="public", difficulty="Medium", topic="Arrays"),
            Problem(id=4, title="Easy B", description="public", difficulty="Easy", topic="Hashing"),
            Problem(id=5, title="Hard A", description="public", difficulty="Hard", topic="Arrays"),
        ])
        db.flush()
        db.add_all([ProblemSkill(problem_id=problem, skill_id=1 if problem != 4 else 2, weight=1.0)
                    for problem in range(1, 6)])
        db.add_all([ProblemTestCase(
            id=problem * 2 - 1, problem_id=problem, input="public", expected_output="1",
            is_sample=True, is_hidden=False, weight=1,
        ) for problem in range(1, 6)])
        db.add_all([ProblemTestCase(
            id=problem * 2, problem_id=problem, input="PRIVATE HIDDEN INPUT", expected_output="PRIVATE HIDDEN OUTPUT",
            is_sample=False, is_hidden=True, weight=1,
        ) for problem in range(1, 6)])
        db.commit()
    monkeypatch.setattr(attempt_service, "datetime", FrozenClock)
    monkeypatch.setattr(learning_event_service, "datetime", FrozenClock)
    # Recommendation creation/consumption must share the Attempt fixture clock;
    # otherwise lifecycle constraints start failing as the real date advances.
    monkeypatch.setattr(recommendation_service, "datetime", FrozenClock)
    FrozenClock.value = NOW
    return AdaptiveDatabase(factory), engine
