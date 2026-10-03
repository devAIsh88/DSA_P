from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attempt import Attempt
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.test_case import TestCase
from app.models.test_result import TestResult
from app.schemas.execution import ExecutionRequest, ExecutionStatus, TestCaseExecution
from app.schemas.learning_event import EvidenceSource, LearningEventType
from app.schemas.submission import SubmissionCreate, SubmissionReadResponse, SubmissionResultResponse, TestResultResponse
from app.services.evaluation_service import EvaluationService
from app.services.execution_service import ExecutionProvider
from app.services.attempt_service import ensure_attempt_owner, single_learner_id
from app.services.learning_event_service import append_event, event_by_key, hint_summary, lock_attempt
from app.services.problem_service import ProblemNotFoundError


class SubmissionAttemptNotFoundError(Exception):
    """The requested Attempt does not exist."""


class SubmissionConflictError(Exception):
    """The Attempt or retry key conflicts with this submission."""


class SubmissionNotFoundError(Exception):
    """The requested persisted Submission does not exist."""


def get_submission(db: Session, submission_id: int) -> SubmissionReadResponse:
    """Recover only Attempt-owned source; unlinked Phase 3 rows lack a safe owner."""

    single_learner_id(db)
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise SubmissionNotFoundError
    if submission.attempt_id is None:
        raise SubmissionConflictError("Unlinked submission ownership cannot be established")
    attempt = db.get(Attempt, submission.attempt_id)
    if attempt is None:
        raise SubmissionConflictError("Submission ownership cannot be established")
    ensure_attempt_owner(db, attempt)
    return SubmissionReadResponse(
        **_persisted_response(db, submission).model_dump(),
        problem_id=submission.problem_id, attempt_id=submission.attempt_id,
        language=submission.language, code=submission.source_code, created_at=submission.created_at,
    )


def _validate_attempt(db: Session, attempt: Attempt | None, problem_id: int) -> Attempt:
    if attempt is None:
        raise SubmissionAttemptNotFoundError
    ensure_attempt_owner(db, attempt)
    if attempt.problem_id != problem_id:
        raise SubmissionConflictError("Attempt belongs to a different problem")
    if attempt.status != "ACTIVE":
        raise SubmissionConflictError("Submissions require an ACTIVE Attempt")
    return attempt


def _persisted_response(db: Session, submission: Submission) -> SubmissionResultResponse:
    """Rebuild the Phase 3 response for an idempotent retry."""

    results = list(db.scalars(
        select(TestResult).where(TestResult.submission_id == submission.id).order_by(TestResult.id)
    ))
    return SubmissionResultResponse(
        submission_id=submission.id,
        overall_status=ExecutionStatus(submission.overall_status),
        tests_passed=submission.tests_passed,
        tests_total=submission.tests_total,
        edge_cases_failed=submission.edge_cases_failed,
        execution_time_ms=submission.execution_time_ms,
        memory_used_kb=submission.memory_used_kb,
        test_results=[TestResultResponse(
            test_case_id=item.test_case_id, is_hidden=item.is_hidden,
            status=ExecutionStatus(item.status), stdout=item.stdout,
        ) for item in results],
    )


def _retry_response(db: Session, payload: SubmissionCreate) -> SubmissionResultResponse | None:
    if payload.attempt_id is None or payload.idempotency_key is None:
        return None
    event = event_by_key(db, payload.attempt_id, payload.idempotency_key)
    if event is None:
        return None
    if event.event_type != LearningEventType.SUBMISSION_EVALUATED.value or event.submission_id is None:
        raise SubmissionConflictError("Idempotency key was used for another action")
    submission = db.get(Submission, event.submission_id)
    if (submission is None or submission.attempt_id != payload.attempt_id
            or submission.problem_id != payload.problem_id or submission.source_code != payload.code
            or submission.language != payload.language):
        raise SubmissionConflictError("Idempotency key was used for another submission")
    return _persisted_response(db, submission)


async def create_submission(
    db: Session, payload: SubmissionCreate, provider: ExecutionProvider
) -> SubmissionResultResponse:
    """Execute all cases in one provider call, evaluate, persist, and redact for the API."""

    problem = db.scalar(select(Problem).where(Problem.id == payload.problem_id))
    if problem is None:
        raise ProblemNotFoundError
    if payload.attempt_id is not None:
        attempt = db.get(Attempt, payload.attempt_id)
        if attempt is None:
            raise SubmissionAttemptNotFoundError
        ensure_attempt_owner(db, attempt)
        retried = _retry_response(db, payload)
        if retried is not None:
            return retried
        _validate_attempt(db, attempt, problem.id)
    test_cases = list(db.scalars(select(TestCase).where(TestCase.problem_id == problem.id).order_by(TestCase.id)))
    executions = await provider.execute_batch(
        ExecutionRequest(
            code=payload.code,
            language=payload.language,
            test_cases=[TestCaseExecution(id=item.id, input_data=item.input) for item in test_cases],
        )
    )
    evaluation = EvaluationService().evaluate(test_cases, executions)
    if payload.attempt_id is not None:
        _validate_attempt(db, lock_attempt(db, payload.attempt_id), problem.id)
        retried = _retry_response(db, payload)
        if retried is not None:
            db.rollback()
            return retried
    submission = Submission(
        problem_id=problem.id, attempt_id=payload.attempt_id,
        language=payload.language, source_code=payload.code,
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
    if payload.attempt_id is not None:
        hint_count, max_hint_level = hint_summary(db, payload.attempt_id)
        append_event(
            db, payload.attempt_id, LearningEventType.SUBMISSION_EVALUATED,
            {"schema_version": 1, "submission_id": submission.id,
             "overall_status": evaluation.overall_status.value,
             "tests_passed": evaluation.tests_passed, "tests_total": evaluation.tests_total,
             "edge_cases_failed": evaluation.edge_cases_failed,
             "execution_time_ms": evaluation.execution_time_ms,
             "hint_count_at_submission": hint_count,
             "max_hint_level_at_submission": max_hint_level},
            {"source": EvidenceSource.EXECUTION_EVALUATION_ENGINE.value,
             "submission_id": submission.id,
             "evaluation": {"source": EvidenceSource.DETERMINISTIC_RULE.value,
                            "rule_id": "phase3_test_comparison", "rule_version": "phase3-v1"}},
            submission_id=submission.id,
            idempotency_key=payload.idempotency_key,
        )
    db.commit()
    return SubmissionResultResponse(
        submission_id=submission.id, overall_status=evaluation.overall_status, tests_passed=evaluation.tests_passed,
        tests_total=evaluation.tests_total, edge_cases_failed=evaluation.edge_cases_failed,
        execution_time_ms=evaluation.execution_time_ms, memory_used_kb=evaluation.memory_used_kb,
        test_results=response_results,
    )
