"""Pure, replaceable knowledge-tracing contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True)
class TracingObservation:
    """One Attempt-level observation derived from recorded learner evidence."""

    correct: float
    hint_level: int
    attempt_id: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not isfinite(self.correct) or not 0.0 <= self.correct <= 1.0:
            raise ValueError("Observation correctness must be a probability")
        if self.hint_level < 0 or self.attempt_id <= 0:
            raise ValueError("Observation context is invalid")


@dataclass(frozen=True)
class SkillStateSnapshot:
    """Provider output; persistence and provenance belong to the application service."""

    mastery_probability: float
    mastery_uncertainty: float
    attempt_count: int
    successful_attempt_count: int
    independent_solve_count: int
    hint_dependent_count: int
    hint_count_total: int
    model_version: str
    param_version: str


class KnowledgeTracingProvider(ABC):
    """Algorithm boundary without database or event-store dependencies."""

    @abstractmethod
    def initial_state(self) -> SkillStateSnapshot:
        """Return a new projection before observations are applied."""

    @abstractmethod
    def update_skill_state(
        self, current_state: SkillStateSnapshot, observation: TracingObservation,
    ) -> SkillStateSnapshot:
        """Return an updated projection without mutating the input."""

    @abstractmethod
    def replay_skill_state(
        self, observations: list[TracingObservation], initial_state: SkillStateSnapshot | None = None,
    ) -> SkillStateSnapshot:
        """Rebuild the same projection from the same ordered observations."""
