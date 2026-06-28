"""CIE Platform — SCR-06 Results & Report Editing screen.

Presentation only. No business logic, no explicit session_state writes.

Tab structure:
  📊 結果  — Key statistical results with traceability popovers
  🖼 図表  — Figures / charts from the execution
  📝 原稿  — AI-drafted manuscript sections (editable)

Returns {"export_approved": bool, "export_type": str} to app.py.
"""

from __future__ import annotations

import os

import streamlit as st

_EXPORT_TYPES = ["ローカルファイル (.docx)", "Google Docs（要オンライン）"]


def render_results(
    execution_result: dict,
    figures: list[dict],
    manuscript_sections: dict,
    review_result: dict,
    execution_id: str | None = None,
) -> dict:
    """Render SCR-06 Results & Report.

    Args:
        execution_result: Output from runtime execution agent.
        figures: List of figure dicts, each with at least ``title`` and
                 optionally ``path`` (image file) or ``figure`` (plt Figure).
        manuscript_sections: Section key → dict with ``text``, ``is_ai_generated``,
                              and optional ``unresolved_items`` list.
        review_result: Output from reviewer agent. Expected key: ``quality_score``.
        execution_id: Execution ID for traceability display.

    Returns:
        ``{"export_approved": bool, "export_type": str}``
        ``export_approved`` is True only on the render where the button is clicked.
    """
    st.title("結果・レポート編集")

    reviewer_score: int = int(review_result.get("quality_score", 0))

    # Reviewer score summary in a compact bar at the top
    _render_score_summary(reviewer_score, review_result)
    st.divider()

    tab_results, tab_figures, tab_manuscript = st.tabs(["📊 結果", "🖼 図表", "📝 原稿"])

    with tab_results:
        _render_results_tab(execution_result, execution_id)

    with tab_figures:
        _render_figures_tab(figures)

    with tab_manuscript:
        _render_manuscript_tab(manuscript_sections)

    # Export panel — always visible, disabled when score < 90 (SCR-06 spec)
    st.divider()
    return _render_export_panel(reviewer_score, review_result)


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def _render_results_tab(execution_result: dict, execution_id: str | None) -> None:
    primary: dict = execution_result.get("primary_result", {})

    if not primary:
        st.info("解析結果がありません。")
        return

    st.markdown("### 主要結果")

    # Display each numeric result as a metric with a traceability popover
    _eid = execution_id or "—"

    for field, value in primary.items():
        col_metric, col_trace = st.columns([4, 1])
        with col_metric:
            st.metric(label=field, value=_format_value(value))
        with col_trace:
            with st.popover("出典 🔍"):
                st.markdown(f"**フィールド:** `execution_result.primary_result.{field}`")
                st.markdown(f"**値:** `{value}`")
                st.markdown(f"**実行ID:** `{_eid}`")

    # Secondary / additional results
    secondary: dict = execution_result.get("secondary_results", {})
    if secondary:
        with st.expander("▼ 補足結果"):
            st.json(secondary)

    # Effect size / confidence intervals
    effect_size: dict = execution_result.get("effect_size", {})
    if effect_size:
        st.markdown("### 効果量・信頼区間")
        for field, value in effect_size.items():
            st.markdown(f"- **{field}:** {_format_value(value)}")


def _render_figures_tab(figures: list[dict]) -> None:
    if not figures:
        st.info("図表がありません。")
        return

    for fig in figures:
        title = fig.get("title", "図")
        st.markdown(f"#### {title}")

        # Matplotlib Figure object
        mpl_fig = fig.get("figure")
        if mpl_fig is not None:
            st.pyplot(mpl_fig)
            st.divider()
            continue

        # File path
        path: str | None = fig.get("path")
        if path and os.path.exists(path):
            st.image(path, caption=title)
        elif path:
            st.warning(f"図ファイルが見つかりません: `{path}`")
        else:
            st.caption("図データが指定されていません。")

        st.divider()


def _render_manuscript_tab(manuscript_sections: dict) -> None:
    if not manuscript_sections:
        st.info("原稿がありません。")
        return

    _SECTION_ORDER = [
        "abstract", "introduction", "methods", "results",
        "discussion", "conclusion", "limitations",
    ]
    _SECTION_LABELS_JA: dict[str, str] = {
        "abstract":     "抄録",
        "introduction": "緒言",
        "methods":      "方法",
        "results":      "結果",
        "discussion":   "考察",
        "conclusion":   "結論",
        "limitations":  "限界",
    }

    ordered_keys = [k for k in _SECTION_ORDER if k in manuscript_sections]
    other_keys   = [k for k in manuscript_sections if k not in _SECTION_ORDER]

    for key in ordered_keys + other_keys:
        section: dict = manuscript_sections[key]
        label = _SECTION_LABELS_JA.get(key, key)
        text:           str        = section.get("text", "")
        is_ai:          bool       = section.get("is_ai_generated", False)
        unresolved:     list[dict] = section.get("unresolved_items", [])

        st.markdown(f"#### {label}")

        if is_ai:
            # AI content marker (SCR-06: --cie-ai-teal left border)
            st.markdown(
                '<div style="border-left:4px solid #0D9488;padding:4px 10px;'
                'background:#F0FDFA;margin-bottom:4px;">'
                "<small>🤖 AI生成テキスト</small></div>",
                unsafe_allow_html=True,
            )

        # Editable text area — key is section-specific so Streamlit tracks state
        st.text_area(
            label=f"{label}（編集可能）",
            value=text,
            height=150,
            key=f"manuscript_{key}",
            label_visibility="collapsed",
        )

        # Unresolved item annotations (Google Docs-style, SCR-06 spec)
        if unresolved:
            for item in unresolved:
                st.warning(
                    f"⚠️ [{item.get('item_id', '')}] {item.get('description', '')}"
                )

        st.divider()


# ---------------------------------------------------------------------------
# Export panel
# ---------------------------------------------------------------------------

def _render_export_panel(reviewer_score: int, review_result: dict) -> dict:
    """Render the export approval panel at the bottom of SCR-06.

    Export is disabled when reviewer_score < 90 (SCR-06 spec).
    """
    st.markdown("### 📄 レポートのエクスポート")

    col_score, col_export = st.columns([2, 3])

    with col_score:
        score_color = "#059669" if reviewer_score >= 90 else "#D97706"
        score_label = "✓ PASS" if reviewer_score >= 90 else "REVIEW"
        st.markdown(
            f'<div style="font-size:24px;font-weight:600;color:{score_color};">'
            f"Reviewer Score: {reviewer_score}/100 {score_label}</div>",
            unsafe_allow_html=True,
        )

        unresolved_count: int = review_result.get("unresolved_count", 0)
        if unresolved_count:
            st.warning(f"⚠️ 未解決の項目: {unresolved_count} 件")

    with col_export:
        export_type = st.radio(
            "エクスポート先",
            options=_EXPORT_TYPES,
            key="export_type_radio",
        )

        export_disabled = reviewer_score < 90
        export_clicked = st.button(
            "エクスポートを承認する",
            disabled=export_disabled,
            type="primary",
            key="export_approve_btn",
            help=(
                f"品質スコアが90未満のためエクスポートできません（現在: {reviewer_score}）"
                if export_disabled
                else None
            ),
        )

    return {
        "export_approved": export_clicked,
        "export_type": export_type or _EXPORT_TYPES[0],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_score_summary(reviewer_score: int, review_result: dict) -> None:
    total_steps = review_result.get("total_steps", 0)
    passed_steps = review_result.get("passed_steps", 0)

    col1, col2, col3 = st.columns(3)
    col1.metric("Reviewer Score", f"{reviewer_score}/100")
    if total_steps:
        col2.metric("チェック通過", f"{passed_steps}/{total_steps}")
    unresolved = review_result.get("unresolved_count", 0)
    col3.metric("未解決項目", unresolved)


def _format_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
