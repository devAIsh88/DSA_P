from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.problem import Problem
from app.models.submission import Submission
from app.models.test_case import TestCase
from app.models.test_result import TestResult
from app.schemas.execution import ExecutionRequest, TestCaseExecution
from app.schemas.submission import SubmissionCreate, SubmissionResultResponse, TestResultResponse
from app.services.evaluation_service import EvaluationService
from app.services.execution_service import ExecutionProvider
from app.services.problem_service import ProblemNotFoundError


async def create_submission(
    db: Session, payload: SubmissionCreate, provider: ExecutionProvider
) -> SubmissionResultResponse:
    """Execute all cases in one provider call, evaluate, persist, and redact for the API."""

    problem = db.scalar(select(Problem).where(Problem.id == payload.problem_id))
    if problem is None:
        raise ProblemNotFoundError
    test_cases = list(db.scalars(select(TestCase).where(TestCase.problem_id == problem.id).order_by(TestCase.id)))
    executions = await provider.execute_batch(
        ExecutionRequest(
            code=payload.code,
            language=payload.language,
            test_cases=[TestCaseExecution(id=item.id, input_data=item.input) for item in test_cases],
        )
    )
    evaluation = EvaluationService().evaluate(test_cases, executions)
    submission = Submission(
        problem_id=problem.id, language=payload.language, source_code=payload.code,
        overall_status=evaluation.overall_status.value, tests_passed=evaluation.tests_passed,
        tests_total=evaluation.tests_total, edge_cases_failed=evaluation.edge_cases_failed,
        execution_time_ms=evaluation.execution_time_ms, memory_used_kb=evaluation.memory_used_kb,
    )
    db.add(submission)
    db.flush()
    response_results = []
    for result in evaluation.results:
        db.add(TestResult(
            submission_id=submission.id, test_case_id=result.test_case.id, is_hidden=result.test_case.is_hidden,
            status=result.status.value, stdout=result.execution.stdout, stderr=result.execution.stderr,
            compile_output=result.execution.compile_output, time_ms=result.execution.time_ms, memory_kb=result.execution.memory_kb,
        ))
        response_results.append(TestResultResponse(
            test_case_id=result.test_case.id, is_hidden=result.test_case.is_hidden, status=result.status,
            stdout=result.execution.stdout,
        ))
    db.commit()
    return SubmissionResultResponse(
        submission_id=submission.id, overall_status=evaluation.overall_status, tests_passed=evaluation.tests_passed,
        tests_total=evaluation.tests_total, edge_cases_failed=evaluation.edge_cases_failed,
        execution_time_ms=evaluation.execution_time_ms, memory_used_kb=evaluation.memory_used_kb,
        test_results=response_results,
    )
