"""add problem catalog tables

Revision ID: 20260828_0002
Revises: 20260817_0001
Create Date: 2026-08-28 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828_0002"
down_revision = "20260817_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("parent_skill_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("difficulty_range", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["parent_skill_id"], ["skills.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "problems",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("subtopic", sa.String(length=100), nullable=True),
        sa.Column("constraints", sa.Text(), nullable=True),
        sa.Column("input_format", sa.Text(), nullable=True),
        sa.Column("output_format", sa.Text(), nullable=True),
        sa.Column("expected_complexity", sa.String(length=100), nullable=True),
        sa.Column("target_track", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "test_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text(), nullable=False),
        sa.Column("is_sample", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("weight", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_cases_problem_id", "test_cases", ["problem_id"])

    skills = sa.table("skills", sa.column("id", sa.Integer()), sa.column("name", sa.String()), sa.column("description", sa.Text()), sa.column("difficulty_range", sa.String()))
    problems = sa.table(
        "problems",
        sa.column("id", sa.Integer()), sa.column("title", sa.String()), sa.column("description", sa.Text()),
        sa.column("difficulty", sa.String()), sa.column("source", sa.String()), sa.column("topic", sa.String()),
        sa.column("subtopic", sa.String()), sa.column("constraints", sa.Text()), sa.column("input_format", sa.Text()),
        sa.column("output_format", sa.Text()), sa.column("expected_complexity", sa.String()), sa.column("target_track", sa.String()),
    )
    test_cases = sa.table(
        "test_cases", sa.column("id", sa.Integer()), sa.column("problem_id", sa.Integer()), sa.column("input", sa.Text()),
        sa.column("expected_output", sa.Text()), sa.column("is_sample", sa.Boolean()), sa.column("is_hidden", sa.Boolean()), sa.column("weight", sa.Integer()),
    )
    op.bulk_insert(skills, [{"id": 1, "name": "Arrays", "description": "Techniques for traversing and searching arrays.", "difficulty_range": "Easy-Medium"}])
    op.bulk_insert(problems, [{
        "id": 1, "title": "Two Sum", "description": "Given an integer array and a target, return indices of two distinct elements whose sum equals the target.",
        "difficulty": "Easy", "source": "DEV Placement OS", "topic": "Arrays", "subtopic": "Hashing",
        "constraints": "2 <= len(nums) <= 10^4", "input_format": "Line 1: space-separated integers. Line 2: target integer.",
        "output_format": "Two zero-based indices separated by a space.", "expected_complexity": "O(n) time, O(n) space", "target_track": "Core DSA",
    }])
    op.bulk_insert(test_cases, [
        {"id": 1, "problem_id": 1, "input": "2 7 11 15\n9", "expected_output": "0 1", "is_sample": True, "is_hidden": False, "weight": 1},
        {"id": 2, "problem_id": 1, "input": "3 2 4\n6", "expected_output": "1 2", "is_sample": False, "is_hidden": True, "weight": 2},
    ])


def downgrade() -> None:
    op.drop_index("ix_test_cases_problem_id", table_name="test_cases")
    op.drop_table("test_cases")
    op.drop_table("problems")
    op.drop_table("skills")
