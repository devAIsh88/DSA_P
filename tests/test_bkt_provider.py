"""BKT arithmetic, configuration, and replay behavior without persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.bkt_provider import BKTParameters, BKTProvider, load_bkt_parameters
from app.services.knowledge_tracing import TracingObservation


PARAMETERS = BKTParameters(prior_mastery=0.20, learn_rate=0.10, slip=0.15, guess=0.25, version="test-v1")


def observation(correct: float, *, attempt_id: int = 1, hint_level: int = 0) -> TracingObservation:
    return TracingObservation(correct=correct, hint_level=hint_level, attempt_id=attempt_id,
                              occurred_at=datetime(2026, 9, 29, tzinfo=UTC))


def test_correct_and_incorrect_posteriors_then_learning_transition() -> None:
    provider = BKTProvider(PARAMETERS)
    initial = provider.initial_state()
    correct = provider.update_skill_state(initial, observation(1.0))
    incorrect = provider.update_skill_state(initial, observation(0.0))

    assert correct.mastery_probability == pytest.approx(0.5135135135)
    assert incorrect.mastery_probability == pytest.approx(0.1428571429)
    assert correct.mastery_uncertainty == pytest.approx(1.0 - correct.mastery_probability)
    assert initial.mastery_probability == 0.20
    assert initial.attempt_count == 0
    assert (correct.attempt_count, correct.successful_attempt_count, correct.independent_solve_count) == (1, 1, 1)
    assert (incorrect.attempt_count, incorrect.successful_attempt_count) == (1, 0)


def test_replay_is_deterministic_and_does_not_mutate_inputs() -> None:
    provider = BKTProvider(PARAMETERS)
    observations = [observation(1.0), observation(0.0, attempt_id=2), observation(1.0, attempt_id=3)]
    initial = provider.initial_state()
    first = provider.replay_skill_state(observations)
    second = provider.replay_skill_state(observations)

    assert first == second
    assert first == provider.update_skill_state(
        provider.update_skill_state(provider.update_skill_state(initial, observations[0]), observations[1]),
        observations[2],
    )
    assert initial.attempt_count == 0
    assert first.attempt_count == 3
    assert first.successful_attempt_count == 2


def test_probability_bounds_and_impossible_evidence() -> None:
    provider = BKTProvider(BKTParameters(1.0, 0.0, 0.0, 0.0, "edge-v1"))
    assert provider.update_skill_state(provider.initial_state(), observation(1.0)).mastery_probability == 0.999
    with pytest.raises(ValueError, match="zero likelihood"):
        provider.update_skill_state(provider.initial_state(), observation(0.0))


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_parameters_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="finite probabilities"):
        BKTParameters(value, 0.1, 0.15, 0.25, "invalid-v1")


def test_fractional_or_assisted_observations_require_a_separate_policy() -> None:
    provider = BKTProvider(PARAMETERS)
    with pytest.raises(ValueError, match="binary, unassisted"):
        provider.update_skill_state(provider.initial_state(), observation(0.5))
    with pytest.raises(ValueError, match="binary, unassisted"):
        provider.update_skill_state(provider.initial_state(), observation(1.0, hint_level=1))


def test_parameter_configuration_is_versioned() -> None:
    parameters = load_bkt_parameters()
    assert parameters.version == "experimental-v1"
    assert all(0.0 <= value <= 1.0 for value in (
        parameters.prior_mastery, parameters.learn_rate, parameters.slip, parameters.guess,
    ))
