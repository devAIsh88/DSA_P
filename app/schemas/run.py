"""Non-authoritative execution of a problem's public samples."""

from pydantic import BaseModel, Field, model_validator

from app.schemas.execution import ExecutionStatus
from app.schemas.submission import TestResultResponse


class RunCreate(BaseModel):
    problem_id: int = Field(gt=0)
    code: str = Field(min_length=1)
    language: str = "python3"

    @model_validator(mode="after")
    def only_python3(self) -> "RunCreate":
        if self.language.lower() not in {"python3", "python"}:
            raise ValueError("Only Python 3 runs are supported")
        self.language = "python3"
        return self


class RunResponse(BaseModel):
    problem_id: int
    overall_status: ExecutionStatus
    tests_passed: int
    tests_total: int
    edge_cases_failed: int
    execution_time_ms: float | None
    memory_used_kb: float | None
    test_results: list[TestResultResponse]
