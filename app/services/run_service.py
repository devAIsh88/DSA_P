"""Isolated sample practice without authoritative learning evidence."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.problem import Problem
from app.models.test_case import TestCase
from app.schemas.execution import ExecutionRequest, ExecutionResult, ExecutionStatus, TestCaseExecution
from app.schemas.run import RunCreate, RunResponse
from app.schemas.submission import TestResultResponse
from app.services.evaluation_service import EvaluationService
from app.services.execution_service import ExecutionProvider
from app.services.problem_service import ProblemNotFoundError


class NoPublicSamplesError(Exception):
    """The problem has no explicitly public sample execution cases."""


async def run_code(db: Session, payload: RunCreate, provider: ExecutionProvider) -> RunResponse:
    """Run public samples once; never persist submissions, events or state."""

    problem = db.get(Problem, payload.problem_id)
    if problem is None:
        raise ProblemNotFoundError
    test_cases = list(db.scalars(
        select(TestCase).where(
            TestCase.problem_id == problem.id,
            TestCase.is_sample.is_(True),
            TestCase.is_hidden.is_(False),
        ).order_by(TestCase.id)
    ))
    if not test_cases:
        raise NoPublicSamplesError
    request = ExecutionRequest(
        code=payload.code, language=payload.language,
        test_cases=[TestCaseExecution(id=item.id, input_data=item.input) for item in test_cases],
    )
    try:
        executions = await provider.execute_batch(request)
    except Exception:
        # Adapter failure must not become learner incorrectness or expose diagnostics.
        executions = [ExecutionResult(test_case_id=item.id, status=ExecutionStatus.SYSTEM_ERROR)
                      for item in test_cases]
    evaluation = EvaluationService().evaluate(test_cases, executions)
    return RunResponse(
        problem_id=problem.id, overall_status=evaluation.overall_status,
        tests_passed=evaluation.tests_passed, tests_total=evaluation.tests_total,
        edge_cases_failed=0, execution_time_ms=evaluation.execution_time_ms,
        memory_used_kb=evaluation.memory_used_kb,
        test_results=[TestResultResponse(
            test_case_id=item.test_case.id, is_hidden=False,
            status=item.status, stdout=item.execution.stdout,
        ) for item in evaluation.results],
    )
