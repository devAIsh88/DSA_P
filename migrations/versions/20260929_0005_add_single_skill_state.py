"""add single-skill learner-state projection

Revision ID: 20260929_0005
Revises: 20260929_0004
Create Date: 2026-09-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260929_0005"
down_revision = "20260929_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "problem_skills",
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.CheckConstraint("weight > 0", name="ck_problem_skills_positive_weight"),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("problem_id", "skill_id"),
    )
    op.create_table(
        "skill_states",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("mastery_probability", sa.Float(), nullable=False),
        sa.Column("mastery_uncertainty", sa.Float(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("successful_attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("independent_solve_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("hint_dependent_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("hint_count_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("average_hint_level", sa.Float(), nullable=True),
        sa.Column("average_duration_ms", sa.Float(), nullable=True),
        sa.Column("recent_error_types", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_signal", sa.Float(), nullable=True),
        sa.Column("last_evidence_event_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=60), nullable=False),
        sa.Column("param_version", sa.String(length=60), nullable=False),
        sa.Column("observation_rule_version", sa.String(length=60), nullable=False),
        sa.Column("attribution_rule_version", sa.String(length=60), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("mastery_probability BETWEEN 0 AND 1", name="ck_skill_states_mastery_probability"),
        sa.CheckConstraint("mastery_uncertainty BETWEEN 0 AND 1", name="ck_skill_states_mastery_uncertainty"),
        sa.CheckConstraint(
            "attempt_count >= 0 AND successful_attempt_count >= 0 AND independent_solve_count >= 0 "
            "AND hint_dependent_count >= 0 AND hint_count_total >= 0",
            name="ck_skill_states_nonnegative_counts",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"]),
        sa.ForeignKeyConstraint(["last_evidence_event_id"], ["learning_events.id"]),
        sa.PrimaryKeyConstraint("user_id", "skill_id"),
    )


def downgrade() -> None:
    op.drop_table("skill_states")
    op.drop_table("problem_skills")
