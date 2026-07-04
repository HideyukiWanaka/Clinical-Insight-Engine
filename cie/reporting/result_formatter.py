"""CIE Platform — statistical result formatter.

Renders the ``statistical_results`` object (produced by the Runtime Agent from
the R script's ``result.json``) into human-readable text. This is a pure
function over already-computed numbers — it never computes or invents values,
so it is safe to display directly to the user.

Phase 3 will extend this with journal-style (APA/AMA/Vancouver) and reporting
checklist awareness; this module provides the neutral, always-available
rendering used from Phase 1 onward.
"""

from __future__ import annotations

from typing import Any

# Fields rendered in a fixed, readable order when present.
_ORDERED_FIELDS: list[tuple[str, str]] = [
    ("test_name", "検定"),
    ("method_id", "手法ID"),
    ("test_statistic", "検定統計量"),
    ("df", "自由度"),
    ("p_value", "p値"),
    ("effect_size", "効果量"),
    ("effect_size_measure", "効果量の種類"),
    ("sample_size", "標本サイズ"),
]


def _fmt_number(value: Any) -> str:
    """Format a number compactly; pass through non-numbers as str."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != 0 and (abs(value) < 1e-3 or abs(value) >= 1e6):
            return f"{value:.3e}"
        return f"{value:.4g}"
    return str(value)


def _format_p_value(value: Any) -> str:
    """APA-ish p-value rendering (p < .001 for very small values)."""
    try:
        p = float(value)
    except (TypeError, ValueError):
        return str(value)
    if p < 0.001:
        return "< 0.001"
    return f"{p:.3f}"


def format_statistical_results(
    statistical_results: dict | None,
    reason: str | None = None,
) -> str:
    """Render ``statistical_results`` as a Markdown summary.

    Args:
        statistical_results: Parsed result.json from the Runtime Agent, or None.
        reason: When results are None, the reason string from the Runtime Agent.

    Returns:
        A Markdown string suitable for display. Never raises on odd input.
    """
    if not statistical_results:
        detail = f"（理由: {reason}）" if reason else ""
        return (
            "### 統計結果\n\n"
            f"統計結果は生成されませんでした。{detail}\n\n"
            "R スクリプトが `result.json` を出力しなかったか、実行に失敗した可能性があります。"
        )

    lines: list[str] = ["### 統計結果", ""]

    for key, label in _ORDERED_FIELDS:
        if key not in statistical_results or statistical_results[key] is None:
            continue
        value = statistical_results[key]
        rendered = _format_p_value(value) if key == "p_value" else _fmt_number(value)
        lines.append(f"- **{label}**: {rendered}")

    ci_lower = statistical_results.get("ci_lower")
    ci_upper = statistical_results.get("ci_upper")
    if ci_lower is not None and ci_upper is not None:
        lines.append(
            f"- **95%信頼区間**: [{_fmt_number(ci_lower)}, {_fmt_number(ci_upper)}]"
        )

    group_summaries = statistical_results.get("group_summaries")
    if isinstance(group_summaries, dict) and group_summaries:
        lines.append("")
        lines.append("**群別要約**")
        for group, summary in group_summaries.items():
            if isinstance(summary, dict):
                parts = ", ".join(f"{k}={_fmt_number(v)}" for k, v in summary.items())
                lines.append(f"- {group}: {parts}")
            else:
                lines.append(f"- {group}: {_fmt_number(summary)}")

    # Surface any extra keys the script emitted that we didn't render above.
    rendered_keys = {k for k, _ in _ORDERED_FIELDS} | {
        "ci_lower", "ci_upper", "group_summaries",
    }
    extras = {
        k: v for k, v in statistical_results.items()
        if k not in rendered_keys and v is not None
    }
    if extras:
        lines.append("")
        lines.append("**その他**")
        for k, v in extras.items():
            lines.append(f"- {k}: {_fmt_number(v)}")

    return "\n".join(lines)
