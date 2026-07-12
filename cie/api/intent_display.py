"""Shared var_n un-masking for Planner output (Fix C).

The Planner authors human-readable text (``natural_language_summary`` and
clarification labels) in var_n alias space — it never sees real column names on
the intent path — so those aliases would otherwise leak into the chat as raw
internal identifiers like ``var_4``. Both the REST ``/api/intent`` route and the
streaming ``WS /ws/chat`` route resolve them here, the single server-side source
of truth, so the invariant holds identically on both paths.

Structured identifiers (``outcome_variables[].var_n`` etc.) are deliberately left
intact — the frontend keeps using them programmatically; only prose the user
reads is resolved. A var whose header signalled PII is shown as an anonymised
placeholder, never its real name.
"""

from __future__ import annotations

import re

_VAR_TOKEN_RE = re.compile(r"\bvar_\d+\b")
_MASKED_LABEL = "（匿名化された列）"


def unmask_var_tokens(
    text: str, alias_map: dict[str, str], masked_vars: set[str]
) -> str:
    """Replace ``var_N`` tokens in user-facing text with real column names.

    A var listed in ``masked_vars`` (its header signalled PII) is replaced with
    an anonymised placeholder rather than its real name.
    """
    if not text:
        return text

    def repl(match: re.Match[str]) -> str:
        var_n = match.group(0)
        if var_n in masked_vars:
            return _MASKED_LABEL
        return alias_map.get(var_n, var_n)

    return _VAR_TOKEN_RE.sub(repl, text)


def resolve_intent_display(
    intent_object: dict,
    clarification_options: list[dict],
    alias_map: dict[str, str],
    masked_vars: set[str],
) -> None:
    """In-place: un-mask var_n tokens in the human-readable fields only.

    Resolves ``intent_object.natural_language_summary`` and each clarification
    option's ``label``; structured identifiers are left untouched.
    """
    summary = intent_object.get("natural_language_summary")
    if isinstance(summary, str):
        intent_object["natural_language_summary"] = unmask_var_tokens(
            summary, alias_map, masked_vars
        )
    for opt in clarification_options:
        label = opt.get("label")
        if isinstance(label, str):
            opt["label"] = unmask_var_tokens(label, alias_map, masked_vars)
