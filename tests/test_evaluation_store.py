"""Independent evaluation persistence, replay plan and learner-integrity tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import app.models
from app.db.base import Base
from app.models.evaluation import EvaluationResult, EvaluationReview, EvaluationRun
from app.schemas.benchmark import EvaluationCandidate, ExecutionPolicy, HumanReviewCreate
from app.services.benchmark_suite import load_suite
from app.services.evaluation_runner import invoke_case
from app.services.evaluation_store import (
    EvaluationPlanConflictError, EvaluationStoreError, finish_run, get_run,
    record_result, record_review, results_for_run, start_run,
)
from app.services.recommendation_service import get_next_recommendation
from adaptive_fixtures import NOW, create_adaptive_database
from evaluation_fixtures import ScriptedProvider


SUITE_PATH = Path(__file__).resolve().parents[1] / "benchmarks/tutor/v1/suite.json"
REVISION = "a" * 40


@pytest.fixture
def loaded():
    return load_suite(SUITE_PATH)


@pytest.fixture
def candidate():
    return EvaluationCandidate(candidate_id="fixture", provider="fixture", model_id="fixture-v1", synthetic=True)


@pytest.fixture
def evaluation_db(monkeypatch):
    database, engine = create_adaptive_database(monkeypatch)
    database.solve(1, reasoning=True)
    with database.factory() as db:
        get_next_recommendation(db, now=NOW)
    try:
        yield database.factory
    finally:
        engine.dispose()


def learner_snapshot(db):
    return {table.name: [dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
            for table in Base.metadata.sorted_tables if not table.name.startswith("evaluation_")}


def create_run(db, loaded, candidate, *, cases=None, group_id=None, **changes):
    parameters = {"candidate": candidate, "loaded_suite": loaded, "policy": ExecutionPolicy(),
                  "selected_cases": list(cases if cases is not None else loaded.suite.cases[:1]),
                  "group_id": group_id or uuid4(), "pricing": None, "code_revision": REVISION}
    parameters.update(changes)
    return start_run(db, **parameters)


def observation(case, candidate):
    return asyncio.run(invoke_case(ScriptedProvider(), case, candidate, ExecutionPolicy()))


def review_payload(result, loaded, *, score=3, notes="Independent fixture review."):
    applicable = set(loaded.rubric.applicable_dimensions(result.task_type))
    return HumanReviewCreate(result_id=result.id, reviewer_label="fixture-reviewer",
                             rubric_version=loaded.rubric.rubric_version,
                             scores={dimension.name: score if dimension.name in applicable else None
                                     for dimension in loaded.rubric.dimensions}, notes=notes)


def test_evaluation_tables_have_only_evaluation_foreign_keys():
    assert {table.name for table in Base.metadata.tables.values() if table.name.startswith("evaluation_")} == {
        "evaluation_runs", "evaluation_results", "evaluation_reviews",
    }
    assert not EvaluationRun.__table__.foreign_keys
    assert {key.column.table.name for key in EvaluationResult.__table__.foreign_keys} == {"evaluation_runs"}
    assert {key.column.table.name for key in EvaluationReview.__table__.foreign_keys} == {"evaluation_results"}


def test_committed_run_result_review_preserve_every_learner_table(evaluation_db, loaded, candidate):
    with evaluation_db() as db:
        before = learner_snapshot(db)
        run = create_run(db, loaded, candidate)
        assert run.status == "RUNNING" and run.synthetic is True
        result = record_result(db, run.id, loaded.suite.cases[0], observation(loaded.suite.cases[0], candidate))
        review = record_review(db, review_payload(result, loaded), loaded)
        finish_run(db, run.id)
        assert get_run(db, run.id).status == "COMPLETED"
        assert review.id and result.id
        assert learner_snapshot(db) == before
    with evaluation_db() as db:
        assert db.scalar(select(func.count()).select_from(EvaluationRun)) == 1
        assert db.scalar(select(func.count()).select_from(EvaluationResult)) == 1
        assert db.scalar(select(func.count()).select_from(EvaluationReview)) == 1


def test_recorded_result_does_not_duplicate_benchmark_input_bodies(evaluation_db, loaded, candidate):
    case = loaded.suite.cases[0]
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate)
        result = record_result(db, run.id, case, observation(case, candidate))
        assert result.case_id == case.case_id
        assert len(result.case_digest) == len(result.request_digest) == 64
        assert not {"context", "source_code", "reasoning_text", "request"} & set(result.__table__.columns.keys())
        assert result.input_tokens is None and result.output_tokens is None


def test_duplicate_case_identity_cannot_overwrite_or_duplicate(evaluation_db, loaded, candidate):
    case = loaded.suite.cases[0]
    value = observation(case, candidate)
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate)
        first = record_result(db, run.id, case, value)
        try:
            duplicate = record_result(db, run.id, case, value)
        except EvaluationStoreError:
            pass
        else:
            assert duplicate.id == first.id
        assert len(results_for_run(db, run.id)) == 1
        changed = value.model_copy(update={"latency_ms": value.latency_ms + 1})
        with pytest.raises(EvaluationStoreError):
            record_result(db, run.id, case, changed)
        assert len(results_for_run(db, run.id)) == 1


def test_finish_refuses_incomplete_run_and_resume_preserves_committed_results(evaluation_db, loaded, candidate):
    cases = list(loaded.suite.cases[:2])
    group_id = uuid4()
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate, cases=cases, group_id=group_id)
        first = record_result(db, run.id, cases[0], observation(cases[0], candidate))
        with pytest.raises(EvaluationStoreError):
            finish_run(db, run.id)
        resumed = create_run(db, loaded, candidate, cases=cases, group_id=group_id, run_id=run.id)
        assert resumed.id == run.id and len(results_for_run(db, run.id)) == 1
        assert results_for_run(db, run.id)[0].id == first.id
        record_result(db, run.id, cases[1], observation(cases[1], candidate))
        finish_run(db, run.id)
        assert get_run(db, run.id).completed_at is not None


@pytest.mark.parametrize("change", ["policy", "candidate", "selection", "revision"])
def test_resume_rejects_changed_plan(evaluation_db, loaded, candidate, change):
    group_id = uuid4()
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate, group_id=group_id)
        changes = {"policy": {"policy": ExecutionPolicy(max_retries=1)},
                   "candidate": {"candidate": candidate.model_copy(update={"model_id": "other-model"})},
                   "selection": {"cases": list(loaded.suite.cases[1:2])},
                   "revision": {"code_revision": "b" * 40}}[change]
        resumed_candidate = changes.pop("candidate", candidate)
        with pytest.raises(EvaluationPlanConflictError):
            create_run(db, loaded, resumed_candidate, group_id=group_id, run_id=run.id, **changes)
        assert get_run(db, run.id).status == "RUNNING"


def test_observation_identity_must_match_case_and_recorded_plan(evaluation_db, loaded, candidate):
    case = loaded.suite.cases[0]
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate)
        with pytest.raises(EvaluationStoreError):
            record_result(db, run.id, case, observation(case, candidate).model_copy(update={"request_digest": "f" * 64}))
        with pytest.raises(EvaluationStoreError):
            record_result(db, run.id, loaded.suite.cases[1], observation(loaded.suite.cases[1], candidate))
        assert results_for_run(db, run.id) == []


@pytest.mark.parametrize("field,value", [("policy_version", "other"), ("candidate_id", "other"),
                                         ("suite_digest", "b" * 64), ("selected_case_ids", [])])
def test_committed_run_configuration_cannot_be_changed(evaluation_db, loaded, candidate, field, value):
    if field == "policy_version":
        field, value = "execution_policy", {"version": "other"}
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate)
        setattr(run, field, value)
        with pytest.raises(ValueError, match="immutable"):
            db.flush()
        db.rollback()


@pytest.mark.parametrize("kind", ["run", "result", "review"])
def test_committed_evaluation_history_cannot_be_deleted(evaluation_db, loaded, candidate, kind):
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate)
        result = record_result(db, run.id, loaded.suite.cases[0], observation(loaded.suite.cases[0], candidate))
        review = record_review(db, review_payload(result, loaded), loaded)
        db.delete({"run": run, "result": result, "review": review}[kind])
        with pytest.raises(ValueError, match="cannot be deleted"):
            db.flush()
        db.rollback()


@pytest.mark.parametrize("kind", ["result", "review"])
def test_committed_observation_and_review_cannot_be_rewritten(evaluation_db, loaded, candidate, kind):
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate)
        result = record_result(db, run.id, loaded.suite.cases[0], observation(loaded.suite.cases[0], candidate))
        if kind == "result":
            result.outcome = "TIMEOUT"
        else:
            review = record_review(db, review_payload(result, loaded), loaded)
            review.notes = "Rewritten history"
        with pytest.raises(ValueError, match="immutable"):
            db.flush()
        db.rollback()


def test_completed_run_cannot_be_reopened_even_with_expired_columns(evaluation_db, loaded, candidate):
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate)
        record_result(db, run.id, loaded.suite.cases[0], observation(loaded.suite.cases[0], candidate))
        finish_run(db, run.id)
        run.status, run.completed_at = "RUNNING", None
        with pytest.raises(ValueError, match="immutable"):
            db.flush()
        db.rollback()


def test_review_is_appended_and_missing_dimensions_rejected(evaluation_db, loaded, candidate):
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate)
        result = record_result(db, run.id, loaded.suite.cases[0], observation(loaded.suite.cases[0], candidate))
        first = record_review(db, review_payload(result, loaded, score=1), loaded)
        second = record_review(db, review_payload(result, loaded, score=4), loaded)
        assert first.id != second.id
        assert db.scalar(select(func.count()).select_from(EvaluationReview)) == 2
        bad = review_payload(result, loaded).model_copy(update={"scores": {}})
        with pytest.raises(EvaluationStoreError):
            record_review(db, bad, loaded)


def test_result_commit_failure_rolls_back_without_fake_return(evaluation_db, loaded, candidate, monkeypatch):
    case = loaded.suite.cases[0]
    with evaluation_db() as db:
        run = create_run(db, loaded, candidate)
        original_commit = db.commit
        def fail_commit():
            raise SQLAlchemyError("private database details")
        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(EvaluationStoreError) as error:
            record_result(db, run.id, case, observation(case, candidate))
        assert "private database details" not in str(error.value)
        monkeypatch.setattr(db, "commit", original_commit)
        assert results_for_run(db, run.id) == []
        stored = record_result(db, run.id, case, observation(case, candidate))
        assert stored.id


def test_database_foreign_keys_reject_missing_evaluation_run(evaluation_db):
    with evaluation_db() as db:
        db.add(EvaluationResult(run_id=uuid4(), case_id="case", case_digest="a" * 64,
                                request_digest="b" * 64, task_type="hint", outcome="PROVIDER_ERROR",
                                structured_output=None, automatic_metrics={}, latency_ms=0,
                                attempt_count=1, error_code="PROVIDER_ERROR"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_group_candidate_uniqueness_rejects_an_ambiguous_repeat_plan(evaluation_db, loaded, candidate):
    group = uuid4()
    with evaluation_db() as db:
        first = create_run(db, loaded, candidate, group_id=group)
        with pytest.raises(EvaluationStoreError):
            create_run(db, loaded, candidate, group_id=group)
        assert get_run(db, first.id).candidate_id == candidate.candidate_id
        assert db.scalar(select(func.count()).select_from(EvaluationRun)) == 1


def test_evaluator_cannot_commit_unrelated_pending_learner_changes(evaluation_db, loaded, candidate):
    from app.models.problem import Problem
    with evaluation_db() as db:
        original = db.get(Problem, 1).title
        db.get(Problem, 1).title = "Pending unrelated edit"
        with pytest.raises(EvaluationStoreError, match="unrelated"):
            create_run(db, loaded, candidate)
        db.rollback()
        assert db.get(Problem, 1).title == original
