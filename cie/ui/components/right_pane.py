"""CIE Platform — RightPane component.

Presentation only. No business logic (component-library.md, ui-principles UP-002, UP-005).
UI events (approve / cancel) are communicated back to app.py via return values so that
this component never mutates st.session_state directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

_MAX_FEED_ITEMS = 50


def render_right_pane(
    workflow_state: str | None,  # noqa: ARG001 — reserved for future workflow-status widget
    agent_activity_log: list[dict],
    approval_pending: bool,
    approval_context: dict | None,
) -> dict[str, bool]:
    """Render the right context pane.

    Returns:
        dict with keys ``"approved"`` and ``"cancelled"`` indicating whether the
        human clicked the respective button in the approval panel this render cycle.
        Callers should act on these values and update st.session_state accordingly.
    """
    result: dict[str, bool] = {"approved": False, "cancelled": False}

    if approval_pending and approval_context:
        result = _render_approval_panel(approval_context)
        st.divider()

    _render_activity_feed(agent_activity_log)

    return result


def _render_approval_panel(approval_context: dict) -> dict[str, bool]:
    st.markdown("### 🟣 HUMAN APPROVAL REQUIRED")
    st.warning(approval_context.get("title", "承認が必要な操作があります"))

    if approval_context.get("is_irreversible"):
        st.error("⚠️ この操作は取り消せません")

    description = approval_context.get("description")
    if description:
        st.markdown(description)

    code_block = approval_context.get("code_block")
    if code_block:
        lang = approval_context.get("code_language", "r")
        st.code(code_block, language=lang)

    confirmed = st.checkbox("内容を確認しました", key="approval_confirmed")

    col_cancel, col_approve = st.columns(2)

    approved = col_approve.button(
        "承認して実行",
        disabled=not confirmed,
        type="primary",
        key="approve_btn",
    )
    cancelled = col_cancel.button("キャンセル", key="cancel_btn")

    return {"approved": approved, "cancelled": cancelled}


def _render_activity_feed(agent_activity_log: list[dict]) -> None:
    st.subheader("Agent アクティビティ")

    recent = agent_activity_log[-_MAX_FEED_ITEMS:]

    if not recent:
        st.caption("アクティビティはまだありません")
        return

    for entry in reversed(recent):
        ts_raw = entry.get("timestamp", "")
        agent_id = entry.get("agent_id", "")
        action = entry.get("action", "")
        summary = entry.get("summary", "")
        severity = entry.get("severity", "INFO")

        try:
            dt = datetime.fromisoformat(ts_raw).astimezone(timezone.utc)
            ts_display = dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            ts_display = ts_raw

        line = f"[{ts_display}]  {agent_id:<12}  {action:<20}  {summary}"

        if severity in ("CRITICAL", "BREACH"):
            st.error(line)
        elif severity == "WARNING":
            st.warning(line)
        else:
            st.code(line, language=None)
