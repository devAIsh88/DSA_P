"""Problem-to-skill mapping; attribution policy is separate from this relation."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProblemSkill(Base):
    """A skill associated with a problem, without assigning mastery credit."""

    __tablename__ = "problem_skills"
    __table_args__ = (CheckConstraint("weight > 0", name="ck_problem_skills_positive_weight"),)

    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default=text("1.0"))
