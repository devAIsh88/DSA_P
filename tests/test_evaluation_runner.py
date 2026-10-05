"""Independent evaluator invocation, isolation, failure and accounting tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.schemas.benchmark import EvaluationCandidate, EvaluationOutcome, ExecutionPolicy, InvocationAccounting
from app.services.benchmark_suite import load_suite, request_digest
from app.services.evaluation_runner import invoke_case
from app.services.evaluation_candidates import SYNTHETIC_CANDIDATES, build_synthetic_provider
from app.services.tutor_provider import TutorProviderError
from evaluation_fixtures import ScriptedProvider, valid_result


SUITE_PATH = Path(__file__).resolve().parents[1] / "benchmarks/tutor/v1/suite.json"


@pytest.fixture
def loaded():
    return load_suite(SUITE_PATH)


@pytest.fixture
def candidate():
    return EvaluationCandidate(candidate_id="fixture", provider="fixture", model_id="fixture-v1", synthetic=True)


def invoke(provider, case, candidate, **policy):
    return asyncio.run(invoke_case(provider, case, candidate, ExecutionPolicy(**policy)))


@pytest.mark.parametrize("task", ["hint", "diagnosis", "reasoning", "explanation", "understanding"])
def test_every_capability_uses_existing_typed_provider_contract(loaded, candidate, task):
    case = next(case for case in loaded.suite.cases if case.task_type.value == task)
    provider = ScriptedProvider()
    observation = invoke(provider, case, candidate)
    assert observation.outcome == EvaluationOutcome.SUCCESS
    assert [call[0] for call in provider.calls] == [task]
    assert observation.case_id == case.case_id
    assert observation.request_digest == request_digest(case)
    assert observation.attempt_count == 1 and observation.latency_ms >= 0
    assert observation.structured_output["provenance"]["provider"] == candidate.provider
    assert observation.automatic_metrics["structured_output_valid"] is True
    assert observation.automatic_metrics["identity_valid"] is True
    assert observation.input_tokens is None and observation.output_tokens is None
    assert observation.accounting_version is None and observation.accounting_basis is None


def test_provider_mutation_cannot_change_original_or_next_candidate_input(loaded, candidate):
    case = loaded.suite.cases[0]
    original = case.request.model_dump(mode="json")
    first = ScriptedProvider(mutate=True)
    second = ScriptedProvider()
    assert invoke(first, case, candidate).outcome == EvaluationOutcome.SUCCESS
    assert invoke(second, case, candidate).outcome == EvaluationOutcome.SUCCESS
    assert case.request.model_dump(mode="json") == original
    assert "MUTATED BY PROVIDER" not in second.calls[0][1].context.skill_names
    assert first.calls[0][1] is not second.calls[0][1]


def test_provider_error_is_sanitized_and_no_fallback_output_is_invented(loaded, candidate):
    provider = ScriptedProvider([TutorProviderError("private traceback, credential and provider details")])
    result = invoke(provider, loaded.suite.cases[0], candidate)
    assert result.outcome == EvaluationOutcome.PROVIDER_ERROR
    assert result.structured_output is None
    assert result.error_code
    assert "private traceback" not in result.model_dump_json()
    assert len(provider.calls) == 1


def test_invalid_object_or_schema_has_an_explicit_outcome(loaded, candidate):
    result = invoke(ScriptedProvider([object()]), loaded.suite.cases[0], candidate)
    assert result.outcome == EvaluationOutcome.INVALID_SCHEMA
    assert result.structured_output is None
    assert result.automatic_metrics["structured_output_valid"] is False


@pytest.mark.parametrize("identity,value", [
    ("provider", "other-provider"), ("model_id", "other-model"),
    ("prompt_version", "other-prompt"), ("schema_version", "other-schema"),
])
def test_provider_identity_and_contract_drift_are_explicit(loaded, candidate, identity, value):
    result = valid_result("hint")
    setattr(result.provenance, identity, value)
    observation = invoke(ScriptedProvider([result]), loaded.suite.cases[0], candidate)
    assert observation.outcome == EvaluationOutcome.IDENTITY_MISMATCH
    assert observation.structured_output is None
    assert observation.automatic_metrics["identity_valid"] is False


def test_obvious_credentials_in_generated_text_are_not_retained(loaded, candidate):
    result = valid_result("hint")
    result.hint_text = "API_KEY=synthetic-not-a-real-credential"
    observation = invoke(ScriptedProvider([result]), loaded.suite.cases[0], candidate)
    assert observation.outcome == EvaluationOutcome.UNSAFE_OUTPUT
    assert observation.structured_output is None
    assert "synthetic-not-a-real-credential" not in observation.model_dump_json()


def test_input_budget_rejection_does_not_invoke_provider(loaded, candidate):
    provider = ScriptedProvider()
    observation = invoke(provider, loaded.suite.cases[0], candidate, max_input_chars=1)
    assert observation.outcome == EvaluationOutcome.INPUT_TOO_LARGE
    assert observation.attempt_count == 0 and not provider.calls
    assert observation.structured_output is None


def test_bounded_retry_counts_all_attempts_and_uses_isolated_requests(loaded, candidate):
    provider = ScriptedProvider([TutorProviderError("safe failure"), valid_result("hint")], mutate=True)
    original = loaded.suite.cases[0].request.model_dump(mode="json")
    observation = invoke(provider, loaded.suite.cases[0], candidate, max_retries=1)
    assert observation.outcome == EvaluationOutcome.SUCCESS
    assert observation.attempt_count == 2 and len(provider.calls) == 2
    assert provider.calls[0][1] is not provider.calls[1][1]
    assert loaded.suite.cases[0].request.model_dump(mode="json") == original


def test_retries_are_bounded_on_final_provider_failure(loaded, candidate):
    provider = ScriptedProvider([TutorProviderError("first"), TutorProviderError("second"), valid_result("hint")])
    observation = invoke(provider, loaded.suite.cases[0], candidate, max_retries=1)
    assert observation.outcome == EvaluationOutcome.PROVIDER_ERROR
    assert observation.attempt_count == 2 and len(provider.calls) == 2
    assert observation.structured_output is None


def test_timeout_is_measured_and_does_not_loop(loaded, candidate):
    async def delayed(_task, _request):
        await asyncio.sleep(0.1)
        return valid_result("hint")
    provider = ScriptedProvider([delayed, delayed])
    observation = invoke(provider, loaded.suite.cases[0], candidate, timeout_seconds=0.005, max_retries=1)
    assert observation.outcome == EvaluationOutcome.TIMEOUT
    assert observation.attempt_count == 2 and len(provider.calls) == 2
    assert observation.latency_ms >= 0
    assert observation.structured_output is None


def test_explicit_accounting_for_all_attempts_is_retained(loaded, candidate):
    accounting = [None, InvocationAccounting(input_tokens=30, output_tokens=5, accounting_version="usage-v1", accounting_basis="tokens-v1",
                                             scope="all_attempts", attempt_count=2)]
    provider = ScriptedProvider([TutorProviderError("retry"), valid_result("hint")], accounting=accounting)
    observation = invoke(provider, loaded.suite.cases[0], candidate, max_retries=1)
    assert (observation.input_tokens, observation.output_tokens) == (30, 5)
    assert observation.accounting_version == "usage-v1" and observation.accounting_basis == "tokens-v1"


@pytest.mark.parametrize("invalid", [None, {}, {"input_tokens": 4},
                                    {"input_tokens": -1, "output_tokens": 0, "accounting_version": "usage-v1", "accounting_basis": "tokens-v1"}])
def test_missing_or_invalid_accounting_is_unknown_not_estimated(loaded, candidate, invalid):
    observation = invoke(ScriptedProvider(accounting=[invalid]), loaded.suite.cases[0], candidate)
    assert observation.input_tokens is None and observation.output_tokens is None
    assert observation.accounting_version is None and observation.accounting_basis is None


def test_partial_retry_accounting_does_not_understate_total_usage(loaded, candidate):
    accounted = InvocationAccounting(input_tokens=20, output_tokens=5, accounting_version="usage-v1", accounting_basis="tokens-v1")
    provider = ScriptedProvider([TutorProviderError("retry"), valid_result("hint")], accounting=[None, accounted])
    observation = invoke(provider, loaded.suite.cases[0], candidate, max_retries=1)
    assert observation.input_tokens is None and observation.output_tokens is None
    assert observation.accounting_version is None


def test_individual_last_attempt_accounting_is_not_mistaken_for_retry_total(loaded, candidate):
    accounting = [InvocationAccounting(input_tokens=10, output_tokens=0, accounting_version="usage-v1", accounting_basis="tokens-v1"),
                  InvocationAccounting(input_tokens=20, output_tokens=5, accounting_version="usage-v1", accounting_basis="tokens-v1")]
    provider = ScriptedProvider([TutorProviderError("retry"), valid_result("hint")], accounting=accounting)
    observation = invoke(provider, loaded.suite.cases[0], candidate, max_retries=1)
    assert observation.input_tokens is None and observation.output_tokens is None


@pytest.mark.parametrize("scope", ["all_attempts", "invocation"])
def test_accounting_scope_must_cover_the_claimed_attempt_count(loaded, candidate, scope):
    accounting = InvocationAccounting(input_tokens=30, output_tokens=5, accounting_version="usage-v1", accounting_basis="tokens-v1",
                                     scope=scope, attempt_count=3)
    observation = invoke(ScriptedProvider(accounting=[accounting]), loaded.suite.cases[0], candidate)
    assert observation.input_tokens is None and observation.output_tokens is None


@pytest.mark.parametrize("good", [True, False])
def test_synthetic_oracle_and_contrast_cover_all_25_cases_without_network(loaded, good):
    selected_candidate = SYNTHETIC_CANDIDATES[0 if good else 1]
    for case in loaded.suite.cases:
        provider = build_synthetic_provider(selected_candidate, case)
        result = invoke(provider, case, selected_candidate)
        assert result.outcome == EvaluationOutcome.SUCCESS
        assert result.structured_output["provenance"]["source"] == "synthetic"
        metrics = result.automatic_metrics
        if metrics["expected_label_matches"]:
            assert all(metrics["expected_label_matches"].values()) is good
        if good:
            assert all(metrics["required_content_matches"].values())
            assert not metrics["forbidden_content_matches"]
        elif case.forbidden_content:
            assert metrics["forbidden_content_matches"]


def test_structurally_invalid_outputs_do_not_retry_or_create_label_denominators(loaded, candidate):
    provider = ScriptedProvider([object(), valid_result("hint")])
    result = invoke(provider, loaded.suite.cases[0], candidate, max_retries=3)
    assert result.outcome == EvaluationOutcome.INVALID_SCHEMA
    assert result.attempt_count == 1 and len(provider.calls) == 1
    assert result.automatic_metrics["expected_label_matches"] == {}
    assert result.automatic_metrics["required_content_matches"] == {}


def test_real_candidate_cannot_claim_a_synthetic_or_fallback_invocation(loaded):
    candidate = EvaluationCandidate(candidate_id="real-fixture", provider="fixture", model_id="fixture-v1", synthetic=False)
    result = valid_result("hint")
    observation = invoke(ScriptedProvider([result]), loaded.suite.cases[0], candidate)
    assert observation.outcome == EvaluationOutcome.IDENTITY_MISMATCH
    assert observation.structured_output is None


def test_async_usage_hook_cannot_hang_the_evaluator(loaded, candidate):
    class SlowAccounting(ScriptedProvider):
        async def take_invocation_accounting(self):
            await asyncio.sleep(10)
    observation = invoke(SlowAccounting(), loaded.suite.cases[0], candidate, timeout_seconds=0.005)
    assert observation.outcome == EvaluationOutcome.SUCCESS
    assert observation.input_tokens is None
    assert observation.latency_ms < 1000
