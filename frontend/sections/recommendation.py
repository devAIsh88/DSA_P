"""Present backend decisions without reproducing recommendation policy."""

from collections.abc import Mapping, Sequence

import streamlit as st

from app.schemas.attempt import AttemptResponse
from app.schemas.problem import ProblemListItemResponse
from app.schemas.recommendation import (
    RecommendationAction, RecommendationReasonCode, RecommendationResponse,
    RecommendationUnavailableReason,
)
from frontend.api_client import APIClient, APIError
from frontend.interaction import navigate


ACTION_LABELS = {
    RecommendationAction.NEXT_PROBLEM: "Next problem",
    RecommendationAction.REVISE_CONCEPT: "Scheduled concept review",
    RecommendationAction.RETRY_SIMILAR_PROBLEM: "Practice or revisit",
    RecommendationAction.INCREASE_DIFFICULTY: "Try the next difficulty",
    RecommendationAction.DECREASE_DIFFICULTY: "Practice at a lower difficulty",
}

REASON_TEXT = {
    RecommendationReasonCode.COLD_START: "Start with this problem.",
    RecommendationReasonCode.UNPRACTICED_SKILL: "Practice a skill with no recorded eligible observations yet.",
    RecommendationReasonCode.NEW_PROBLEM: "Try a problem you have not completed yet.",
    RecommendationReasonCode.UNATTRIBUTED_CATALOGUE: "Explore the catalogue; this choice does not imply skill mastery attribution.",
    RecommendationReasonCode.SCHEDULED_REVIEW_DUE: "Scheduled review is due; this is not evidence of forgetting.",
    RecommendationReasonCode.EVALUATED_FAILURE_RETRY: "Practice after a recent deterministic evaluation that did not pass.",
    RecommendationReasonCode.ASSISTED_SUCCESS_PRACTICE: "Practice independently after a solve with recorded hint assistance.",
    RecommendationReasonCode.ABANDONED_PROBLEM_RETRY: "Return to this unfinished problem.",
    RecommendationReasonCode.DECLARED_GIVE_UP_RETRY: "Revisit a problem you previously finished as gave up.",
    RecommendationReasonCode.INDEPENDENT_PRACTICE_PENDING: "Build more independent practice evidence at this difficulty.",
    RecommendationReasonCode.INDEPENDENT_SUCCESS_PROGRESSION: "Try the next difficulty after corroborated independent success.",
    RecommendationReasonCode.CONSECUTIVE_EVALUATED_FAILURES: "Practice at a lower difficulty after recent evaluated failures.",
    RecommendationReasonCode.OBSERVED_LOW_MASTERY: "Practice a skill with supported evidence and a low current mastery estimate.",
}

EMPTY_TEXT = {
    RecommendationUnavailableReason.EMPTY_CATALOGUE: "No problems are configured yet. Provision the local demo catalogue explicitly.",
    RecommendationUnavailableReason.NO_ELIGIBLE_PROBLEM: "The current catalogue has no problem eligible under the configured recommendation rules.",
    RecommendationUnavailableReason.CATALOGUE_EXHAUSTED: "No fresh, remedial or scheduled-review problem is currently eligible. You can still browse the catalogue.",
}


def render_active_attempts(attempts: Sequence[AttemptResponse],
                           problems: Mapping[int, ProblemListItemResponse]) -> None:
    """Offer explicit recovery without creating or reopening an Attempt."""

    st.info("Resume your active engagement before requesting another activity.")
    for attempt in sorted(attempts, key=lambda item: item.id):
        problem = problems.get(attempt.problem_id)
        title = problem.title if problem else f"Problem {attempt.problem_id}"
        st.write(f"Attempt {attempt.id} · {title} · ACTIVE")
        if st.button(f"Resume Attempt {attempt.id}", key=f"active_resume_{attempt.id}",
                     disabled=st.session_state.get("busy", False)):
            navigate(attempt.problem_id, attempt.id)


def _render_decision(recommendation: RecommendationResponse,
                     problems: Mapping[int, ProblemListItemResponse], *, saved: bool) -> None:
    problem = problems.get(recommendation.problem_id)
    title = problem.title if problem else f"Problem {recommendation.problem_id}"
    st.subheader(ACTION_LABELS[recommendation.action_type])
    st.write(title)
    if problem:
        st.caption(f"{problem.difficulty} · {problem.topic}")
    for reason in recommendation.reason_codes:
        st.write(REASON_TEXT[reason])
    st.caption(f"Policy: {recommendation.policy_version} · Recommendation {recommendation.id}")
    if saved:
        st.caption("Saved recommendation snapshot; it may be stale. Refresh to check current evidence and scheduling.")
    else:
        st.caption("Last requested backend decision. Refresh if activity or scheduling has changed.")
    if st.button("Open recommended problem", key="recommendation_open",
                 disabled=st.session_state.get("busy", False)):
        navigate(recommendation.problem_id)


def render_recommendation(client: APIClient, user_id: int, active_attempts: Sequence[AttemptResponse],
                          saved: RecommendationResponse | None,
                          problems: Mapping[int, ProblemListItemResponse]) -> None:
    """Issue only explicit requests; persisted snapshots never claim freshness."""

    st.subheader("Next activity")
    if active_attempts:
        st.session_state.pop("recommendation_response", None)
        st.session_state.pop("recommendation_error", None)
        render_active_attempts(active_attempts, problems)
        return
    if st.session_state.get("recommendation_user_id") != user_id:
        st.session_state.pop("recommendation_response", None)
        st.session_state.pop("recommendation_error", None)
        st.session_state["recommendation_user_id"] = user_id
    cached = st.session_state.get("recommendation_response")
    button_label = "Refresh recommendation" if cached is not None or saved is not None else "Get next activity"
    if st.button(button_label, key="recommendation_refresh", disabled=st.session_state.get("busy", False)):
        st.session_state["busy"] = True
        try:
            with st.spinner("Checking the next activity…"):
                cached = client.recommendation()
            st.session_state["recommendation_response"] = cached
            st.session_state.pop("recommendation_error", None)
        except APIError as error:
            st.session_state.pop("recommendation_response", None)
            cached = None
            st.session_state["recommendation_error"] = {
                "message": str(error), "code": error.code, "attempt_ids": error.attempt_ids,
            }
        finally:
            st.session_state["busy"] = False
    error = st.session_state.get("recommendation_error")
    if error:
        st.warning(error["message"])
        if error["code"] == "ACTIVE_ATTEMPT_EXISTS":
            recovered = []
            for attempt_id in error["attempt_ids"]:
                try:
                    attempt = client.attempt(attempt_id)
                    if attempt.status.value == "ACTIVE":
                        recovered.append(attempt)
                except APIError:
                    st.caption(f"Attempt {attempt_id} could not be recovered. Reload Home to check saved state.")
            if recovered:
                render_active_attempts(recovered, problems)
            return
    if cached is not None:
        if cached.recommendation:
            _render_decision(cached.recommendation, problems, saved=False)
        elif cached.unavailable_reason:
            st.info(EMPTY_TEXT[cached.unavailable_reason])
    elif saved is not None:
        _render_decision(saved, problems, saved=True)
    else:
        st.caption("Request a deterministic next activity, or browse the catalogue below.")
