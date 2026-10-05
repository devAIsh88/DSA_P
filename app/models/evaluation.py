"""Evaluation-only history; no learner entities or production-state relationships."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, Uuid, event, inspect, select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


EVALUATION_JSON = JSONB().with_variant(JSON(), "sqlite")


class EvaluationRun(Base):
    """Frozen experiment plan with a RUNNING-to-COMPLETED lifecycle."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        UniqueConstraint("group_id", "candidate_id", name="uq_evaluation_runs_group_candidate"),
        CheckConstraint("status IN ('RUNNING', 'COMPLETED')", name="ck_evaluation_runs_status"),
        CheckConstraint("(status = 'RUNNING' AND completed_at IS NULL) OR "
                        "(status = 'COMPLETED' AND completed_at IS NOT NULL)",
                        name="ck_evaluation_runs_completion_pair"),
        CheckConstraint("completed_at IS NULL OR completed_at >= created_at",
                        name="ck_evaluation_runs_completion_time"),
        CheckConstraint("length(suite_digest) = 64 AND length(selected_cases_digest) = 64 AND "
                        "length(rubric_digest) = 64 AND length(schema_digest) = 64 AND "
                        "length(protocol_fingerprint) = 64", name="ck_evaluation_runs_digest_length"),
        Index("ix_evaluation_runs_group_created", "group_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    group_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    suite_id: Mapped[str] = mapped_column(String(120), nullable=False)
    suite_version: Mapped[str] = mapped_column(String(120), nullable=False)
    suite_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_case_ids: Mapped[list[str]] = mapped_column(EVALUATION_JSON, nullable=False)
    case_manifest: Mapped[list[dict[str, str]]] = mapped_column(EVALUATION_JSON, nullable=False)
    selected_cases_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    runner_version: Mapped[str] = mapped_column(String(60), nullable=False)
    code_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_versions: Mapped[dict[str, str]] = mapped_column(EVALUATION_JSON, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(60), nullable=False)
    schema_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(120), nullable=False)
    rubric_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_policy: Mapped[dict[str, Any]] = mapped_column(EVALUATION_JSON, nullable=False)
    pricing_snapshot: Mapped[dict[str, Any] | None] = mapped_column(EVALUATION_JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                               default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvaluationResult(Base):
    """One committed benchmark observation, including failures without raw exceptions."""

    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", name="uq_evaluation_results_run_case"),
        CheckConstraint("task_type IN ('hint', 'diagnosis', 'reasoning', 'explanation', 'understanding')",
                        name="ck_evaluation_results_task"),
        CheckConstraint("outcome IN ('SUCCESS', 'TIMEOUT', 'PROVIDER_ERROR', 'INVALID_SCHEMA', "
                        "'UNSAFE_OUTPUT', 'IDENTITY_MISMATCH', 'INPUT_TOO_LARGE')",
                        name="ck_evaluation_results_outcome"),
        CheckConstraint("latency_ms >= 0 AND attempt_count >= 0", name="ck_evaluation_results_measurements"),
        CheckConstraint("(input_tokens IS NULL OR input_tokens >= 0) AND "
                        "(output_tokens IS NULL OR output_tokens >= 0)", name="ck_evaluation_results_tokens"),
        CheckConstraint("length(case_digest) = 64 AND length(request_digest) = 64",
                        name="ck_evaluation_results_digest_length"),
        Index("ix_evaluation_results_run_created", "run_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("evaluation_runs.id"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(120), nullable=False)
    case_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    structured_output: Mapped[dict[str, Any] | None] = mapped_column(EVALUATION_JSON, nullable=True)
    automatic_metrics: Mapped[dict[str, Any]] = mapped_column(EVALUATION_JSON, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accounting_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accounting_basis: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                               default=lambda: datetime.now(UTC))


class EvaluationReview(Base):
    """Append-only human review; aggregation chooses the latest rating per reviewer."""

    __tablename__ = "evaluation_reviews"
    __table_args__ = (
        Index("ix_evaluation_reviews_result_reviewer", "result_id", "reviewer_label", "reviewed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("evaluation_results.id"), nullable=False)
    reviewer_label: Mapped[str] = mapped_column(String(100), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(120), nullable=False)
    scores: Mapped[dict[str, int | None]] = mapped_column(EVALUATION_JSON, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                default=lambda: datetime.now(UTC))


@event.listens_for(EvaluationRun, "before_insert")
def _start_running(_mapper, _connection, target: EvaluationRun) -> None:
    if target.status not in {None, "RUNNING"} or target.completed_at is not None:
        raise ValueError("Evaluation runs must begin RUNNING")


@event.listens_for(EvaluationRun, "before_update")
def _protect_run(_mapper, connection, target: EvaluationRun) -> None:
    attributes = inspect(target).attrs
    changed = {column.key for column in target.__table__.columns
               if attributes[column.key].history.has_changes()}
    if changed - {"status", "completed_at"}:
        raise ValueError("Committed evaluation plans are immutable")
    if changed:
        previous = connection.execute(select(
            target.__table__.c.status, target.__table__.c.completed_at,
        ).where(target.__table__.c.id == target.id)).one()
        if previous.status != "RUNNING" or previous.completed_at is not None:
            raise ValueError("Completed evaluation run lifecycle is immutable")
        if target.status != "COMPLETED" or target.completed_at is None:
            raise ValueError("Only RUNNING to COMPLETED evaluation transitions are allowed")


def _protect_observation(_mapper, _connection, _target) -> None:
    raise ValueError("Committed evaluation results and reviews are immutable")


def _protect_history(_mapper, _connection, _target) -> None:
    raise ValueError("Evaluation history cannot be deleted through normal ORM behavior")


for _model in (EvaluationResult, EvaluationReview):
    event.listen(_model, "before_update", _protect_observation)
for _model in (EvaluationRun, EvaluationResult, EvaluationReview):
    event.listen(_model, "before_delete", _protect_history)
