"""CIE Platform — Knowledge Management screen.

Orchestrates the four existing knowledge_review.py components into a single
cohesive screen (SCR-KM) using a two-tab layout:

  📤 ドキュメント登録  — upload + AI draft review
  📚 知識ライブラリ    — active registry + expiry warnings

Presentation only. No business logic. Returns an event dict to app.py which
then calls KnowledgeIngestionAgent / KnowledgeLifecycleService as appropriate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from cie.ui.components.knowledge_review import (
    render_expiry_warnings,
    render_knowledge_draft_review,
    render_knowledge_registry_panel,
    render_knowledge_upload_panel,
)

if TYPE_CHECKING:
    from cie.knowledge.ingestion_agent import KnowledgeEntryDraft
    from cie.knowledge.loader import ExpiryWarning
    from cie.knowledge.models import KnowledgeEntry


def render_knowledge_management(
    entries: list["KnowledgeEntry"],
    draft: "KnowledgeEntryDraft | None",
    expiry_warnings: list["ExpiryWarning"],
    current_user_id: str,
    current_user_role: str,
) -> dict | None:
    """Render the Knowledge Management screen.

    Args:
        entries:           All active KnowledgeEntry objects from the registry.
        draft:             Pending KnowledgeEntryDraft awaiting human review,
                           or None when no upload is pending.
        expiry_warnings:   ExpiryWarning list from KnowledgeLoader.check_expiry_warnings().
        current_user_id:   ID of the currently logged-in user (for archive auth).
        current_user_role: Role of the current user (``"admin"`` or ``"researcher"``).

    Returns:
        One of:
          ``{"action": "upload",         "file_bytes": bytes, "filename": str}``
          ``{"action": "draft_approved", "trust_level": str,  "domain": str,
              "draft_id": str}``
          ``{"action": "draft_rejected", "draft_id": str}``
          ``{"action": "archive",        "entry_id": str}``
          ``None`` — no event this render cycle.
    """
    st.title("知識管理")
    st.caption("機関内知識ライブラリの管理・登録・更新を行います。")

    # Expiry warnings are shown prominently at the top (always visible)
    if expiry_warnings:
        render_expiry_warnings(expiry_warnings)
        st.divider()

    tab_ingest, tab_library = st.tabs(["📤 ドキュメント登録", "📚 知識ライブラリ"])

    event: list[dict] = []  # mutable container to capture callbacks

    # ----------------------------------------------------------------
    # Tab 1: Document upload + AI draft review
    # ----------------------------------------------------------------
    with tab_ingest:
        if draft is not None:
            # A draft is awaiting human review — show review UI first
            st.info(
                f"🔍 **レビュー待ちのドラフトがあります:** `{draft.draft_id}`  \n"
                "以下の内容を確認し、承認または却下してください。"
            )
            decision = render_knowledge_draft_review(draft)

            if decision == "approve":
                trust_level = st.session_state.get(
                    f"trust_{draft.draft_id}", draft.extracted_trust_level
                )
                domain = st.session_state.get(
                    f"domain_{draft.draft_id}", draft.extracted_domain
                )
                event.append(
                    {
                        "action": "draft_approved",
                        "draft_id": draft.draft_id,
                        "trust_level": trust_level,
                        "domain": domain,
                    }
                )

            elif decision == "reject":
                event.append(
                    {
                        "action": "draft_rejected",
                        "draft_id": draft.draft_id,
                    }
                )

        else:
            # No pending draft — show upload panel
            st.markdown("#### 新規ドキュメントをアップロード")
            st.caption(
                "PDF / Markdown / テキスト / Word ファイルをアップロードすると、"
                "AI が知識項目を抽出してドラフトを作成します。"
                "抽出結果は必ず人間がレビューしてから登録されます。"
            )

            def _on_upload(file_bytes: bytes, filename: str) -> None:
                event.append(
                    {"action": "upload", "file_bytes": file_bytes, "filename": filename}
                )

            render_knowledge_upload_panel(on_upload=_on_upload)

    # ----------------------------------------------------------------
    # Tab 2: Active registry + expiry-aware display
    # ----------------------------------------------------------------
    with tab_library:
        st.markdown(f"#### 登録済み知識エントリ ({len(entries)} 件)")

        def _on_archive(entry_id: str) -> None:
            event.append({"action": "archive", "entry_id": entry_id})

        render_knowledge_registry_panel(
            entries=entries,
            current_user_id=current_user_id,
            current_user_role=current_user_role,
            on_archive=_on_archive,
        )

    return event[0] if event else None
