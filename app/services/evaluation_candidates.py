"""Synthetic oracle/contrast harness fixtures; never evidence of real model quality."""

from __future__ import annotations

from app.schemas.benchmark import BenchmarkCase, EvaluationCandidate
from app.schemas.tutor import (
    AnswerQuality, DiagnosisResult, ExplanationResult, GenerationProvenance, HintResult, HintTask,
    MisconceptionCategory, ReasoningQuality, ReasoningResult, ReasoningTask, TutorRequest,
    UnderstandingResult, UnderstandingTask,
)
from app.services.benchmark_suite import canonical_hash, request_digest
from app.services.tutor_prompts import PROMPT_VERSIONS
from app.services.tutor_provider import TutorProvider, TutorProviderError


SYNTHETIC_CANDIDATES = (
    EvaluationCandidate(candidate_id="synthetic-good", provider="synthetic", model_id="synthetic-good-v1", synthetic=True),
    EvaluationCandidate(candidate_id="synthetic-bad", provider="synthetic", model_id="synthetic-bad-v1", synthetic=True),
)


class _SyntheticFixtureProvider(TutorProvider):
    """Gold access is confined to this clearly synthetic, one-case harness adapter."""

    def __init__(self, candidate: EvaluationCandidate, case: BenchmarkCase) -> None:
        self._candidate = candidate
        self._case = case
        self._good = candidate.model_id == "synthetic-good-v1"

    def _prepare(self, task: str, request: TutorRequest) -> tuple[str, GenerationProvenance]:
        if self._case.task_type.value != task or canonical_hash(request) != request_digest(self._case):
            raise TutorProviderError("Synthetic fixture does not match this task")
        if self._good:
            text = "Synthetic oracle fixture: " + "; ".join(self._case.required_content)
        else:
            text = "Synthetic contrast fixture: unsupported feedback. " + "; ".join(self._case.forbidden_content)
        return text, GenerationProvenance(
            source="synthetic", provider=self._candidate.provider, model_id=self._candidate.model_id,
            prompt_version=PROMPT_VERSIONS[task], schema_version="tutor-v1",
        )

    async def generate_hint(self, request: HintTask) -> HintResult:
        text, provenance = self._prepare("hint", request)
        return HintResult(hint_text=text, hint_content_id=f"synthetic-hint-{request.level}", provenance=provenance)

    async def diagnose_attempt(self, request: TutorRequest) -> DiagnosisResult:
        text, provenance = self._prepare("diagnosis", request)
        expected = self._case.expected_labels.get("misconception_category")
        label = expected if self._good else ("LOGICAL_ERROR" if expected != "LOGICAL_ERROR" else "SYNTAX_ERROR")
        return DiagnosisResult(misconception_category=MisconceptionCategory(label) if label else None,
                               diagnosis_summary=text, provenance=provenance)

    async def analyze_reasoning(self, request: ReasoningTask) -> ReasoningResult:
        text, provenance = self._prepare("reasoning", request)
        expected = self._case.expected_labels["reasoning_quality"]
        label = expected if self._good else ("FLAWED" if expected != "FLAWED" else "SOUND")
        return ReasoningResult(reasoning_quality=ReasoningQuality(label), feedback_text=text, provenance=provenance)

    async def generate_post_attempt_explanation(self, request: TutorRequest) -> ExplanationResult:
        text, provenance = self._prepare("explanation", request)
        return ExplanationResult(explanation_text=text, key_insight=text, provenance=provenance)

    async def evaluate_understanding(self, request: UnderstandingTask) -> UnderstandingResult:
        text, provenance = self._prepare("understanding", request)
        expected = self._case.expected_labels["answer_quality"]
        label = expected if self._good else ("INCORRECT" if expected != "INCORRECT" else "CORRECT")
        return UnderstandingResult(answer_quality=AnswerQuality(label), feedback_text=text, provenance=provenance)


def build_synthetic_provider(candidate: EvaluationCandidate, case: BenchmarkCase) -> TutorProvider:
    if candidate not in SYNTHETIC_CANDIDATES:
        raise ValueError("Only the named synthetic harness candidates are supported")
    return _SyntheticFixtureProvider(candidate, case)
