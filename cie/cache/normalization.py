"""CIE Platform — Prompt normalization for the semantic cache (ADR-0004).

Phase 1 rules (prompts/phase_semantic_cache.md SC-1):
    1. Full-width alphanumerics → half-width
    2. ASCII letters → lower case
    3. Strip trailing polite/volitional suffixes（をしたいです 等）
    4. Collapse consecutive whitespace to a single space
    5. Remove punctuation（。、．，）

Phase 2 (SC-4): SYNONYM_MAP substitution applied as the final step.
Hiragana/katakana are intentionally NOT converted — doing so can change
meaning (ADR-0004).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

# Longest-first so that e.g. をしたいです wins over です.
# たい/たいです cover volitional endings（「〜を見たいです」→「〜を見」）.
_TRAILING_SUFFIXES: tuple[str, ...] = (
    "をしてください",
    "をしたいです",
    "をしたい",
    "してください",
    "したいです",
    "したい",
    "たいです",
    "たい",
    "です",
    "ます",
)

_PUNCTUATION_RE = re.compile(r"[。、．，]")
_WHITESPACE_RE = re.compile(r"\s+")

# ADR-0004 Phase 2 — curated from accumulated original_prompts.
SYNONYM_MAP: dict[str, str] = {
    "比べたい": "比較したい",
    "差を見たい": "比較したい",
    "違いを調べたい": "比較したい",
    "差異": "差",
    "ビフォーアフター": "前後",
    "before after": "前後",
    "介入前後": "前後",
    "治療前後": "前後",
    "関係を見たい": "相関を調べたい",
    "関連を見たい": "相関を調べたい",
    "relate": "相関",
    "correlation": "相関",
    "compare": "比較",
}


def normalize_prompt(prompt: str) -> str:
    """Normalize a user prompt into its canonical cache-key form."""
    # 1+2 — NFKC folds full-width alphanumerics to half-width; then lowercase.
    text = unicodedata.normalize("NFKC", prompt).lower()

    # 5 — punctuation removal before suffix stripping so 「〜です。」 still matches.
    text = _PUNCTUATION_RE.sub("", text)

    # 4 — whitespace collapse
    text = _WHITESPACE_RE.sub(" ", text).strip()

    # Phase 2 (pre-pass) — volitional variants like 「比べたい」 must be
    # unified BEFORE suffix stripping, or the trailing 「たい」 is removed
    # first and the synonym never matches.
    text = _apply_synonyms(text)

    # 3 — strip trailing suffixes repeatedly (「をしたいです」「見たいです」…)
    changed = True
    while changed:
        changed = False
        for suffix in _TRAILING_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)].rstrip()
                changed = True
                break

    # Phase 2 — synonym substitution is always the final step.
    return _apply_synonyms(text)


def _apply_synonyms(text: str) -> str:
    for variant, canonical in SYNONYM_MAP.items():
        text = text.replace(variant, canonical)
    return text


def make_dataset_fingerprint(metadata: dict) -> str:
    """Fingerprint the dataset's column structure (CA-006).

    Accepts either the list form ``{"columns": [{"var_n": ..,
    "inferred_type": ..}, ...]}`` or the mapping form
    ``{"var_1": {"inferred_type": ..}, ...}`` used by planner payloads.
    """
    columns = metadata.get("columns")
    if isinstance(columns, list):
        pairs = sorted(
            (col.get("var_n", ""), col.get("inferred_type", ""))
            for col in columns
        )
    else:
        pairs = sorted(
            (var_n, (info or {}).get("inferred_type", ""))
            for var_n, info in metadata.items()
            if isinstance(info, dict)
        )
    raw = json.dumps(pairs, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
