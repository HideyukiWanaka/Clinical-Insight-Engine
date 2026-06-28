"""CIE Platform — SCR-07 Audit Log & Observability screen.

Presentation only. No business logic, no explicit session_state writes.

Returns the audit event dict selected by the user (for right-pane JSON display),
or None if no row is selected.

CSV export includes only metadata columns — no payload content (SCR-07 spec).
"""

from __future__ import annotations

import csv
import io
from datetime import date

import streamlit as st

_ALL_SEVERITIES = ["INFO", "WARNING", "CRITICAL", "BREACH"]

# Columns to include in the downloadable CSV (SCR-07 spec: payload_hash only, no content)
_CSV_COLUMNS = [
    "timestamp",
    "agent_id",
    "action",
    "status",
    "event_severity",
    "execution_id",
    "token_id",
    "payload_hash",
]

# Background colours for severity rows (SCR-07 spec)
_SEVERITY_BG: dict[str, str] = {
    "WARNING":  "#FFF7ED",
    "CRITICAL": "#FEF2F2",
    "BREACH":   "#DC2626",
}
_SEVERITY_TEXT: dict[str, str] = {
    "BREACH": "#FFFFFF",
}


def render_audit_log(
    audit_events: list[dict],
    workflow_id: str | None,
    execution_id: str | None = None,
) -> dict | None:
    """Render SCR-07 Audit Log.

    Args:
        audit_events: List of audit event dicts from the orchestrator.
        workflow_id:  Current workflow / project ID (shown in the header).
        execution_id: Used for the CSV filename.

    Returns:
        The selected event dict (for right-pane JSON display), or None.
    """
    st.title("監査ログ")
    if workflow_id:
        st.caption(f"ワークフロー: `{workflow_id}`")

    if not audit_events:
        st.info("監査イベントがありません。")
        return None

    # --- Filter controls ---
    col_filter, col_main = st.columns([1, 3])

    with col_filter:
        st.markdown("#### フィルター")
        all_agents = sorted({e.get("agent_id", "") for e in audit_events if e.get("agent_id")})
        agent_filter: list[str] = st.multiselect(
            "Agent",
            options=all_agents,
            default=[],
            key="audit_agent_filter",
        )
        severity_filter: list[str] = st.multiselect(
            "重要度",
            options=_ALL_SEVERITIES,
            default=[],
            key="audit_severity_filter",
        )

    # Apply filters
    filtered = _apply_filters(audit_events, agent_filter, severity_filter)

    with col_main:
        st.markdown(f"#### タイムライン ({len(filtered)} 件)")

        if not filtered:
            st.info("フィルター条件に一致するイベントがありません。")
            _render_csv_download(audit_events, execution_id)
            return None

        selected_event = _render_timeline(filtered)
        _render_csv_download(audit_events, execution_id)

    return selected_event


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_filters(
    events: list[dict],
    agent_filter: list[str],
    severity_filter: list[str],
) -> list[dict]:
    result = events
    if agent_filter:
        result = [e for e in result if e.get("agent_id") in agent_filter]
    if severity_filter:
        result = [e for e in result if e.get("event_severity") in severity_filter]
    return result


def _render_timeline(events: list[dict]) -> dict | None:
    """Render audit events as a styled timeline.

    Returns the clicked event or None.
    """
    selected: dict | None = None

    try:
        import pandas as pd

        rows = [
            {
                "タイムスタンプ": e.get("timestamp", ""),
                "Agent":          e.get("agent_id", ""),
                "アクション":     e.get("action", ""),
                "状態":           e.get("status", ""),
                "重要度":         e.get("event_severity", "INFO"),
            }
            for e in events
        ]
        df = pd.DataFrame(rows)

        def _row_style(row: "pd.Series") -> list[str]:
            sev = row.get("重要度", "INFO")
            bg  = _SEVERITY_BG.get(sev, "")
            fg  = _SEVERITY_TEXT.get(sev, "")
            style = f"background-color:{bg};" if bg else ""
            if fg:
                style += f"color:{fg};"
            return [style] * len(row)

        styled = df.style.apply(_row_style, axis=1)

        event_selection = st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="audit_table",
        )

        # Handle row selection
        sel_rows = event_selection.selection.get("rows", [])  # type: ignore[attr-defined]
        if sel_rows:
            idx = sel_rows[0]
            if 0 <= idx < len(events):
                selected = events[idx]
                with st.expander("📋 選択イベントの詳細 (JSON)", expanded=True):
                    st.json(selected)

    except ImportError:
        # Fallback without pandas: plain text list
        for i, event in enumerate(events):
            ts  = event.get("timestamp", "")[:19]
            aid = event.get("agent_id", "")
            act = event.get("action", "")
            sev = event.get("event_severity", "INFO")
            line = f"`[{ts}]`  **{aid}**  {act}"

            if sev == "BREACH":
                st.error(line)
            elif sev == "CRITICAL":
                st.error(line)
            elif sev == "WARNING":
                st.warning(line)
            else:
                st.markdown(line)

            if st.button("詳細", key=f"audit_detail_{i}", help="イベント詳細を表示"):
                selected = event
                st.json(event)

    return selected


def _render_csv_download(
    events: list[dict],
    execution_id: str | None,
) -> None:
    """Render the CSV download button. Payload content is excluded (SCR-07 spec)."""
    today = date.today().strftime("%Y%m%d")
    eid_short = (execution_id or "unknown")[:8]
    filename = f"audit_log_{eid_short}_{today}.csv"

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for event in events:
        writer.writerow({col: event.get(col, "") for col in _CSV_COLUMNS})

    st.download_button(
        label="📥 CSV出力",
        data=buf.getvalue().encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        key="audit_csv_download",
        help="ペイロード本文を除く監査ログをCSVでダウンロードします",
    )
