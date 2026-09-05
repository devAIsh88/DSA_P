from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Skill(Base):
    """A DSA concept that can be arranged in a parent-child hierarchy."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    parent_skill_id: Mapped[Optional[int]] = mapped_column(ForeignKey("skills.id"), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difficulty_range: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
