"""Recomputable learner-state projection for one learner and skill."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


STATE_JSON = JSONB().with_variant(JSON(), "sqlite")


class SkillState(Base):
    """Derived state; LearningEvents retain the authoritative history."""

    __tablename__ = "skill_states"
    __table_args__ = (
        CheckConstraint("mastery_probability BETWEEN 0 AND 1", name="ck_skill_states_mastery_probability"),
        CheckConstraint("mastery_uncertainty BETWEEN 0 AND 1", name="ck_skill_states_mastery_uncertainty"),
        CheckConstraint(
            "attempt_count >= 0 AND successful_attempt_count >= 0 AND independent_solve_count >= 0 "
            "AND hint_dependent_count >= 0 AND hint_count_total >= 0",
            name="ck_skill_states_nonnegative_counts",
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), primary_key=True)
    mastery_probability: Mapped[float] = mapped_column(Float, nullable=False)
    mastery_uncertainty: Mapped[float] = mapped_column(Float, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    successful_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    independent_solve_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    hint_dependent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    hint_count_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    average_hint_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    recent_error_types: Mapped[list[str] | None] = mapped_column(STATE_JSON, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_evidence_event_id: Mapped[int] = mapped_column(ForeignKey("learning_events.id"), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    param_version: Mapped[str] = mapped_column(String(60), nullable=False)
    observation_rule_version: Mapped[str] = mapped_column(String(60), nullable=False)
    attribution_rule_version: Mapped[str] = mapped_column(String(60), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  onupdate=func.now(), nullable=False)
