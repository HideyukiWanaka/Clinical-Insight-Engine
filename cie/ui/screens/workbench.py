"""CIE Platform — Workbench screen (RStudio-style chat + R execution).

Presentation only. No business logic, no direct session_state writes — this
mirrors the convention used by every other screen in ``cie/ui/screens/``
(see e.g. ``intent_entry.py``, ``results.py``): the render function returns a
single ``event`` dict describing what the user did this render cycle, and
``cie/ui/app.py`` is responsible for calling agents / mutating state.

Layout (per the user's "IDE-like, role-separated spaces" request):
  - Left:  chat transcript (``st.chat_message`` / ``st.chat_input``) — the
           only native-chat UI in the app; the AI explains its recommended
           method(s) and proposes selectable R code candidates here.
  - Right: tabs — 🖥 Rコード（編集可能） / 📊 実行結果 / 📁 ファイル / 📝 原稿

This screen does not replace the existing wizard (dashboard/intent/.../
settings) — it is an additional, more direct entry point that talks to the
same agents (Planner / Statistics / Runtime / Visualization / Reporting)
without going through the Orchestrator DAG, the same way the existing
"continuation analysis" mini-pipeline in app.py already does.
"""

from __future__ import annotations

import uuid

import streamlit as st

from cie.ui.screens.format_selection import render_format_selection
from cie.ui.components.file_browser import render_file_browser


def render_workbench(
    chat_history: list[dict],
    active_code: str,
    last_run: dict | None,
    manuscript_sections: dict,
    dataset_uploaded: bool,
    workspace_dir: str | None,
    available_user_skills: list[str],
    format_settings: dict,
) -> dict:
    """Render the Workbench screen.

    Args:
        chat_history: List of ``{"id", "role", "content", "candidates"}`` dicts.
            ``candidates`` (assistant messages only) is a list of
            ``{"candidate_id", "label", "r_code"}``.
        active_code: Current contents of the R code editor pane.
        last_run: Most recent execution result dict, or None if nothing has
            run yet. Expected keys: ``execution_result`` (status/detail/...),
            ``statistical_results``, ``statistical_results_formatted``,
            ``error_detail``, ``figures``, ``generated_files``.
        manuscript_sections: Section key → dict with ``text`` (Phase 6 output).
        dataset_uploaded: Whether a dataset is already available in this session.
        workspace_dir: Absolute path to the workspace directory (for the file
            browser pane), or None if not yet known.
        available_user_skills: Skill IDs for the format-selection panel.
        format_settings: Current ``{"checklist_id", "journal_style", "skill_id"}``.

    Returns:
        An event dict, e.g. ``{"action": "user_message", "text": "..."}``,
        or ``{}`` when nothing happened this render.
    """
    st.title("🧪 ワークベンチ")
    st.caption(
        "チャットで相談 → 提案されたRコードを確認・編集 → 実行 → 結果とファイルを確認、"
        "という一連の流れをこの画面だけで完結できます。"
    )

    event: dict = {}

    with st.expander("📋 出力フォーマット設定", expanded=False):
        fmt_event = render_format_selection(
            available_user_skills,
            current_checklist=format_settings.get("checklist_id"),
            current_journal_style=format_settings.get("journal_style", "APA"),
            current_skill_id=format_settings.get("skill_id"),
        )
        if fmt_event != format_settings:
            event = {"action": "update_format_settings", **fmt_event}

    chat_col, work_col = st.columns([1, 1])

    with chat_col:
        st.subheader("💬 チャット")

        if not dataset_uploaded:
            uploaded = st.file_uploader(
                "データセット（CSV/TSV/XLSX）を最初にアップロードしてください",
                type=["csv", "tsv", "xlsx"],
                key="wb_dataset_upload",
            )
            if uploaded is not None:
                event = {
                    "action": "upload_dataset",
                    "bytes": uploaded.read(),
                    "filename": uploaded.name,
                }

        chat_container = st.container(height=460)
        with chat_container:
            for msg in chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    for cand in msg.get("candidates", []):
                        st.code(cand["r_code"], language="r")
                        btn_key = f"wb_run_{msg['id']}_{cand['candidate_id']}"
                        if st.button(f"▶ {cand['label']} を実行", key=btn_key):
                            event = {
                                "action": "run_candidate",
                                "candidate_id": cand["candidate_id"],
                                "r_code": cand["r_code"],
                                "label": cand["label"],
                            }

        user_text = st.chat_input(
            "研究の質問や追加解析の依頼を入力（例: 男女の血圧の差を比べたい）",
            disabled=not dataset_uploaded,
        )
        if user_text:
            event = {"action": "user_message", "text": user_text}

    with work_col:
        tab_code, tab_output, tab_files, tab_manuscript = st.tabs(
            ["🖥 Rコード", "📊 実行結果", "📁 ファイル", "📝 原稿"]
        )

        with tab_code:
            edited_code = st.text_area(
                "実行するRコード（自由に編集できます）",
                value=active_code or "",
                height=340,
                key="wb_code_editor",
            )
            if st.button(
                "▶ このコードを実行",
                key="wb_run_button",
                type="primary",
                disabled=not edited_code.strip(),
            ):
                event = {"action": "run_code", "code": edited_code}

        with tab_output:
            _render_output_pane(last_run)

        with tab_files:
            render_file_browser(workspace_dir)

        with tab_manuscript:
            _render_manuscript_pane(manuscript_sections, last_run)
            if st.button(
                "📝 この結果を原稿に変換",
                key="wb_manuscript_button",
                disabled=not (last_run and last_run.get("statistical_results")),
            ):
                event = {"action": "generate_manuscript"}

    return event


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_output_pane(last_run: dict | None) -> None:
    if not last_run:
        st.info("まだRコードを実行していません。左のチャットで候補を選ぶか、Rコードタブで実行してください。")
        return

    error_detail: str | None = last_run.get("error_detail")
    if error_detail:
        st.error(f"実行結果を取得できませんでした。\n\n{error_detail}")

    formatted = last_run.get("statistical_results_formatted")
    if formatted:
        st.markdown(formatted)
        st.divider()

    execution_result: dict = last_run.get("execution_result") or {}
    stdout_summary = execution_result.get("sanitized_stdout_summary")
    if stdout_summary:
        with st.expander("▼ 標準出力（サニタイズ済み）"):
            st.code(stdout_summary, language="text")

    figures: list[dict] = last_run.get("figures") or []
    if figures:
        st.markdown("### 🖼 図表")
        for fig in figures:
            path = fig.get("path")
            if path:
                st.image(path, caption=fig.get("title"))

    generated_files: list = last_run.get("generated_files") or []
    if generated_files:
        with st.expander("▼ 生成されたファイル"):
            for f in generated_files:
                st.text(f)


def _render_manuscript_pane(manuscript_sections: dict, last_run: dict | None) -> None:
    if not manuscript_sections:
        st.caption(
            "統計結果が出たら「この結果を原稿に変換」を押すと、"
            "上で設定したフォーマットで原稿セクションが生成されます。"
        )
        return
    for section_id, section in manuscript_sections.items():
        st.markdown(f"**{section_id}**")
        st.text_area(
            f"section_{section_id}",
            value=section.get("text", ""),
            height=160,
            key=f"wb_manuscript_{section_id}",
            label_visibility="collapsed",
        )


def new_message_id() -> str:
    """Generate a stable widget-key suffix for a new chat message."""
    return uuid.uuid4().hex[:8]
