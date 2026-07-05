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

# Human-readable labels for intent_object fields (SCR-02, right pane spec).
# Keys match analysis-request.schema.json IntentObject properties.
_FIELD_LABELS: dict[str, str] = {
    "objective":                     "研究目的",
    "outcome_type":                  "アウトカム種別",
    "outcome_variables":             "主要変数",
    "predictor_type":                "比較群/予測因子種別",
    "predictor_variables":           "予測変数",
    "study_design":                  "研究デザイン",
    "distribution_assumptions":      "分布の仮定",
    "reporting_checklist_inference": "報告チェックリスト",
}


def render_intent_entry(
    on_submit: Callable[[str, bytes | None], None],
    intent_confirmed: bool = False,
    existing_csv_filename: str | None = None,
    existing_csv_bytes: bytes | None = None,
) -> tuple[bool, bytes | None, str | None]:
    """Render SCR-02 Research Intent Entry (centre pane).

    Args:
        on_submit: Called with (prompt_text, csv_bytes) when the user clicks
                   「研究意図を解析」. Business logic (Planner invocation) lives
                   in this callback, not in this component.
        intent_confirmed: Whether the intent_object has been reviewed and
                          confirmed by the user (controls the start button).
        existing_csv_filename: Filename of a previously uploaded file stored in
                               session_state, shown when the uploader is empty.
        existing_csv_bytes: Bytes of a previously uploaded file, used to render
                            the summary when the uploader widget is reset.

    Returns:
        Tuple of (start_clicked, csv_bytes, csv_filename).
        app.py saves bytes and filename to session_state on every render.
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
    csv_filename: str | None = None
    if uploaded is not None:
        csv_bytes = uploaded.read()
        csv_filename = uploaded.name
        _render_upload_summary(csv_filename, csv_bytes)
        st.info("🔒 このデータは安全に処理されます。raw dataはAIに送信されません。")
    elif existing_csv_bytes is not None and existing_csv_filename is not None:
        # Show previously uploaded file info after navigating back to this screen
        st.caption("📂 読み込み済みファイル")
        _render_upload_summary(existing_csv_filename, existing_csv_bytes)

    st.divider()

    # 3. Analyze button — explicitly triggered (no 500ms debounce in Streamlit)
    active_bytes = csv_bytes if csv_bytes is not None else existing_csv_bytes
    analyze_disabled = not intent_text.strip()
    if st.button(
        "研究意図を解析",
        disabled=analyze_disabled,
        key="analyze_intent_btn",
    ):
        on_submit(intent_text.strip(), active_bytes)

    # 4. Start analysis button (UP-002: disabled until intent confirmed)
    st.write("")  # spacer
    start_clicked = st.button(
        "解析を開始する →",
        disabled=not intent_confirmed,
        type="primary",
        key="start_analysis_btn",
        help="研究意図を解析・確認してから実行できます" if not intent_confirmed else None,
    )

    return start_clicked, csv_bytes, csv_filename


def render_intent_preview(payload: dict) -> None:
    """Render the Planner Agent's intent interpretation (right pane / SCR-02).

    Accepts the Planner ``output_payload`` (which nests the actual intent under
    the ``intent_object`` key). Display-only — no session_state writes.
    """
    if not payload:
        st.caption("「研究意図を解析」をクリックすると解析結果がここに表示されます")
        return

    # Unwrap: fields live under output_payload["intent_object"]; confidence and
    # clarification flags live at the output_payload top level.
    intent_object = payload.get("intent_object", payload)

    st.subheader("🤖 AI解釈結果")

    # Confidence score indicator (SCR-02 right pane spec)
    confidence = payload.get("confidence_score", intent_object.get("confidence_score"))
    if confidence is not None:
        _render_confidence(float(confidence))

    st.divider()

    # Field-by-field display with null / low-confidence highlighting
    for field, label in _FIELD_LABELS.items():
        value = _format_field_value(intent_object.get(field))
        if value is None:
            # Yellow highlight for missing / ambiguous fields (interaction-flow.md §4)
            st.markdown(
                f'<div style="background:#FFFBEB;border-left:3px solid #D97706;'
                f'padding:4px 8px;margin:3px 0;border-radius:2px;">'
                f'<strong>{label}:</strong> 🟡 確認が必要</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"**{label}:** {value}")

    # One-sentence summary if the Planner provided one
    summary = intent_object.get("natural_language_summary")
    if summary:
        st.caption(summary)

    # Raw JSON in expander for level-3 detail (UP-003)
    with st.expander("▼ 詳細 (JSON)"):
        st.json(payload)


_VALUE_LABELS: dict[str, str] = {
    # objective
    "between_group_comparison":        "群間比較",
    "paired_comparison":               "対応比較（前後比較）",
    "correlation_analysis":            "相関分析",
    "regression_analysis":             "回帰分析",
    "survival_analysis":               "生存時間分析",
    "diagnostic_accuracy":             "診断精度",
    "prediction_model":                "予測モデル",
    "descriptive_only":                "記述統計",
    "systematic_review":               "システマティックレビュー",
    # outcome_type / predictor_type
    "continuous":                      "連続変数",
    "categorical_binary":              "2値カテゴリ変数",
    "categorical_ordinal":             "順序カテゴリ変数",
    "categorical_nominal":             "名義カテゴリ変数",
    "survival":                        "生存時間",
    "mixed":                           "混合",
    "unknown":                         "不明",
    # study_design
    "randomized_controlled_trial":     "ランダム化比較試験（RCT）",
    "observational":                   "観察研究",
    "cohort":                          "コホート研究",
    "case_control":                    "症例対照研究",
    "cross_sectional":                 "横断研究",
    "systematic_review_or_meta_analysis": "システマティックレビュー／メタ分析",
    "diagnostic_accuracy_study":       "診断精度研究",
    # distribution_assumptions
    "assumed_normal":                  "正規分布を仮定",
    "assumed_non_normal":              "非正規分布を仮定",
    # variable roles
    "primary_outcome":                 "主要アウトカム",
    "secondary_outcome":               "副次アウトカム",
    "time_to_event":                   "イベント発生時間",
    "event_indicator":                 "イベント指標",
    "primary_predictor":               "主要予測因子",
    "covariate":                       "共変量",
    "grouping_variable":               "群分け変数",
    "matching_variable":               "マッチング変数",
    # reporting checklists (proper nouns — keep acronym, add context)
    "CONSORT":  "CONSORT（RCT）",
    "STROBE":   "STROBE（観察研究）",
    "TRIPOD":   "TRIPOD（予測モデル）",
    "PRISMA":   "PRISMA（システマティックレビュー）",
    "STARD":    "STARD（診断精度）",
}


def _format_field_value(value: object) -> str | None:
    """Format an intent_object field for display, or None if empty.

    Handles var_n list fields (outcome_variables / predictor_variables) by
    joining their var_n / role pairs into a readable string.
    Enum values are translated to Japanese via _VALUE_LABELS.
    """
    if value is None or value == "":
        return None
    if isinstance(value, list):
        if not value:
            return None
        parts = []
        for item in value:
            if isinstance(item, dict):
                var_n = item.get("var_n", "?")
                role = item.get("role")
                role_ja = _VALUE_LABELS.get(role, role) if role else None
                parts.append(f"{var_n}（{role_ja}）" if role_ja else str(var_n))
            else:
                parts.append(_VALUE_LABELS.get(str(item), str(item)))
        return ", ".join(parts)
    s = str(value)
    return _VALUE_LABELS.get(s, s)


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
