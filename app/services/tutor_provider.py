"""Replaceable tutor boundary and deterministic test/fallback providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha256

from app.schemas.tutor import (
    AnswerQuality, DiagnosisResult, ExplanationResult, GenerationProvenance,
    HintResult, HintTask, ReasoningQuality, ReasoningResult, ReasoningTask,
    TutorRequest, UnderstandingResult, UnderstandingTask,
)
from app.services.tutor_prompts import PROMPT_VERSIONS


class TutorProviderError(Exception):
    """A provider could not return a validated tutor result."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class TutorProvider(ABC):
    """Vendor-independent interface; implementations do not access persistence."""

    @abstractmethod
    async def generate_hint(self, request: HintTask) -> HintResult: ...

    @abstractmethod
    async def diagnose_attempt(self, request: TutorRequest) -> DiagnosisResult: ...

    @abstractmethod
    async def analyze_reasoning(self, request: ReasoningTask) -> ReasoningResult: ...

    @abstractmethod
    async def generate_post_attempt_explanation(self, request: TutorRequest) -> ExplanationResult: ...

    @abstractmethod
    async def evaluate_understanding(self, request: UnderstandingTask) -> UnderstandingResult: ...


class MockTutorProvider(TutorProvider):
    """Deterministic isolated provider for normal tests and local development."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    @staticmethod
    def _provenance(task: str) -> GenerationProvenance:
        return GenerationProvenance(provider="mock", model_id="mock-v1", prompt_version=PROMPT_VERSIONS[task])

    async def generate_hint(self, request: HintTask) -> HintResult:
        self.calls.append(("hint", request))
        return HintResult(hint_text=f"Level {request.level} guidance for {request.context.problem_title}.",
                          hint_content_id=f"mock-hint-{request.level}", provenance=self._provenance("hint"))

    async def diagnose_attempt(self, request: TutorRequest) -> DiagnosisResult:
        self.calls.append(("diagnosis", request))
        return DiagnosisResult(diagnosis_summary="Review the approach against the evaluated result.",
                               provenance=self._provenance("diagnosis"))

    async def analyze_reasoning(self, request: ReasoningTask) -> ReasoningResult:
        self.calls.append(("reasoning", request))
        return ReasoningResult(reasoning_quality=ReasoningQuality.UNDETERMINED,
                               feedback_text="Explain the invariant and an edge case.",
                               provenance=self._provenance("reasoning"))

    async def generate_post_attempt_explanation(self, request: TutorRequest) -> ExplanationResult:
        self.calls.append(("explanation", request))
        return ExplanationResult(explanation_text="Review the final approach and its complexity.",
                                 key_insight="Connect the invariant to the result.",
                                 provenance=self._provenance("explanation"))

    async def evaluate_understanding(self, request: UnderstandingTask) -> UnderstandingResult:
        self.calls.append(("understanding", request))
        return UnderstandingResult(answer_quality=AnswerQuality.UNDETERMINED,
                                   feedback_text="Explain why the approach handles edge cases.",
                                   provenance=self._provenance("understanding"))


class FallbackHintProvider:
    """Hint-only deterministic fallback; never invents a diagnosis or solution."""

    async def generate_hint(self, request: HintTask) -> HintResult | None:
        # Level 6 cannot safely synthesize an unknown solution from a static template.
        if request.level == 6:
            return None
        templates = {
            1: "Restate the input, output, and key constraint in your own words.",
            2: "Try a small example and list the state that must be tracked.",
            3: "Identify an invariant that stays true after each step.",
            4: "Outline the algorithm before translating it into code.",
            5: "Walk through the edge cases and complexity of your approach.",
        }
        hint_text = templates[request.level]
        content_id = sha256(f"fallback-hint-v1:{request.level}".encode()).hexdigest()[:24]
        return HintResult(hint_text=hint_text, hint_content_id=content_id,
                          provenance=GenerationProvenance(source="deterministic_rule", provider="fallback",
                                                          model_id="none", prompt_version="fallback-hint-v1"))
