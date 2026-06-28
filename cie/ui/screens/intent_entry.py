"""CIE Platform — SCR-02 Research Intent Entry screen.

Presentation only. No business logic, no direct session_state writes.

``render_intent_entry`` calls the ``on_submit`` callback when the user
requests intent analysis, and returns True when the user requests to start
the analysis workflow (signalling app.py to open the approval panel).

``render_intent_preview`` shows the Planner Agent's interpretation of
the research intent (right-pane display; read-only).
"""

from __future__ import annotations

from typing import Callable

import streamlit as st

_INTENT_PLACEHOLDER = (
    "研究目的を自然な言葉で記述してください。\n\n"
    "例）「治療群Aと対照群Bの術後90日死亡率を比較したい」\n"
    "    「BMIと血圧の相関を調べたい」\n"
    "    「介入前後の痛みスコアを同一患者で比較したい」"
)

# Human-readable labels for intent_object fields (SCR-02, right pane spec)
_FIELD_LABELS: dict[str, str] = {
    "objective":         "研究目的",
    "outcome_type":      "アウトカム種別",
    "primary_variable":  "主要変数",
    "comparison_groups": "比較群",
    "paired":            "対応あり/なし",
    "subject_id_var":    "患者ID変数",
    "analysis_type":     "解析タイプ",
    "study_design":      "研究デザイン",
}


def render_intent_entry(
    on_submit: Callable[[str, bytes | None], None],
    intent_confirmed: bool = False,
) -> bool:
    """Render SCR-02 Research Intent Entry (centre pane).

    Args:
        on_submit: Called with (prompt_text, csv_bytes) when the user clicks
                   「研究意図を解析」. Business logic (Planner invocation) lives
                   in this callback, not in this component.
        intent_confirmed: Whether the intent_object has been reviewed and
                          confirmed by the user (controls the start button).

    Returns:
        True when the user clicks「解析を開始する →」(app.py should then set
        ``approval_pending=True`` in session_state).  False otherwise.
    """
    st.title("研究意図入力")

    # 1. Intent textarea (UP-001: intent is the visual centre)
    intent_text: str = st.text_area(
        "研究目的を入力してください",
        placeholder=_INTENT_PLACEHOLDER,
        height=200,
        key="intent_text_input",
    )

    # 2. Dataset dropzone (SCR-02: DatasetDropzone spec)
    uploaded = st.file_uploader(
        "データセット（CSV/TSV/XLSX）",
        type=["csv", "tsv", "xlsx"],
        key="dataset_upload",
    )

    csv_bytes: bytes | None = None
    if uploaded is not None:
        csv_bytes = uploaded.read()
        _render_upload_summary(uploaded.name, csv_bytes)
        st.info("🔒 このデータは安全に処理されます。raw dataはAIに送信されません。")

    st.divider()

    # 3. Analyze button — explicitly triggered (no 500ms debounce in Streamlit)
    analyze_disabled = not intent_text.strip()
    if st.button(
        "研究意図を解析",
        disabled=analyze_disabled,
        key="analyze_intent_btn",
    ):
        on_submit(intent_text.strip(), csv_bytes)

    # 4. Start analysis button (UP-002: disabled until intent confirmed)
    st.write("")  # spacer
    start_clicked = st.button(
        "解析を開始する →",
        disabled=not intent_confirmed,
        type="primary",
        key="start_analysis_btn",
        help="研究意図を解析・確認してから実行できます" if not intent_confirmed else None,
    )

    return start_clicked


def render_intent_preview(intent_object: dict) -> None:
    """Render the Planner Agent's intent interpretation (right pane / SCR-02).

    Display-only — no session_state writes.
    """
    if not intent_object:
        st.caption("「研究意図を解析」をクリックすると解析結果がここに表示されます")
        return

    st.subheader("🤖 AI解釈結果")

    # Confidence score indicator (SCR-02 right pane spec)
    confidence = intent_object.get("confidence_score")
    if confidence is not None:
        _render_confidence(float(confidence))

    st.divider()

    # Field-by-field display with null / low-confidence highlighting
    for field, label in _FIELD_LABELS.items():
        value = intent_object.get(field)
        if value is None:
            # Yellow highlight for missing / ambiguous fields (interaction-flow.md §4)
            st.markdown(
                f'<div style="background:#FFFBEB;border-left:3px solid #D97706;'
                f'padding:4px 8px;margin:3px 0;border-radius:2px;">'
                f'<strong>{label}:</strong> 🟡 確認が必要</div>',
                unsafe_allow_html=True,
            )
        elif value is False or value == "false":
            st.markdown(f"**{label}:** {value}")
        else:
            st.markdown(f"**{label}:** {value}")

    # Raw JSON in expander for level-3 detail (UP-003)
    with st.expander("▼ 詳細 (JSON)"):
        st.json(intent_object)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _render_confidence(score: float) -> None:
    if score >= 0.8:
        st.markdown(f"**確信度:** 🟢 {score:.2f}")
    elif score >= 0.6:
        st.markdown(f"**確信度:** 🟡 {score:.2f} — 確認推奨")
    else:
        st.markdown("**確信度:** 🔴 人間による確認が必要です")


def _render_upload_summary(filename: str, data: bytes) -> None:
    """Show file name and rough row/size summary after upload."""
    size_kb = len(data) / 1024

    if filename.lower().endswith((".csv", ".tsv")):
        sep = b"\t" if filename.lower().endswith(".tsv") else b","
        row_count = max(0, data.count(b"\n") - 1)
        # Estimate column count from first line
        try:
            first_line = data.split(b"\n")[0]
            col_count = len(first_line.split(sep))
        except Exception:
            col_count = "?"
        st.success(
            f"📂 {filename}  "
            f"（推定 {row_count:,} 行 × {col_count} 列、{size_kb:.1f} KB）"
        )
    else:
        st.success(f"📂 {filename}  （{size_kb:.1f} KB）")
