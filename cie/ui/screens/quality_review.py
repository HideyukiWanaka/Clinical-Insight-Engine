"""CIE Platform — SCR-04 Data Quality Review screen.

Presentation only. No business logic, no explicit session_state writes.

Widget keys (e.g. ``ack_{finding_id}``) are managed by Streamlit's own
session_state mechanism — these are not "direct writes" in the sense of
the PROJECT_RULES constraint.
"""

from __future__ import annotations

import streamlit as st


def render_quality_review(
    quality_report: dict,
    column_alias_map: dict | None,
) -> dict:
    """Render SCR-04 Data Quality Review.

    Args:
        quality_report: Output from data_quality agent. Expected keys:
            ``quality_gate_passed``, ``critical_findings``,
            ``advisory_findings``, ``missing_value_summary``,
            ``variable_names``.
        column_alias_map: var_n → original column name. ``None`` means
                          Security Agent has not yet restored variables
                          (mask display, UP-004).

    Returns:
        ``{"proceed": bool, "acknowledged_findings": list[str]}``
        ``proceed`` is True only on the render where the button is clicked.
    """
    st.title("データ品質レビュー")

    gate_passed: bool = quality_report.get("quality_gate_passed", False)
    if gate_passed:
        st.success("✅ データ品質チェック: 通過")
    else:
        st.error("❌ データ品質チェック: 未通過")

    critical_findings: list[dict] = quality_report.get("critical_findings", [])
    advisory_findings: list[dict] = quality_report.get(
        "advisory_findings", quality_report.get("warnings", [])
    )

    # Critical Issues — always expanded (UP-003)
    if critical_findings:
        st.markdown(f"### ❌ Critical Issues ({len(critical_findings)} 件)")
        for finding in critical_findings:
            _render_critical_finding(finding)

    # Warning Issues — collapsed by default (UP-003)
    if advisory_findings:
        st.markdown(f"### ⚠️ Warnings ({len(advisory_findings)} 件)")
        for finding in advisory_findings:
            _render_advisory_finding(finding)

    # Missing value visualisation
    missing_data: dict = quality_report.get("missing_value_summary", {})
    if missing_data:
        st.markdown("### 欠損値の可視化")
        _render_missing_value_chart(missing_data)

    # Column alias panel (UP-004: PII styling)
    st.divider()
    render_column_alias_panel(quality_report, column_alias_map)

    # Determine which findings are acknowledged via widget state (read-only access)
    acknowledged = [
        f.get("finding_id", "")
        for f in critical_findings
        if st.session_state.get(f"ack_{f.get('finding_id', '')}", False)
    ]
    all_acknowledged = len(acknowledged) == len(critical_findings)
    can_proceed = gate_passed or all_acknowledged

    proceed_clicked = st.button(
        "次へ進む →",
        disabled=not can_proceed,
        type="primary",
        key="quality_proceed_btn",
        help=(
            "Critical Issueをすべて解消または承認してから進んでください"
            if not can_proceed
            else None
        ),
    )

    return {"proceed": proceed_clicked, "acknowledged_findings": acknowledged}


def render_column_alias_panel(
    quality_report: dict,
    column_alias_map: dict | None,
) -> None:
    """Render the PII column alias mapping panel (UP-004).

    If ``column_alias_map`` is None, original column names are masked with
    ``---``. When Security Agent has restored variables, the real names are
    shown.
    """
    var_ns: list[str] = quality_report.get("variable_names", [])
    if not var_ns and column_alias_map is None:
        return

    with st.container(border=True):
        st.markdown(
            '<div style="background:#FFF7ED;border-left:4px solid #D97706;'
            'padding:8px 12px;border-radius:2px;margin-bottom:8px;">'
            "<strong>🔒 個人識別情報を含む操作</strong></div>",
            unsafe_allow_html=True,
        )
        if column_alias_map is None:
            st.caption("列名はSecurity Agentの承認後に表示されます。")
            for var_n in var_ns:
                st.markdown(f"`{var_n}` → `---`")
        else:
            st.caption("Security Agentが列名を復元しました。")
            for var_n, original in column_alias_map.items():
                st.markdown(f"`{var_n}` → **{original}**")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _render_critical_finding(finding: dict) -> None:
    """Render one Critical Issue card (expanded=True, UP-003)."""
    fid = finding.get("finding_id", "unknown")
    component = finding.get("affected_component", "変数")
    description = finding.get("description", "")
    label = f"❌ {component}: {description[:50]}"

    with st.expander(label, expanded=True):
        st.error(description)

        steps: list[str] = finding.get("remediation_steps", [])
        if steps:
            st.markdown("**対処方法:**")
            for i, step in enumerate(steps, 1):
                st.markdown(f"{i}. {step}")

        st.divider()
        col_resolve, col_ack = st.columns(2)

        with col_resolve:
            st.button(
                "解消方法を確認",
                key=f"resolve_{fid}",
                help="詳細な解消手順を確認します",
            )

        with col_ack:
            already_acked: bool = st.session_state.get(f"ack_{fid}", False)
            if not already_acked:
                st.caption(
                    "⚠️ 解消せずに進む場合は、リスクを理解した上で確認してください。"
                )
            st.checkbox(
                "リスクを理解した上で進む",
                key=f"ack_{fid}",
            )


def _render_advisory_finding(finding: dict) -> None:
    """Render one Warning card (expanded=False, UP-003)."""
    component = finding.get("affected_component", "変数")
    description = finding.get("description", "")
    label = f"⚠️ {component}: {description[:50]}"

    with st.expander(label, expanded=False):
        st.warning(description)


def _render_missing_value_chart(missing_data: dict[str, float]) -> None:
    """Visualise missing-value rates as a bar chart (SCR-04 spec)."""
    try:
        import pandas as pd

        df = pd.DataFrame(
            [{"変数": k, "欠損率 (%)": float(v)} for k, v in missing_data.items()]
        )
        st.bar_chart(df.set_index("変数")["欠損率 (%)"])
    except ImportError:
        # Fallback: progress bars
        for var_n, rate in missing_data.items():
            pct = float(rate)
            color = "🔴" if pct >= 20 else ("🟠" if pct >= 5 else "🟢")
            st.write(f"{color} `{var_n}`: {pct:.1f}%")
            st.progress(min(pct / 100, 1.0))

    st.markdown(
        '<div style="font-size:12px;color:#DC2626;">'
        "─ 赤: 20% 閾値 (Critical) &nbsp; "
        '<span style="color:#D97706;">─ オレンジ: 5% 閾値 (Warning)</span>'
        "</div>",
        unsafe_allow_html=True,
    )
