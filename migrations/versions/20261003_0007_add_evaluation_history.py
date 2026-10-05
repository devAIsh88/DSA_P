"""add isolated benchmark runs, observations and human reviews

Revision ID: 20261003_0007
Revises: 20261003_0006
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261003_0007"
down_revision = "20261003_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("group_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("suite_id", sa.String(120), nullable=False),
        sa.Column("suite_version", sa.String(120), nullable=False),
        sa.Column("suite_digest", sa.String(64), nullable=False),
        sa.Column("selected_case_ids", postgresql.JSONB(), nullable=False),
        sa.Column("case_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("selected_cases_digest", sa.String(64), nullable=False),
        sa.Column("candidate_id", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(120), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("runner_version", sa.String(60), nullable=False),
        sa.Column("code_revision", sa.String(64), nullable=False),
        sa.Column("prompt_versions", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.String(60), nullable=False),
        sa.Column("schema_digest", sa.String(64), nullable=False),
        sa.Column("rubric_version", sa.String(120), nullable=False),
        sa.Column("rubric_digest", sa.String(64), nullable=False),
        sa.Column("protocol_fingerprint", sa.String(64), nullable=False),
        sa.Column("execution_policy", postgresql.JSONB(), nullable=False),
        sa.Column("pricing_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("group_id", "candidate_id", name="uq_evaluation_runs_group_candidate"),
        sa.CheckConstraint("status IN ('RUNNING', 'COMPLETED')", name="ck_evaluation_runs_status"),
        sa.CheckConstraint("(status = 'RUNNING' AND completed_at IS NULL) OR "
                           "(status = 'COMPLETED' AND completed_at IS NOT NULL)",
                           name="ck_evaluation_runs_completion_pair"),
        sa.CheckConstraint("completed_at IS NULL OR completed_at >= created_at",
                           name="ck_evaluation_runs_completion_time"),
        sa.CheckConstraint("length(suite_digest) = 64 AND length(selected_cases_digest) = 64 AND "
                           "length(rubric_digest) = 64 AND length(schema_digest) = 64 AND "
                           "length(protocol_fingerprint) = 64", name="ck_evaluation_runs_digest_length"),
    )
    op.create_index("ix_evaluation_runs_group_created", "evaluation_runs", ["group_id", "created_at"])
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Uuid(as_uuid=True), sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("case_id", sa.String(120), nullable=False),
        sa.Column("case_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("task_type", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("structured_output", postgresql.JSONB(), nullable=True),
        sa.Column("automatic_metrics", postgresql.JSONB(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("accounting_version", sa.String(120), nullable=True),
        sa.Column("accounting_basis", sa.String(120), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "case_id", name="uq_evaluation_results_run_case"),
        sa.CheckConstraint("task_type IN ('hint', 'diagnosis', 'reasoning', 'explanation', 'understanding')",
                           name="ck_evaluation_results_task"),
        sa.CheckConstraint("outcome IN ('SUCCESS', 'TIMEOUT', 'PROVIDER_ERROR', 'INVALID_SCHEMA', "
                           "'UNSAFE_OUTPUT', 'IDENTITY_MISMATCH', 'INPUT_TOO_LARGE')",
                           name="ck_evaluation_results_outcome"),
        sa.CheckConstraint("latency_ms >= 0 AND attempt_count >= 0", name="ck_evaluation_results_measurements"),
        sa.CheckConstraint("(input_tokens IS NULL OR input_tokens >= 0) AND "
                           "(output_tokens IS NULL OR output_tokens >= 0)", name="ck_evaluation_results_tokens"),
        sa.CheckConstraint("length(case_digest) = 64 AND length(request_digest) = 64",
                           name="ck_evaluation_results_digest_length"),
    )
    op.create_index("ix_evaluation_results_run_created", "evaluation_results", ["run_id", "created_at"])
    op.create_table(
        "evaluation_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("evaluation_results.id"), nullable=False),
        sa.Column("reviewer_label", sa.String(100), nullable=False),
        sa.Column("rubric_version", sa.String(120), nullable=False),
        sa.Column("scores", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evaluation_reviews_result_reviewer", "evaluation_reviews",
                    ["result_id", "reviewer_label", "reviewed_at"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_reviews_result_reviewer", table_name="evaluation_reviews")
    op.drop_table("evaluation_reviews")
    op.drop_index("ix_evaluation_results_run_created", table_name="evaluation_results")
    op.drop_table("evaluation_results")
    op.drop_index("ix_evaluation_runs_group_created", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
