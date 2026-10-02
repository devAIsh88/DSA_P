"""Pure deterministic adaptive rules over already-validated learner evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas.attempt import AttemptOutcome, AttemptStatus
from app.schemas.recommendation import (
    RecommendationAction as Action,
    RecommendationCandidate,
    RecommendationContext,
    RecommendationDecision,
    RecommendationPolicyConfig,
    RecommendationReasonCode as Reason,
    RecommendationResult,
    RecommendationSkillState,
    RecommendationUnavailableReason as Unavailable,
    TerminalEvidence,
)


POLICY_FILE = Path(__file__).resolve().parents[2] / "config" / "recommendation_policy.json"
_FAILED_EVALUATIONS = frozenset({
    "WRONG_ANSWER", "TIME_LIMIT_EXCEEDED", "MEMORY_LIMIT_EXCEEDED",
    "COMPILATION_ERROR", "RUNTIME_ERROR",
})


def load_policy_config(path: Path = POLICY_FILE) -> RecommendationPolicyConfig:
    """Load explicit versioned MVP heuristics without provider/runtime dependencies."""

    return RecommendationPolicyConfig.model_validate_json(path.read_text(encoding="utf-8"))


class RecommendationPolicy:
    """Ordered rule cascade; neither history nor learner state is changed."""

    def __init__(self, config: RecommendationPolicyConfig) -> None:
        self.config = config

    def _difficulty(self, candidate: RecommendationCandidate | None) -> int | None:
        if candidate is None:
            return None
        normalized = candidate.difficulty.strip().casefold()
        return next((index for index, level in enumerate(self.config.difficulty_order)
                     if level.strip().casefold() == normalized), None)

    def _eligible(self, candidate: RecommendationCandidate) -> bool:
        if self._difficulty(candidate) is None:
            return False
        if self.config.target_track is not None:
            if candidate.target_track is None or candidate.target_track.strip() != self.config.target_track.strip():
                return False
        return (candidate.skill_id is not None or self.config.allow_unattributed_catalogue)

    def _select(
        self, candidates: list[RecommendationCandidate], attempted: set[int], latest_problem: int | None,
    ) -> RecommendationCandidate | None:
        if not candidates:
            return None
        return min(candidates, key=lambda item: (
            item.problem_id in attempted,
            self.config.avoid_immediate_repetition and item.problem_id == latest_problem,
            item.problem_id,
        ))

    @staticmethod
    def _decision(candidate: RecommendationCandidate, action: Action, reason: Reason) -> RecommendationDecision:
        reasons = (reason,)
        if candidate.skill_id is None and action == Action.NEXT_PROBLEM:
            reasons += (Reason.UNATTRIBUTED_CATALOGUE,)
        return RecommendationDecision(action_type=action, problem_id=candidate.problem_id,
                                      skill_id=candidate.skill_id, reason_codes=reasons)

    def _skill_candidates(
        self, candidates: list[RecommendationCandidate], skill_id: int, difficulty: int | None = None,
    ) -> list[RecommendationCandidate]:
        return [item for item in candidates if item.skill_id == skill_id
                and (difficulty is None or self._difficulty(item) == difficulty)]

    @staticmethod
    def _history(context: RecommendationContext) -> list[TerminalEvidence]:
        seen: set[int] = set()
        history = []
        for fact in sorted(context.attempts, key=lambda item: item.event_id):
            if fact.attempt_id not in seen:
                seen.add(fact.attempt_id)
                history.append(fact)
        return history

    @staticmethod
    def _independent(fact: TerminalEvidence) -> bool:
        return not (fact.has_hint_action or fact.hint_requests or fact.max_hint_level)

    def _review_schedule(
        self, history: list[TerminalEvidence], states: dict[int, RecommendationSkillState],
        candidates: list[RecommendationCandidate],
    ) -> list[tuple[datetime, int, TerminalEvidence]]:
        schedule = []
        for skill_id, state in states.items():
            successes = [fact for fact in history if fact.skill_id == skill_id and fact.binary_correct == 1]
            if (state.mastery_probability < self.config.review_mastery_threshold
                    or len(successes) < self.config.review_min_independent_successes
                    or not self._skill_candidates(candidates, skill_id)):
                continue
            latest_success = max(successes, key=lambda fact: (fact.occurred_at, fact.event_id))
            due = latest_success.occurred_at + timedelta(days=self.config.review_interval_days)
            schedule.append((due, skill_id, latest_success))
        return sorted(schedule, key=lambda item: (item[0], item[1]))

    def _demotion(
        self, history: list[TerminalEvidence], candidates: list[RecommendationCandidate],
        catalogue: dict[int, RecommendationCandidate], attempted: set[int],
    ) -> RecommendationDecision | None:
        latest = history[-1]
        if latest.skill_id is None:
            return None
        difficulty = self._difficulty(catalogue.get(latest.problem_id))
        if difficulty is None or difficulty == 0:
            return None
        run = [fact for fact in reversed(history) if fact.skill_id == latest.skill_id]
        run = run[:self.config.demotion_consecutive_struggles]
        if len(run) != self.config.demotion_consecutive_struggles:
            return None
        if any(fact.status != AttemptStatus.COMPLETED or fact.outcome != AttemptOutcome.GAVE_UP
               or fact.binary_correct != 0 or not self._independent(fact)
               or fact.final_status not in self.config.demotion_statuses
               or self._difficulty(catalogue.get(fact.problem_id)) != difficulty for fact in run):
            return None
        selected = self._select(self._skill_candidates(candidates, latest.skill_id, difficulty - 1),
                                attempted, latest.problem_id)
        return (self._decision(selected, Action.DECREASE_DIFFICULTY, Reason.CONSECUTIVE_EVALUATED_FAILURES)
                if selected is not None else None)

    def _remediation(
        self, latest: TerminalEvidence, candidates: list[RecommendationCandidate],
        catalogue: dict[int, RecommendationCandidate], attempted: set[int],
    ) -> RecommendationDecision | None:
        if latest.skill_id is None or latest.status != AttemptStatus.COMPLETED:
            return None
        reason = None
        if latest.outcome == AttemptOutcome.GAVE_UP and latest.final_status in _FAILED_EVALUATIONS:
            reason = Reason.EVALUATED_FAILURE_RETRY
        elif (latest.outcome == AttemptOutcome.SOLVED
              and latest.max_hint_level >= self.config.assisted_success_hint_level):
            reason = Reason.ASSISTED_SUCCESS_PRACTICE
        difficulty = self._difficulty(catalogue.get(latest.problem_id))
        if reason is None or difficulty is None:
            return None
        selected = self._select(self._skill_candidates(candidates, latest.skill_id, difficulty),
                                attempted, latest.problem_id)
        return self._decision(selected, Action.RETRY_SIMILAR_PROBLEM, reason) if selected is not None else None

    def _revision(
        self, schedule: list[tuple[datetime, int, TerminalEvidence]], context: RecommendationContext,
        candidates: list[RecommendationCandidate], attempted: set[int], latest_problem: int,
    ) -> RecommendationDecision | None:
        for due, skill_id, last_success in schedule:
            if due > context.evaluated_at:
                continue
            options = self._skill_candidates(candidates, skill_id)
            # A scheduled review deliberately revisits demonstrated independent success.
            selected = next((item for item in options if item.problem_id == last_success.problem_id), None)
            if selected is None:
                selected = self._select(options, attempted, latest_problem)
            if selected is not None:
                return self._decision(selected, Action.REVISE_CONCEPT, Reason.SCHEDULED_REVIEW_DUE)
        return None

    def _promotion(
        self, history: list[TerminalEvidence], states: dict[int, RecommendationSkillState],
        candidates: list[RecommendationCandidate], catalogue: dict[int, RecommendationCandidate],
        attempted: set[int],
    ) -> RecommendationDecision | None:
        latest = history[-1]
        state = states.get(latest.skill_id)
        difficulty = self._difficulty(catalogue.get(latest.problem_id))
        if (state is None or state.mastery_probability < self.config.promotion_mastery_threshold
                or difficulty is None or difficulty + 1 >= len(self.config.difficulty_order)):
            return None
        run = [fact for fact in reversed(history) if fact.skill_id == latest.skill_id]
        run = run[:self.config.promotion_consecutive_solves]
        if (len(run) != self.config.promotion_consecutive_solves
                or len({fact.problem_id for fact in run}) != len(run)
                or any(fact.status != AttemptStatus.COMPLETED or fact.outcome != AttemptOutcome.SOLVED
                       or fact.binary_correct != 1 or not self._independent(fact)
                       or self._difficulty(catalogue.get(fact.problem_id)) != difficulty for fact in run)):
            return None
        selected = self._select(self._skill_candidates(candidates, state.skill_id, difficulty + 1),
                                attempted, latest.problem_id)
        return (self._decision(selected, Action.INCREASE_DIFFICULTY, Reason.INDEPENDENT_SUCCESS_PROGRESSION)
                if selected is not None else None)

    def _weak_skill(
        self, history: list[TerminalEvidence], states: dict[int, RecommendationSkillState],
        candidates: list[RecommendationCandidate], catalogue: dict[int, RecommendationCandidate],
        attempted: set[int],
    ) -> RecommendationDecision | None:
        ranked = []
        for skill_id, state in states.items():
            observations = [fact for fact in history if fact.skill_id == skill_id and fact.binary_correct is not None]
            if (len(observations) < self.config.weak_min_observations
                    or state.mastery_probability > self.config.weak_mastery_threshold):
                continue
            hint_ratio = (state.hint_dependent_count / state.successful_attempt_count
                          if state.successful_attempt_count else None)
            solve_rate = sum(fact.binary_correct for fact in observations) / len(observations)
            last_practice = state.last_attempt_at or datetime.min.replace(tzinfo=UTC)
            ranked.append(((state.mastery_probability, hint_ratio is None,
                            -hint_ratio if hint_ratio is not None else 0, solve_rate,
                            last_practice, skill_id), state))
        for _, state in sorted(ranked, key=lambda item: item[0]):
            skill_history = [fact for fact in history if fact.skill_id == state.skill_id]
            anchor = skill_history[-1] if skill_history else None
            difficulty = self._difficulty(catalogue.get(anchor.problem_id)) if anchor is not None else None
            options = self._skill_candidates(candidates, state.skill_id, difficulty)
            if difficulty is None and options:
                lowest = min(self._difficulty(item) for item in options)
                options = [item for item in options if self._difficulty(item) == lowest]
            selected = self._select(options, attempted, history[-1].problem_id)
            if selected is not None:
                return self._decision(selected, Action.NEXT_PROBLEM, Reason.OBSERVED_LOW_MASTERY)
        return None

    def _coverage(
        self, history: list[TerminalEvidence], candidates: list[RecommendationCandidate],
        catalogue: dict[int, RecommendationCandidate], attempted: set[int],
    ) -> RecommendationDecision | None:
        supported = [item for item in candidates if item.skill_id is not None and item.problem_id not in attempted]
        skill_ids = {item.skill_id for item in supported}
        ranked = sorted(skill_ids, key=lambda skill_id: (
            sum(fact.skill_id == skill_id for fact in history), skill_id,
        ))
        for skill_id in ranked:
            options = self._skill_candidates(supported, skill_id)
            facts = [fact for fact in history if fact.skill_id == skill_id]
            anchor = self._difficulty(catalogue.get(facts[-1].problem_id)) if facts else None
            current = [item for item in options if self._difficulty(item) == anchor] if anchor is not None else []
            if current:
                options = current
            else:
                lowest = min(self._difficulty(item) for item in options)
                options = [item for item in options if self._difficulty(item) == lowest]
            selected = self._select(options, attempted, history[-1].problem_id)
            reason = Reason.UNPRACTICED_SKILL if not facts else Reason.NEW_PROBLEM
            return self._decision(selected, Action.NEXT_PROBLEM, reason)
        unattributed = [item for item in candidates if item.skill_id is None and item.problem_id not in attempted]
        if unattributed:
            selected = min(unattributed, key=lambda item: (self._difficulty(item), item.problem_id))
            return self._decision(selected, Action.NEXT_PROBLEM, Reason.NEW_PROBLEM)
        return None

    def _revisit(
        self, history: list[TerminalEvidence], candidates: list[RecommendationCandidate],
    ) -> RecommendationDecision | None:
        eligible = {item.problem_id: item for item in candidates}
        latest = history[-1]
        if latest.status == AttemptStatus.ABANDONED and latest.problem_id in eligible:
            return self._decision(eligible[latest.problem_id], Action.RETRY_SIMILAR_PROBLEM,
                                  Reason.ABANDONED_PROBLEM_RETRY)
        independently_solved = {fact.problem_id for fact in history if fact.binary_correct == 1}
        for fact in sorted(history, key=lambda item: (item.occurred_at, item.problem_id, item.event_id)):
            candidate = eligible.get(fact.problem_id)
            if (candidate is None or candidate.skill_id is None or fact.skill_id != candidate.skill_id
                    or fact.problem_id in independently_solved):
                continue
            if fact.status == AttemptStatus.COMPLETED and fact.outcome == AttemptOutcome.GAVE_UP:
                return self._decision(candidate, Action.RETRY_SIMILAR_PROBLEM, Reason.DECLARED_GIVE_UP_RETRY)
            if (fact.status == AttemptStatus.COMPLETED and fact.outcome == AttemptOutcome.SOLVED
                    and not self._independent(fact)):
                return self._decision(candidate, Action.RETRY_SIMILAR_PROBLEM, Reason.INDEPENDENT_PRACTICE_PENDING)
        return None

    def recommend(self, context: RecommendationContext) -> RecommendationResult:
        """Choose one persisted-action candidate or a defined empty result."""

        if context.active_attempt_ids:
            raise ValueError("The application must resolve the active Attempt gate before policy evaluation")
        if not context.candidates:
            return RecommendationResult(unavailable_reason=Unavailable.EMPTY_CATALOGUE)
        candidates = [item for item in context.candidates if self._eligible(item)]
        if not candidates:
            return RecommendationResult(unavailable_reason=Unavailable.NO_ELIGIBLE_PROBLEM)
        history = self._history(context)
        if not history:
            selected = min(candidates, key=lambda item: (
                self._difficulty(item), item.skill_id is None,
                item.skill_id if item.skill_id is not None else 0, item.problem_id,
            ))
            return RecommendationResult(decision=self._decision(selected, Action.NEXT_PROBLEM, Reason.COLD_START))
        states = {item.skill_id: item for item in context.skills}
        catalogue = {item.problem_id: item for item in context.candidates}
        attempted = {fact.problem_id for fact in history}
        schedule = self._review_schedule(history, states, candidates)
        reevaluate_at = min((due for due, _, _ in schedule if due > context.evaluated_at), default=None)
        decision = (
            self._demotion(history, candidates, catalogue, attempted)
            or self._remediation(history[-1], candidates, catalogue, attempted)
            or self._revision(schedule, context, candidates, attempted, history[-1].problem_id)
            or self._promotion(history, states, candidates, catalogue, attempted)
            or self._weak_skill(history, states, candidates, catalogue, attempted)
            or self._coverage(history, candidates, catalogue, attempted)
            or self._revisit(history, candidates)
        )
        if decision is None:
            return RecommendationResult(unavailable_reason=Unavailable.CATALOGUE_EXHAUSTED,
                                        reevaluate_at=reevaluate_at)
        return RecommendationResult(decision=decision, reevaluate_at=reevaluate_at)
