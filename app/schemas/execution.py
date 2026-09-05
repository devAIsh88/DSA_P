from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ExecutionStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    ACCEPTED = "ACCEPTED"
    WRONG_ANSWER = "WRONG_ANSWER"
    COMPILATION_ERROR = "COMPILATION_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    TIME_LIMIT_EXCEEDED = "TIME_LIMIT_EXCEEDED"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class TestCaseExecution(BaseModel):
    id: int
    input_data: str
    time_limit_secs: float = Field(default=2.0, gt=0, le=2.0)
    memory_limit_kb: int = Field(default=256000, gt=0, le=256000)


class ExecutionRequest(BaseModel):
    code: str = Field(min_length=1)
    language: str = "python3"
    language_id: int = 71
    test_cases: list[TestCaseExecution] = Field(min_length=1)


class ExecutionResult(BaseModel):
    test_case_id: int
    status: ExecutionStatus
    stdout: str = ""
    stderr: str = ""
    compile_output: str = ""
    time_ms: float | None = None
    memory_kb: float | None = None
