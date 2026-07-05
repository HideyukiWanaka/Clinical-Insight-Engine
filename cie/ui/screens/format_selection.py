"""CIE Platform — Format Selection component (Phase 5).

A compact settings panel rendered during SCR-02 Research Intent Entry.
Users choose:
  - Reporting checklist  (CONSORT / STROBE / TRIPOD+AI / PRISMA / STARD / auto)
  - Target journal style (APA / AMA / Vancouver)
  - User-defined reporting Skill override (from skills/user/, if any)

All state writes happen in app.py; this component is presentation-only and
returns a plain dict so it can be unit-tested without Streamlit.
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHECKLIST_VALUES: list[str | None] = [
    None,
    "CONSORT",
    "STROBE",
    "TRIPOD",
    "PRISMA",
    "STARD",
]

_CHECKLIST_LABELS: list[str] = [
    "自動判定（study_design から推論）",
    "CONSORT 2010  — ランダム化比較試験",
    "STROBE 2007  — 観察研究 (コホート / 症例対照 / 横断)",
    "TRIPOD+AI 2024  — 予測モデル開発・検証",
    "PRISMA 2020  — システマティックレビュー・メタ解析",
    "STARD 2015  — 診断精度研究",
]

_JOURNAL_STYLES: list[str] = ["APA", "AMA", "Vancouver"]

_STYLE_EXAMPLES: dict[str, str] = {
    "APA":       "p = .034  /  p < .001  （7th edition, leading zero なし）",
    "AMA":       "P = .034  /  P < .001  （11th edition, 大文字 P）",
    "Vancouver": "p = 0.034  /  p < 0.001  （leading zero あり）",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_format_selection(
    available_user_skills: list[str],
    current_checklist: str | None = None,
    current_journal_style: str = "APA",
    current_skill_id: str | None = None,
) -> dict:
    """Render the reporting format selection panel inside an expander.

    This is a *presentation-only* function: it never writes to session_state.
    The caller (app.py) is responsible for persisting the returned values.

    Args:
        available_user_skills: Skill IDs from skills/user/ namespace.
        current_checklist:     Pre-selected checklist ID, or None for auto.
        current_journal_style: Pre-selected journal style ("APA" / "AMA" / "Vancouver").
        current_skill_id:      Pre-selected user skill ID, or None.

    Returns:
        {
            "checklist_id":  str | None,  # None = infer from study_design
            "journal_style": str,          # "APA" / "AMA" / "Vancouver"
            "skill_id":      str | None,   # None = use core skill
        }
    """
    with st.expander("📋 フォーマット設定（チェックリスト・雑誌スタイル・Skill）", expanded=False):
        st.caption(
            "ワークフロー実行前に設定した値が原稿生成に反映されます。"
            "未設定の場合は自動判定またはデフォルト（APA）が使われます。"
        )

        # --- Reporting checklist ---
        st.markdown("**報告チェックリスト**")
        current_cl_idx = 0
        if current_checklist in _CHECKLIST_VALUES:
            current_cl_idx = _CHECKLIST_VALUES.index(current_checklist)

        selected_cl_label: str = st.selectbox(
            "チェックリスト",
            options=_CHECKLIST_LABELS,
            index=current_cl_idx,
            key="fmt_checklist_selectbox",
            label_visibility="collapsed",
        )
        selected_checklist: str | None = _CHECKLIST_VALUES[
            _CHECKLIST_LABELS.index(selected_cl_label)
        ]

        # --- Journal style ---
        st.markdown("**雑誌スタイル（p 値フォーマット）**")
        current_style_idx = (
            _JOURNAL_STYLES.index(current_journal_style)
            if current_journal_style in _JOURNAL_STYLES
            else 0
        )
        selected_style: str = st.radio(
            "雑誌スタイル",
            options=_JOURNAL_STYLES,
            index=current_style_idx,
            horizontal=True,
            key="fmt_journal_style_radio",
            label_visibility="collapsed",
        )
        st.caption(_STYLE_EXAMPLES.get(selected_style or "APA", ""))

        # --- User Skill (reporting) ---
        st.markdown("**ユーザーSkill（報告スタイル上書き）**")
        selected_skill: str | None = None
        if available_user_skills:
            skill_options = ["なし（コアSkillを使用）"] + available_user_skills
            current_skill_idx = 0
            if current_skill_id in available_user_skills:
                current_skill_idx = available_user_skills.index(current_skill_id) + 1
            selected_skill_label: str = st.selectbox(
                "ユーザーSkill",
                options=skill_options,
                index=current_skill_idx,
                key="fmt_user_skill_selectbox",
                label_visibility="collapsed",
            )
            if selected_skill_label != "なし（コアSkillを使用）":
                selected_skill = selected_skill_label
        else:
            st.caption(
                "登録済みのユーザーSkillはありません。"
                "`skills/user/` にSkillを追加するか、"
                "知識管理画面からSkillをアップロードしてください。"
            )

    return {
        "checklist_id": selected_checklist,
        "journal_style": selected_style or "APA",
        "skill_id": selected_skill,
    }
