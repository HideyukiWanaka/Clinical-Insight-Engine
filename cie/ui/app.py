"""CIE Platform — Streamlit main entry point.

Run: streamlit run cie/ui/app.py

This module is the ONLY place that writes to st.session_state.
Screen / component functions communicate via return values (see PROJECT_RULES).
"""

from __future__ import annotations

import streamlit as st

from cie.ui.components.right_pane import render_right_pane
from cie.ui.components.status_bar import render_status_bar
from cie.ui.screens.analysis_config import render_analysis_config
from cie.ui.screens.audit_log import render_audit_log
from cie.ui.screens.dashboard import render_dashboard
from cie.ui.screens.intent_entry import render_intent_entry, render_intent_preview
from cie.ui.screens.knowledge_management import render_knowledge_management
from cie.ui.screens.quality_review import render_quality_review
from cie.ui.screens.results import render_results
from cie.ui.screens.workflow_view import render_workflow_view

_CSS_VARIABLES = """
<style>
:root {
    --cie-blue-700: #1D4E89;
    --cie-blue-500: #2E74C0;
    --cie-blue-100: #DBEAFE;
    --cie-gray-900: #111827;
    --cie-gray-600: #4B5563;
    --cie-gray-200: #E5E7EB;
    --cie-gray-50:  #F9FAFB;
    --cie-success:  #059669;
    --cie-warning:  #D97706;
    --cie-critical: #DC2626;
    --cie-approval: #7C3AED;
    --cie-ai-teal:  #0D9488;
}
</style>
"""

_SCREENS = ("dashboard", "intent", "workflow", "quality", "analysis", "results", "audit", "knowledge")

_NAV_LABELS: dict[str, str] = {
    "dashboard": "ダッシュボード",
    "intent":    "研究意図入力",
    "workflow":  "ワークフロー",
    "quality":   "データ品質",
    "analysis":  "統計解析",
    "results":   "結果・レポート",
    "audit":     "監査ログ",
    "knowledge": "知識管理",
}


def _init_session_state() -> None:
    defaults: dict[str, object] = {
        "current_screen":         "dashboard",
        "execution_id":           None,
        "workflow_state":         None,
        "agent_activity_log":     [],
        "approval_pending":       False,
        "approval_context":       None,
        "connection_status":      "online",
        "security_events":        [],
        # Project / intent state
        "projects":               [],
        "current_project":        None,
        "intent_object":          None,
        "intent_object_confirmed": False,
        # Workflow state
        "workflow_definition":    {},
        "node_statuses":          {},
        "node_outputs":           {},
        # Quality review
        "quality_report":         {},
        "column_alias_map":       None,
        # Analysis
        "analysis_plan":          {},
        "assumption_report":      None,
        # Results
        "execution_result":       {},
        "figures":                [],
        "manuscript_sections":    {},
        "review_result":          {},
        # Audit
        "audit_events":           [],
        "audit_selected_event":   None,
        # Knowledge management
        "knowledge_entries":          [],
        "knowledge_draft":            None,
        "knowledge_expiry_warnings":  [],
        "knowledge_pending_upload":   None,
        "knowledge_approval_request": None,
        "knowledge_archive_request":  None,
        "current_user_id":            "researcher",
        "current_user_role":          "researcher",
        # Intent raw inputs (stored for external agent consumption)
        "intent_raw_text":            "",
        "intent_csv_bytes":           None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ---------------------------------------------------------------------------
# Navigation (left pane)
# ---------------------------------------------------------------------------

def _render_left_pane() -> None:
    st.markdown("### ナビゲーション")
    for screen in _SCREENS:
        label = _NAV_LABELS[screen]
        is_active = st.session_state["current_screen"] == screen
        if st.button(
            label,
            key=f"nav_{screen}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            st.session_state["current_screen"] = screen
            st.rerun()


# ---------------------------------------------------------------------------
# Right pane — context panel (intent preview on SCR-02, activity on others)
# ---------------------------------------------------------------------------

def _render_right_pane_content() -> None:
    screen = st.session_state["current_screen"]

    # SCR-02: show intent preview above the activity feed
    if screen == "intent" and st.session_state.get("intent_object"):
        render_intent_preview(st.session_state["intent_object"])
        st.divider()

    # All screens: approval panel + activity feed (handled by right_pane component)
    pane_result = render_right_pane(
        workflow_state=st.session_state["workflow_state"],
        agent_activity_log=st.session_state["agent_activity_log"],
        approval_pending=st.session_state["approval_pending"],
        approval_context=st.session_state.get("approval_context"),
    )

    # Handle approval / cancellation events from the right pane
    if pane_result.get("approved"):
        st.session_state["approval_pending"] = False
        st.session_state["approval_context"] = None
        # Log approval in activity feed
        _append_activity(
            agent_id="human",
            action="approved",
            summary="ユーザーが承認しました",
            severity="INFO",
        )
        st.rerun()

    if pane_result.get("cancelled"):
        # Cancellation keeps workflow in waiting_for_human (interaction-flow.md §2)
        _append_activity(
            agent_id="human",
            action="cancel_clicked",
            summary="承認待ち継続中",
            severity="INFO",
        )
        st.rerun()


# ---------------------------------------------------------------------------
# Main content routing
# ---------------------------------------------------------------------------

def render_main_content() -> None:
    screen = st.session_state["current_screen"]

    if screen == "dashboard":
        _handle_dashboard()

    elif screen == "intent":
        _handle_intent()

    elif screen == "workflow":
        _handle_workflow()

    elif screen == "quality":
        _handle_quality()

    elif screen == "analysis":
        _handle_analysis()

    elif screen == "results":
        _handle_results()

    elif screen == "audit":
        _handle_audit()

    elif screen == "knowledge":
        _handle_knowledge()


def _handle_dashboard() -> None:
    selected = render_dashboard(st.session_state["projects"])

    if selected is None:
        return

    if selected.get("__action__") == "new_project":
        st.session_state["current_screen"] = "intent"
        st.session_state["current_project"] = None
        st.session_state["intent_object"] = None
        st.session_state["intent_object_confirmed"] = False
        st.rerun()
        return

    # User opened an existing project → go to workflow view
    st.session_state["current_project"] = selected
    st.session_state["execution_id"] = selected.get("execution_id")
    st.session_state["workflow_state"] = selected.get("workflow_state")
    st.session_state["current_screen"] = "workflow"
    st.rerun()


def _handle_intent() -> None:
    def _on_submit(prompt_text: str, csv_bytes: bytes | None) -> None:
        # In a real app, this would call the Planner Agent.
        # Here we store the raw text and let the agent be invoked externally.
        st.session_state["intent_raw_text"] = prompt_text
        st.session_state["intent_csv_bytes"] = csv_bytes
        # Placeholder: set a mock intent_object so the UI can progress
        st.session_state["intent_object"] = {
            "objective": prompt_text[:120],
            "confidence_score": 0.85,
        }
        _append_activity(
            agent_id="planner",
            action="intent_submitted",
            summary=f"テキスト長 {len(prompt_text)} 文字",
            severity="INFO",
        )

    start_requested = render_intent_entry(
        on_submit=_on_submit,
        intent_confirmed=st.session_state.get("intent_object_confirmed", False),
    )

    if start_requested:
        st.session_state["approval_pending"] = True
        st.session_state["approval_context"] = {
            "title": "この解釈で解析を開始します。内容を確認してください。",
            "is_irreversible": False,
        }
        st.rerun()


def _handle_workflow() -> None:
    _ = render_workflow_view(
        workflow_definition=st.session_state.get("workflow_definition", {}),
        node_statuses=st.session_state.get("node_statuses", {}),
        node_outputs=st.session_state.get("node_outputs", {}),
    )
    # clicked_node is handled inside render_workflow_view (shows expander)
    # If future logic needs it, app.py can act on it here.


def _handle_quality() -> None:
    result = render_quality_review(
        quality_report=st.session_state.get("quality_report", {}),
        column_alias_map=st.session_state.get("column_alias_map"),
    )
    if result["proceed"]:
        acked = result["acknowledged_findings"]
        if acked:
            _append_activity(
                agent_id="human",
                action="quality_acknowledged",
                summary=f"承認済み finding: {', '.join(acked)}",
                severity="WARNING",
            )
        st.session_state["current_screen"] = "analysis"
        st.rerun()


def _handle_analysis() -> None:
    result = render_analysis_config(
        analysis_plan=st.session_state.get("analysis_plan", {}),
        assumption_report=st.session_state.get("assumption_report"),
    )
    if result["approved"]:
        # Override recorded to audit trail; actual invocation is external
        if result["override_method"]:
            _append_activity(
                agent_id="human",
                action="method_override",
                summary=(
                    f"{result['override_method']}: {result['override_reason'] or '理由未記入'}"
                ),
                severity="WARNING",
            )
        st.session_state["approval_pending"] = True
        st.session_state["approval_context"] = {
            "title": "Rスクリプトを実行します。内容を確認してください。",
            "is_irreversible": True,
        }
        st.rerun()


def _handle_results() -> None:
    result = render_results(
        execution_result=st.session_state.get("execution_result", {}),
        figures=st.session_state.get("figures", []),
        manuscript_sections=st.session_state.get("manuscript_sections", {}),
        review_result=st.session_state.get("review_result", {}),
        execution_id=st.session_state.get("execution_id"),
    )
    if result["export_approved"]:
        st.session_state["approval_pending"] = True
        st.session_state["approval_context"] = {
            "title": f"レポートをエクスポートします（{result['export_type']}）。",
            "is_irreversible": False,
        }
        _append_activity(
            agent_id="human",
            action="export_requested",
            summary=result["export_type"],
            severity="INFO",
        )
        st.rerun()


def _handle_audit() -> None:
    selected_event = render_audit_log(
        audit_events=st.session_state.get("audit_events", []),
        workflow_id=(st.session_state.get("current_project") or {}).get("execution_id"),
        execution_id=st.session_state.get("execution_id"),
    )
    if selected_event is not None:
        st.session_state["audit_selected_event"] = selected_event


def _handle_knowledge() -> None:
    event = render_knowledge_management(
        entries=st.session_state.get("knowledge_entries", []),
        draft=st.session_state.get("knowledge_draft"),
        expiry_warnings=st.session_state.get("knowledge_expiry_warnings", []),
        current_user_id=st.session_state.get("current_user_id", "researcher"),
        current_user_role=st.session_state.get("current_user_role", "researcher"),
    )

    if event is None:
        return

    action = event.get("action")

    if action == "upload":
        st.session_state["knowledge_pending_upload"] = event
        _append_activity(
            agent_id="knowledge_ingestion",
            action="upload_received",
            summary=f"ファイル受信: {event.get('filename')}",
            severity="INFO",
        )
        st.rerun()

    elif action == "draft_approved":
        st.session_state["knowledge_approval_request"] = event
        _append_activity(
            agent_id="human",
            action="draft_approved",
            summary=f"ドラフト承認: {event.get('draft_id')} "
                    f"(trust={event.get('trust_level')}, domain={event.get('domain')})",
            severity="INFO",
        )
        st.rerun()

    elif action == "draft_rejected":
        st.session_state["knowledge_draft"] = None
        _append_activity(
            agent_id="human",
            action="draft_rejected",
            summary=f"ドラフト却下: {event.get('draft_id')}",
            severity="WARNING",
        )
        st.rerun()

    elif action == "archive":
        st.session_state["knowledge_archive_request"] = event
        _append_activity(
            agent_id="human",
            action="archive_requested",
            summary=f"アーカイブ要求: {event.get('entry_id')}",
            severity="WARNING",
        )
        st.rerun()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _append_activity(
    agent_id: str,
    action: str,
    summary: str,
    severity: str = "INFO",
) -> None:
    from datetime import datetime, timezone
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent_id,
        "action": action,
        "summary": summary,
        "severity": severity,
    }
    log: list = st.session_state.setdefault("agent_activity_log", [])
    log.append(entry)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="CIE Platform",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(_CSS_VARIABLES, unsafe_allow_html=True)
    _init_session_state()

    render_status_bar(
        project_name=(
            (st.session_state.get("current_project") or {}).get("project_name")
        ),
        execution_id=st.session_state["execution_id"],
        connection_status=st.session_state["connection_status"],
        security_events=st.session_state["security_events"],
        workflow_state=st.session_state["workflow_state"],
    )

    st.divider()

    left_col, center_col, right_col = st.columns([1, 3, 1.3])

    with left_col:
        _render_left_pane()

    with center_col:
        render_main_content()

    with right_col:
        _render_right_pane_content()


if __name__ == "__main__":
    main()
