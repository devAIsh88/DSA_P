"""Load versioned synthetic fixtures and bind experiment identities to canonical hashes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.schemas.benchmark import BenchmarkCase, BenchmarkSuite, ExecutionPolicy, RubricDefinition, TaskType
from app.schemas.tutor import DiagnosisResult, ExplanationResult, HintResult, ReasoningResult, UnderstandingResult
from app.services.tutor_prompts import PROMPT_VERSIONS


RUNNER_VERSION = "tutor-evaluation-v1"
TUTOR_SCHEMA_VERSION = "tutor-v1"
OUTPUT_TYPES = {
    TaskType.HINT: HintResult, TaskType.DIAGNOSIS: DiagnosisResult,
    TaskType.REASONING: ReasoningResult, TaskType.EXPLANATION: ExplanationResult,
    TaskType.UNDERSTANDING: UnderstandingResult,
}


class BenchmarkDefinitionError(ValueError):
    """A fixture definition failed validation; its unsafe contents are not echoed."""


@dataclass(frozen=True)
class LoadedSuite:
    suite: BenchmarkSuite
    rubric: RubricDefinition
    digest: str
    rubric_digest: str
    schema_digest: str
    case_ids: tuple[str, ...]
    case_by_id: dict[str, BenchmarkCase]


def canonical_hash(value: Any) -> str:
    """Hash semantic JSON rather than formatting; no token/cost inference is involved."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def request_digest(case: BenchmarkCase) -> str:
    return canonical_hash(case.request)


def selected_case_digest(cases: Sequence[BenchmarkCase]) -> str:
    return canonical_hash([case.model_dump(mode="json") for case in cases])


def _read_definition(path: Path) -> object:
    # The curated foundation is deliberately small. Refuse oversized inputs
    # before reading/parsing them, independently of individual DTO field limits.
    if not path.is_file() or path.stat().st_size > 256000:
        raise BenchmarkDefinitionError("Benchmark definitions must be bounded existing JSON files")
    return json.loads(path.read_text(encoding="utf-8"))


def load_suite(path: str | Path) -> LoadedSuite:
    """Require a complete five-task suite and its matching adjacent rubric."""

    suite_path = Path(path)
    if suite_path.is_dir():
        suite_path = suite_path / "suite.json"
    try:
        suite = BenchmarkSuite.model_validate(_read_definition(suite_path))
        rubric = RubricDefinition.model_validate(_read_definition(suite_path.with_name("rubric.json")))
        if suite.rubric_version != rubric.rubric_version:
            raise BenchmarkDefinitionError("Suite and rubric versions differ")
        if any(not rubric.applicable_dimensions(case.task_type) for case in suite.cases):
            raise BenchmarkDefinitionError("Every task requires applicable human-review dimensions")
    except (OSError, UnicodeError, ValueError, ValidationError):
        raise BenchmarkDefinitionError("Benchmark suite or rubric is invalid") from None
    return LoadedSuite(
        suite=suite, rubric=rubric, digest=canonical_hash(suite), rubric_digest=canonical_hash(rubric),
        schema_digest=canonical_hash({task.value: result.model_json_schema() for task, result in OUTPUT_TYPES.items()}),
        case_ids=tuple(case.case_id for case in suite.cases), case_by_id={case.case_id: case for case in suite.cases},
    )


def protocol_fingerprint(loaded_suite: LoadedSuite, policy: ExecutionPolicy,
                         selected_cases: Sequence[BenchmarkCase], code_revision: str) -> str:
    """Candidate/provider pricing differ; the actual comparison protocol must match."""

    return canonical_hash({
        "suite_digest": loaded_suite.digest, "rubric_digest": loaded_suite.rubric_digest,
        "schema_digest": loaded_suite.schema_digest, "selected_case_digest": selected_case_digest(selected_cases),
        "runner_version": RUNNER_VERSION, "tutor_schema_version": TUTOR_SCHEMA_VERSION,
        "prompt_versions": dict(PROMPT_VERSIONS), "code_revision": code_revision,
        "execution_policy": policy.model_dump(mode="json"),
    })
