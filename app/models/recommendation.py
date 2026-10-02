"""Immutable adaptive decisions with a small controlled lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, event, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


RECOMMENDATION_JSON = JSONB().with_variant(JSON(), "sqlite")
_LIFECYCLE_FIELDS = frozenset({"consumed_at", "consumed_attempt_id", "superseded_at"})


class Recommendation(Base):
    """Decision history; only consumption/supersession may change after insertion."""

    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint("action_type IN ('NEXT_PROBLEM', 'REVISE_CONCEPT', 'RETRY_SIMILAR_PROBLEM', "
                        "'INCREASE_DIFFICULTY', 'DECREASE_DIFFICULTY')", name="ck_recommendations_action"),
        CheckConstraint("evidence_event_count >= 0", name="ck_recommendations_event_count"),
        CheckConstraint("(consumed_at IS NULL AND consumed_attempt_id IS NULL) OR "
                        "(consumed_at IS NOT NULL AND consumed_attempt_id IS NOT NULL)",
                        name="ck_recommendations_consumption_pair"),
        CheckConstraint("consumed_at IS NULL OR superseded_at IS NULL", name="ck_recommendations_exclusive_end"),
        CheckConstraint("(consumed_at IS NULL OR consumed_at >= created_at) AND "
                        "(superseded_at IS NULL OR superseded_at >= created_at)",
                        name="ck_recommendations_lifecycle_time"),
        CheckConstraint("skill_id IS NOT NULL OR action_type = 'NEXT_PROBLEM' OR "
                        "action_type = 'RETRY_SIMILAR_PROBLEM'", name="ck_recommendations_target_skill"),
        Index("ix_recommendations_user_created", "user_id", "created_at"),
        Index("uq_recommendations_active_user", "user_id", unique=True,
              postgresql_where=text("consumed_at IS NULL AND superseded_at IS NULL"),
              sqlite_where=text("consumed_at IS NULL AND superseded_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), nullable=False)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(60), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(RECOMMENDATION_JSON, nullable=False)
    evidence_through_event_id: Mapped[int | None] = mapped_column(ForeignKey("learning_events.id"), nullable=True)
    evidence_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(RECOMMENDATION_JSON, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reevaluate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempts.id"), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@event.listens_for(Recommendation, "before_insert")
def _validate_decision(_mapper, _connection, target: Recommendation) -> None:
    if (target.skill_id is None and target.action_type == "RETRY_SIMILAR_PROBLEM"
            and "ABANDONED_PROBLEM_RETRY" not in target.reason_codes):
        raise ValueError("Only explicit abandonment retry may lack a supported skill")


@event.listens_for(Recommendation, "before_update")
def _protect_decision(_mapper, _connection, target: Recommendation) -> None:
    """Normal ORM writes cannot revise decisions or reopen a terminal lifecycle."""

    attrs = inspect(target).attrs
    changed = {column.key for column in target.__table__.columns if attrs[column.key].history.has_changes()}
    if changed - _LIFECYCLE_FIELDS:
        raise ValueError("Committed recommendation decisions are immutable")
    if changed:
        # Expired attributes may have no deleted history when overwritten. Read the
        # stored lifecycle through the flush connection, not the new Python values.
        previous = _connection.execute(select(
            target.__table__.c.consumed_at, target.__table__.c.superseded_at,
        ).where(target.__table__.c.id == target.id)).one()
        if previous.consumed_at is not None or previous.superseded_at is not None:
            raise ValueError("Terminal recommendation lifecycle is immutable")


@event.listens_for(Recommendation, "before_delete")
def _protect_history(_mapper, _connection, _target: Recommendation) -> None:
    raise ValueError("Recommendation history cannot be deleted through normal ORM behavior")
