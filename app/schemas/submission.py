from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.execution import ExecutionStatus


class SubmissionCreate(BaseModel):
    problem_id: int = Field(gt=0)
    code: str = Field(min_length=1)
    language: str = "python3"

    @model_validator(mode="after")
    def only_python3(self) -> "SubmissionCreate":
        if self.language.lower() not in {"python3", "python"}:
            raise ValueError("Only Python 3 submissions are supported")
        self.language = "python3"
        return self


class TestResultResponse(BaseModel):
    """Learner response. Hidden execution evidence is always redacted."""

    model_config = ConfigDict(from_attributes=True)

    test_case_id: int
    is_hidden: bool
    status: ExecutionStatus
    stdout: str | None = None

    @model_validator(mode="after")
    def redact_hidden_evidence(self) -> "TestResultResponse":
        if self.is_hidden:
            self.stdout = None
        return self


class SubmissionResultResponse(BaseModel):
    submission_id: int
    overall_status: ExecutionStatus
    tests_passed: int
    tests_total: int
    edge_cases_failed: int
    execution_time_ms: float | None
    memory_used_kb: float | None
    test_results: list[TestResultResponse]
