"""CIE Platform — SCR-01 Project Dashboard.

Presentation only. No business logic, no session_state writes.
Returns the selected project dict (or {"__action__": "new_project"}) to app.py.
"""

from __future__ import annotations

import streamlit as st

_STATE_BADGE: dict[str, str] = {
    "completed":         "✅ 完了",
    "running":           "⟳ 実行中",
    "waiting_for_human": "🟣 承認待ち",
    "failed":            "❌ 失敗",
    "retrying":          "🔄 リトライ中",
    "cancelled":         "🚫 キャンセル済み",
    "archived":          "📦 アーカイブ済み",
}

_STATE_BORDER: dict[str, str] = {
    "completed":         "#059669",  # --cie-success
    "running":           "#2E74C0",  # --cie-blue-500
    "waiting_for_human": "#7C3AED",  # --cie-approval
    "failed":            "#DC2626",  # --cie-critical
    "retrying":          "#D97706",  # --cie-warning
}

_DEFAULT_BADGE  = "○ 準備中"
_DEFAULT_BORDER = "#E5E7EB"   # --cie-gray-200


def render_dashboard(
    projects: list[dict],
    csv_filename: str | None = None,
    csv_size_bytes: int | None = None,
) -> dict | None:
    """Render SCR-01 Project Dashboard.

    Projects with ``waiting_for_human`` state are sorted to the front.

    Returns:
        The selected project dict, ``{"__action__": "new_project"}`` when the
        new-project button is clicked, or ``None`` if nothing was clicked.
    """
    col_title, col_btn = st.columns([6, 1])
    with col_title:
        st.title("CIE Platform")
    with col_btn:
        st.write("")  # vertical alignment spacer
        if st.button("＋ 新規プロジェクト", type="primary", key="new_project_btn"):
            return {"__action__": "new_project"}

    # Current dataset indicator
    if csv_filename is not None:
        size_label = f"{csv_size_bytes / 1024:.1f} KB" if csv_size_bytes else ""
        st.info(f"📂 読み込み済みデータセット: **{csv_filename}**　{size_label}")

    # Waiting-for-human banner (SCR-01 spec: priority display)
    waiting = [p for p in projects if p.get("workflow_state") == "waiting_for_human"]
    if waiting:
        st.warning(f"🟣 承認待ちのプロジェクトが {len(waiting)} 件あります")

    if not projects:
        st.info("プロジェクトがありません。「＋ 新規プロジェクト」から開始してください。")
        return None

    # Sort: waiting_for_human first, then by last_updated descending
    other = [p for p in projects if p.get("workflow_state") != "waiting_for_human"]

    def _last_updated(p: dict) -> str:
        return p.get("last_updated", "")

    sorted_projects = (
        sorted(waiting, key=_last_updated, reverse=True)
        + sorted(other, key=_last_updated, reverse=True)
    )

    # 3-column card grid
    cols = st.columns(3)
    for idx, project in enumerate(sorted_projects):
        with cols[idx % 3]:
            if _render_project_card(project):
                return project

    return None


def _render_project_card(project: dict) -> bool:
    """Render one ProjectCard. Returns True when the open button is clicked."""
    state        = project.get("workflow_state", "draft")
    badge        = _STATE_BADGE.get(state, _DEFAULT_BADGE)
    border_color = _STATE_BORDER.get(state, _DEFAULT_BORDER)
    name         = project.get("project_name") or project.get("execution_id", "Unknown")
    last_updated = project.get("last_updated", "—")
    approval_cnt = project.get("approval_pending_count", 0)
    quality_score = project.get("quality_score")

    with st.container(border=True):
        # Left-border accent (UP-009: consistent state representation)
        st.markdown(
            f'<div style="border-left:4px solid {border_color};'
            f'padding-left:8px;margin-bottom:6px;">'
            f'<strong style="font-size:15px">{name}</strong></div>',
            unsafe_allow_html=True,
        )

        st.markdown(f"**状態:** {badge}")
        st.caption(f"最終更新: {last_updated}")

        if approval_cnt > 0:
            st.markdown(
                f'<span style="color:#7C3AED;font-weight:600;">'
                f'🟣 承認待ち {approval_cnt} 件</span>',
                unsafe_allow_html=True,
            )

        if quality_score is not None and state == "completed":
            _render_quality_badge(quality_score)

        return st.button(
            "開く →",
            key=f"open_{project.get('execution_id', name)}",
            use_container_width=True,
        )


def _render_quality_badge(score: float) -> None:
    if score >= 90:
        color, label = "#059669", "PASS"
    elif score >= 70:
        color, label = "#D97706", "REVIEW"
    else:
        color, label = "#DC2626", "FAIL"

    st.markdown(
        f'<span style="color:{color};font-weight:600;">'
        f'品質スコア: {score:.0f} [{label}]</span>',
        unsafe_allow_html=True,
    )
