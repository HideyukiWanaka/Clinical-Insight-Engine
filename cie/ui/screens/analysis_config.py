"""CIE Platform — SCR-05 Analysis Configuration & Execution Approval screen.

Presentation only. Business logic (Planner/Statistics Agent) is invoked by
callers, not here.

Returns an event dict to app.py, which then sets ``approval_pending=True``
when the user requests execution approval.
"""

from __future__ import annotations

import streamlit as st

# Japanese display names for statistical methods (SCR-05 spec)
_METHOD_NAMES_JA: dict[str, str] = {
    "welch_t_test":        "Welch t検定",
    "student_t_test":      "Student t検定",
    "paired_t_test":       "対応のある t検定",
    "mann_whitney_u":      "Mann-Whitney U検定",
    "wilcoxon":            "Wilcoxon符号順位検定",
    "one_way_anova":       "一元配置分散分析",
    "repeated_anova":      "繰り返し測定分散分析",
    "kruskal_wallis":      "Kruskal-Wallis検定",
    "pearson_correlation":  "Pearson積率相関係数",
    "spearman_correlation": "Spearman順位相関",
    "linear_regression":   "線形回帰",
    "logistic_regression":  "ロジスティック回帰",
    "cox_regression":       "Cox比例ハザード回帰",
    "kaplan_meier":         "Kaplan-Meier曲線",
    "chi_square":           "カイ二乗検定",
    "fisher_exact":         "Fisher正確確率検定",
    "mcnemar":              "McNemar検定",
}

# Brief plain-language descriptions for each method
_METHOD_DESCRIPTIONS_JA: dict[str, str] = {
    "welch_t_test":       "2群間の連続変数を比較するための検定です。正規分布が確認され、等分散を仮定しない堅牢な手法です。",
    "student_t_test":     "2群間の連続変数を比較するための検定です。正規分布と等分散を仮定します。",
    "paired_t_test":      "同一対象の2時点間を比較するための検定です。対応のある繰り返し測定に使用します。",
    "mann_whitney_u":     "正規分布が確認されない2群間の比較に用いるノンパラメトリック検定です。",
    "wilcoxon":           "対応のある2時点間を比較するノンパラメトリック検定です。",
    "one_way_anova":      "3群以上の連続変数を一度に比較する分析手法です。",
    "kruskal_wallis":     "正規分布が確認されない3群以上を比較するノンパラメトリック検定です。",
    "pearson_correlation": "2変数間の線形相関の強さを定量化します（正規分布を仮定）。",
    "spearman_correlation": "順位に基づく相関係数です。非線形関係や外れ値に頑健です。",
    "linear_regression":  "連続アウトカムを1つ以上の説明変数で予測・説明する回帰モデルです。",
    "logistic_regression": "二値アウトカム（発症あり/なし）を予測するロジスティック回帰モデルです。",
    "cox_regression":     "生存時間データにおいて、複数の共変量が死亡・イベント発生率に与える影響を解析します。",
    "kaplan_meier":       "生存曲線を推定し、群間の生存率の差を視覚化します。",
    "chi_square":         "カテゴリ変数間の独立性を検定します（期待度数5以上が推奨）。",
    "fisher_exact":       "カテゴリ変数間の独立性を正確に検定します（サンプルサイズが小さい場合に使用）。",
}

_AVAILABLE_METHODS = sorted(_METHOD_NAMES_JA.keys())


def render_analysis_config(
    analysis_plan: dict,
    assumption_report: dict | None,
) -> dict:
    """Render SCR-05 Analysis Configuration.

    Args:
        analysis_plan: Output from statistics / planner agent. Expected keys:
            ``method_used``, ``method_justification``, ``secondary_methods``.
        assumption_report: Optional dict with key ``checks`` (list of dicts
            with ``name``, ``passed``, ``result_summary``).

    Returns:
        ``{
            "approved": bool,          # True: request approval panel from app.py
            "override_method": str | None,
            "override_reason": str | None,
        }``
        ``approved`` is True only on the render where the approval button is clicked.
    """
    st.title("統計解析設定・実行")

    method_used: str = analysis_plan.get("method_used", "")
    method_ja    = _METHOD_NAMES_JA.get(method_used, method_used)
    justification = analysis_plan.get(
        "method_justification",
        "統計エンジンが選択しました。",
    )

    # 1. Selected method card (SCR-05 spec)
    st.markdown("### 選択された統計手法")
    with st.container(border=True):
        col_icon, col_content = st.columns([1, 6])
        with col_icon:
            st.markdown("## 📊")
        with col_content:
            st.markdown(f"#### {method_ja}")
            if method_used in _METHOD_DESCRIPTIONS_JA:
                st.write(_METHOD_DESCRIPTIONS_JA[method_used])
            st.caption(f"選択根拠: {justification}")

        # "変更する" expander — method override UI
        with st.expander("▼ 変更する"):
            override_method = st.selectbox(
                "代替手法を選択",
                options=["（変更しない）"] + _AVAILABLE_METHODS,
                format_func=lambda m: (
                    "（変更しない）" if m == "（変更しない）"
                    else f"{_METHOD_NAMES_JA.get(m, m)} ({m})"
                ),
                key="override_method_select",
            )
            override_reason = st.text_area(
                "変更理由（必須）",
                placeholder="変更理由を具体的に記述してください（監査ログに記録されます）",
                key="override_reason_text",
            )

    st.divider()

    # 2. Assumption checklist (SCR-05 / REDCap-style list)
    if assumption_report:
        st.markdown("### 仮定チェック結果")
        _render_assumption_checklist(assumption_report)
        st.divider()

    # 3. Request execution approval — communicated to app.py via return value
    st.markdown("### 解析の実行承認")
    st.info(
        "承認後、Rスクリプトが実行されます。この操作は取り消せません。\n\n"
        "右ペインの承認パネルで「内容を確認しました」にチェックを入れてから承認してください。"
    )
    approve_requested = st.button(
        "承認パネルを表示する →",
        type="primary",
        key="request_analysis_approval_btn",
    )

    # Build return value
    selected_override = (
        override_method
        if "override_method_select" in st.session_state
        and st.session_state["override_method_select"] != "（変更しない）"
        else None
    )
    selected_reason = (
        st.session_state.get("override_reason_text") or None
    )

    return {
        "approved": approve_requested,
        "override_method": selected_override,
        "override_reason": selected_reason,
    }


def _render_assumption_checklist(assumption_report: dict) -> None:
    """Render REDCap-style assumption check results."""
    checks: list[dict] = assumption_report.get("checks", [])
    if not checks:
        st.caption("仮定チェック結果がありません。")
        return

    st.markdown(
        "<hr style='border:1px solid var(--cie-gray-200,#E5E7EB);'/>",
        unsafe_allow_html=True,
    )
    for check in checks:
        passed: bool = check.get("passed", True)
        name: str = check.get("name", "")
        summary: str = check.get("result_summary", "")
        icon = "✅" if passed else "⚠️"
        st.markdown(f"{icon} &nbsp; **{name}**")
        if summary:
            st.caption(f"&nbsp;&nbsp;&nbsp;&nbsp;{summary}")

    st.markdown(
        "<hr style='border:1px solid var(--cie-gray-200,#E5E7EB);'/>",
        unsafe_allow_html=True,
    )
