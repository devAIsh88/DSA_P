"""Initial single-skill Bayesian Knowledge Tracing implementation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from app.services.knowledge_tracing import KnowledgeTracingProvider, SkillStateSnapshot, TracingObservation


MODEL_VERSION = "bkt-v1"
PARAMETER_FILE = Path(__file__).resolve().parents[2] / "config" / "learner_model.json"


@dataclass(frozen=True)
class BKTParameters:
    """Versioned, experimental parameters for one BKT model instance."""

    prior_mastery: float
    learn_rate: float
    slip: float
    guess: float
    version: str

    def __post_init__(self) -> None:
        for value in (self.prior_mastery, self.learn_rate, self.slip, self.guess):
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("BKT parameters must be finite probabilities")
        if not self.version or len(self.version) > 60:
            raise ValueError("BKT parameter version is required")


def load_bkt_parameters(path: Path = PARAMETER_FILE) -> BKTParameters:
    """Load the active parameter set; retain old versions in the config for replay."""

    config = json.loads(path.read_text(encoding="utf-8"))
    version = config["active_bkt_parameters"]
    return BKTParameters(version=version, **config["bkt_parameter_sets"][version])


def _posterior(prior: float, correct: bool, slip: float, guess: float) -> float:
    if correct:
        numerator = prior * (1.0 - slip)
        denominator = numerator + (1.0 - prior) * guess
    else:
        numerator = prior * slip
        denominator = numerator + (1.0 - prior) * (1.0 - guess)
    if denominator <= 0.0:
        raise ValueError("Observation has zero likelihood under these BKT parameters")
    return numerator / denominator


class BKTProvider(KnowledgeTracingProvider):
    """Pure BKT math for binary, unassisted Attempt observations."""

    def __init__(self, parameters: BKTParameters) -> None:
        self.parameters = parameters

    def initial_state(self) -> SkillStateSnapshot:
        mastery = self.parameters.prior_mastery
        return SkillStateSnapshot(
            mastery_probability=mastery, mastery_uncertainty=1.0 - mastery,
            attempt_count=0, successful_attempt_count=0, independent_solve_count=0,
            hint_dependent_count=0, hint_count_total=0,
            model_version=MODEL_VERSION, param_version=self.parameters.version,
        )

    def update_skill_state(
        self, current_state: SkillStateSnapshot, observation: TracingObservation,
    ) -> SkillStateSnapshot:
        if (current_state.model_version != MODEL_VERSION
                or current_state.param_version != self.parameters.version):
            raise ValueError("Replay is required when the model or parameters change")
        if observation.hint_level != 0 or observation.correct not in (0.0, 1.0):
            raise ValueError("This BKT version requires binary, unassisted observations")
        prior = current_state.mastery_probability
        if not isfinite(prior) or not 0.0 <= prior <= 1.0:
            raise ValueError("Current mastery probability is invalid")
        posterior = _posterior(prior, observation.correct == 1.0,
                               self.parameters.slip, self.parameters.guess)
        transitioned = posterior + (1.0 - posterior) * self.parameters.learn_rate
        mastery = min(0.999, max(0.001, transitioned))
        solved = int(observation.correct == 1.0)
        return SkillStateSnapshot(
            mastery_probability=mastery, mastery_uncertainty=1.0 - mastery,
            attempt_count=current_state.attempt_count + 1,
            successful_attempt_count=current_state.successful_attempt_count + solved,
            independent_solve_count=current_state.independent_solve_count + solved,
            hint_dependent_count=current_state.hint_dependent_count,
            hint_count_total=current_state.hint_count_total,
            model_version=MODEL_VERSION, param_version=self.parameters.version,
        )

    def replay_skill_state(
        self, observations: list[TracingObservation], initial_state: SkillStateSnapshot | None = None,
    ) -> SkillStateSnapshot:
        state = initial_state if initial_state is not None else self.initial_state()
        for observation in observations:
            state = self.update_skill_state(state, observation)
        return state
