"""Per-dimension experiment reporting; never ranks or selects production models."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from math import ceil
import re
from statistics import mean, median
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evaluation import EvaluationResult, EvaluationReview, EvaluationRun
from app.schemas.benchmark import PricingSnapshot, TaskType
from app.services.benchmark_suite import LoadedSuite, canonical_hash, request_digest, selected_case_digest


class EvaluationReportError(ValueError):
    """A report cannot safely interpret the supplied experiment definitions."""


def calculate_cost(result: EvaluationResult, pricing: PricingSnapshot | None) -> Decimal | None:
    """Derive cost only from complete, explicitly compatible reported counters."""

    if (pricing is None or not result.accounting_version
            or result.accounting_basis != pricing.accounting_basis
            or result.input_tokens is None or result.output_tokens is None):
        return None
    if any(type(value) is not int or value < 0 for value in (result.input_tokens, result.output_tokens)):
        return None
    return (Decimal(result.input_tokens) * pricing.input_usd_per_million
            + Decimal(result.output_tokens) * pricing.output_usd_per_million) / Decimal(1_000_000)


def _load_group(db: Session, group_id: UUID | str, loaded: LoadedSuite):
    if loaded.digest != canonical_hash(loaded.suite) or loaded.rubric_digest != canonical_hash(loaded.rubric):
        raise EvaluationReportError("Loaded definitions differ from their content hashes")
    try:
        identity = UUID(str(group_id))
    except ValueError:
        raise EvaluationReportError("Invalid evaluation group identity") from None
    runs = list(db.scalars(select(EvaluationRun).where(
        EvaluationRun.group_id == identity,
    ).order_by(EvaluationRun.candidate_id, EvaluationRun.id)))
    if not runs:
        raise EvaluationReportError("Evaluation group not found")
    for run in runs:
        if (run.suite_digest != loaded.digest or run.rubric_digest != loaded.rubric_digest
                or run.schema_digest != loaded.schema_digest
                or run.rubric_version != loaded.rubric.rubric_version):
            raise EvaluationReportError("Report definitions differ from the recorded experiment")
        if not run.selected_case_ids or any(case_id not in loaded.case_by_id for case_id in run.selected_case_ids):
            raise EvaluationReportError("Recorded case selection is unavailable")
        if run.selected_cases_digest != selected_case_digest([loaded.case_by_id[key] for key in run.selected_case_ids]):
            raise EvaluationReportError("Recorded case selection content has changed")
    results = list(db.scalars(select(EvaluationResult).where(
        EvaluationResult.run_id.in_([run.id for run in runs]),
    ).order_by(EvaluationResult.id)))
    run_by_id = {run.id: run for run in runs}
    for result in results:
        case = loaded.case_by_id.get(result.case_id)
        if (case is None or result.case_digest != canonical_hash(case.model_dump(mode="json"))
                or result.case_id not in run_by_id[result.run_id].selected_case_ids
                or result.request_digest != request_digest(case) or result.task_type != case.task_type.value):
            raise EvaluationReportError("Recorded benchmark case content has changed")
    reviews = list(db.scalars(select(EvaluationReview).where(
        EvaluationReview.result_id.in_([result.id for result in results]),
    ).order_by(EvaluationReview.id)))
    return runs, results, reviews


def _automatic(results: list[EvaluationResult], expected: int) -> dict:
    attempted = len(results)
    successful = sum(result.outcome == "SUCCESS" for result in results)
    valid = sum(result.automatic_metrics.get("structured_output_valid") is True for result in results)
    label_checks = [value for result in results
                    for value in result.automatic_metrics.get("expected_label_matches", {}).values()]
    required_checks = [value for result in results
                       for value in result.automatic_metrics.get("required_content_matches", {}).values()]
    forbidden = sum(bool(result.automatic_metrics.get("forbidden_content_matches")) for result in results)
    latencies = [result.latency_ms for result in results if result.attempt_count > 0]
    ordered = sorted(latencies)
    return {
        "cases_expected": expected, "cases_attempted": attempted, "cases_successful": successful,
        "completion_rate": successful / expected if expected else None,
        "structured_output_valid_count": valid,
        "schema_reliability": valid / attempted if attempted else None,
        "gold_label_checks": len(label_checks), "gold_label_matches": sum(value is True for value in label_checks),
        "gold_label_match_rate": sum(value is True for value in label_checks) / len(label_checks) if label_checks else None,
        "required_literal_checks": len(required_checks),
        "required_literal_matches": sum(value is True for value in required_checks),
        "forbidden_literal_case_count": forbidden,
        "literal_checks_are_limited_indicators": True,
        "errors": dict(sorted(Counter(result.outcome for result in results if result.outcome != "SUCCESS").items())),
        "provider_invocation_count": sum(result.attempt_count for result in results),
        "latency_observation_count": len(latencies),
        "latency_median_ms": median(latencies) if latencies else None,
        "latency_p95_ms": ordered[ceil(.95 * len(ordered)) - 1] if len(ordered) >= 20 else None,
        "latency_quantile_method": "nearest_rank; p95 requires at least 20 observations",
        "latency_includes_runner_retries": True,
    }


def _human(results, reviews, selected_ids, loaded: LoadedSuite) -> dict:
    result_by_id = {result.id: result for result in results}
    latest = {}
    for review in reviews:
        if review.result_id in result_by_id and review.rubric_version == loaded.rubric.rubric_version:
            latest[(review.result_id, review.reviewer_label)] = review
    dimensions = {}
    for dimension in loaded.rubric.dimensions:
        applicable = [case_id for case_id in selected_ids
                      if dimension.name in loaded.rubric.applicable_dimensions(loaded.case_by_id[case_id].task_type)]
        by_case = defaultdict(list)
        for review in latest.values():
            case_id = result_by_id[review.result_id].case_id
            score = review.scores.get(dimension.name)
            if case_id in applicable and type(score) is int:
                by_case[case_id].append(score)
        case_means = [mean(scores) for scores in by_case.values()]
        dimensions[dimension.name] = {
            "mean_score": mean(case_means) if case_means else None,
            "scale": "human rubric 0–4; not objective correctness",
            "applicable_cases": len(applicable), "reviewed_cases": len(by_case),
            "reviewer_ratings": sum(len(scores) for scores in by_case.values()),
            "status": "NOT_APPLICABLE" if not applicable else (
                "UNREVIEWED" if not by_case else "REVIEWED" if len(by_case) == len(applicable) else "PARTIALLY_REVIEWED"),
        }
    return dimensions


def compare_group(db: Session, group_id: UUID | str, loaded_suite: LoadedSuite) -> dict:
    """Report coverage and measurements without inventing scores or a winner."""

    runs, all_results, reviews = _load_group(db, group_id, loaded_suite)
    compatible = len({run.protocol_fingerprint for run in runs}) == 1
    candidates = []
    for run in runs:
        results = [result for result in all_results if result.run_id == run.id]
        pricing = PricingSnapshot.model_validate(run.pricing_snapshot) if run.pricing_snapshot else None
        if pricing and (pricing.provider != run.provider or pricing.model_id != run.model_id
                        or pricing.synthetic != run.synthetic):
            raise EvaluationReportError("Pricing snapshot does not identify this candidate")
        costs = [calculate_cost(result, pricing) for result in results]
        known = [cost for cost in costs if cost is not None]
        accounting = [result for result in results if result.input_tokens is not None and result.output_tokens is not None]
        bases = {(result.accounting_basis, result.accounting_version) for result in accounting}
        human = _human(results, reviews, run.selected_case_ids, loaded_suite)
        auto = _automatic(results, len(run.selected_case_ids))
        candidates.append({
            "run_id": str(run.id), "candidate_id": run.candidate_id, "provider": run.provider,
            "model_id": run.model_id, "synthetic": run.synthetic, "run_status": run.status,
            "automatic": auto,
            "by_task": {task.value: _automatic(
                [result for result in results if result.task_type == task.value],
                sum(loaded_suite.case_by_id[case_id].task_type == task for case_id in run.selected_case_ids),
            ) for task in TaskType},
            "human": human,
            "accounting": {
                "token_covered_results": len(accounting),
                "known_input_tokens": sum(result.input_tokens for result in accounting) if accounting and len(bases) == 1 else None,
                "known_output_tokens": sum(result.output_tokens for result in accounting) if accounting and len(bases) == 1 else None,
                "accounting_bases": [{"basis": basis, "version": version} for basis, version in sorted(bases)],
                "cost_covered_results": len(known), "currency": "USD" if pricing else None,
                "known_cost_subtotal": str(sum(known, Decimal(0))) if known else None,
                "estimated_total_cost": str(sum(known, Decimal(0))) if known and len(known) == len(results) else None,
                "status": "COMPLETE" if results and len(known) == len(results) else "UNAVAILABLE_OR_PARTIAL",
                "pricing_version": pricing.version if pricing else None,
            },
        })
    real = [candidate for candidate in candidates if not candidate["synthetic"]]
    blockers = []
    if not compatible:
        blockers.append("INCOMPARABLE_PROTOCOLS")
    if len({(candidate["provider"], candidate["model_id"]) for candidate in real}) < 2:
        blockers.append("TWO_DISTINCT_REAL_CANDIDATES_REQUIRED")
    if len(real) != len(candidates):
        blockers.append("SYNTHETIC_RESULTS_ARE_NOT_MODEL_EVIDENCE")
    for candidate in real:
        run = next(run for run in runs if str(run.id) == candidate["run_id"])
        if re.fullmatch(r"[a-f0-9]{40}", run.code_revision) is None:
            blockers.append("IDENTIFIABLE_CLEAN_CODE_REVISION_REQUIRED")
        auto = candidate["automatic"]
        if candidate["run_status"] != "COMPLETED" or auto["cases_attempted"] != auto["cases_expected"]:
            blockers.append("INCOMPLETE_REAL_RUN")
        if (auto["errors"] or auto["forbidden_literal_case_count"]
                or auto["required_literal_matches"] != auto["required_literal_checks"]
                or auto["gold_label_matches"] != auto["gold_label_checks"]):
            blockers.append("AUTOMATIC_FAILURE_REQUIRES_REVIEW")
        if any(value["status"] not in {"REVIEWED", "NOT_APPLICABLE"} for value in candidate["human"].values()):
            blockers.append("REQUIRED_HUMAN_REVIEW_MISSING")
    unknown_cost = any(candidate["accounting"]["status"] != "COMPLETE" for candidate in real)
    return {
        "group_id": str(runs[0].group_id), "suite_id": loaded_suite.suite.suite_id,
        "suite_version": loaded_suite.suite.version, "suite_digest": loaded_suite.digest,
        "rubric_version": loaded_suite.rubric.rubric_version, "comparison_compatible": compatible,
        "candidates": candidates,
        "selection_readiness": {
            "eligible_for_human_selection_review": not blockers,
            "blocking_reasons": sorted(set(blockers)),
            "unknown_cost_acknowledgment_required": unknown_cost,
            "production_model_selected": False,
        },
        "system_outcomes": {name: "NOT_MEASURED_BY_TUTOR_BENCHMARK" for name in (
            "hint_dependency_behavior", "learner_state_update_quality", "recommendation_quality",
            "retention", "personalization_gain")},
        "overall_score": None,
    }


def export_group(db: Session, group_id: UUID | str, loaded_suite: LoadedSuite) -> dict:
    """Export synthetic case context and validated output for explicit human review."""

    runs, results, reviews = _load_group(db, group_id, loaded_suite)
    return {
        "comparison": compare_group(db, group_id, loaded_suite),
        "rubric": loaded_suite.rubric.model_dump(mode="json"),
        "runs": [{"run_id": str(run.id), "candidate_id": run.candidate_id, "synthetic": run.synthetic,
                  "code_revision": run.code_revision, "protocol_fingerprint": run.protocol_fingerprint,
                  "execution_policy": run.execution_policy} for run in runs],
        "cases": [loaded_suite.case_by_id[case_id].model_dump(mode="json")
                  for case_id in dict.fromkeys(case_id for run in runs for case_id in run.selected_case_ids)],
        "results": [{"result_id": result.id, "run_id": str(result.run_id), "case_id": result.case_id,
                     "outcome": result.outcome, "output": result.structured_output,
                     "automatic_metrics": result.automatic_metrics,
                     "review_template": {"result_id": result.id, "reviewer_label": "reviewer-1",
                                         "rubric_version": loaded_suite.rubric.rubric_version,
                                         "scores": {dimension.name: None for dimension in loaded_suite.rubric.dimensions},
                                         "notes": "Fill every applicable rubric score before import."}}
                    for result in results],
        "reviews": [{"result_id": review.result_id, "reviewer_label": review.reviewer_label,
                     "rubric_version": review.rubric_version, "scores": review.scores,
                     "notes": review.notes, "reviewed_at": review.reviewed_at.isoformat()} for review in reviews],
    }
