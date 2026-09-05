from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.schemas.execution import ExecutionRequest, ExecutionResult, ExecutionStatus

MAX_OUTPUT_BYTES = 10 * 1024
JUDGE0_PYTHON3_LANGUAGE_ID = 71


def _truncate(value: object) -> str:
    """Bound untrusted provider output before it enters application memory."""

    if not isinstance(value, str):
        return ""
    return value[:MAX_OUTPUT_BYTES]


class ExecutionProvider(ABC):
    """Boundary for isolated code execution providers."""

    @abstractmethod
    async def execute_batch(self, request: ExecutionRequest) -> list[ExecutionResult]:
        """Execute every case once and return raw execution evidence."""


class Judge0ExecutionService(ExecutionProvider):
    """Judge0 adapter; it executes code but never determines correctness."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def execute_batch(self, request: ExecutionRequest) -> list[ExecutionResult]:
        if not self.base_url:
            return self._system_errors(request)
        payload = {
            "submissions": [
                {
                    "source_code": request.code,
                    "language_id": JUDGE0_PYTHON3_LANGUAGE_ID,
                    "stdin": case.input_data,
                    "cpu_time_limit": case.time_limit_secs,
                    "wall_time_limit": 5.0,
                    "memory_limit": case.memory_limit_kb,
                    "enable_network": False,
                }
                for case in request.test_cases
            ]
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.post(
                    f"{self.base_url}/submissions/batch",
                    params={"base64_encoded": "false", "wait": "true"},
                    json=payload,
                )
            if response.status_code == 502 or response.is_error:
                return self._system_errors(request)
            body = response.json()
            if not isinstance(body, list) or len(body) != len(request.test_cases):
                return self._system_errors(request)
            return [self._to_result(case.id, raw) for case, raw in zip(request.test_cases, body, strict=True)]
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return self._system_errors(request)

    @staticmethod
    def _system_errors(request: ExecutionRequest) -> list[ExecutionResult]:
        return [ExecutionResult(test_case_id=case.id, status=ExecutionStatus.SYSTEM_ERROR) for case in request.test_cases]

    @staticmethod
    def _to_result(test_case_id: int, raw: object) -> ExecutionResult:
        if not isinstance(raw, dict) or not isinstance(raw.get("status"), dict):
            return ExecutionResult(test_case_id=test_case_id, status=ExecutionStatus.SYSTEM_ERROR)
        status_id = raw["status"].get("id")
        status = {
            3: ExecutionStatus.ACCEPTED,
            5: ExecutionStatus.TIME_LIMIT_EXCEEDED,
            6: ExecutionStatus.COMPILATION_ERROR,
            7: ExecutionStatus.RUNTIME_ERROR,
            8: ExecutionStatus.RUNTIME_ERROR,
            9: ExecutionStatus.RUNTIME_ERROR,
            10: ExecutionStatus.RUNTIME_ERROR,
            11: ExecutionStatus.RUNTIME_ERROR,
            12: ExecutionStatus.RUNTIME_ERROR,
            13: ExecutionStatus.SYSTEM_ERROR,
            14: ExecutionStatus.SYSTEM_ERROR,
        }.get(status_id, ExecutionStatus.SYSTEM_ERROR)
        return ExecutionResult(
            test_case_id=test_case_id,
            status=status,
            stdout=_truncate(raw.get("stdout")),
            stderr=_truncate(raw.get("stderr")),
            compile_output=_truncate(raw.get("compile_output")),
            time_ms=float(raw["time"]) * 1000 if raw.get("time") is not None else None,
            memory_kb=float(raw["memory"]) if raw.get("memory") is not None else None,
        )
