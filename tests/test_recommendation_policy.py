"""Independent checks of the frozen adaptive rules; no persistence or providers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.recommendation import (
    RecommendationCandidate,
    RecommendationContext,
    RecommendationPolicyConfig,
    RecommendationSkillState,
    TerminalEvidence,
)
from app.services.recommendation_policy import RecommendationPolicy, load_policy_config


NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


def candidate(
    problem_id: int,
    *,
    difficulty: str = "Easy",
    skill_id: int | None = 1,
    mapping_status: str = "single_skill",
    target_track: str | None = None,
) -> RecommendationCandidate:
    return RecommendationCandidate(
        problem_id=problem_id, difficulty=difficulty, skill_id=skill_id,
        mapping_status=mapping_status, target_track=target_track,
    )


def fact(
    event_id: int,
    problem_id: int,
    *,
    skill_id: int | None = 1,
    outcome: str | None = "SOLVED",
    status: str = "COMPLETED",
    correct: int | None = 1,
    final_status: str | None = "ACCEPTED",
    days_ago: float = 0,
    hint_level: int = 0,
    hint_requests: int = 0,
    has_hint_action: bool = False,
) -> TerminalEvidence:
    return TerminalEvidence(
        event_id=event_id, attempt_id=event_id, problem_id=problem_id,
        skill_id=skill_id, occurred_at=NOW - timedelta(days=days_ago),
        status=status, outcome=outcome, final_status=final_status,
        binary_correct=correct, max_hint_level=hint_level,
        hint_requests=hint_requests, has_hint_action=has_hint_action,
    )


def skill(
    skill_id: int = 1,
    *,
    mastery: float = 0.20,
    attempts: int = 0,
    successes: int = 0,
    hint_dependent: int = 0,
    days_ago: float | None = None,
) -> RecommendationSkillState:
    return RecommendationSkillState(
        skill_id=skill_id, mastery_probability=mastery,
        attempt_count=attempts, successful_attempt_count=successes,
        hint_dependent_count=hint_dependent,
        last_attempt_at=None if days_ago is None else NOW - timedelta(days=days_ago),
    )


def recommend(
    candidates: tuple[RecommendationCandidate, ...],
    attempts: tuple[TerminalEvidence, ...] = (),
    skills: tuple[RecommendationSkillState, ...] = (),
    *,
    config: RecommendationPolicyConfig | None = None,
):
    return RecommendationPolicy(config or RecommendationPolicyConfig()).recommend(
        RecommendationContext(
            evaluated_at=NOW, candidates=candidates, attempts=attempts, skills=skills,
        )
    )


def assert_decision(result, action: str, problem_id: int, reason: str) -> None:
    assert result.unavailable_reason is None
    assert result.decision is not None
    assert result.decision.action_type == action
    assert result.decision.problem_id == problem_id
    assert reason in result.decision.reason_codes


def test_cold_start_uses_lowest_difficulty_supported_mapping_then_stable_ids() -> None:
    candidates = (
        candidate(9, difficulty="Medium"), candidate(8, skill_id=2),
        candidate(7, skill_id=None, mapping_status="unmapped"), candidate(6), candidate(5),
    )
    first = recommend(candidates)
    second = recommend(tuple(reversed(candidates)))
    assert first == second
    assert_decision(first, "NEXT_PROBLEM", 5, "COLD_START")
    assert first.decision.skill_id == 1


def test_no_history_low_prior_is_cold_start_not_confirmed_weakness() -> None:
    result = recommend((candidate(1),), skills=(skill(mastery=0.01),))
    assert_decision(result, "NEXT_PROBLEM", 1, "COLD_START")
    assert "OBSERVED_LOW_MASTERY" not in result.decision.reason_codes


@pytest.mark.parametrize("mapping", ["unmapped", "multiple_skills_require_policy", "nonunit_weight_requires_policy"])
def test_unsupported_mapping_can_supply_unattributed_baseline(mapping: str) -> None:
    result = recommend((candidate(1, skill_id=None, mapping_status=mapping),))
    assert_decision(result, "NEXT_PROBLEM", 1, "COLD_START")
    assert result.decision.skill_id is None
    assert "UNATTRIBUTED_CATALOGUE" in result.decision.reason_codes


def test_unattributed_baseline_can_be_disabled_without_inventing_a_skill() -> None:
    config = RecommendationPolicyConfig(allow_unattributed_catalogue=False)
    result = recommend((candidate(1, skill_id=None, mapping_status="unmapped"),), config=config)
    assert result.decision is None
    assert result.unavailable_reason == "NO_ELIGIBLE_PROBLEM"


def test_empty_catalogue_and_unknown_difficulty_have_distinct_empty_results() -> None:
    assert recommend(()).unavailable_reason == "EMPTY_CATALOGUE"
    unknown = recommend((candidate(1, difficulty="Expert"),))
    assert unknown.decision is None
    assert unknown.unavailable_reason == "NO_ELIGIBLE_PROBLEM"


def test_recognized_difficulty_ignores_case_and_outer_whitespace() -> None:
    result = recommend((candidate(2, difficulty="MEDIUM"), candidate(1, difficulty=" easy ")))
    assert_decision(result, "NEXT_PROBLEM", 1, "COLD_START")


def test_target_filter_is_explicit_and_not_inferred_from_other_tracks() -> None:
    config = RecommendationPolicyConfig(target_track=" interview ")
    result = recommend((candidate(1, target_track="other"), candidate(2, target_track=" interview ")), config=config)
    assert_decision(result, "NEXT_PROBLEM", 2, "COLD_START")
    assert recommend((candidate(1, target_track="other"),), config=config).unavailable_reason == "NO_ELIGIBLE_PROBLEM"


def test_evidenced_weak_skill_requires_two_binary_observations_and_inclusive_threshold() -> None:
    attempts = (fact(1, 1, outcome="GAVE_UP", correct=0, final_status=None), fact(2, 2))
    result = recommend((candidate(1), candidate(2), candidate(3)), attempts,
                       (skill(mastery=0.50, attempts=2, successes=1),))
    assert_decision(result, "NEXT_PROBLEM", 3, "OBSERVED_LOW_MASTERY")


def test_one_binary_observation_is_not_evidenced_weakness() -> None:
    result = recommend((candidate(1), candidate(2)), (fact(1, 1),),
                       (skill(mastery=0.20, attempts=1, successes=1),))
    assert_decision(result, "NEXT_PROBLEM", 2, "NEW_PROBLEM")
    assert "OBSERVED_LOW_MASTERY" not in result.decision.reason_codes


def test_assisted_and_abandoned_reporting_counts_do_not_supply_binary_evidence() -> None:
    attempts = (
        fact(1, 1, correct=None, hint_requests=1, has_hint_action=True),
        fact(2, 2, status="ABANDONED", outcome=None, correct=None, final_status=None),
    )
    result = recommend((candidate(1), candidate(2), candidate(3)), attempts,
                       (skill(mastery=0.01, attempts=2, successes=1, hint_dependent=1),))
    assert_decision(result, "NEXT_PROBLEM", 3, "NEW_PROBLEM")
    assert "OBSERVED_LOW_MASTERY" not in result.decision.reason_codes


def test_weak_skills_tie_by_available_hint_dependency_before_independent_success_rate() -> None:
    attempts = (
        fact(1, 1, skill_id=1, outcome="GAVE_UP", correct=0, final_status=None),
        fact(2, 2, skill_id=1),
        fact(3, 3, skill_id=2, outcome="GAVE_UP", correct=0, final_status=None),
        fact(4, 4, skill_id=2),
    )
    result = recommend((candidate(1), candidate(2), candidate(3, skill_id=2), candidate(4, skill_id=2),
                        candidate(5), candidate(6, skill_id=2)), attempts,
                       (skill(1, mastery=0.4, attempts=2, successes=2),
                        skill(2, mastery=0.4, attempts=2, successes=2, hint_dependent=1)))
    assert_decision(result, "NEXT_PROBLEM", 6, "OBSERVED_LOW_MASTERY")
    assert result.decision.skill_id == 2


@pytest.mark.parametrize("failure", ["WRONG_ANSWER", "COMPILATION_ERROR", "RUNTIME_ERROR"])
def test_latest_evaluated_give_up_selects_same_difficulty_alternative(failure: str) -> None:
    result = recommend((candidate(1), candidate(2), candidate(3, difficulty="Medium")),
                       (fact(1, 1, outcome="GAVE_UP", correct=0, final_status=failure),),
                       (skill(attempts=1),))
    assert_decision(result, "RETRY_SIMILAR_PROBLEM", 2, "EVALUATED_FAILURE_RETRY")


def test_declared_give_up_without_evaluation_is_not_evaluated_remediation() -> None:
    result = recommend((candidate(1),),
                       (fact(1, 1, outcome="GAVE_UP", correct=0, final_status=None),),
                       (skill(attempts=1),))
    assert_decision(result, "RETRY_SIMILAR_PROBLEM", 1, "DECLARED_GIVE_UP_RETRY")
    assert "EVALUATED_FAILURE_RETRY" not in result.decision.reason_codes


def test_actual_level_four_delivery_triggers_assisted_success_practice() -> None:
    result = recommend((candidate(1), candidate(2)),
                       (fact(1, 1, correct=None, hint_level=4, hint_requests=2, has_hint_action=True),),
                       (skill(mastery=0.20, attempts=1, successes=1, hint_dependent=1),))
    assert_decision(result, "RETRY_SIMILAR_PROBLEM", 2, "ASSISTED_SUCCESS_PRACTICE")


@pytest.mark.parametrize("hint_level,hint_requests", [(0, 6), (3, 1)])
def test_requests_or_lower_delivered_levels_do_not_trigger_high_assistance_remediation(
    hint_level: int, hint_requests: int,
) -> None:
    result = recommend((candidate(1), candidate(2)),
                       (fact(1, 1, correct=None, hint_level=hint_level,
                             hint_requests=hint_requests, has_hint_action=True),),
                       (skill(attempts=1, successes=1, hint_dependent=1),))
    assert_decision(result, "NEXT_PROBLEM", 2, "NEW_PROBLEM")


def test_scheduled_review_at_boundary_requires_independent_success_and_no_forgetting_claim() -> None:
    result = recommend((candidate(1), candidate(2, difficulty="Medium")),
                       (fact(1, 1, days_ago=7),), (skill(mastery=0.60, attempts=1, successes=1),))
    assert_decision(result, "REVISE_CONCEPT", 1, "SCHEDULED_REVIEW_DUE")
    assert all("FORGET" not in reason and "RETENTION_FAILURE" not in reason
               for reason in result.decision.reason_codes)


def test_future_review_deadline_is_exposed_before_new_evidence_arrives() -> None:
    result = recommend((candidate(1), candidate(2)), (fact(1, 1, days_ago=6),),
                       (skill(mastery=0.60, attempts=1, successes=1),))
    assert_decision(result, "NEXT_PROBLEM", 2, "NEW_PROBLEM")
    assert result.reevaluate_at == NOW + timedelta(days=1)


def test_review_anchors_to_independent_success_not_recent_assisted_completion() -> None:
    attempts = (fact(1, 1, days_ago=8),
                fact(2, 2, days_ago=1, correct=None, hint_level=2, hint_requests=1, has_hint_action=True))
    result = recommend((candidate(1), candidate(2), candidate(3)), attempts,
                       (skill(mastery=0.65, attempts=2, successes=2, hint_dependent=1, days_ago=1),))
    assert_decision(result, "REVISE_CONCEPT", 1, "SCHEDULED_REVIEW_DUE")


def test_assisted_success_only_is_not_eligible_for_review_despite_old_timing() -> None:
    result = recommend((candidate(1), candidate(2)),
                       (fact(1, 1, days_ago=30, correct=None, hint_level=1, has_hint_action=True),),
                       (skill(mastery=0.65, attempts=1, successes=1, hint_dependent=1),))
    assert_decision(result, "NEXT_PROBLEM", 2, "NEW_PROBLEM")
    assert result.reevaluate_at is None


def test_revision_selects_most_overdue_supported_skill() -> None:
    result = recommend((candidate(1), candidate(2, skill_id=2)),
                       (fact(1, 1, days_ago=9), fact(2, 2, skill_id=2, days_ago=8)),
                       (skill(1, mastery=0.65, attempts=1, successes=1),
                        skill(2, mastery=0.65, attempts=1, successes=1)))
    assert_decision(result, "REVISE_CONCEPT", 1, "SCHEDULED_REVIEW_DUE")


def test_independent_success_on_distinct_problems_promotes_at_threshold() -> None:
    result = recommend((candidate(1), candidate(2), candidate(3, difficulty="Medium")),
                       (fact(1, 1), fact(2, 2)), (skill(mastery=0.70, attempts=2, successes=2),))
    assert_decision(result, "INCREASE_DIFFICULTY", 3, "INDEPENDENT_SUCCESS_PROGRESSION")


@pytest.mark.parametrize("case", ["repeated_problem", "assisted", "below_threshold", "different_difficulty"])
def test_promotion_requires_distinct_independent_same_level_corroboration(case: str) -> None:
    candidates = (candidate(1), candidate(2), candidate(3, difficulty="Medium"))
    second = fact(2, 2)
    mastery = 0.8
    if case == "repeated_problem":
        second = fact(2, 1)
    elif case == "assisted":
        second = fact(2, 2, correct=None, has_hint_action=True, hint_requests=1)
    elif case == "below_threshold":
        mastery = 0.699
    else:
        candidates = (candidate(1), candidate(2, difficulty="Medium"), candidate(3, difficulty="Hard"))
    result = recommend(candidates, (fact(1, 1), second),
                       (skill(mastery=mastery, attempts=2, successes=2),))
    assert result.decision is not None
    assert result.decision.action_type != "INCREASE_DIFFICULTY"


@pytest.mark.parametrize("failure", ["WRONG_ANSWER", "TIME_LIMIT_EXCEEDED", "MEMORY_LIMIT_EXCEEDED"])
def test_two_independent_evaluated_failures_demote_before_same_level_retry(failure: str) -> None:
    result = recommend((candidate(1, difficulty="Medium"), candidate(2, difficulty="Medium"), candidate(3)),
                       (fact(1, 1, outcome="GAVE_UP", correct=0, final_status=failure),
                        fact(2, 2, outcome="GAVE_UP", correct=0, final_status=failure)),
                       (skill(mastery=0.20, attempts=2),))
    assert_decision(result, "DECREASE_DIFFICULTY", 3, "CONSECUTIVE_EVALUATED_FAILURES")


@pytest.mark.parametrize("break_kind", ["abandoned", "assisted", "solved", "missing", "system", "runtime", "different_difficulty"])
def test_nonqualifying_terminal_fact_breaks_demotion_streak(break_kind: str) -> None:
    candidates = (candidate(1, difficulty="Medium"), candidate(2, difficulty="Medium"),
                  candidate(3, difficulty="Medium"), candidate(4))
    first = fact(1, 1, outcome="GAVE_UP", correct=0, final_status="WRONG_ANSWER")
    middle = fact(2, 2, outcome="GAVE_UP", correct=0, final_status="WRONG_ANSWER")
    if break_kind == "abandoned":
        middle = fact(2, 2, status="ABANDONED", outcome=None, correct=None, final_status=None)
    elif break_kind == "assisted":
        middle = fact(2, 2, outcome="GAVE_UP", correct=None, final_status="WRONG_ANSWER", has_hint_action=True)
    elif break_kind == "solved":
        middle = fact(2, 2)
    elif break_kind == "missing":
        middle = fact(2, 2, outcome="GAVE_UP", correct=0, final_status=None)
    elif break_kind == "system":
        middle = fact(2, 2, outcome="GAVE_UP", correct=None, final_status="SYSTEM_ERROR")
    elif break_kind == "runtime":
        middle = fact(2, 2, outcome="GAVE_UP", correct=0, final_status="RUNTIME_ERROR")
    else:
        candidates = (candidate(1, difficulty="Medium"), candidate(2),
                      candidate(3, difficulty="Medium"), candidate(4))
    last = fact(3, 3, outcome="GAVE_UP", correct=0, final_status="WRONG_ANSWER")
    result = recommend(candidates, (first, middle, last), (skill(attempts=3),))
    assert result.decision is not None
    assert result.decision.action_type == "RETRY_SIMILAR_PROBLEM"
    assert "CONSECUTIVE_EVALUATED_FAILURES" not in result.decision.reason_codes


def test_demotion_without_lower_level_falls_through_to_same_level_retry() -> None:
    result = recommend((candidate(1), candidate(2), candidate(3)),
                       (fact(1, 1, outcome="GAVE_UP", correct=0, final_status="WRONG_ANSWER"),
                        fact(2, 2, outcome="GAVE_UP", correct=0, final_status="WRONG_ANSWER")),
                       (skill(attempts=2),))
    assert_decision(result, "RETRY_SIMILAR_PROBLEM", 3, "EVALUATED_FAILURE_RETRY")


def test_catalogue_coverage_prefers_less_practiced_supported_skill() -> None:
    result = recommend((candidate(1), candidate(2), candidate(3, skill_id=2)),
                       (fact(1, 1),), (skill(1, mastery=0.60, attempts=1, successes=1), skill(2)))
    assert_decision(result, "NEXT_PROBLEM", 3, "UNPRACTICED_SKILL")


def test_unsupported_candidates_only_supply_coverage_not_false_skill_targeting() -> None:
    result = recommend((candidate(1), candidate(2, skill_id=None, mapping_status="multiple_skills_require_policy")),
                       (fact(1, 1),), (skill(mastery=0.20, attempts=1, successes=1),))
    assert_decision(result, "NEXT_PROBLEM", 2, "UNATTRIBUTED_CATALOGUE")
    assert result.decision.skill_id is None


def test_latest_abandonment_can_retry_original_unattributed_problem_without_mastery_claim() -> None:
    problem = candidate(1, skill_id=None, mapping_status="nonunit_weight_requires_policy")
    result = recommend((problem,), (fact(1, 1, skill_id=None, status="ABANDONED", outcome=None,
                                       correct=None, final_status=None),))
    assert_decision(result, "RETRY_SIMILAR_PROBLEM", 1, "ABANDONED_PROBLEM_RETRY")
    assert result.decision.skill_id is None
    assert "CONSECUTIVE_EVALUATED_FAILURES" not in result.decision.reason_codes


def test_assisted_only_solved_problem_can_be_revisited_without_changing_mastery() -> None:
    result = recommend((candidate(1),),
                       (fact(1, 1, correct=None, hint_level=1, has_hint_action=True),),
                       (skill(attempts=1, successes=1, hint_dependent=1),))
    assert_decision(result, "RETRY_SIMILAR_PROBLEM", 1, "INDEPENDENT_PRACTICE_PENDING")


def test_independent_success_resolves_an_older_give_up_or_assisted_only_revisit() -> None:
    attempts = (
        fact(1, 1, outcome="GAVE_UP", correct=0, final_status=None),
        fact(2, 1, correct=None, hint_level=1, has_hint_action=True),
        fact(3, 1),
    )
    result = recommend((candidate(1),), attempts,
                       (skill(mastery=0.60, attempts=3, successes=2, hint_dependent=1),))
    assert result.decision is None
    assert result.unavailable_reason == "CATALOGUE_EXHAUSTED"


@pytest.mark.parametrize("outcome", ["GAVE_UP", "SOLVED"])
@pytest.mark.parametrize("historical_skill", [None, 2])
def test_new_mapping_does_not_reattribute_unsupported_historical_revisit(
    outcome: str, historical_skill: int | None,
) -> None:
    historical = fact(1, 1, skill_id=historical_skill, outcome=outcome, correct=None,
                      final_status="WRONG_ANSWER" if outcome == "GAVE_UP" else "ACCEPTED",
                      has_hint_action=outcome == "SOLVED")
    result = recommend((candidate(1),), (historical,))
    assert result.decision is None
    assert result.unavailable_reason == "CATALOGUE_EXHAUSTED"


def test_independently_solved_problem_is_not_recycled_before_review_due() -> None:
    result = recommend((candidate(1),), (fact(1, 1),), (skill(mastery=0.60, attempts=1, successes=1),))
    assert result.decision is None
    assert result.unavailable_reason == "CATALOGUE_EXHAUSTED"
    assert result.reevaluate_at == NOW + timedelta(days=7)


def test_policy_preserves_inputs_and_is_deterministic_for_reordered_snapshots() -> None:
    context = RecommendationContext(
        evaluated_at=NOW, candidates=(candidate(3), candidate(2), candidate(1)),
        attempts=(fact(2, 2), fact(1, 1, outcome="GAVE_UP", correct=0, final_status=None)),
        skills=(skill(mastery=0.40, attempts=2, successes=1),),
    )
    before = context.model_dump(mode="json")
    policy = RecommendationPolicy(RecommendationPolicyConfig())
    first = policy.recommend(context)
    second = policy.recommend(context)
    reversed_context = context.model_copy(update={
        "candidates": tuple(reversed(context.candidates)), "attempts": tuple(reversed(context.attempts)),
    })
    assert first == second == policy.recommend(reversed_context)
    assert context.model_dump(mode="json") == before


def test_policy_config_loads_explicit_versioned_uncalibrated_defaults() -> None:
    config = load_policy_config()
    assert config.version == "adaptive-rules-v1"
    assert config.weak_min_observations == 2
    assert config.weak_mastery_threshold == 0.50
    assert config.review_mastery_threshold == 0.60
    assert config.review_interval_days == 7
    assert config.promotion_mastery_threshold == 0.70
    assert config.promotion_consecutive_solves == 2
    assert config.demotion_consecutive_struggles == 2
    assert config.assisted_success_hint_level == 4


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_policy_probability_configuration_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        RecommendationPolicyConfig(weak_mastery_threshold=value)


def test_fractional_observation_cannot_enter_binary_recommendation_evidence() -> None:
    with pytest.raises(ValidationError):
        fact(1, 1, correct=0.6)


def test_active_attempt_is_rejected_without_inventing_sixth_action() -> None:
    context = RecommendationContext(evaluated_at=NOW, candidates=(candidate(1),),
                                    attempts=(), skills=(), active_attempt_ids=(9,))
    with pytest.raises(ValueError):
        RecommendationPolicy(RecommendationPolicyConfig()).recommend(context)
