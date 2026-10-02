"""Provider-neutral Phase 6 tutor contracts and learner-facing responses."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MisconceptionCategory(str, Enum):
    SYNTAX_ERROR = "SYNTAX_ERROR"
    IMPLEMENTATION_ERROR = "IMPLEMENTATION_ERROR"
    LOGICAL_ERROR = "LOGICAL_ERROR"
    CONCEPTUAL_ERROR = "CONCEPTUAL_ERROR"
    COMPLEXITY_ERROR = "COMPLEXITY_ERROR"
    EDGE_CASE_ERROR = "EDGE_CASE_ERROR"
    MISREAD_PROBLEM = "MISREAD_PROBLEM"
    WRONG_PATTERN = "WRONG_PATTERN"
    INCOMPLETE_REASONING = "INCOMPLETE_REASONING"


class ReasoningQuality(str, Enum):
    SOUND = "SOUND"
    PARTIAL = "PARTIAL"
    FLAWED = "FLAWED"
    UNDETERMINED = "UNDETERMINED"


class AnswerQuality(str, Enum):
    CORRECT = "CORRECT"
    PARTIALLY_CORRECT = "PARTIALLY_CORRECT"
    INCORRECT = "INCORRECT"
    UNDETERMINED = "UNDETERMINED"


class TutorContext(BaseModel):
    """Bounded, sanitized context; never accepts ORM/test-result objects."""

    problem_title: str = Field(max_length=200)
    problem_description: str = Field(max_length=6000)
    problem_constraints: str | None = Field(default=None, max_length=2000)
    attempt_status: str
    attempt_outcome: str | None = None
    reasoning_text: str | None = Field(default=None, max_length=10000)
    source_code: str | None = Field(default=None, max_length=12000)
    deterministic_status: str | None = None
    tests_passed: int | None = None
    tests_total: int | None = None
    skill_names: list[str] = Field(default_factory=list, max_length=8)
    mastery_probability: float | None = Field(default=None, ge=0, le=1)
    prior_hint_levels: list[int] = Field(default_factory=list, max_length=20)


class TutorRequest(BaseModel):
    context: TutorContext


class HintTask(TutorRequest):
    level: int = Field(ge=1, le=6)


class ReasoningTask(TutorRequest):
    reasoning_text: str = Field(min_length=1, max_length=10000)


class UnderstandingTask(TutorRequest):
    question: str = Field(min_length=1, max_length=1000)
    answer_text: str = Field(min_length=1, max_length=20000)


class GenerationProvenance(BaseModel):
    source: str = "model"
    provider: str
    model_id: str
    prompt_version: str
    schema_version: str = "tutor-v1"
    invocation_id: str | None = None
    served_model_id: str | None = None
    max_output_tokens: int | None = None


class HintResult(BaseModel):
    hint_text: str = Field(min_length=1, max_length=8000)
    hint_content_id: str = Field(min_length=1, max_length=120)
    provenance: GenerationProvenance


class DiagnosisResult(BaseModel):
    misconception_category: MisconceptionCategory | None = None
    misconception_label: str | None = Field(default=None, max_length=200)
    diagnosis_summary: str = Field(min_length=1, max_length=8000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: GenerationProvenance


class ReasoningResult(BaseModel):
    reasoning_quality: ReasoningQuality
    feedback_text: str = Field(min_length=1, max_length=8000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: GenerationProvenance


class ExplanationResult(BaseModel):
    explanation_text: str = Field(min_length=1, max_length=12000)
    key_insight: str = Field(min_length=1, max_length=2000)
    provenance: GenerationProvenance


class UnderstandingResult(BaseModel):
    answer_quality: AnswerQuality
    feedback_text: str = Field(min_length=1, max_length=8000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: GenerationProvenance


class TutorActionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=100)


class HintRequest(TutorActionRequest):
    attempt_id: int = Field(gt=0)
    requested_level: int = Field(ge=1, le=6)


class DiagnoseRequest(TutorActionRequest):
    submission_id: int = Field(gt=0)


class ReasoningAnalysisRequest(TutorActionRequest):
    reasoning_event_id: int = Field(gt=0)


class PostExplanationRequest(TutorActionRequest):
    pass


class UnderstandingCheckRequest(TutorActionRequest):
    pass


class UnderstandingAnswerRequest(TutorActionRequest):
    answer_text: str = Field(min_length=1, max_length=20000)


class HintResponse(BaseModel):
    attempt_id: int
    request_event_id: int
    delivery_event_id: int
    requested_level: int
    delivered_level: int
    hint_text: str
    hint_content_id: str
    source: str


class DiagnoseResponse(BaseModel):
    diagnosis_event_id: int
    submission_id: int
    deterministic_status: str
    misconception_category: MisconceptionCategory | None
    misconception_label: str | None
    diagnosis_summary: str


class ReasoningAnalysisResponse(BaseModel):
    analysis_event_id: int
    reasoning_event_id: int
    reasoning_quality: ReasoningQuality
    feedback_text: str


class PostExplanationResponse(BaseModel):
    explanation_event_id: int
    explanation_text: str
    key_insight: str


class UnderstandingCheckResponse(BaseModel):
    check_event_id: int
    question: str
    question_version: str


class UnderstandingAnswerResponse(BaseModel):
    answer_event_id: int
    evaluation_event_id: int
    answer_quality: AnswerQuality
    feedback_text: str
