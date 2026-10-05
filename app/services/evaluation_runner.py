"""Pure async tutor invocation and limited automatic checks, without persistence."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from app.schemas.benchmark import (
    BenchmarkCase, EvaluationCandidate, EvaluationObservation, EvaluationOutcome,
    ExecutionPolicy, InvocationAccounting, TaskType, validate_safe_value,
)
from app.schemas.tutor import GenerationProvenance
from app.services.benchmark_suite import OUTPUT_TYPES, TUTOR_SCHEMA_VERSION, request_digest
from app.services.tutor_prompts import PROMPT_VERSIONS
from app.services.tutor_provider import TutorProvider


_METHODS = {
    TaskType.HINT: "generate_hint", TaskType.DIAGNOSIS: "diagnose_attempt",
    TaskType.REASONING: "analyze_reasoning", TaskType.EXPLANATION: "generate_post_attempt_explanation",
    TaskType.UNDERSTANDING: "evaluate_understanding",
}


def validate_output(raw: object, task: TaskType) -> BaseModel:
    """Validate task shape strictly; no vendor-specific objects or extra fields escape."""

    if isinstance(raw, BaseModel):
        raw = raw.model_dump(mode="json")
    validate_safe_value(raw)
    if not isinstance(raw, dict):
        raise TypeError("A structured tutor result is required")
    schema = OUTPUT_TYPES[task]
    # Existing production DTOs intentionally ignore unknown fields. Evaluation
    # must instead detect malformed/extra provider data without altering them.
    if set(raw) - set(schema.model_fields):
        raise TypeError("Unexpected structured result field")
    provenance = raw.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) - set(GenerationProvenance.model_fields):
        raise TypeError("Invalid provenance structure")
    return schema.model_validate(raw)


async def _accounting(provider: TutorProvider, timeout_seconds: float) -> InvocationAccounting | None:
    """Optional adapter hook only; malformed/absent counters remain unknown."""

    hook = getattr(provider, "take_invocation_accounting", None)
    if hook is None or not callable(hook):
        return None
    try:
        raw = hook()
        if inspect.isawaitable(raw):
            raw = await asyncio.wait_for(raw, timeout=timeout_seconds)
        return InvocationAccounting.model_validate(raw)
    except Exception:
        return None


def automatic_checks(case: BenchmarkCase, output: dict[str, Any]) -> dict[str, Any]:
    """Reproducible literal/label indicators, distinct from human quality judgments."""

    # Match delivered text only; provenance and classification identifiers are
    # not pedagogical content. These literal indicators are not semantic scores.
    fields = ("hint_text", "diagnosis_summary", "misconception_label", "feedback_text",
              "explanation_text", "key_insight")
    text = "\n".join(output[field] for field in fields if isinstance(output.get(field), str)).casefold()
    return {
        "structured_output_valid": True, "identity_valid": True,
        "expected_label_matches": {field: output.get(field) == expected
                                    for field, expected in case.expected_labels.items()},
        "required_content_matches": {literal: literal.casefold() in text for literal in case.required_content},
        "forbidden_content_matches": [literal for literal in case.forbidden_content if literal.casefold() in text],
    }


async def invoke_case(provider: TutorProvider, case: BenchmarkCase, candidate: EvaluationCandidate,
                      policy: ExecutionPolicy) -> EvaluationObservation:
    """Invoke one case, retaining validated data and safe failures only."""

    started = time.perf_counter()
    metrics: dict[str, Any] = {
        "structured_output_valid": False, "identity_valid": False,
        "expected_label_matches": {}, "required_content_matches": {}, "forbidden_content_matches": [],
    }
    output = None
    accounting = None
    attempts = 0
    outcome = EvaluationOutcome.INPUT_TOO_LARGE
    request_json = json.dumps(case.request.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False)
    if len(request_json) <= policy.max_input_chars:
        for attempt_number in range(1, policy.max_retries + 2):
            attempts = attempt_number
            try:
                # Every candidate/retry receives a fresh input object. No gold
                # criteria, another candidate's output or ORM entity is attached.
                raw = await asyncio.wait_for(
                    getattr(provider, _METHODS[case.task_type])(case.request.model_copy(deep=True)),
                    timeout=policy.timeout_seconds,
                )
                serialized = raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
                try:
                    validate_safe_value(serialized)
                except ValueError:
                    outcome = EvaluationOutcome.UNSAFE_OUTPUT
                    break
                try:
                    result = validate_output(serialized, case.task_type)
                except (ValidationError, TypeError, ValueError):
                    outcome = EvaluationOutcome.INVALID_SCHEMA
                    break
                metrics["structured_output_valid"] = True
                provenance = result.provenance
                if (provenance.provider != candidate.provider or provenance.model_id != candidate.model_id
                        or provenance.prompt_version != PROMPT_VERSIONS[case.task_type.value]
                        or provenance.schema_version != TUTOR_SCHEMA_VERSION
                        or provenance.source != ("synthetic" if candidate.synthetic else "model")):
                    outcome = EvaluationOutcome.IDENTITY_MISMATCH
                    break
                output = result.model_dump(mode="json")
                metrics = automatic_checks(case, output)
                outcome = EvaluationOutcome.SUCCESS
                break
            except TimeoutError:
                outcome = EvaluationOutcome.TIMEOUT
            except Exception:
                # Never persist str(error), raw SDK responses or tracebacks.
                outcome = EvaluationOutcome.PROVIDER_ERROR
            finally:
                accounting = await _accounting(provider, policy.timeout_seconds)
            # Only transient timeout/provider errors are retried. Structural,
            # safety and identity failures require an explicit corrected run.
            if outcome not in (EvaluationOutcome.TIMEOUT, EvaluationOutcome.PROVIDER_ERROR):
                break
    if accounting is not None and attempts > 1 and (
        accounting.scope != "all_attempts" or accounting.attempt_count != attempts
    ):
        accounting = None
    if accounting is not None and accounting.scope == "all_attempts" and accounting.attempt_count != attempts:
        accounting = None
    if accounting is not None and accounting.scope == "invocation" and accounting.attempt_count != 1:
        accounting = None
    return EvaluationObservation(
        case_id=case.case_id, task_type=case.task_type, request_digest=request_digest(case),
        outcome=outcome, structured_output=output, automatic_metrics=metrics,
        latency_ms=(time.perf_counter() - started) * 1000, attempt_count=attempts,
        input_tokens=accounting.input_tokens if accounting else None,
        output_tokens=accounting.output_tokens if accounting else None,
        accounting_version=accounting.accounting_version if accounting else None,
        accounting_basis=accounting.accounting_basis if accounting else None,
        error_code=None if outcome == EvaluationOutcome.SUCCESS else outcome.value,
    )
