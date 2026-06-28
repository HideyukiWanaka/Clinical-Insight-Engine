"""Knowledge Ingestion Pipeline — Human Review UI components.

All business logic is delegated to callbacks (on_upload, on_archive).
This module never imports KnowledgeIngestionAgent or KnowledgeLifecycleService
directly (ADR-0003 Phase 3 / Phase 9 UI rules).
"""

from __future__ import annotations

from typing import Callable

import streamlit as st

from cie.knowledge.ingestion_agent import KnowledgeEntryDraft
from cie.knowledge.loader import ExpiryWarning
from cie.knowledge.models import KnowledgeEntry, KnowledgeStatus

_TRUST_LEVEL_BADGE: dict[str, str] = {
    "regulatory": "🟢",
    "peer_reviewed": "🔵",
    "institutional": "🟡",
    "experimental": "🔴",
}

_TRUST_LEVELS = ["regulatory", "peer_reviewed", "institutional", "experimental"]
_DOMAINS = ["statistics", "clinical", "reporting", "R", "Python", "visualization"]

_CONFIDENCE_THRESHOLD = 0.7


def render_knowledge_upload_panel(on_upload: Callable[[bytes, str], None]) -> None:
    """Document upload widget.

    Delegates all business logic (quarantine, parsing, extraction) to
    *on_upload*. No Agent is called from inside this component.
    """
    st.subheader("📄 ドキュメントアップロード")
    uploaded = st.file_uploader(
        "ドキュメントを選択してください（PDF / Markdown / テキスト / Word）",
        type=["pdf", "md", "txt", "docx"],
    )
    if uploaded is not None:
        on_upload(uploaded.read(), uploaded.name)


def render_knowledge_draft_review(draft: KnowledgeEntryDraft) -> str | None:
    """Review panel for an AI-extracted knowledge draft.

    Returns:
        ``"approve"`` when the human clicks the approval button,
        ``"reject"`` when the human clicks the rejection button,
        ``None`` while no decision has been made yet.
    """
    st.subheader(f"🔍 ドラフトレビュー: {draft.draft_id}")

    # Source info
    meta = draft.extracted_metadata
    st.markdown("### 原典情報")
    st.write(f"**タイトル**: {meta.get('title', 'Unknown')}")
    st.write(f"**発行年**: {meta.get('year', 'Unknown')}")
    doi = meta.get("doi")
    url = meta.get("url")
    st.write(f"**DOI**: {doi or 'N/A'}")
    st.write(f"**URL**: {url or 'N/A'}")

    # Knowledge items
    st.markdown("### 抽出済み知識エントリ")
    for item in draft.extracted_knowledge_items:
        confidence = float(item.get("confidence", 1.0))
        prefix = "🟡 " if confidence < _CONFIDENCE_THRESHOLD else ""
        st.markdown(f"**{prefix}Statement**: {item.get('statement', '')}")
        st.write(f"**Direct Quote**: {item.get('direct_quote', '')}")
        st.write(f"**確信度**: {confidence:.2f}")
        caveats = item.get("caveats", "")
        if caveats:
            st.write(f"**注意事項**: {caveats}")
        st.divider()

    # Limitations
    if draft.extraction_limitations:
        st.markdown("### 抽出の限界")
        for lim in draft.extraction_limitations:
            st.write(f"- {lim}")

    # Selectors (researcher can correct AI inference)
    trust_idx = _TRUST_LEVELS.index(draft.extracted_trust_level) if draft.extracted_trust_level in _TRUST_LEVELS else 1
    st.selectbox("Trust Level", options=_TRUST_LEVELS, index=trust_idx, key=f"trust_{draft.draft_id}")

    domain_idx = _DOMAINS.index(draft.extracted_domain) if draft.extracted_domain in _DOMAINS else 0
    st.selectbox("ドメイン", options=_DOMAINS, index=domain_idx, key=f"domain_{draft.draft_id}")

    # Decision buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 承認", key=f"approve_{draft.draft_id}"):
            return "approve"
    with col2:
        if st.button("❌ 却下", key=f"reject_{draft.draft_id}"):
            return "reject"

    return None


def render_expiry_warnings(warnings: list[ExpiryWarning]) -> None:
    """Display expiry alert banners for the UI load.

    ADR-0003 principle 7: on-demand check — no batch jobs required.
    """
    for warning in warnings:
        if warning.level == "expired":
            st.error(f"🔴 {warning.message}")
        elif warning.level == "expiring_soon":
            st.warning(f"🟡 {warning.message}")


def render_knowledge_registry_panel(
    entries: list[KnowledgeEntry],
    current_user_id: str,
    current_user_role: str,
    on_archive: Callable[[str], None],
) -> None:
    """Registered institutional knowledge browser.

    Shows only active entries. Displays trust-level badges, superseded
    warnings, and a conditional archive button (authorization checked here
    AND in KnowledgeLifecycleService — UI check is defence-in-depth only).
    """
    st.subheader("📚 登録済み知識一覧")

    active_entries = [e for e in entries if e.status == KnowledgeStatus.ACTIVE]

    if not active_entries:
        st.info("登録済みの知識エントリがありません。")
        return

    for entry in active_entries:
        badge = _TRUST_LEVEL_BADGE.get(entry.trust_level.value, "⬜")
        st.markdown(f"#### {badge} {entry.entry_id} — {entry.domain.value}")
        st.write(f"**Trust Level**: {entry.trust_level.value}")
        st.write(f"**Version**: {entry.version}")
        src = entry.source_info
        st.write(f"**タイトル**: {src.title} ({src.year})")

        # Superseded warning (ADR-0003 principle 6)
        for rel in entry.related_entries:
            if rel.relationship == "superseded_by":
                st.warning(f"⚠️ この知識には新しいバージョンがあります: {rel.entry_id}")

        # Archive button — shown only to owner or admin (defence-in-depth)
        is_authorized = (current_user_id == entry.created_by) or (current_user_role == "admin")
        if is_authorized:
            if st.button("🗑️ アーカイブ", key=f"archive_{entry.entry_id}"):
                on_archive(entry.entry_id)

        st.divider()
