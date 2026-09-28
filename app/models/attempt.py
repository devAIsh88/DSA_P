"""A single learner engagement with one problem."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Attempt(Base):
    """Group reasoning and submissions until an engagement is closed."""

    __tablename__ = "attempts"
    __table_args__ = (
        Index(
            "uq_attempts_active_user_problem", "user_id", "problem_id", unique=True,
            postgresql_where=text("status = 'ACTIVE'"), sqlite_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "uq_attempts_user_idempotency", "user_id", "idempotency_key", unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
