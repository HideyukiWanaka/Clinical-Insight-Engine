"""CIE Platform — StatusBar component.

Presentation only. No business logic (component-library.md, ui-principles UP-004).
"""

from __future__ import annotations

import streamlit as st


def render_status_bar(
    project_name: str | None,
    execution_id: str | None,
    connection_status: str,
    security_events: list[dict],
    workflow_state: str | None,  # noqa: ARG001 — reserved for future state-dependent styling
) -> None:
    """Render the single-row status bar at the top of the application.

    BREACH events trigger a full-width error overlay (UP-004).
    Returns nothing; UI events are propagated via st.session_state by the caller.
    """
    breach_events = [e for e in security_events if e.get("severity") == "BREACH"]
    critical_events = [e for e in security_events if e.get("severity") == "CRITICAL"]

    col_title, col_exec, col_conn, col_sec = st.columns([4, 2, 1, 1])

    with col_title:
        title = "CIE Platform"
        if project_name:
            title += f"  |  {project_name}"
        st.markdown(f"**{title}**")

    with col_exec:
        if execution_id:
            st.markdown(f"実行ID: `{execution_id[:8]}...`")

    with col_conn:
        if connection_status == "online":
            st.markdown("🟢 オンライン")
        elif connection_status == "offline":
            st.markdown("⚫ オフライン")
        else:
            st.markdown("🔄 確認中")

    with col_sec:
        if breach_events:
            st.markdown('<span style="color:#DC2626">🔴</span>', unsafe_allow_html=True)
        elif critical_events:
            st.markdown("🟠")
        else:
            st.markdown("🔒")

    if breach_events:
        first = breach_events[0]
        error_code = first.get("code", "UNKNOWN")
        timestamp = first.get("timestamp", "")
        st.error(
            f"🚨 セキュリティ違反が検出されました  "
            f"エラーコード: {error_code}  "
            f"発生時刻: {timestamp}"
        )
