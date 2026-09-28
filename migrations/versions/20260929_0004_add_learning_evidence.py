"""add Phase 4A attempts and learning events

Revision ID: 20260929_0004
Revises: 20260904_0003
Create Date: 2026-09-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260929_0004"
down_revision = "20260904_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attempts_user_id", "attempts", ["user_id"])
    op.create_index("ix_attempts_problem_id", "attempts", ["problem_id"])
    op.create_index(
        "uq_attempts_active_user_problem", "attempts", ["user_id", "problem_id"], unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "uq_attempts_user_idempotency", "attempts", ["user_id", "idempotency_key"], unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.add_column("submissions", sa.Column("attempt_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_submissions_attempt_id", "submissions", "attempts", ["attempt_id"], ["id"])
    op.create_index("ix_submissions_attempt_id", "submissions", ["attempt_id"])

    op.create_table(
        "learning_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("submission_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("attempt_sequence", sa.Integer(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("derived_labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"]),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "attempt_sequence", name="uq_learning_events_attempt_sequence"),
    )
    op.create_index("ix_learning_events_user_id", "learning_events", ["user_id"])
    op.create_index("ix_learning_events_attempt_id", "learning_events", ["attempt_id"])
    op.create_index("ix_learning_events_user_skill_occurred", "learning_events", ["user_id", "skill_id", "occurred_at"])
    op.create_index(
        "uq_learning_events_attempt_idempotency", "learning_events", ["attempt_id", "idempotency_key"],
        unique=True, postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_learning_events_evaluated_submission", "learning_events", ["submission_id"],
        unique=True, postgresql_where=sa.text("event_type = 'SUBMISSION_EVALUATED' AND submission_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_learning_events_evaluated_submission", table_name="learning_events")
    op.drop_index("uq_learning_events_attempt_idempotency", table_name="learning_events")
    op.drop_index("ix_learning_events_user_skill_occurred", table_name="learning_events")
    op.drop_index("ix_learning_events_attempt_id", table_name="learning_events")
    op.drop_index("ix_learning_events_user_id", table_name="learning_events")
    op.drop_table("learning_events")
    op.drop_index("ix_submissions_attempt_id", table_name="submissions")
    op.drop_constraint("fk_submissions_attempt_id", "submissions", type_="foreignkey")
    op.drop_column("submissions", "attempt_id")
    op.drop_index("uq_attempts_user_idempotency", table_name="attempts")
    op.drop_index("uq_attempts_active_user_problem", table_name="attempts")
    op.drop_index("ix_attempts_problem_id", table_name="attempts")
    op.drop_index("ix_attempts_user_id", table_name="attempts")
    op.drop_table("attempts")
