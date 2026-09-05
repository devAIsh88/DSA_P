from __future__ import annotations

from dataclasses import dataclass

from app.models.test_case import TestCase
from app.schemas.execution import ExecutionResult, ExecutionStatus


@dataclass(frozen=True)
class EvaluatedTestResult:
    test_case: TestCase
    execution: ExecutionResult
    status: ExecutionStatus


@dataclass(frozen=True)
class EvaluationSummary:
    overall_status: ExecutionStatus
    tests_passed: int
    tests_total: int
    edge_cases_failed: int
    execution_time_ms: float | None
    memory_used_kb: float | None
    results: list[EvaluatedTestResult]


def normalize_output(value: str) -> str:
    """Apply the Phase 3 exact-output normalization policy."""

    return value.replace("\r\n", "\n").strip()


class EvaluationService:
    """Provider-independent deterministic comparison and aggregation."""

    _severity = {
        ExecutionStatus.ACCEPTED: 0,
        ExecutionStatus.WRONG_ANSWER: 1,
        ExecutionStatus.COMPILATION_ERROR: 2,
        ExecutionStatus.RUNTIME_ERROR: 3,
        ExecutionStatus.MEMORY_LIMIT_EXCEEDED: 4,
        ExecutionStatus.TIME_LIMIT_EXCEEDED: 5,
        ExecutionStatus.SYSTEM_ERROR: 6,
        ExecutionStatus.RUNNING: 6,
        ExecutionStatus.QUEUED: 6,
    }

    def evaluate(self, test_cases: list[TestCase], executions: list[ExecutionResult]) -> EvaluationSummary:
        by_id = {item.test_case_id: item for item in executions}
        results: list[EvaluatedTestResult] = []
        for test_case in test_cases:
            execution = by_id.get(test_case.id) or ExecutionResult(
                test_case_id=test_case.id, status=ExecutionStatus.SYSTEM_ERROR
            )
            status = execution.status
            if status is ExecutionStatus.ACCEPTED and normalize_output(execution.stdout) != normalize_output(test_case.expected_output):
                status = ExecutionStatus.WRONG_ANSWER
            results.append(EvaluatedTestResult(test_case=test_case, execution=execution, status=status))
        statuses = [result.status for result in results]
        overall = max(statuses, key=lambda item: self._severity[item]) if statuses else ExecutionStatus.SYSTEM_ERROR
        return EvaluationSummary(
            overall_status=overall,
            tests_passed=sum(status is ExecutionStatus.ACCEPTED for status in statuses),
            tests_total=len(results),
            edge_cases_failed=sum(result.test_case.is_hidden and result.status is not ExecutionStatus.ACCEPTED for result in results),
            execution_time_ms=max((result.execution.time_ms or 0 for result in results), default=0) or None,
            memory_used_kb=max((result.execution.memory_kb or 0 for result in results), default=0) or None,
            results=results,
        )
