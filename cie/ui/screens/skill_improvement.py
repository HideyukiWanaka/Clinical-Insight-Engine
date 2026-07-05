"""CIE Platform — Skill自己改善 UI スクリーン (ADR-0002 Phase 3).

Presentation-only component that:
  - Lists pending SkillImprovementProposals (status = pending_human_review).
  - Displays trigger evidence, root-cause analysis, and proposed diff per proposal.
  - Raises approve / reject events back to app.py via return values (UP-002, UP-005).
    No session_state mutations here.

app.py は返り値を見て:
  "approve_proposal" → approval_pending=True, action="apply_skill_proposal"
  "reject_proposal"  → 直接 apply_approved_proposal(..., rejected) を呼ぶ
"""

from __future__ import annotations

import streamlit as st

_TRIGGER_LABELS: dict[str, str] = {
    "SE-001": "SE-001: 同一問題の繰り返し検出",
    "SE-002": "SE-002: テスト合格率低下",
    "SE-003": "SE-003: 最新実行でテスト失敗",
    "SE-004": "SE-004: 手動リクエスト",
}

_CHANGE_TYPE_BADGES: dict[str, str] = {
    "add":      "🟢 追加",
    "modify":   "🟡 変更",
    "remove":   "🔴 削除",
    "advisory": "⚪ アドバイザリ（diff なし）",
}


def render_skill_improvement(
    proposals: list[dict],
) -> dict:
    """Render the Skill self-improvement screen.

    Args:
        proposals: List of proposal dicts (serialised SkillImprovementProposalRow).
                   Each dict must have keys: proposal_id, target_skill_id,
                   target_namespace, current_version, proposed_version,
                   trigger_id, trigger_evidence, proposed_changes, status,
                   generated_at.

    Returns:
        Event dict. Possible shapes:
          {"approve_proposal": proposal_id}
          {"reject_proposal":  proposal_id}
          {}  (no action this cycle)
    """
    st.header("Skill 自己改善")
    st.caption("評価エージェントが検出したSkillの課題 → AI提案 → 人間承認 → SKILL.md 自動更新 (ADR-0002)")

    pending = [p for p in proposals if p.get("status") == "pending_human_review"]
    reviewed = [p for p in proposals if p.get("status") in ("approved", "rejected")]

    # --- Pending proposals -----------------------------------------------
    if not pending:
        st.info("現在、承認待ちのSkill改善提案はありません。")
    else:
        st.subheader(f"承認待ちの提案  ({len(pending)} 件)")
        for prop in pending:
            event = _render_proposal_card(prop, allow_actions=True)
            if event:
                return event

    # --- Recently reviewed proposals -------------------------------------
    if reviewed:
        with st.expander(f"レビュー済み提案  ({len(reviewed)} 件)", expanded=False):
            for prop in reviewed:
                _render_proposal_card(prop, allow_actions=False)

    return {}


def _render_proposal_card(prop: dict, allow_actions: bool) -> dict:
    """Render one proposal card. Returns an event dict or {}."""
    pid = prop.get("proposal_id", "")
    short = pid[:8]
    skill_id = prop.get("target_skill_id", "")
    ns = prop.get("target_namespace", "core")
    cv = prop.get("current_version", "?")
    pv = prop.get("proposed_version", "?")
    trigger = prop.get("trigger_id", "")
    generated_at = str(prop.get("generated_at", ""))[:19]
    status = prop.get("status", "")
    evidence = prop.get("trigger_evidence") or {}
    changes: list[dict] = prop.get("proposed_changes") or []

    status_icon = {"pending_human_review": "🟣", "approved": "✅", "rejected": "❌"}.get(
        status, "⚪"
    )
    version_badge = f"`{cv}` → `{pv}`"
    trigger_label = _TRIGGER_LABELS.get(trigger, trigger)

    with st.expander(
        f"{status_icon}  **{skill_id}**  {version_badge}  |  {trigger_label}  |  {generated_at}",
        expanded=(status == "pending_human_review"),
    ):
        col_left, col_right = st.columns([2, 1])
        with col_left:
            st.markdown(f"**Skill ID:** `{skill_id}` (namespace: `{ns}`)")
            st.markdown(f"**バージョン変更:** {version_badge}")
            st.markdown(f"**トリガー:** {trigger_label}")
        with col_right:
            st.markdown(f"**ステータス:** {status_icon} `{status}`")
            st.markdown(f"**生成日時:** {generated_at}")
            st.markdown(f"**proposal_id:** `{short}…`")

        # Trigger evidence
        if evidence:
            root = evidence.get("root_cause") or {}
            affected = root.get("affected_sections") or []
            impact = evidence.get("impact") or {}
            raw_evidence = {k: v for k, v in evidence.items()
                            if k not in ("root_cause", "impact")}

            if raw_evidence:
                st.markdown("**トリガーの根拠:**")
                parts = []
                for k, v in raw_evidence.items():
                    if isinstance(v, int):
                        parts.append(f"`{k}` — 再発 {v} 回")
                    else:
                        parts.append(f"`{k}`: {v}")
                st.markdown("  •  ".join(parts))

            if affected:
                st.markdown("**局所化された SKILL.md セクション:**")
                for sec in affected:
                    fid = sec.get("finding_id", "")
                    section = sec.get("affected_section", "")
                    freq = sec.get("frequency")
                    freq_txt = f"（{freq}回）" if freq else ""
                    st.markdown(f"  - `{fid}` → **{section}** {freq_txt}")

            if impact:
                bump = impact.get("version_bump_type", "")
                risk = impact.get("regression_risk", "")
                st.markdown(
                    f"**影響評価:** バージョンバンプ `{bump}` / 回帰リスク `{risk}`"
                )

        # Proposed changes
        st.markdown(f"**提案された変更  ({len(changes)} 件):**")
        for i, change in enumerate(changes, 1):
            c_type = change.get("change_type", "advisory")
            section = change.get("section", "")
            desc = change.get("description", "")
            diff = change.get("diff")
            addresses = change.get("addresses_finding", "")

            badge = _CHANGE_TYPE_BADGES.get(c_type, c_type)
            st.markdown(
                f"**変更 {i}:** {badge}  →  セクション `{section}`"
                f"  （対応 finding: `{addresses}`）"
            )
            st.caption(desc)

            if diff:
                st.markdown("**挿入される内容（diff）:**")
                st.code(diff, language="markdown")
            else:
                st.warning(
                    "このfindingは自動diff非対応です。"
                    "承認後、人間が SKILL.md を直接編集してください。"
                )

        # ADR-0002 invariant notice
        st.info(
            "この操作はSkillファイルを変更します。"
            "human_review_required = True — 必ず内容を確認してから承認してください（ADR-0002）。"
        )

        if not allow_actions:
            decision = prop.get("human_decision") or {}
            st.caption(
                f"レビュー済み（{status}）: {decision.get('action', '')} — "
                f"{str(prop.get('reviewed_at', ''))[:19]}"
            )
            return {}

        # Action buttons
        st.divider()
        col_rej, _, col_app = st.columns([3, 1, 3])
        if col_rej.button("❌ 却下", key=f"reject_{short}", type="secondary"):
            return {"reject_proposal": pid}
        if col_app.button(
            "✅ 承認して適用",
            key=f"approve_{short}",
            type="primary",
        ):
            return {"approve_proposal": pid}

    return {}
