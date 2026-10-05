"""Offline experiment CLI, review and comparison acceptance without external calls."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.models.evaluation import EvaluationResult, EvaluationReview, EvaluationRun
from app.schemas.benchmark import ExecutionPolicy, HumanReviewCreate, PricingSnapshot
from app.services.benchmark_suite import load_suite
from app.services.evaluation_candidates import SYNTHETIC_CANDIDATES, build_synthetic_provider
from app.services.evaluation_provider_factory import build_provider, parse_candidate
from app.services.evaluation_report import calculate_cost, compare_group, export_group, EvaluationReportError
from app.services.evaluation_runner import invoke_case
from app.services.evaluation_store import start_run, record_result, finish_run, record_review
from scripts import run_tutor_benchmark as cli
from adaptive_fixtures import create_adaptive_database


SUITE = Path(__file__).resolve().parents[1] / "benchmarks/tutor/v1/suite.json"
REVISION = "a" * 40


@pytest.fixture
def loaded():
    return load_suite(SUITE)


@pytest.fixture
def database(monkeypatch):
    database, engine = create_adaptive_database(monkeypatch)
    monkeypatch.setattr(cli, "create_evaluation_session_factory", lambda: database.factory)
    monkeypatch.setattr(cli, "_git_revision", lambda: REVISION)
    try:
        yield database.factory
    finally:
        engine.dispose()


def snapshot(db):
    return {table.name: list(db.execute(select(table).order_by(*table.primary_key.columns)).mappings())
            for table in Base.metadata.sorted_tables if not table.name.startswith("evaluation_")}


def run_candidate(db, loaded, candidate, group, *, count=25, policy=None, pricing=None):
    policy = policy or ExecutionPolicy()
    cases = loaded.suite.cases[:count]
    run = start_run(db, candidate, loaded, policy, cases, group, pricing, REVISION)
    for case in cases:
        observation = asyncio.run(invoke_case(build_synthetic_provider(candidate, case), case, candidate, policy))
        record_result(db, run.id, case, observation)
    return finish_run(db, run.id)


def review_scores(loaded, task, score):
    applicable = loaded.rubric.applicable_dimensions(task)
    return {dimension.name: score if dimension.name in applicable else None for dimension in loaded.rubric.dimensions}


def test_dry_run_requires_neither_database_nor_provider(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Dry-run must not create a database or provider")
    monkeypatch.setattr(cli, "create_evaluation_session_factory", forbidden)
    monkeypatch.setattr(cli, "build_provider", forbidden)
    assert cli.main(["run", "--dry-run", "--suite", str(SUITE)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["maximum_invocations"] == 50
    assert len(plan["selected_cases"]) == 25
    assert all(candidate["synthetic"] for candidate in plan["candidates"])


def test_cost_notice_is_explicit_and_does_not_require_a_live_invocation(capsys):
    cli._warn_live_cost(50)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "50 external invocations" in captured.err
    assert "total cost is unknown" in captured.err


@pytest.mark.parametrize("options", [
    ["--timeout-seconds", "0"], ["--timeout-seconds", "nan"], ["--max-calls", "49"],
    ["--max-retries", "4"], ["--suite-version", "incorrect"], ["--case", "missing"],
    ["--candidate", "synthetic-good", "--candidate", "synthetic-good"],
    ["--candidate", "gemini:fixture-model"],
])
def test_invalid_or_unauthorized_plans_fail_before_credentials_or_db(monkeypatch, capsys, options):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid plan reached provider/database construction")
    monkeypatch.setattr(cli, "create_evaluation_session_factory", forbidden)
    monkeypatch.setattr(cli, "build_provider", forbidden)
    assert cli.main(["run", "--dry-run", *options]) == 1
    assert "failed safely" in capsys.readouterr().out


def test_external_factory_requires_opt_in_before_importing_adapter(loaded):
    candidate = parse_candidate("gemini:fixture-model")
    with pytest.raises(ValueError, match="not authorized"):
        build_provider(candidate, loaded.suite.cases[0], ExecutionPolicy())


def test_provider_qualified_model_ids_are_preserved_and_collision_safe():
    first = parse_candidate("gemini:models/example:version")
    second = parse_candidate("gemini:models-example-version")
    assert first.model_id == "models/example:version"
    assert first.candidate_id != second.candidate_id


def test_offline_cli_persists_two_complete_runs_without_touching_learners(database, capsys, monkeypatch):
    original_builder = cli.build_provider
    def synthetic_only(candidate, *args, **kwargs):
        assert candidate.synthetic and not kwargs.get("live_authorized")
        return original_builder(candidate, *args, **kwargs)
    monkeypatch.setattr(cli, "build_provider", synthetic_only)
    with database() as db:
        before = snapshot(db)
    assert cli.main(["run", "--suite", str(SUITE), "--suite-version", "v1"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["comparison_compatible"] is True
    assert summary["selection_readiness"]["production_model_selected"] is False
    assert summary["selection_readiness"]["eligible_for_human_selection_review"] is False
    assert summary["overall_score"] is None
    good, bad = sorted(summary["candidates"], key=lambda row: row["candidate_id"], reverse=True)
    assert good["candidate_id"] == "synthetic-good"
    assert good["automatic"]["gold_label_match_rate"] == 1
    assert bad["automatic"]["gold_label_match_rate"] == 0
    for candidate in (good, bad):
        assert candidate["automatic"]["cases_attempted"] == 25
        assert candidate["automatic"]["latency_p95_ms"] is not None
        assert candidate["accounting"]["estimated_total_cost"] is None
        assert candidate["accounting"]["known_input_tokens"] is None
        assert candidate["human"]["technical_correctness"]["status"] == "UNREVIEWED"
    with database() as db:
        assert snapshot(db) == before
        assert db.scalar(select(func.count()).select_from(EvaluationRun)) == 2
        assert db.scalar(select(func.count()).select_from(EvaluationResult)) == 50
        assert db.scalar(select(func.count()).select_from(EvaluationReview)) == 0


def test_review_import_export_and_latest_reviewer_rating(database, loaded, tmp_path, capsys):
    group = uuid4()
    with database() as db:
        run = run_candidate(db, loaded, SYNTHETIC_CANDIDATES[0], group, count=1)
        result = db.scalar(select(EvaluationResult).where(EvaluationResult.run_id == run.id))
        payload = HumanReviewCreate(result_id=result.id, reviewer_label="synthetic-fixture-reviewer",
                                    rubric_version=loaded.rubric.rubric_version,
                                    scores=review_scores(loaded, result.task_type, 1))
        record_review(db, payload, loaded)
        review = payload.model_copy(update={"scores": review_scores(loaded, result.task_type, 4)})
        path = tmp_path / "review.json"
        path.write_text(review.model_dump_json(), encoding="utf-8")
    assert cli.main(["review", "--input", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == "HUMAN"
    assert cli.main(["compare", "--group-id", str(group)]) == 0
    summary = json.loads(capsys.readouterr().out)
    technical = summary["candidates"][0]["human"]["technical_correctness"]
    assert technical["mean_score"] == 4 and technical["reviewer_ratings"] == 1
    assert technical["status"] == "REVIEWED"
    assert summary["candidates"][0]["human"]["diagnosis_accuracy"]["mean_score"] is None
    assert summary["candidates"][0]["automatic"]["latency_p95_ms"] is None
    output = tmp_path / "export.json"
    assert cli.main(["export", "--group-id", str(group), "--output", str(output)]) == 0
    exported = json.loads(output.read_text(encoding="utf-8"))
    assert len(exported["reviews"]) == 2
    assert len(exported["cases"]) == 1
    assert exported["results"][0]["output"]["provenance"]["source"] == "synthetic"
    assert cli.main(["export", "--group-id", str(group), "--output", str(output)]) == 1


def test_comparison_marks_changed_controls_incomparable(database, loaded):
    group = uuid4()
    with database() as db:
        run_candidate(db, loaded, SYNTHETIC_CANDIDATES[0], group, count=1)
        run_candidate(db, loaded, SYNTHETIC_CANDIDATES[1], group, count=1, policy=ExecutionPolicy(max_retries=1))
        report = compare_group(db, group, loaded)
        assert report["comparison_compatible"] is False
        assert "INCOMPARABLE_PROTOCOLS" in report["selection_readiness"]["blocking_reasons"]


def test_cost_requires_complete_compatible_reported_tokens():
    pricing = PricingSnapshot(version="synthetic-price-v1", effective_at=datetime(2026, 10, 3, tzinfo=UTC),
                              provider="synthetic", model_id="synthetic-good-v1", accounting_basis="tokens-v1",
                              input_usd_per_million="1.25", output_usd_per_million="2.50", synthetic=True)
    result = EvaluationResult(accounting_version="usage-v1", accounting_basis="tokens-v1", input_tokens=100, output_tokens=20)
    assert calculate_cost(result, pricing) == Decimal("0.000175")
    assert calculate_cost(result, None) is None
    result.output_tokens = None
    assert calculate_cost(result, pricing) is None
    result.output_tokens = 20
    result.accounting_basis = "incompatible-v1"
    assert calculate_cost(result, pricing) is None


def test_completed_cli_resume_skips_every_committed_invocation(database, capsys, monkeypatch):
    assert cli.main(["run", "--candidate", "synthetic-good", "--case", "hint-level-1"]) == 0
    capsys.readouterr()
    with database() as db:
        run_id = db.scalar(select(EvaluationRun.id))
    def forbidden(*args, **kwargs):
        raise AssertionError("Completed resume must not call the provider")
    monkeypatch.setattr(cli, "build_provider", forbidden)
    assert cli.main(["run", "--candidate", "synthetic-good", "--case", "hint-level-1", "--resume-run", str(run_id)]) == 0
    with database() as db:
        assert db.scalar(select(func.count()).select_from(EvaluationResult)) == 1


def test_mutated_definition_cannot_be_used_for_report(database, loaded):
    with database() as db:
        group = uuid4()
        run_candidate(db, loaded, SYNTHETIC_CANDIDATES[0], group, count=1)
        loaded.suite.cases[0].request.context.skill_names.append("Changed benchmark")
        with pytest.raises(EvaluationReportError, match="hash"):
            compare_group(db, group, loaded)


def test_safe_cli_failure_does_not_print_imported_sensitive_data(database, tmp_path, capsys):
    path = tmp_path / "review.json"
    path.write_text(json.dumps({"notes": "API_KEY=synthetic-not-a-real-credential"}), encoding="utf-8")
    assert cli.main(["review", "--input", str(path)]) == 1
    assert "synthetic-not-a-real-credential" not in capsys.readouterr().out


def test_evaluation_transport_overrides_disable_hidden_sdk_retries_without_changing_tutor_defaults():
    from app.services.gemini_tutor_provider import GeminiTutorProvider
    from app.schemas.tutor import HintTask
    from test_gemini_tutor_provider import FakeClient, context, settings
    captured = []
    clients = []
    def fake_client(**kwargs):
        captured.append(kwargs["http_options"])
        client = FakeClient({"hint_text": "Consider the invariant."})
        clients.append(client)
        return client
    normal = GeminiTutorProvider(settings(), client_factory=fake_client)
    controlled = GeminiTutorProvider(settings(), client_factory=fake_client, sdk_retry_attempts=1, temperature=0)
    request = HintTask(context=context(), level=1)
    asyncio.run(normal.generate_hint(request))
    asyncio.run(controlled.generate_hint(request))
    assert captured[0].retry_options is None
    assert captured[1].retry_options.attempts == 1
    assert clients[0].aio.models.calls[0]["config"].temperature is None
    assert clients[1].aio.models.calls[0]["config"].temperature == 0


def test_missing_human_review_prevents_real_candidate_selection_readiness(database, loaded):
    from app.schemas.benchmark import EvaluationCandidate
    from evaluation_fixtures import ScriptedProvider, valid_result
    group = uuid4()
    case = loaded.suite.cases[0]
    with database() as db:
        for model_id in ("mock-real-a", "mock-real-b"):
            candidate = EvaluationCandidate(candidate_id=model_id, provider="fixture", model_id=model_id, synthetic=False)
            run = start_run(db, candidate, loaded, ExecutionPolicy(), [case], group, None, REVISION)
            output = valid_result("hint", provider="fixture", model_id=model_id)
            output.provenance.source = "model"
            output.hint_text = "; ".join(case.required_content)
            observation = asyncio.run(invoke_case(ScriptedProvider([output]), case, candidate, ExecutionPolicy()))
            record_result(db, run.id, case, observation)
            finish_run(db, run.id)
        report = compare_group(db, group, loaded)
        assert report["comparison_compatible"]
        assert "REQUIRED_HUMAN_REVIEW_MISSING" in report["selection_readiness"]["blocking_reasons"]
        assert report["selection_readiness"]["unknown_cost_acknowledgment_required"]
        assert not report["selection_readiness"]["eligible_for_human_selection_review"]
        assert not report["selection_readiness"]["production_model_selected"]


def test_missing_values_and_mixed_token_bases_are_not_zero_filled_or_aggregated(database, loaded):
    from app.schemas.benchmark import InvocationAccounting
    from evaluation_fixtures import ScriptedProvider, valid_result
    group = uuid4()
    candidate = SYNTHETIC_CANDIDATES[0]
    cases = loaded.suite.cases[:2]
    with database() as db:
        run = start_run(db, candidate, loaded, ExecutionPolicy(), cases, group, None, REVISION)
        for index, case in enumerate(cases):
            output = valid_result("hint", provider=candidate.provider, model_id=candidate.model_id)
            accounting = InvocationAccounting(input_tokens=20, output_tokens=5, accounting_version="usage-v1",
                                              accounting_basis=f"different-token-basis-{index}")
            observation = asyncio.run(invoke_case(ScriptedProvider([output], accounting=[accounting]), case, candidate, ExecutionPolicy()))
            record_result(db, run.id, case, observation)
        finish_run(db, run.id)
        report = compare_group(db, group, loaded)["candidates"][0]
        assert report["accounting"]["token_covered_results"] == 2
        assert report["accounting"]["known_input_tokens"] is None
        assert report["accounting"]["known_output_tokens"] is None
        assert len(report["accounting"]["accounting_bases"]) == 2
        assert report["accounting"]["estimated_total_cost"] is None
        assert report["by_task"]["diagnosis"]["completion_rate"] is None
