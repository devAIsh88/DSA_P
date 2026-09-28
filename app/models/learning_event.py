"""Append-only historical learner evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


EVENT_JSON = JSONB().with_variant(JSON(), "sqlite")


class LearningEvent(Base):
    """Immutable evidence and provenance within an Attempt ledger."""

    __tablename__ = "learning_events"
    __table_args__ = (
        UniqueConstraint("attempt_id", "attempt_sequence", name="uq_learning_events_attempt_sequence"),
        Index("ix_learning_events_user_skill_occurred", "user_id", "skill_id", "occurred_at"),
        Index(
            "uq_learning_events_attempt_idempotency", "attempt_id", "idempotency_key", unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "uq_learning_events_evaluated_submission", "submission_id", unique=True,
            postgresql_where=text("event_type = 'SUBMISSION_EVALUATED' AND submission_id IS NOT NULL"),
            sqlite_where=text("event_type = 'SUBMISSION_EVALUATED' AND submission_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), nullable=False, index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), nullable=False)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"), nullable=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    attempt_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(EVENT_JSON, nullable=False)
    derived_labels: Mapped[dict[str, Any] | None] = mapped_column(EVENT_JSON, nullable=True)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(EVENT_JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
