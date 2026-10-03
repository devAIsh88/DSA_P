"""Targeted tutor interactions; recorded learner evidence remains authoritative."""

from __future__ import annotations

import streamlit as st

from app.schemas.attempt import AttemptResponse, AttemptStatus
from app.schemas.learning_event import LearningEventResponse, LearningEventType
from app.schemas.submission import SubmissionReadResponse
from app.schemas.tutor import (
    DiagnoseRequest, DiagnoseResponse, HintRequest, HintResponse, PostExplanationRequest,
    PostExplanationResponse, ReasoningAnalysisRequest, ReasoningAnalysisResponse,
    UnderstandingAnswerRequest, UnderstandingAnswerResponse, UnderstandingCheckRequest,
)
from frontend.api_client import APIClient
from frontend.interaction import invoke
from frontend.state import latest_reasoning


_HINT_LABELS = {
    1: "Direction", 2: "Missing information", 3: "Structure",
    4: "Pattern", 5: "Implementation", 6: "Full explanation / solution",
}


def _text(event: LearningEventResponse, field: str) -> str:
    """Only text from the public evidence allowlist is displayed."""

    value = event.evidence.get(field)
    return value if isinstance(value, str) else ""


def _remember(attempt_id: int, event_id: int, response: object) -> None:
    # Response labels exist only in this session. Event-only recovery must not
    # recreate classifications or provider source that the read API omitted.
    st.session_state.setdefault(f"tutor_responses:{attempt_id}", {})[event_id] = response


def _hint_history(attempt: AttemptResponse, events: list[LearningEventResponse]) -> None:
    hints = [event for event in events if event.event_type in (
        LearningEventType.HINT_REQUESTED, LearningEventType.HINT_DELIVERED,
    )]
    if not hints:
        return
    delivered_requests = {request_id for event in hints
                          if event.event_type == LearningEventType.HINT_DELIVERED
                          for request_id in [event.evidence.get("request_event_id")]
                          if type(request_id) is int}
    remembered = st.session_state.get(f"tutor_responses:{attempt.id}", {})
    with st.expander("Recorded hint activity"):
        for event in sorted(hints, key=lambda item: item.attempt_sequence):
            if event.event_type == LearningEventType.HINT_REQUESTED:
                level = event.evidence.get("hint_level_requested")
                st.caption(f"Hint requested: Level {level} · event {event.id}")
                if event.id not in delivered_requests:
                    st.caption("No delivered hint is recorded for this request.")
            else:
                level = event.evidence.get("hint_level_delivered")
                st.caption(f"Hint delivered: Level {level} · event {event.id}")
                response = remembered.get(event.id)
                if isinstance(response, HintResponse):
                    st.caption("Safe static fallback" if response.source == "fallback" else "AI-generated hint")
                st.text(_text(event, "hint_text"))


def _feedback_history(attempt: AttemptResponse, events: list[LearningEventResponse]) -> None:
    fields = {
        LearningEventType.TUTOR_DIAGNOSIS_GENERATED: ("AI diagnosis", "diagnosis_summary"),
        LearningEventType.TUTOR_REASONING_ANALYSIS_GENERATED: ("AI reasoning feedback", "feedback_text"),
        LearningEventType.POST_ATTEMPT_EXPLANATION_GENERATED: ("AI post-attempt explanation", "explanation_text"),
    }
    remembered = st.session_state.get(f"tutor_responses:{attempt.id}", {})
    for event in sorted(events, key=lambda item: item.attempt_sequence):
        if event.event_type not in fields:
            continue
        title, field = fields[event.event_type]
        with st.expander(f"{title} · event {event.id}", expanded=True):
            st.caption("AI interpretation; it does not determine code correctness or mastery.")
            st.text(_text(event, field))
            response = remembered.get(event.id)
            if isinstance(response, DiagnoseResponse):
                if response.misconception_category is not None:
                    st.caption(f"AI classification: {response.misconception_category.value.replace('_', ' ').title()}")
                if response.misconception_label:
                    st.text(response.misconception_label)
            elif isinstance(response, ReasoningAnalysisResponse):
                st.caption(f"AI reasoning assessment: {response.reasoning_quality.value.replace('_', ' ').title()}")
            elif isinstance(response, PostExplanationResponse):
                st.text(response.key_insight)
            elif event.event_type == LearningEventType.POST_ATTEMPT_EXPLANATION_GENERATED:
                st.text(_text(event, "key_insight"))


def _understanding_checks(client: APIClient, attempt: AttemptResponse,
                          events: list[LearningEventResponse], busy: bool) -> None:
    checks = [event for event in events if event.event_type == LearningEventType.UNDERSTANDING_CHECK
              and event.evidence.get("stage") == "PROMPTED"]
    remembered = st.session_state.get(f"tutor_responses:{attempt.id}", {})
    for check in sorted(checks, key=lambda item: item.attempt_sequence):
        with st.expander(f"Understanding check · event {check.id}", expanded=True):
            st.caption(f"Deterministic question · {_text(check, 'question_version')}")
            st.text(_text(check, "question"))
            answers = [event for event in events if event.event_type == LearningEventType.UNDERSTANDING_CHECK
                       and event.evidence.get("stage") == "ANSWERED"
                       and event.evidence.get("check_event_id") == check.id]
            answer = max(answers, key=lambda item: item.attempt_sequence) if answers else None
            if answer is not None:
                st.caption("Saved learner answer")
                st.text(_text(answer, "answer_text"))
                st.button("Answer already saved", disabled=True,
                          key=f"understanding_saved:{attempt.id}:{check.id}")
                evaluations = [event for event in events
                               if event.event_type == LearningEventType.TUTOR_UNDERSTANDING_EVALUATED
                               and event.evidence.get("answer_event_id") == answer.id
                               and event.evidence.get("check_event_id") == check.id]
                if not evaluations:
                    st.info("Answer saved; AI evaluation unavailable.")
                for evaluation in sorted(evaluations, key=lambda item: item.attempt_sequence):
                    st.caption("AI interpretation of understanding; not a mastery update.")
                    st.text(_text(evaluation, "feedback_text"))
                    response = remembered.get(evaluation.id)
                    if isinstance(response, UnderstandingAnswerResponse):
                        st.caption(f"AI answer assessment: {response.answer_quality.value.replace('_', ' ').title()}")
                continue
            with st.form(f"understanding_answer_form:{attempt.id}:{check.id}"):
                answer_text = st.text_area("Your explanation", max_chars=20000,
                                           key=f"understanding_answer:{attempt.id}:{check.id}")
                send = st.form_submit_button("Save answer and request AI evaluation",
                                             disabled=busy or attempt.status != AttemptStatus.COMPLETED)
            if send:
                if not answer_text.strip():
                    st.session_state["notice"] = ("warning", "Enter an answer before saving.")
                else:
                    result = invoke(
                        f"understanding-answer:{attempt.id}:{check.id}",
                        {"attempt_id": attempt.id, "check_event_id": check.id, "answer_text": answer_text},
                        lambda key: client.answer(attempt.id, check.id, UnderstandingAnswerRequest(
                            answer_text=answer_text, idempotency_key=key,
                        )),
                    )
                    if result is not None:
                        _remember(attempt.id, result.evaluation_event_id, result)
                # Reload even after 503: the learner answer may already be committed.
                st.rerun()


def render_tutor(client: APIClient, attempt: AttemptResponse,
                 events: list[LearningEventResponse], submission: SubmissionReadResponse | None) -> None:
    """Render all six frozen flows without generating content on widget reruns."""

    st.subheader("Tutor feedback")
    st.caption("AI feedback is advisory. Execution results and backend learner state remain authoritative.")
    busy = bool(st.session_state.get("busy", False))
    active = attempt.status == AttemptStatus.ACTIVE
    completed = attempt.status == AttemptStatus.COMPLETED

    level = st.selectbox("Hint level", options=tuple(_HINT_LABELS),
                         format_func=lambda value: f"{value} — {_HINT_LABELS[value]}",
                         disabled=not active or busy, key=f"hint_level:{attempt.id}")
    st.caption("The backend applies the hint gate. A hint request can remain recorded even without delivery.")
    if st.button("Request hint", disabled=not active or busy, key=f"hint_request:{attempt.id}"):
        result = invoke(
            f"hint:{attempt.id}", {"attempt_id": attempt.id, "requested_level": level},
            lambda key: client.hint(HintRequest(attempt_id=attempt.id, requested_level=level,
                                               idempotency_key=key)),
        )
        if result is not None:
            _remember(attempt.id, result.delivery_event_id, result)
        st.rerun()
    _hint_history(attempt, events)

    evaluated = submission is not None and any(
        event.event_type == LearningEventType.SUBMISSION_EVALUATED
        and event.submission_id == submission.submission_id for event in events
    )
    diagnose = st.button("Diagnose latest submission", disabled=busy or not (active or completed) or not evaluated,
                         key=f"diagnose:{attempt.id}:{submission.submission_id if submission else 'none'}")
    if diagnose and submission is not None and evaluated and (active or completed):
        result = invoke(
            f"diagnose:{attempt.id}:{submission.submission_id}",
            {"attempt_id": attempt.id, "submission_id": submission.submission_id},
            lambda key: client.diagnose(attempt.id, DiagnoseRequest(
                submission_id=submission.submission_id, idempotency_key=key,
            )),
        )
        if result is not None:
            _remember(attempt.id, result.diagnosis_event_id, result)
        st.rerun()

    reasoning = latest_reasoning(events)
    analyze = st.button("Analyze saved reasoning", disabled=busy or not active or reasoning is None,
                        key=f"analyze_reasoning:{attempt.id}:{reasoning.id if reasoning else 'none'}")
    if analyze and active and reasoning is not None:
        result = invoke(
            f"reasoning-analysis:{attempt.id}:{reasoning.id}",
            {"attempt_id": attempt.id, "reasoning_event_id": reasoning.id},
            lambda key: client.analyze(attempt.id, ReasoningAnalysisRequest(
                reasoning_event_id=reasoning.id, idempotency_key=key,
            )),
        )
        if result is not None:
            _remember(attempt.id, result.analysis_event_id, result)
        st.rerun()

    if completed:
        if st.button("Explain this completed attempt", disabled=busy, key=f"post_explanation:{attempt.id}"):
            result = invoke(
                f"post-explanation:{attempt.id}", {"attempt_id": attempt.id},
                lambda key: client.explain(attempt.id, PostExplanationRequest(idempotency_key=key)),
            )
            if result is not None:
                _remember(attempt.id, result.explanation_event_id, result)
            st.rerun()
        if st.button("Request understanding check", disabled=busy, key=f"understanding_check:{attempt.id}"):
            invoke(
                f"understanding-prompt:{attempt.id}", {"attempt_id": attempt.id},
                lambda key: client.understanding_check(attempt.id, UnderstandingCheckRequest(idempotency_key=key)),
            )
            st.rerun()
    elif not active:
        st.caption("This Attempt is abandoned. Its recorded feedback remains available; retry starts a new Attempt.")

    _feedback_history(attempt, events)
    _understanding_checks(client, attempt, events, busy)
