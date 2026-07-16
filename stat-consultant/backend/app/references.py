"""User reference library — lightweight keyword RAG (Step 4).

Translated from ``cie/knowledge/reference_library.py`` (``MarkdownReferenceLibrary``),
trimmed to what the stat-consultant needs: a single flat folder of the user's
own uploaded Markdown/text references (no ``official/`` tree, no approval flow,
no hierarchy — SPEC 5.6, individual use). Retrieval is keyword-overlap scoring;
no embeddings (SPEC §6, 参考資料検索).

Query terms are extracted from the latest user message across scripts (ASCII,
katakana, kanji) so a distinctive term in the message — a drug name, a guideline
name — surfaces the reference that mentions it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Extract candidate keywords from a (Japanese or English) message. Pure-hiragana
# runs are skipped — they are mostly particles/inflection, not content words.
_ASCII_RE = re.compile(r"[A-Za-z0-9_.]{2,}")
_KATAKANA_RE = re.compile(r"[ァ-ヶー]{2,}")
_KANJI_RE = re.compile(r"[一-龯々]{2,}")


def extract_query_terms(text: str) -> list[str]:
    """Return de-duplicated candidate keywords from ``text`` (order preserved)."""
    terms = (
        _ASCII_RE.findall(text)
        + _KATAKANA_RE.findall(text)
        + _KANJI_RE.findall(text)
    )
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _safe_name(filename: str) -> str:
    """Sanitise an uploaded filename to a safe basename with a text extension."""
    base = Path(filename or "reference").name  # strip any directory component
    base = re.sub(r"[^0-9A-Za-z._\-ぁ-んァ-ヶー一-龯々]", "_", base)
    if not base or base in (".", ".."):
        base = "reference.md"
    if Path(base).suffix.lower() not in ReferenceLibrary.EXTENSIONS:
        base += ".md"
    return base


@dataclass(frozen=True)
class ReferenceDoc:
    """One user reference document."""

    name: str
    content: str

    def excerpt(self, max_chars: int = 1500) -> str:
        """Return the content, truncated to ``max_chars`` for prompt budgeting."""
        if len(self.content) <= max_chars:
            return self.content
        return self.content[:max_chars] + "\n… [truncated] …"


class ReferenceLibrary:
    """Loads and retrieves the user's reference docs from a single flat folder.

    Not thread-safe by design: single-process, localhost-bound app (SPEC 4.1).
    """

    EXTENSIONS = {".md", ".markdown", ".txt"}

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._docs: list[ReferenceDoc] = []
        self.reload()

    def reload(self) -> None:
        """Re-read the folder (cheap; called after each save)."""
        docs: list[ReferenceDoc] = []
        for p in sorted(self._root.glob("*")):
            if p.is_file() and p.suffix.lower() in self.EXTENSIONS:
                try:
                    docs.append(ReferenceDoc(name=p.name, content=p.read_text("utf-8")))
                except OSError:
                    continue
        self._docs = docs

    @property
    def docs(self) -> list[ReferenceDoc]:
        return list(self._docs)

    def save(self, filename: str, content: str) -> str:
        """Save one reference into the folder and reload. Returns the saved name."""
        name = _safe_name(filename)
        (self._root / name).write_text(content, encoding="utf-8")
        self.reload()
        return name

    def retrieve(self, query_terms: list[str], top_k: int = 2) -> list[ReferenceDoc]:
        """Return the ``top_k`` docs most relevant to ``query_terms``.

        Keyword-overlap scoring: each term contributes its occurrence count in a
        doc (filename matches weigh more). Zero-match docs excluded; ties break
        by name for determinism.
        """
        normalized = [t.lower() for t in query_terms if t]
        if not normalized:
            return []
        scored: list[tuple[float, str, ReferenceDoc]] = []
        for doc in self._docs:
            body = doc.content.lower()
            name = doc.name.lower()
            score = 0.0
            for term in normalized:
                score += body.count(term)
                score += name.count(term) * 5
            if score > 0:
                scored.append((score, doc.name, doc))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [doc for _, _, doc in scored[:top_k]]


def build_reference_context(docs: list[ReferenceDoc]) -> str:
    """Render retrieved docs as a system-prompt section, or "" when there are none."""
    if not docs:
        return ""
    parts = [
        "\n\n# ユーザーがアップロードした参考資料",
        "以下はユーザー自身がアップロードした参考資料の抜粋。関連する場合は"
        "これを根拠として回答に反映し、資料名に触れてよい。矛盾する一般論より"
        "この資料を優先する。",
    ]
    for d in docs:
        parts.append(f"\n## {d.name}\n{d.excerpt()}")
    return "\n".join(parts)
