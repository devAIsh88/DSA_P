"""Home and progress presentation using public HTTP reads only."""

import streamlit as st

from app.schemas.dashboard import LearnerStateResponse
from frontend.api_client import APIClient, APIError
from frontend.interaction import navigate, render_notice
from frontend.sections.progress import render_progress, render_skills
from frontend.sections.recommendation import render_recommendation


def render_home(client: APIClient, learner: LearnerStateResponse) -> None:
    st.header("Home / Progress")
    st.caption(f"Learner {learner.user_id} · backend state connected")
    render_notice()
    summary = None
    try:
        summary = client.dashboard()
    except APIError as error:
        st.warning(f"Activity summary unavailable. {error}")
    try:
        catalogue = client.problems()
    except APIError as error:
        catalogue = []
        st.warning(f"Problem catalogue unavailable. {error}")
    problem_by_id = {problem.id: problem for problem in catalogue}
    active_attempts = summary.active_attempts if summary is not None else learner.active_attempts
    render_recommendation(
        client, learner.user_id, active_attempts,
        summary.existing_recommendation if summary is not None else None, problem_by_id,
    )
    st.divider()
    st.subheader("Problem catalogue")
    st.caption("Opening a problem only displays it. Start an Attempt explicitly in the workspace.")
    if not catalogue:
        st.info("No catalogue problems are available to display. Check the backend and explicit demo provisioning.")
    for problem in catalogue:
        with st.expander(f"{problem.title} · {problem.difficulty}"):
            st.write(problem.topic)
            if problem.subtopic:
                st.caption(problem.subtopic)
            if st.button("Open problem", key=f"catalogue_open_{problem.id}",
                         disabled=st.session_state.get("busy", False)):
                navigate(problem.id)
    st.divider()
    if summary is not None:
        render_progress(summary)
        st.subheader("Recent Attempts")
        st.caption("Latest ten recorded Attempts; this is engagement history, not a list of unique solved problems.")
        if not summary.recent_attempts:
            st.info("No Attempts recorded yet.")
        for attempt in summary.recent_attempts:
            problem = problem_by_id.get(attempt.problem_id)
            title = problem.title if problem else f"Problem {attempt.problem_id}"
            outcome = f" · {attempt.outcome.value}" if attempt.outcome is not None else ""
            st.write(f"Attempt {attempt.id} · {title} · {attempt.status.value}{outcome}")
            st.caption(f"Started {attempt.started_at.isoformat()}")
            if st.button(f"View Attempt {attempt.id}", key=f"recent_view_{attempt.id}",
                         disabled=st.session_state.get("busy", False)):
                navigate(attempt.problem_id, attempt.id)
    else:
        render_skills(learner.skills)
