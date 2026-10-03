"""Honest public reporting; estimates and count scopes remain explicit."""

from collections.abc import Sequence

import streamlit as st

from app.schemas.dashboard import DashboardSummaryResponse, SkillProgressResponse


def _duration(value: float | None) -> str:
    return "—" if value is None else f"{value / 1000:.1f} s"


def render_skills(skills: Sequence[SkillProgressResponse]) -> None:
    st.subheader("Skill progress")
    if not skills:
        st.info("No supported skill reporting yet. Complete a mapped problem to record your first activity.")
        return
    st.caption("Estimated mastery is a model estimate, not certainty. Reporting covers terminal Attempts with supported single-skill mappings; assisted reporting does not become independent mastery evidence.")
    st.dataframe([{
        "Skill": skill.skill_name,
        "Estimated mastery": f"{skill.mastery_probability:.1%}",
        "Tracked terminal Attempts": skill.attempt_count,
        "Successful Attempts": skill.successful_attempt_count,
        "Independent solves": skill.independent_solve_count,
        "Hint-associated solves": skill.hint_dependent_count,
        "Hint requests": skill.hint_count_total,
        "Mean delivered hint level": "—" if skill.average_hint_level is None else f"{skill.average_hint_level:.2f}",
        "Mean terminal Attempt duration": _duration(skill.average_duration_ms),
    } for skill in skills], hide_index=True, width="stretch")
    st.caption("Hint-associated solves are successful Attempts with recorded hint requests or deliveries. Mean duration includes all tracked terminal outcomes, not only successful solves.")
    with st.expander("Skill descriptions and model versions"):
        for skill in skills:
            st.write(skill.skill_name)
            if skill.skill_description:
                st.write(skill.skill_description)
            st.caption(f"Model {skill.model_version} · Parameters {skill.param_version}")


def render_progress(summary: DashboardSummaryResponse) -> None:
    st.subheader("Activity summary")
    columns = st.columns(4)
    columns[0].metric("Catalogue problems", summary.catalogue_problem_count)
    columns[1].metric("Recorded Attempts", summary.attempt_count)
    columns[2].metric("Solved Attempts", summary.solved_attempt_count)
    columns[3].metric("Unique solved problems", summary.unique_solved_problem_count)
    st.caption(f"Completed Attempts: {summary.completed_attempt_count} · Abandoned Attempts: {summary.abandoned_attempt_count}. These counts cover this learner's actual history, including activity without supported skill attribution.")
    columns = st.columns(2)
    columns[0].metric("Hint requests", summary.hint_request_count)
    columns[1].metric("Hints delivered", summary.hint_delivery_count)
    with st.expander("Independent and assisted solve reporting"):
        st.write(f"Supported successful Attempts: {summary.successful_supported_attempt_count}")
        st.write(f"Independent solves: {summary.independent_solve_count}")
        st.write(f"Hint-associated solves: {summary.hint_dependent_solve_count}")
        if summary.independent_solve_share is None:
            st.caption("Solve shares are unavailable until at least one supported successful Attempt exists.")
        else:
            st.write(f"Independent share: {summary.independent_solve_share:.1%}")
            hint_share = "—" if summary.hint_dependency_share is None else f"{summary.hint_dependency_share:.1%}"
            st.write(f"Hint-associated share: {hint_share}")
        st.caption("Both shares divide the respective supported solve count by supported successful Attempts. They are not global accuracy, placement readiness or calibrated confidence.")
    render_skills(summary.skills)
