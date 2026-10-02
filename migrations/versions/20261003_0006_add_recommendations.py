"""add immutable adaptive recommendations and lifecycle

Revision ID: 20261003_0006
Revises: 20260929_0005
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261003_0006"
down_revision = "20260929_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("problem_id", sa.Integer(), sa.ForeignKey("problems.id"), nullable=False),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id"), nullable=True),
        sa.Column("policy_version", sa.String(60), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_through_event_id", sa.Integer(), sa.ForeignKey("learning_events.id"), nullable=True),
        sa.Column("evidence_event_count", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reevaluate_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_attempt_id", sa.Integer(), sa.ForeignKey("attempts.id"), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("action_type IN ('NEXT_PROBLEM', 'REVISE_CONCEPT', 'RETRY_SIMILAR_PROBLEM', "
                           "'INCREASE_DIFFICULTY', 'DECREASE_DIFFICULTY')", name="ck_recommendations_action"),
        sa.CheckConstraint("evidence_event_count >= 0", name="ck_recommendations_event_count"),
        sa.CheckConstraint("(consumed_at IS NULL AND consumed_attempt_id IS NULL) OR "
                           "(consumed_at IS NOT NULL AND consumed_attempt_id IS NOT NULL)",
                           name="ck_recommendations_consumption_pair"),
        sa.CheckConstraint("consumed_at IS NULL OR superseded_at IS NULL", name="ck_recommendations_exclusive_end"),
        sa.CheckConstraint("(consumed_at IS NULL OR consumed_at >= created_at) AND "
                           "(superseded_at IS NULL OR superseded_at >= created_at)",
                           name="ck_recommendations_lifecycle_time"),
        sa.CheckConstraint("skill_id IS NOT NULL OR action_type = 'NEXT_PROBLEM' OR "
                           "action_type = 'RETRY_SIMILAR_PROBLEM'", name="ck_recommendations_target_skill"),
    )
    op.create_index("ix_recommendations_user_created", "recommendations", ["user_id", "created_at"])
    op.create_index("uq_recommendations_active_user", "recommendations", ["user_id"], unique=True,
                    postgresql_where=sa.text("consumed_at IS NULL AND superseded_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_recommendations_active_user", table_name="recommendations")
    op.drop_index("ix_recommendations_user_created", table_name="recommendations")
    op.drop_table("recommendations")
