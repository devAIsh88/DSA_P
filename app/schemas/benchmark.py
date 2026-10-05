"""Strict, provider-neutral benchmark definitions and evaluator observations."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator

from app.schemas.tutor import HintTask, ReasoningTask, TutorContext, TutorRequest, UnderstandingTask


_FORBIDDEN_KEYS = frozenset({
    "apikey", "googleapikey", "password", "credentials", "secret", "secrets", "databaseurl",
    "testcases", "testresults", "testbody", "testbodies", "expectedoutput", "expectedoutputs",
    "stderr", "compileoutput", "providertoken", "accesstoken", "rawresponse", "rawexception",
    "userid", "attemptid", "submissionid", "problemid", "stdin", "inputdata",
})
_SECRET_VALUE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bAIza[0-9A-Za-z_-]{25,}|\bsk-[0-9A-Za-z_-]{20,}|"
    r"(?:postgres(?:ql)?|mysql)://[^\s/:]+:[^\s@]+@|"
    r"(?:api[_ -]?key|password|access[_ -]?token)\s*[=:]\s*[^\s]{4,}",
    re.IGNORECASE,
)


def validate_safe_value(value: object) -> None:
    """Reject protected fixture keys/obvious credentials without echoing their values."""

    if isinstance(value, BaseModel):
        validate_safe_value(value.model_dump(mode="json"))
    elif isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in _FORBIDDEN_KEYS or normalized.startswith("hidden"):
                raise ValueError("Protected content is not permitted in evaluation data")
            validate_safe_value(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            validate_safe_value(item)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise ValueError("Credentials are not permitted in evaluation data")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def safe_data(cls, value: object) -> object:
        validate_safe_value(value)
        return value


class TaskType(str, Enum):
    HINT = "hint"
    DIAGNOSIS = "diagnosis"
    REASONING = "reasoning"
    EXPLANATION = "explanation"
    UNDERSTANDING = "understanding"


class StrictTutorContext(TutorContext):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrictTutorRequest(TutorRequest):
    model_config = ConfigDict(extra="forbid", frozen=True)
    context: StrictTutorContext


class StrictHintTask(HintTask):
    model_config = ConfigDict(extra="forbid", frozen=True)
    context: StrictTutorContext


class StrictReasoningTask(ReasoningTask):
    model_config = ConfigDict(extra="forbid", frozen=True)
    context: StrictTutorContext


class StrictUnderstandingTask(UnderstandingTask):
    model_config = ConfigDict(extra="forbid", frozen=True)
    context: StrictTutorContext


REQUEST_TYPES = {
    TaskType.HINT: StrictHintTask, TaskType.DIAGNOSIS: StrictTutorRequest,
    TaskType.REASONING: StrictReasoningTask, TaskType.EXPLANATION: StrictTutorRequest,
    TaskType.UNDERSTANDING: StrictUnderstandingTask,
}
_LABEL_VALUES = {
    TaskType.HINT: {},
    TaskType.DIAGNOSIS: {"misconception_category": {
        None, "SYNTAX_ERROR", "IMPLEMENTATION_ERROR", "LOGICAL_ERROR", "CONCEPTUAL_ERROR",
        "COMPLEXITY_ERROR", "EDGE_CASE_ERROR", "MISREAD_PROBLEM", "WRONG_PATTERN", "INCOMPLETE_REASONING",
    }},
    TaskType.REASONING: {"reasoning_quality": {"SOUND", "PARTIAL", "FLAWED", "UNDETERMINED"}},
    TaskType.EXPLANATION: {},
    TaskType.UNDERSTANDING: {"answer_quality": {"CORRECT", "PARTIALLY_CORRECT", "INCORRECT", "UNDETERMINED"}},
}
_Identifier = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
_ModelIdentifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")]
_Content = Annotated[str, Field(min_length=1, max_length=2000)]


class BenchmarkCase(_StrictModel):
    case_id: _Identifier
    version: _Identifier
    task_type: TaskType
    difficulty: Literal["Easy", "Medium", "Hard"]
    tags: tuple[_Identifier, ...] = Field(max_length=16)
    request: SerializeAsAny[TutorRequest]
    expected_labels: dict[str, str | None] = Field(default_factory=dict)
    required_content: tuple[_Content, ...] = Field(default=(), max_length=16)
    forbidden_content: tuple[_Content, ...] = Field(default=(), max_length=16)
    review_guidance: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="before")
    @classmethod
    def typed_request(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        task = TaskType(data.get("task_type"))
        request = data.get("request")
        if isinstance(request, BaseModel):
            request = request.model_dump(mode="json")
        data["request"] = REQUEST_TYPES[task].model_validate(request)
        return data

    @model_validator(mode="after")
    def valid_labels(self) -> BenchmarkCase:
        permitted = _LABEL_VALUES[self.task_type]
        for field, value in self.expected_labels.items():
            if field not in permitted or value not in permitted[field]:
                raise ValueError("Gold labels must match the task's existing result contract")
        validate_safe_value(self.request)
        return self


class BenchmarkSuite(_StrictModel):
    suite_id: _Identifier
    version: _Identifier
    rubric_version: _Identifier
    cases: tuple[BenchmarkCase, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def curated_coverage(self) -> BenchmarkSuite:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Benchmark case IDs must be unique")
        if (self.suite_id, self.version) != ("dev-placement-tutor", "v1"):
            return self
        expected = {TaskType.HINT: 6, TaskType.DIAGNOSIS: 9, TaskType.REASONING: 4,
                    TaskType.EXPLANATION: 2, TaskType.UNDERSTANDING: 4}
        if any(sum(case.task_type == task for case in self.cases) != count for task, count in expected.items()):
            raise ValueError("Suite v1 requires its curated five-task coverage")
        levels = {case.request.level for case in self.cases if case.task_type == TaskType.HINT}
        if levels != set(range(1, 7)):
            raise ValueError("Suite v1 requires all six hint levels")
        return self


class RubricDimension(_StrictModel):
    name: _Identifier
    task_types: tuple[TaskType, ...] = Field(min_length=1)
    anchors: dict[str, str]

    @model_validator(mode="after")
    def anchored_scale(self) -> RubricDimension:
        if set(self.anchors) != {str(value) for value in range(5)}:
            raise ValueError("Every rubric dimension needs explicit 0–4 anchors")
        if any(not value or len(value) > 2000 for value in self.anchors.values()):
            raise ValueError("Rubric anchors must be bounded nonempty descriptions")
        return self


_Score = Annotated[int, Field(strict=True, ge=0, le=4)]


class RubricDefinition(_StrictModel):
    rubric_version: _Identifier
    dimensions: tuple[RubricDimension, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_dimensions(self) -> RubricDefinition:
        if len({dimension.name for dimension in self.dimensions}) != len(self.dimensions):
            raise ValueError("Rubric dimensions must be unique")
        return self

    def applicable_dimensions(self, task_type: TaskType) -> tuple[str, ...]:
        return tuple(dimension.name for dimension in self.dimensions if task_type in dimension.task_types)

    def validate_review_scores(self, scores: dict[str, int | None], task_type: TaskType) -> None:
        if set(scores) != {dimension.name for dimension in self.dimensions}:
            raise ValueError("Review must explicitly rate every dimension or mark it not applicable")
        applicable = set(self.applicable_dimensions(task_type))
        if any((score is None) == (name in applicable) for name, score in scores.items()):
            raise ValueError("Applicable dimensions require scores; others require explicit null")


class EvaluationCandidate(_StrictModel):
    candidate_id: _Identifier
    provider: _Identifier
    model_id: _ModelIdentifier
    synthetic: bool


class ExecutionPolicy(_StrictModel):
    version: _Identifier = "evaluation-controls-v1"
    timeout_seconds: float = Field(default=30, gt=0, le=300, allow_inf_nan=False)
    max_retries: int = Field(default=0, strict=True, ge=0, le=3)
    max_input_chars: int = Field(default=30000, strict=True, ge=1, le=100000)
    max_output_tokens: int = Field(default=2048, strict=True, ge=1, le=8192)
    temperature: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)


class PricingSnapshot(_StrictModel):
    version: _Identifier
    effective_at: datetime
    provider: _Identifier
    model_id: _ModelIdentifier
    accounting_basis: _Identifier
    input_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    currency: Literal["USD"] = "USD"
    synthetic: bool = False


class HumanReviewCreate(_StrictModel):
    result_id: int = Field(gt=0, strict=True)
    reviewer_label: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    rubric_version: _Identifier
    scores: dict[str, _Score | None]
    notes: str = Field(default="", max_length=4000)


class InvocationAccounting(_StrictModel):
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    accounting_version: _Identifier
    accounting_basis: _Identifier
    scope: Literal["invocation", "all_attempts"] = "invocation"
    attempt_count: int = Field(default=1, strict=True, ge=1)


class EvaluationOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    UNSAFE_OUTPUT = "UNSAFE_OUTPUT"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"


class EvaluationObservation(_StrictModel):
    case_id: _Identifier
    task_type: TaskType
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: EvaluationOutcome
    structured_output: dict[str, Any] | None
    automatic_metrics: dict[str, Any]
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    attempt_count: int = Field(ge=0, strict=True)
    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    accounting_version: str | None = None
    accounting_basis: str | None = None
    error_code: str | None
