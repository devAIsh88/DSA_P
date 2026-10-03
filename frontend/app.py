"""Run with: python -m streamlit run frontend/app.py."""

import sys
from pathlib import Path

# Streamlit executes this file directly, so resolve the package root independently of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from pydantic import ValidationError

from frontend.api_client import APIClient, APIError
from frontend.config import UISettings
from frontend.state import positive_id
from frontend.interaction import render_notice
from frontend.views.home import render_home
from frontend.views.workspace import render_workspace


def main() -> None:
    st.set_page_config(page_title="DEV Placement OS", layout="wide")
    st.title("DEV Placement OS")
    st.caption("Practice Python • preserve reasoning • learn from deterministic evidence")
    try:
        settings = UISettings()
    except ValidationError:
        st.error("Check the local UI configuration. No private configuration values are displayed.")
        return
    if settings.learner_id is None:
        st.info("Run python -m scripts.provision_demo, then set UI_LEARNER_ID to its reported learner ID.")
        return
    client = APIClient(settings.api_base_url, settings.request_timeout_seconds)
    try:
        learner = client.learner()
    except APIError as error:
        st.error(str(error))
        st.caption("Check FastAPI and explicit demo provisioning; the UI does not create accounts.")
        return
    if learner.user_id != settings.learner_id:
        st.error("UI_LEARNER_ID does not match the backend learner. Correct local configuration before continuing.")
        return
    if st.sidebar.button("Home / Progress"):
        st.query_params.clear()
        st.rerun()
    render_notice()
    attempt_id = positive_id(st.query_params.get("attempt_id"))
    problem_id = positive_id(st.query_params.get("problem_id"))
    if attempt_id or problem_id:
        render_workspace(client, learner, problem_id, attempt_id)
    else:
        render_home(client, learner)


if __name__ == "__main__":
    main()
