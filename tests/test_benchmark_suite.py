"""Independent benchmark definition, versioning and request-safety checks."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

from app.services.benchmark_suite import canonical_hash, load_suite, request_digest
from app.schemas.benchmark import ExecutionPolicy, HumanReviewCreate, InvocationAccounting


SUITE_PATH = Path(__file__).resolve().parents[1] / "benchmarks/tutor/v1/suite.json"


def changed_suite(tmp_path, change):
    definition = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    change(definition)
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    (tmp_path / "rubric.json").write_text(
        SUITE_PATH.with_name("rubric.json").read_text(encoding="utf-8"), encoding="utf-8",
    )
    return path


def test_curated_suite_has_unique_cases_for_every_provider_capability():
    loaded = load_suite(SUITE_PATH)
    assert len(loaded.suite.cases) == 25
    assert len(set(loaded.case_ids)) == 25
    assert Counter(case.task_type.value for case in loaded.suite.cases) == {
        "hint": 6, "diagnosis": 9, "reasoning": 4, "explanation": 2, "understanding": 4,
    }
    assert sorted(case.request.level for case in loaded.suite.cases if case.task_type.value == "hint") == list(range(1, 7))
    assert all(case.case_id and case.version and case.review_guidance for case in loaded.suite.cases)
    assert all(len(value) == 64 for value in (loaded.digest, loaded.rubric_digest, loaded.schema_digest))


def test_canonical_hash_is_order_independent_but_preserves_meaningful_changes():
    assert canonical_hash({"a": 1, "b": [2, 3]}) == canonical_hash({"b": [2, 3], "a": 1})
    assert canonical_hash({"b": [2, 3]}) != canonical_hash({"b": [3, 2]})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_fixture_request_is_separate_from_gold_criteria_and_hash_detects_drift(tmp_path):
    original = load_suite(SUITE_PATH)
    first = original.suite.cases[0]
    request = first.request.model_dump(mode="json")
    assert not {"case_id", "expected_labels", "required_content", "forbidden_content", "review_guidance"} & request.keys()
    changed = load_suite(changed_suite(tmp_path, lambda definition: definition["cases"][0]["request"]["context"].update(problem_title="Different public title")))
    assert changed.digest != original.digest
    assert request_digest(changed.suite.cases[0]) != request_digest(first)
    assert first.request.model_dump(mode="json") == request


@pytest.mark.parametrize("level", ["suite", "case", "request", "context"])
def test_unknown_keys_are_rejected_recursively(tmp_path, level):
    def change(definition):
        targets = {"suite": definition, "case": definition["cases"][0],
                   "request": definition["cases"][0]["request"],
                   "context": definition["cases"][0]["request"]["context"]}
        targets[level]["unapproved_private_field"] = "must not be silently discarded"
    with pytest.raises((ValueError, TypeError)):
        load_suite(changed_suite(tmp_path, change))


@pytest.mark.parametrize("private_field", ["hidden_tests", "expected_output", "stderr", "user_id", "attempt_id", "provider_config"])
def test_private_or_orm_context_fields_are_rejected(tmp_path, private_field):
    with pytest.raises((ValueError, TypeError)):
        load_suite(changed_suite(tmp_path, lambda definition: definition["cases"][0]["request"]["context"].update({private_field: "PRIVATE"})))


def test_oversized_request_context_is_rejected(tmp_path):
    with pytest.raises((ValueError, TypeError)):
        load_suite(changed_suite(tmp_path, lambda definition: definition["cases"][0]["request"]["context"].update(problem_description="x" * 6001)))


def test_duplicate_case_identity_is_rejected(tmp_path):
    def change(definition):
        definition["cases"][1]["case_id"] = definition["cases"][0]["case_id"]
    with pytest.raises((ValueError, TypeError)):
        load_suite(changed_suite(tmp_path, change))


def test_hint_level_out_of_contract_is_rejected(tmp_path):
    with pytest.raises((ValueError, TypeError)):
        load_suite(changed_suite(tmp_path, lambda definition: definition["cases"][0]["request"].update(level=7)))


def test_gold_metadata_does_not_change_provider_request_digest(tmp_path):
    original = load_suite(SUITE_PATH)
    changed = load_suite(changed_suite(tmp_path, lambda definition: definition["cases"][0].update(review_guidance="A reviewed, updated criterion.")))
    assert changed.digest != original.digest
    assert request_digest(changed.suite.cases[0]) == request_digest(original.suite.cases[0])


@pytest.mark.parametrize("unsafe_text", [
    "postgresql://synthetic_user:synthetic_password@localhost/synthetic_db",
    "API_KEY=synthetic-not-a-real-credential",
    "-----BEGIN PRIVATE KEY----- synthetic fixture -----END PRIVATE KEY-----",
])
def test_obvious_credentials_are_rejected_without_echoing_them(tmp_path, unsafe_text):
    with pytest.raises(ValueError) as failure:
        load_suite(changed_suite(tmp_path, lambda definition: definition["cases"][0]["request"]["context"].update(problem_description=unsafe_text)))
    assert unsafe_text not in str(failure.value)


@pytest.mark.parametrize("changes", [
    {"timeout_seconds": 0}, {"timeout_seconds": float("nan")},
    {"max_retries": -1}, {"max_retries": True}, {"max_retries": 4},
    {"max_input_chars": 0}, {"max_output_tokens": 8193}, {"temperature": float("inf")},
    {"provider_config": {"secret": "never permitted"}},
])
def test_execution_controls_are_bounded_explicit_and_provider_neutral(changes):
    with pytest.raises(ValueError):
        ExecutionPolicy(**changes)


def test_missing_or_partial_accounting_cannot_be_presented_as_complete_usage():
    with pytest.raises(ValueError):
        InvocationAccounting(input_tokens=1, accounting_version="usage-v1", accounting_basis="tokens-v1")
    with pytest.raises(ValueError):
        InvocationAccounting(input_tokens=-1, output_tokens=0, accounting_version="usage-v1", accounting_basis="tokens-v1")
    with pytest.raises(ValueError):
        InvocationAccounting(input_tokens=True, output_tokens=0, accounting_version="usage-v1", accounting_basis="tokens-v1")


def test_review_scores_require_applicable_dimensions_and_explicit_nulls():
    loaded = load_suite(SUITE_PATH)
    case = loaded.suite.cases[0]
    applicable = set(loaded.rubric.applicable_dimensions(case.task_type))
    scores = {dimension.name: 3 if dimension.name in applicable else None for dimension in loaded.rubric.dimensions}
    loaded.rubric.validate_review_scores(scores, case.task_type)
    with pytest.raises(ValueError):
        loaded.rubric.validate_review_scores({}, case.task_type)
    missing = dict(scores)
    missing[next(iter(applicable))] = None
    with pytest.raises(ValueError):
        loaded.rubric.validate_review_scores(missing, case.task_type)
    with pytest.raises(ValueError):
        HumanReviewCreate(result_id=1, reviewer_label="reviewer", rubric_version=loaded.rubric.rubric_version,
                          scores={next(iter(applicable)): True})
