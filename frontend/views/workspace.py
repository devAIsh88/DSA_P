"""Problem engagement, authoritative recovery and explicit lifecycle commands."""

import streamlit as st

from app.schemas.attempt import (
    AttemptAbandon, AttemptComplete, AttemptOutcome, AttemptStart, ReasoningCreate,
)
from app.schemas.dashboard import LearnerStateResponse
from app.schemas.execution import ExecutionStatus
from frontend.api_client import APIClient, APIError
from frontend.interaction import invoke, navigate
from frontend.sections.execution import render_execution
from frontend.state import latest_reasoning, latest_submission_id


def render_workspace(client: APIClient, learner: LearnerStateResponse,
                     problem_id: int | None, attempt_id: int | None) -> None:
    attempt = None
    events = []
    try:
        if attempt_id is not None:
            attempt = client.attempt(attempt_id)
            problem_id = attempt.problem_id
            events = client.events(attempt.id)
        if problem_id is None:
            st.error("Select a problem or resume an Attempt from Home.")
            return
        problem = client.problem(problem_id)
    except APIError as error:
        st.error(str(error))
        return
    st.header("Problem Workspace")
    st.subheader(problem.title)
    st.caption(f"{problem.difficulty} • {problem.topic}" + (f" / {problem.subtopic}" if problem.subtopic else ""))
    st.text(problem.description)
    for label, text in (("Constraints", problem.constraints), ("Input format", problem.input_format),
                        ("Output format", problem.output_format)):
        if text:
            with st.expander(label):
                st.text(text)
    with st.expander("Public examples", expanded=True):
        if not problem.sample_test_cases:
            st.info("No public samples are configured. Grading may still be available.")
        for index, sample in enumerate(problem.sample_test_cases, 1):
            st.write(f"Example {index} — input")
            st.code(sample.input, language="text")
            st.write("Expected sample output")
            st.code(sample.expected_output, language="text")
    if attempt is None:
        st.caption("Viewing this problem has not started an Attempt.")
        if learner.active_attempts:
            st.info("Resume existing activity before starting another problem.")
            for current in learner.active_attempts:
                if st.button(f"Resume Attempt {current.id}", key=f"resume:{current.id}"):
                    navigate(current.problem_id, current.id)
        elif st.button("Start Attempt", type="primary", key=f"start:{problem.id}"):
            result = invoke(f"start:{problem.id}", {"user_id": learner.user_id, "problem_id": problem.id},
                            lambda key: client.start(AttemptStart(user_id=learner.user_id,
                                                    problem_id=problem.id, idempotency_key=key)))
            if result is not None:
                navigate(problem.id, result.id)
            st.rerun()
        return
    active = attempt.status.value == "ACTIVE"
    st.info(f"Attempt {attempt.id}: {attempt.status.value}" + (f" / {attempt.outcome.value}" if attempt.outcome else ""))
    submission = None
    submission_id = latest_submission_id(events)
    if submission_id is not None:
        try:
            submission = client.submission(submission_id)
        except APIError as error:
            st.warning(f"Saved submission could not be restored. {error}")
    code_key = f"code:{attempt.id}"
    if code_key not in st.session_state or not active:
        st.session_state[code_key] = submission.code if submission is not None else "# Read from stdin and write to stdout.\n"
    code = st.text_area("Python code", key=code_key, height=260, disabled=not active,
                        help="Drafts survive Streamlit reruns; unsaved edits may be lost on full reload.")
    reasoning = latest_reasoning(events)
    reasoning_key = f"reasoning:{attempt.id}"
    if reasoning_key not in st.session_state:
        st.session_state[reasoning_key] = reasoning.evidence.get("reasoning_text", "") if reasoning else ""
    if active:
        with st.form(f"reasoning_form:{attempt.id}"):
            reasoning_text = st.text_area("Reasoning (optional)", key=reasoning_key, max_chars=20000,
                                          help="Save explicitly; each revision adds historical evidence.")
            saved = st.form_submit_button("Save reasoning", disabled=st.session_state.get("busy", False))
        if saved:
            if not reasoning_text.strip():
                st.warning("Enter reasoning before saving.")
            else:
                invoke(f"reasoning:{attempt.id}", {"reasoning_text": reasoning_text},
                       lambda key: client.reasoning(attempt.id, ReasoningCreate(
                           reasoning_text=reasoning_text, idempotency_key=key)))
                st.rerun()
    if reasoning:
        with st.expander("Saved reasoning"):
            st.text(reasoning.evidence.get("reasoning_text", ""))
    render_execution(client, attempt, code, submission)
    if active:
        st.subheader("Finish this Attempt")
        accepted = submission is not None and submission.overall_status == ExecutionStatus.ACCEPTED
        columns = st.columns(3)
        if columns[0].button("Finish — solved", key=f"solved:{attempt.id}", disabled=not accepted):
            invoke(f"complete:{attempt.id}", {"outcome": "SOLVED"}, lambda key: client.complete(
                attempt.id, AttemptComplete(outcome=AttemptOutcome.SOLVED, idempotency_key=key)))
            st.rerun()
        if columns[1].button("Finish — gave up", key=f"gave_up:{attempt.id}"):
            invoke(f"complete:{attempt.id}", {"outcome": "GAVE_UP"}, lambda key: client.complete(
                attempt.id, AttemptComplete(outcome=AttemptOutcome.GAVE_UP, idempotency_key=key)))
            st.rerun()
        if columns[2].button("Abandon Attempt", key=f"abandon:{attempt.id}"):
            invoke(f"abandon:{attempt.id}", {}, lambda key: client.abandon(
                attempt.id, AttemptAbandon(idempotency_key=key)))
            st.rerun()
        if not accepted:
            st.caption("Solved completion requires the latest graded submission to be accepted; a sample Run is insufficient.")
    else:
        if learner.active_attempts:
            st.caption("Resume other active activity from Home before starting a revisit.")
        elif st.button("Start a new Attempt", key=f"revisit:{attempt.id}"):
            result = invoke(f"revisit:{attempt.id}", {"user_id": learner.user_id, "problem_id": problem.id},
                            lambda key: client.start(AttemptStart(user_id=learner.user_id,
                                                    problem_id=problem.id, idempotency_key=key)))
            if result is not None:
                navigate(problem.id, result.id)
            st.rerun()
        st.caption("View progress and get the next activity from Home.")
    # Tutor and history sections use only public DTOs, never database/provider imports.
    from frontend.sections.tutor import render_tutor

    render_tutor(client, attempt, events, submission)
    with st.expander("Attempt activity"):
        for event in events:
            st.caption(f"{event.attempt_sequence} • {event.event_type.value} • {event.occurred_at.isoformat()}")
