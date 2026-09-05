from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.problem import Problem
from app.models.test_case import TestCase


class ProblemNotFoundError(Exception):
    """Raised when a requested problem does not exist."""


def list_problems(db: Session) -> list[Problem]:
    """Return the learner-visible problem catalogue in stable order."""

    return list(db.scalars(select(Problem).order_by(Problem.id)))


def get_problem(db: Session, problem_id: int) -> tuple[Problem, list[TestCase]]:
    """Return a problem and only its learner-visible sample test cases."""

    problem = db.scalar(select(Problem).where(Problem.id == problem_id))
    if problem is None:
        raise ProblemNotFoundError

    sample_cases = list(
        db.scalars(
            select(TestCase)
            .where(TestCase.problem_id == problem_id, TestCase.is_sample.is_(True), TestCase.is_hidden.is_(False))
            .order_by(TestCase.id)
        )
    )
    return problem, sample_cases
