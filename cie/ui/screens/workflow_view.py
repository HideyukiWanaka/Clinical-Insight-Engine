"""CIE Platform — SCR-03 Workflow Visualiser screen.

Presentation only. No business logic, no session_state writes.

render_workflow_view shows each workflow node as a horizontal step card
and returns the node_id of the card that was clicked (for detail display),
or None if nothing was clicked.
"""

from __future__ import annotations

import streamlit as st

_STATUS_ICON: dict[str, str] = {
    "pending":          "○",
    "running":          "⟳",
    "completed":        "✅",
    "failed":           "❌",
    "waiting_for_human": "🟣",
    "retrying":         "🔄",
    "skipped":          "—",
}

_STATUS_BORDER: dict[str, str] = {
    "completed":         "#059669",  # --cie-success
    "running":           "#2E74C0",  # --cie-blue-500
    "waiting_for_human": "#7C3AED",  # --cie-approval
    "failed":            "#DC2626",  # --cie-critical
    "retrying":          "#D97706",  # --cie-warning
    "pending":           "#E5E7EB",  # --cie-gray-200
    "skipped":           "#E5E7EB",
}


def render_workflow_view(
    workflow_definition: dict,
    node_statuses: dict[str, str],
    node_outputs: dict[str, dict],
) -> str | None:
    """Render SCR-03 Workflow Visualiser.

    Args:
        workflow_definition: Parsed workflow.yaml dict.  Expected to have a
                             ``nodes`` list; each node is a dict with at least
                             ``id``, ``name``, ``agent``, and ``type``.
        node_statuses: Mapping of node_id → WorkflowState string.
        node_outputs: Mapping of node_id → output payload dict (only for
                      completed nodes).

    Returns:
        The node_id whose detail button was clicked, or None.
    """
    st.title("ワークフロービジュアライザー")
    st.caption(
        "解析パイプラインの各ステップ（Agent）の実行状況を示します。"
        "カードをクリックすると各ステップの入出力・判断根拠を確認できます。"
    )

    # Legend
    with st.expander("凡例 — ステップの状態"):
        cols = st.columns(3)
        cols[0].markdown("○ **pending** — 未実行")
        cols[0].markdown("⟳ **running** — 実行中")
        cols[1].markdown("✅ **completed** — 完了")
        cols[1].markdown("❌ **failed** — 失敗")
        cols[2].markdown("🟣 **waiting_for_human** — 承認待ち")
        cols[2].markdown("🔄 **retrying** — 再試行中")

    nodes: list[dict] = workflow_definition.get("nodes", [])
    if not nodes:
        st.info("ワークフロー定義が見つかりません。解析を開始するとパイプラインがここに表示されます。")
        return None

    # Overall workflow progress summary
    total = len(nodes)
    completed = sum(
        1 for n in nodes if node_statuses.get(n["id"]) == "completed"
    )
    st.progress(completed / total if total else 0, text=f"進捗: {completed}/{total} ステップ完了")

    st.divider()

    # Horizontal step cards — one column per node (SCR-03 spec)
    clicked_node: str | None = None
    cols = st.columns(len(nodes))
    for col, node in zip(cols, nodes):
        node_id = node.get("id", "")
        with col:
            if _render_step_card(node, node_statuses.get(node_id, "pending")):
                clicked_node = node_id

    # Node detail expander (shown below cards when a node was selected)
    if clicked_node:
        _render_node_detail(clicked_node, nodes, node_statuses, node_outputs)

    return clicked_node


def _render_step_card(node: dict, status: str) -> bool:
    """Render one WorkflowStepCard. Returns True when the detail button is clicked."""
    node_id   = node.get("id", "")
    node_name = node.get("name", node_id)
    agent_id  = node.get("agent", "—")
    icon      = _STATUS_ICON.get(status, "?")
    border    = _STATUS_BORDER.get(status, "#E5E7EB")

    with st.container(border=True):
        st.markdown(
            f'<div style="border-left:3px solid {border};padding-left:6px;">'
            f'<strong>{icon} {node_name}</strong></div>',
            unsafe_allow_html=True,
        )
        st.caption(f"Agent: {agent_id}")

        return st.button("詳細 ▼", key=f"detail_{node_id}", use_container_width=True)


def _render_node_detail(
    node_id: str,
    nodes: list[dict],
    node_statuses: dict[str, str],
    node_outputs: dict[str, dict],
) -> None:
    """Render expanded detail for a selected node (SCR-03 step detail spec)."""
    node = next((n for n in nodes if n.get("id") == node_id), None)
    if node is None:
        return

    status    = node_statuses.get(node_id, "pending")
    node_name = node.get("name", node_id)
    agent_id  = node.get("agent", "—")
    node_type = node.get("type", "—")

    with st.expander(f"📋 {node_name} の詳細", expanded=True):
        col_meta1, col_meta2 = st.columns(2)
        col_meta1.metric("Agent", agent_id)
        col_meta2.metric("タイプ", node_type)

        st.markdown(f"**状態:** {_STATUS_ICON.get(status, '?')} `{status}`")

        tab_input, tab_output, tab_decision = st.tabs(["入力", "出力", "判断根拠"])

        with tab_input:
            node_input = node.get("input") or node.get("inputs")
            if node_input:
                schema_ref = node.get("schema_ref", "")
                if schema_ref:
                    st.caption(f"schema_ref: `{schema_ref}`")
                st.json(node_input)
            else:
                st.caption("入力ペイロードは定義されていません。")

        with tab_output:
            if status == "completed" and node_id in node_outputs:
                st.json(node_outputs[node_id])
            elif status == "completed":
                st.caption("出力ペイロードが存在しません。")
            else:
                st.caption("完了後に出力ペイロードが表示されます。")

        with tab_decision:
            decision = node.get("decision_branch_taken") or (
                node_outputs.get(node_id, {}).get("decision_branch_taken")
            )
            if decision:
                st.markdown(f"**選択された分岐:** `{decision}`")
                rationale = node_outputs.get(node_id, {}).get("decision_rationale")
                if rationale:
                    st.markdown(f"**判断理由:** {rationale}")
            else:
                st.caption("この手順に判断分岐はありません。")
