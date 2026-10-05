"""Atomic evaluation history, separate from every learner-state transaction."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.evaluation import EvaluationResult, EvaluationReview, EvaluationRun
from app.schemas.benchmark import (
    BenchmarkCase, BenchmarkSuite, EvaluationCandidate, EvaluationObservation,
    EvaluationOutcome, ExecutionPolicy, HumanReviewCreate, InvocationAccounting,
    PricingSnapshot, RubricDefinition, TaskType, validate_safe_value,
)
from app.services.benchmark_suite import (
    OUTPUT_TYPES, RUNNER_VERSION, TUTOR_SCHEMA_VERSION, LoadedSuite, canonical_hash,
    protocol_fingerprint, request_digest, selected_case_digest,
)
from app.services.evaluation_runner import automatic_checks, validate_output
from app.services.tutor_prompts import PROMPT_VERSIONS


class EvaluationStoreError(ValueError):
    """Evaluation history could not be validated or persisted safely."""


class EvaluationPlanConflictError(EvaluationStoreError):
    """A supplied identity differs from its committed plan or observation."""


def _clean_session(db: Session) -> None:
    if db.new or db.dirty or db.deleted:
        raise EvaluationStoreError("Evaluation storage requires a session without unrelated pending writes")


def _uuid(value: UUID | str, label: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise EvaluationStoreError(f"Invalid evaluation {label} identity") from None


def _validate_loaded(loaded: LoadedSuite) -> None:
    """A caller cannot mutate nested fixture data while retaining an old digest."""

    BenchmarkSuite.model_validate(loaded.suite.model_dump(mode="json"))
    RubricDefinition.model_validate(loaded.rubric.model_dump(mode="json"))
    if (loaded.digest != canonical_hash(loaded.suite)
            or loaded.rubric_digest != canonical_hash(loaded.rubric)
            or loaded.schema_digest != canonical_hash({
                task.value: schema.model_json_schema() for task, schema in OUTPUT_TYPES.items()
            })
            or loaded.suite.rubric_version != loaded.rubric.rubric_version
            or loaded.case_ids != tuple(case.case_id for case in loaded.suite.cases)
            or set(loaded.case_by_id) != set(loaded.case_ids)):
        raise EvaluationPlanConflictError("Benchmark definitions differ from their recorded identity")
    if any(canonical_hash(loaded.case_by_id[case.case_id]) != canonical_hash(case)
           for case in loaded.suite.cases):
        raise EvaluationPlanConflictError("Benchmark case lookup differs from suite content")


def _manifest(cases: Sequence[BenchmarkCase]) -> list[dict[str, str]]:
    return [{"case_id": case.case_id, "case_digest": canonical_hash(case),
             "request_digest": request_digest(case), "task_type": case.task_type.value}
            for case in cases]


def _run_plan(candidate: EvaluationCandidate, loaded: LoadedSuite, policy: ExecutionPolicy,
              cases: Sequence[BenchmarkCase], group_id: UUID | str,
              pricing: PricingSnapshot | None, code_revision: str) -> dict:
    _validate_loaded(loaded)
    candidate = EvaluationCandidate.model_validate(candidate.model_dump(mode="json"))
    policy = ExecutionPolicy.model_validate(policy.model_dump(mode="json"))
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise EvaluationPlanConflictError("A nonempty unique case selection is required")
    for case in cases:
        BenchmarkCase.model_validate(case.model_dump(mode="json"))
        original = loaded.case_by_id.get(case.case_id)
        if original is None or canonical_hash(case) != canonical_hash(original):
            raise EvaluationPlanConflictError("Selected case differs from the loaded benchmark")
    if not isinstance(code_revision, str) or not 1 <= len(code_revision) <= 64:
        raise EvaluationStoreError("A bounded code revision is required")
    validate_safe_value(code_revision)
    pricing_json = None
    if pricing is not None:
        pricing = PricingSnapshot.model_validate(pricing.model_dump(mode="json"))
        if (pricing.provider != candidate.provider or pricing.model_id != candidate.model_id
                or pricing.synthetic != candidate.synthetic):
            raise EvaluationPlanConflictError("Pricing does not identify the evaluation candidate")
        pricing_json = pricing.model_dump(mode="json")
    return {
        "group_id": _uuid(group_id, "group"), "suite_id": loaded.suite.suite_id,
        "suite_version": loaded.suite.version, "suite_digest": loaded.digest,
        "selected_case_ids": [case.case_id for case in cases], "case_manifest": _manifest(cases),
        "selected_cases_digest": selected_case_digest(cases), "candidate_id": candidate.candidate_id,
        "provider": candidate.provider, "model_id": candidate.model_id, "synthetic": candidate.synthetic,
        "runner_version": RUNNER_VERSION, "code_revision": code_revision,
        "prompt_versions": dict(PROMPT_VERSIONS), "schema_version": TUTOR_SCHEMA_VERSION,
        "schema_digest": loaded.schema_digest, "rubric_version": loaded.rubric.rubric_version,
        "rubric_digest": loaded.rubric_digest,
        "protocol_fingerprint": protocol_fingerprint(loaded, policy, cases, code_revision),
        "execution_policy": policy.model_dump(mode="json"), "pricing_snapshot": pricing_json,
    }


def get_run(db: Session, run_id: UUID | str) -> EvaluationRun:
    run = db.get(EvaluationRun, _uuid(run_id, "run"))
    if run is None:
        raise EvaluationStoreError("Evaluation run not found")
    return run


def start_run(db: Session, candidate: EvaluationCandidate, loaded_suite: LoadedSuite,
              policy: ExecutionPolicy, selected_cases: Sequence[BenchmarkCase], group_id: UUID | str,
              pricing: PricingSnapshot | None, code_revision: str,
              run_id: UUID | str | None = None) -> EvaluationRun:
    """Persist a new plan or explicitly resume exactly the same immutable plan."""

    _clean_session(db)
    try:
        plan = _run_plan(candidate, loaded_suite, policy, selected_cases, group_id, pricing, code_revision)
        if run_id is not None:
            run = get_run(db, run_id)
            if any(getattr(run, key) != value for key, value in plan.items()):
                raise EvaluationPlanConflictError("Resume requires the original complete evaluation plan")
            return run
        # Same-version fixture drift must not quietly become another experiment definition.
        previous_suite = db.scalar(select(EvaluationRun.id).where(
            EvaluationRun.suite_id == plan["suite_id"], EvaluationRun.suite_version == plan["suite_version"],
            EvaluationRun.suite_digest != plan["suite_digest"],
        ).limit(1))
        previous_rubric = db.scalar(select(EvaluationRun.id).where(
            EvaluationRun.rubric_version == plan["rubric_version"],
            EvaluationRun.rubric_digest != plan["rubric_digest"],
        ).limit(1))
        if previous_suite is not None or previous_rubric is not None:
            raise EvaluationPlanConflictError("Changed benchmark or rubric content requires a new version")
        run = EvaluationRun(id=uuid4(), status="RUNNING", created_at=datetime.now(UTC), **plan)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    except EvaluationStoreError:
        db.rollback()
        raise
    except (ValueError, TypeError, ValidationError):
        db.rollback()
        raise EvaluationStoreError("Invalid evaluation plan") from None
    except SQLAlchemyError:
        db.rollback()
        raise EvaluationStoreError("Evaluation plan could not be persisted") from None


def results_for_run(db: Session, run_id: UUID | str) -> list[EvaluationResult]:
    """Read recorded observations in the experiment's original selection order."""

    run = get_run(db, run_id)
    results = list(db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)))
    order = {case_id: index for index, case_id in enumerate(run.selected_case_ids)}
    return sorted(results, key=lambda result: (order.get(result.case_id, len(order)), result.id))


def _observation_values(run: EvaluationRun, case: BenchmarkCase,
                        observation: EvaluationObservation) -> dict:
    case = BenchmarkCase.model_validate(case.model_dump(mode="json"))
    observation = EvaluationObservation.model_validate(observation.model_dump(mode="json"))
    identity = _manifest([case])[0]
    recorded = next((entry for entry in run.case_manifest if entry["case_id"] == case.case_id), None)
    if (recorded != identity or observation.case_id != case.case_id
            or observation.task_type != case.task_type
            or observation.request_digest != identity["request_digest"]):
        raise EvaluationPlanConflictError("Observation differs from its committed case identity")
    policy = ExecutionPolicy.model_validate(run.execution_policy)
    if observation.attempt_count > policy.max_retries + 1:
        raise EvaluationStoreError("Observation exceeds the committed retry limit")
    metrics = {"structured_output_valid": False, "identity_valid": False,
               "expected_label_matches": {}, "required_content_matches": {}, "forbidden_content_matches": []}
    output = None
    if observation.outcome == EvaluationOutcome.SUCCESS:
        if observation.structured_output is None or observation.attempt_count < 1 or observation.error_code is not None:
            raise EvaluationStoreError("Successful observations require a validated invocation")
        result = validate_output(observation.structured_output, case.task_type)
        provenance = result.provenance
        if (provenance.provider != run.provider or provenance.model_id != run.model_id
                or provenance.prompt_version != run.prompt_versions[case.task_type.value]
                or provenance.schema_version != run.schema_version
                or provenance.source != ("synthetic" if run.synthetic else "model")):
            raise EvaluationPlanConflictError("Observation provenance differs from the evaluation candidate")
        output = result.model_dump(mode="json")
        metrics = automatic_checks(case, output)
    else:
        if observation.structured_output is not None or observation.error_code != observation.outcome.value:
            raise EvaluationStoreError("Failure observations require null output and a standardized error code")
        if observation.outcome == EvaluationOutcome.INPUT_TOO_LARGE:
            if observation.attempt_count != 0:
                raise EvaluationStoreError("Input rejection cannot claim provider invocations")
        elif observation.attempt_count < 1:
            raise EvaluationStoreError("Provider outcomes require a recorded invocation")
        if observation.outcome == EvaluationOutcome.IDENTITY_MISMATCH:
            metrics["structured_output_valid"] = True
    if observation.automatic_metrics != metrics:
        raise EvaluationPlanConflictError("Automatic metrics differ from the validated observation")
    accounting_values = (observation.input_tokens, observation.output_tokens,
                         observation.accounting_version, observation.accounting_basis)
    if any(value is not None for value in accounting_values):
        if any(value is None for value in accounting_values) or observation.attempt_count == 0:
            raise EvaluationStoreError("Token accounting must be complete and tied to an invocation")
        InvocationAccounting.model_validate({"input_tokens": observation.input_tokens,
            "output_tokens": observation.output_tokens, "accounting_version": observation.accounting_version,
            "accounting_basis": observation.accounting_basis})
    return {
        "case_id": case.case_id, "case_digest": identity["case_digest"],
        "request_digest": identity["request_digest"], "task_type": case.task_type.value,
        "outcome": observation.outcome.value, "structured_output": output, "automatic_metrics": metrics,
        "latency_ms": observation.latency_ms, "attempt_count": observation.attempt_count,
        "input_tokens": observation.input_tokens, "output_tokens": observation.output_tokens,
        "accounting_version": observation.accounting_version, "accounting_basis": observation.accounting_basis,
        "error_code": observation.error_code,
    }


def record_result(db: Session, run_id: UUID | str, case: BenchmarkCase,
                  observation: EvaluationObservation) -> EvaluationResult:
    """Atomically save one case; identical retries reuse only the original observation."""

    _clean_session(db)
    try:
        run = get_run(db, run_id)
        values = _observation_values(run, case, observation)
        existing = db.scalar(select(EvaluationResult).where(
            EvaluationResult.run_id == run.id, EvaluationResult.case_id == case.case_id,
        ))
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in values.items()):
                raise EvaluationPlanConflictError("A committed case observation cannot be replaced")
            return existing
        if run.status != "RUNNING":
            raise EvaluationPlanConflictError("Completed runs cannot accept new case observations")
        result = EvaluationResult(run_id=run.id, created_at=datetime.now(UTC), **values)
        db.add(result)
        db.commit()
        db.refresh(result)
        return result
    except EvaluationStoreError:
        db.rollback()
        raise
    except (ValueError, TypeError, ValidationError):
        db.rollback()
        raise EvaluationStoreError("Invalid evaluation observation") from None
    except SQLAlchemyError:
        db.rollback()
        raise EvaluationStoreError("Evaluation observation could not be persisted") from None


def finish_run(db: Session, run_id: UUID | str) -> EvaluationRun:
    """Close only a fully recorded plan; repeated finish does not revise history."""

    _clean_session(db)
    try:
        run = get_run(db, run_id)
        results = results_for_run(db, run.id)
        if {result.case_id for result in results} != set(run.selected_case_ids):
            raise EvaluationPlanConflictError("All selected cases must be recorded before completion")
        for result in results:
            expected = next(entry for entry in run.case_manifest if entry["case_id"] == result.case_id)
            if (result.case_digest != expected["case_digest"]
                    or result.request_digest != expected["request_digest"]
                    or result.task_type != expected["task_type"]):
                raise EvaluationPlanConflictError("Stored observations differ from the committed case plan")
        if run.status == "COMPLETED":
            return run
        run.status = "COMPLETED"
        run.completed_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        return run
    except EvaluationStoreError:
        db.rollback()
        raise
    except (ValueError, TypeError):
        db.rollback()
        raise EvaluationStoreError("Evaluation run could not be completed") from None
    except SQLAlchemyError:
        db.rollback()
        raise EvaluationStoreError("Evaluation completion could not be persisted") from None


def record_review(db: Session, payload: HumanReviewCreate,
                  loaded_suite: LoadedSuite) -> EvaluationReview:
    """Append a rubric-validated pseudonymous review; never replace prior ratings."""

    _clean_session(db)
    try:
        _validate_loaded(loaded_suite)
        payload = HumanReviewCreate.model_validate(payload.model_dump(mode="json"))
        result = db.get(EvaluationResult, payload.result_id)
        if result is None:
            raise EvaluationStoreError("Evaluation result not found")
        run = get_run(db, result.run_id)
        case = loaded_suite.case_by_id.get(result.case_id)
        if (case is None or payload.rubric_version != run.rubric_version
                or run.rubric_digest != loaded_suite.rubric_digest
                or run.suite_digest != loaded_suite.digest
                or run.schema_digest != loaded_suite.schema_digest
                or result.case_digest != canonical_hash(case)):
            raise EvaluationPlanConflictError("Review definitions differ from the recorded observation")
        loaded_suite.rubric.validate_review_scores(payload.scores, TaskType(result.task_type))
        review = EvaluationReview(result_id=result.id, reviewer_label=payload.reviewer_label,
            rubric_version=payload.rubric_version, scores=dict(payload.scores), notes=payload.notes,
            reviewed_at=datetime.now(UTC))
        db.add(review)
        db.commit()
        db.refresh(review)
        return review
    except EvaluationStoreError:
        db.rollback()
        raise
    except (ValueError, TypeError, ValidationError):
        db.rollback()
        raise EvaluationStoreError("Invalid evaluation review") from None
    except SQLAlchemyError:
        db.rollback()
        raise EvaluationStoreError("Evaluation review could not be persisted") from None
