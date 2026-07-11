"""Unit tests for cie.api.routes.intent display-time var_n un-masking (Fix C).

The Planner authors natural_language_summary and clarification labels in var_n
alias space; the intent route resolves those to real column names before the
chat renders them, and shows an anonymised placeholder for PII-masked columns.
"""

from __future__ import annotations

from cie.api.routes.intent import (
    _MASKED_LABEL,
    _resolve_intent_display,
    _unmask_var_tokens,
)

_ALIAS_MAP = {
    "var_4": "検査年",
    "var_6": "性別",
    "var_10": "収縮期血圧_mmHg",
    "var_2": "患者氏名",
}


def test_unmask_replaces_var_tokens_with_real_names() -> None:
    text = "Compare var_10 as blood pressure between var_6 as sex."
    out = _unmask_var_tokens(text, _ALIAS_MAP, masked_vars=set())
    assert "var_10" not in out and "var_6" not in out
    assert "収縮期血圧_mmHg" in out and "性別" in out


def test_unmask_shows_placeholder_for_pii_masked_var() -> None:
    text = "Group by var_2."
    out = _unmask_var_tokens(text, _ALIAS_MAP, masked_vars={"var_2"})
    assert "患者氏名" not in out
    assert _MASKED_LABEL in out


def test_resolve_intent_display_updates_summary_and_labels_only() -> None:
    intent = {
        "natural_language_summary": "compare var_10 between var_6",
        # Structured identifiers must stay untouched for programmatic use.
        "outcome_variables": [{"var_n": "var_10", "role": "primary_outcome"}],
    }
    options = [{"option_id": "outcome:var_10", "label": "outcome is var_10"}]

    _resolve_intent_display(intent, options, _ALIAS_MAP, masked_vars=set())

    assert intent["natural_language_summary"] == "compare 収縮期血圧_mmHg between 性別"
    assert options[0]["label"] == "outcome is 収縮期血圧_mmHg"
    # var_n identifiers in structured fields are preserved verbatim.
    assert intent["outcome_variables"][0]["var_n"] == "var_10"
