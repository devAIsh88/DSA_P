"""Shared presentation helpers for explicit commands and safe navigation."""

from collections.abc import Callable
from typing import TypeVar

import streamlit as st

from frontend.api_client import APIError
from frontend.state import finish_operation, operation_key

T = TypeVar("T")


def navigate(problem_id: int, attempt_id: int | None = None) -> None:
    st.query_params.clear()
    st.query_params["problem_id"] = str(problem_id)
    if attempt_id is not None:
        st.query_params["attempt_id"] = str(attempt_id)
    st.rerun()


def invoke(action: str, payload: dict, call: Callable[[str], T]) -> T | None:
    """No automatic retry: retain identity after uncertainty, then reload saved state."""
    if st.session_state.get("busy", False):
        return None
    key = operation_key(st.session_state, action, payload)
    st.session_state["busy"] = True
    try:
        with st.spinner("Working…"):
            result = call(key)
        finish_operation(st.session_state, action)
        if not action.startswith("run:"):
            st.session_state.pop("recommendation_response", None)
        return result
    except APIError as error:
        st.session_state["notice"] = ("error", str(error))
        return None
    finally:
        st.session_state["busy"] = False


def render_notice() -> None:
    notice = st.session_state.pop("notice", None)
    if notice:
        kind, text = notice
        getattr(st, kind)(text)
