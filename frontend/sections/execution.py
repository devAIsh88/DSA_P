"""Sample practice and persisted grading are intentionally distinct."""

import streamlit as st

from app.schemas.attempt import AttemptResponse
from app.schemas.execution import ExecutionStatus
from app.schemas.run import RunCreate, RunResponse
from app.schemas.submission import SubmissionCreate, SubmissionReadResponse, SubmissionResultResponse
from frontend.api_client import APIClient
from frontend.interaction import invoke

_STATUS_TEXT = {
    ExecutionStatus.ACCEPTED: "Accepted",
    ExecutionStatus.WRONG_ANSWER: "Wrong answer",
    ExecutionStatus.COMPILATION_ERROR: "Compilation error",
    ExecutionStatus.RUNTIME_ERROR: "Runtime error",
    ExecutionStatus.TIME_LIMIT_EXCEEDED: "Time limit exceeded",
    ExecutionStatus.MEMORY_LIMIT_EXCEEDED: "Memory limit exceeded",
    ExecutionStatus.SYSTEM_ERROR: "Execution infrastructure unavailable",
    ExecutionStatus.QUEUED: "Queued",
    ExecutionStatus.RUNNING: "Running",
}


def render_result(result: RunResponse | SubmissionResultResponse, *, sample_run: bool = False) -> None:
    st.subheader("Sample Run result" if sample_run else "Deterministic submission result")
    status = _STATUS_TEXT[result.overall_status]
    if result.overall_status == ExecutionStatus.SYSTEM_ERROR:
        st.warning(f"{status}. This is not evidence of learner incorrectness.")
    elif result.overall_status == ExecutionStatus.ACCEPTED:
        st.success(status)
    else:
        st.info(status)
    st.write(f"Tests passed: {result.tests_passed} / {result.tests_total}")
    if sample_run:
        st.caption("Public samples only. This does not count as a graded submission or permit solved completion.")
    if result.execution_time_ms is not None:
        st.caption(f"Execution time: {result.execution_time_ms:g} ms")
    if result.memory_used_kb is not None:
        st.caption(f"Memory: {result.memory_used_kb:g} KB")
    with st.expander("Test statuses"):
        for index, test in enumerate(result.test_results, 1):
            visibility = "Hidden" if test.is_hidden else "Public"
            st.write(f"{visibility} test {index}: {_STATUS_TEXT[test.status]}")
            if not test.is_hidden and test.stdout is not None:
                st.code(test.stdout, language="text")


def render_execution(client: APIClient, attempt: AttemptResponse, code: str,
                     submission: SubmissionReadResponse | None) -> None:
    run_key = f"run_result:{attempt.id}"
    active = attempt.status.value == "ACTIVE"
    disabled = not active or not code.strip() or st.session_state.get("busy", False)
    columns = st.columns(2)
    if columns[0].button("Run public samples", key=f"run:{attempt.id}", disabled=disabled):
        result = invoke(f"run:{attempt.id}", {"problem_id": attempt.problem_id, "code": code},
                        lambda key: client.run(RunCreate(problem_id=attempt.problem_id, code=code)))
        if result is not None:
            st.session_state[run_key] = result
        st.rerun()
    if columns[1].button("Submit for grading", key=f"submit:{attempt.id}", disabled=disabled, type="primary"):
        invoke(f"submit:{attempt.id}", {"problem_id": attempt.problem_id, "attempt_id": attempt.id, "code": code},
               lambda key: client.submit(SubmissionCreate(problem_id=attempt.problem_id,
                       attempt_id=attempt.id, code=code, idempotency_key=key)))
        st.rerun()
    if run_key in st.session_state:
        render_result(st.session_state[run_key], sample_run=True)
    if submission is not None:
        render_result(submission)
    else:
        st.caption("No persisted submission yet.")
