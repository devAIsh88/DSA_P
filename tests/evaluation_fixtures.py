"""Independent deterministic providers for the offline evaluation tests."""

from __future__ import annotations

from collections import deque
from typing import Any

from app.schemas.tutor import (
    DiagnosisResult, ExplanationResult, GenerationProvenance, HintResult,
    ReasoningResult, UnderstandingResult,
)
from app.services.tutor_prompts import PROMPT_VERSIONS
from app.services.tutor_provider import TutorProvider


def valid_result(task: str, *, provider: str = "fixture", model_id: str = "fixture-v1"):
    provenance = GenerationProvenance(
        source="synthetic", provider=provider, model_id=model_id, prompt_version=PROMPT_VERSIONS[task],
        schema_version="tutor-v1", invocation_id="fixture-invocation",
    )
    if task == "hint":
        return HintResult(hint_text="Describe the invariant and consider an edge case.",
                          hint_content_id="fixture-hint", provenance=provenance)
    if task == "diagnosis":
        return DiagnosisResult(misconception_category=None,
                               diagnosis_summary="Compare the approach with the invariant.",
                               provenance=provenance)
    if task == "reasoning":
        return ReasoningResult(reasoning_quality="SOUND", feedback_text="State the invariant clearly.",
                               provenance=provenance)
    if task == "explanation":
        return ExplanationResult(explanation_text="The invariant preserves all relevant candidates.",
                                 key_insight="Explain why each update preserves the invariant.",
                                 provenance=provenance)
    if task == "understanding":
        return UnderstandingResult(answer_quality="CORRECT", feedback_text="The explanation is consistent.",
                                   provenance=provenance)
    raise AssertionError(f"Unexpected task: {task}")


class ScriptedProvider(TutorProvider):
    """Record calls and optionally return controlled results or failures."""

    def __init__(self, responses=(), *, accounting=(), mutate: bool = False) -> None:
        self.responses = deque(responses)
        self.accounting = deque(accounting)
        self.mutate = mutate
        self.calls: list[tuple[str, Any]] = []
        self.received_titles: list[str] = []

    async def _call(self, task, request):
        self.calls.append((task, request))
        self.received_titles.append(request.context.problem_title)
        if self.mutate:
            # Frozen Pydantic attributes do not freeze nested list contents.
            request.context.skill_names.append("MUTATED BY PROVIDER")
        if self.responses:
            response = self.responses.popleft()
            if isinstance(response, BaseException):
                raise response
            if callable(response):
                response = response(task, request)
                if hasattr(response, "__await__"):
                    response = await response
            return response
        return valid_result(task)

    def take_invocation_accounting(self):
        return self.accounting.popleft() if self.accounting else None

    async def generate_hint(self, request):
        return await self._call("hint", request)

    async def diagnose_attempt(self, request):
        return await self._call("diagnosis", request)

    async def analyze_reasoning(self, request):
        return await self._call("reasoning", request)

    async def generate_post_attempt_explanation(self, request):
        return await self._call("explanation", request)

    async def evaluate_understanding(self, request):
        return await self._call("understanding", request)
