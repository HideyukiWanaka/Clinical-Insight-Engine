"""CIE Platform — Local embedding index for Knowledge retrieval (ADR-0005).

Replaces the keyword-overlap retriever (``MarkdownReferenceLibrary``) with a
local semantic search over the Markdown knowledge base. Implements
``spec/knowledge/embedding-rag-spec.md`` Section 2:

- Chunk ``knowledge/official/**/*.md`` (plus approved ``institutional/`` entry
  bodies) on heading boundaries, embed each chunk with a **fully local** model,
  and persist the vectors to a file-based, offline vector store.
- Expose ``EmbeddingReferenceLibrary.retrieve(query_terms, top_k)`` with the
  **same signature** as
  :meth:`cie.knowledge.reference_library.MarkdownReferenceLibrary.retrieve`, so
  callers in ``cie/agents/statistics.py``, ``visualization.py`` and
  ``reporting.py`` are switched purely by dependency injection (services.py).

Offline-first (PROJECT_RULES.md S.8, ADR-0005 原則3): the default vectorizer
(:class:`TfidfVectorizer`) is pure-stdlib and deterministic — it needs no model
download and performs **zero** network I/O, so indexing and search are fully
offline. Only the *retrieval* embedding is local; the R-code-generating LLM
stays the cloud model.

Why this beats the keyword retriever on 表記ゆれ (notation variants): the
tokeniser splits on *every* non-alphanumeric byte, so "Mann-Whitney",
"mann_whitney_u_test" and "mann whitney" all reduce to the same ``{mann,
whitney}`` tokens. IDF weighting then makes distinctive terms (``wilcox``,
``mann``) dominate over ubiquitous ones (``test``, ``u``), and character
tri-grams on longer tokens bridge morphological variants. Cosine similarity over
these vectors ranks the right reference section even when the surface strings
differ — which raw keyword-count scoring cannot do.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from cie.knowledge.reference_library import ReferenceDoc

# ---------------------------------------------------------------------------
# Tokenisation / parsing helpers
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(r"^#\s+(.*\S)\s*$", re.MULTILINE)
_DOMAIN_RE = re.compile(r"^#\s*Domain:\s*(.+?)\s*$", re.MULTILINE)
# Chunk on top-level section headings (H1/H2). Deeper headings stay inside their
# parent section so chunks are coherent topical units, not one-line fragments.
_SECTION_HEADING_RE = re.compile(r"^(#{1,2})\s+(.*\S)\s*$")
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
# ASCII word tokens; separator-agnostic (see module docstring).
_WORD_RE = re.compile(r"[a-z0-9]+")
# Runs of non-ASCII characters (CJK etc.) — embedded via character n-grams so
# Japanese reference text is searchable without a word segmenter.
_CJK_RUN_RE = re.compile(r"[^\x00-\x7f]+")

_STORE_VERSION = 3
_WORD_WEIGHT = 1.0
_CHAR_WEIGHT = 0.35          # sub-token trigrams: supportive signal only
_CJK_WEIGHT = 1.0
_CHAR_NGRAM_MIN_LEN = 6      # only long tokens get char trigrams (avoid noise)


def _feature_counts(text: str) -> dict[str, float]:
    """Weighted bag-of-features (term frequencies) for one text span.

    Features:
      * ``w:<token>``   — ASCII word unigrams (separator-agnostic; primary).
      * ``c:<trigram>`` — padded char trigrams for tokens >= 6 chars (bridges
        morphological variants / typos; down-weighted to stay supportive).
      * ``j:<ngram>``   — char bi/tri-grams over non-ASCII runs (CJK).
    """
    lower = text.lower()
    counts: dict[str, float] = {}

    for token in _WORD_RE.findall(lower):
        key = "w:" + token
        counts[key] = counts.get(key, 0.0) + _WORD_WEIGHT
        if len(token) >= _CHAR_NGRAM_MIN_LEN:
            padded = f"^{token}$"
            for i in range(len(padded) - 2):
                gram = "c:" + padded[i : i + 3]
                counts[gram] = counts.get(gram, 0.0) + _CHAR_WEIGHT

    for run in _CJK_RUN_RE.findall(lower):
        if len(run) == 1:
            key = "j:" + run
            counts[key] = counts.get(key, 0.0) + _CJK_WEIGHT
            continue
        for n in (2, 3):
            for i in range(len(run) - n + 1):
                key = "j:" + run[i : i + n]
                counts[key] = counts.get(key, 0.0) + _CJK_WEIGHT

    return counts


class TfidfVectorizer:
    """Deterministic, offline TF-IDF vectorizer (default embedder).

    Fitted on the chunk corpus to learn per-feature inverse document frequency,
    then turns any text into a sparse, L2-normalised vector (``dict[str,
    float]``) so that the dot product of two vectors equals their cosine
    similarity. Pure stdlib — no model files, no downloads, no network.
    """

    def __init__(self, idf: dict[str, float] | None = None) -> None:
        self._idf: dict[str, float] = idf or {}

    @property
    def idf(self) -> dict[str, float]:
        return self._idf

    def fit(self, corpus: list[str]) -> TfidfVectorizer:
        n_docs = len(corpus) or 1
        df: dict[str, int] = {}
        for text in corpus:
            for feature in _feature_counts(text):
                df[feature] = df.get(feature, 0) + 1
        # Smoothed IDF: log((N+1)/(df+1)) + 1  (always positive).
        self._idf = {
            feat: math.log((n_docs + 1) / (d + 1)) + 1.0 for feat, d in df.items()
        }
        return self

    def transform(self, text: str) -> dict[str, float]:
        vec: dict[str, float] = {}
        for feature, tf in _feature_counts(text).items():
            idf = self._idf.get(feature)
            if idf is None:
                continue  # out-of-vocabulary features carry no weight
            # Sublinear tf dampens very frequent terms within a chunk.
            vec[feature] = (1.0 + math.log(tf)) * idf
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm == 0.0:
            return vec
        return {k: v / norm for k, v in vec.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Dot product of two L2-normalised sparse vectors (== cosine similarity)."""
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(k, 0.0) for k, w in a.items())


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Chunk:
    doc_title: str
    domain: str
    path: Path
    heading: str
    content: str


def chunk_markdown(text: str, *, max_chars: int = 1600) -> list[tuple[str, str]]:
    """Split *text* into ``(heading, chunk_text)`` pairs on H1/H2 boundaries.

    A section longer than *max_chars* is further split on blank-line paragraph
    boundaries so no single chunk blows the embedding/prompt budget. Returns at
    least one chunk (the whole text) for heading-free documents.
    """
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current: list[str] = []
    for line in lines:
        m = _SECTION_HEADING_RE.match(line)
        if m:
            if current:
                sections.append((current_heading, current))
            current_heading = m.group(2).strip()
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append((current_heading, current))
    if not sections:
        sections = [("", lines)]

    chunks: list[tuple[str, str]] = []
    for heading, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        if len(body) <= max_chars:
            chunks.append((heading, body))
            continue
        buf: list[str] = []
        size = 0
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if not para:
                continue
            if size + len(para) > max_chars and buf:
                chunks.append((heading, "\n\n".join(buf)))
                buf, size = [], 0
            buf.append(para)
            size += len(para) + 2
        if buf:
            chunks.append((heading, "\n\n".join(buf)))
    return chunks or [("", text.strip())]


# ---------------------------------------------------------------------------
# Reference library
# ---------------------------------------------------------------------------


class EmbeddingReferenceLibrary:
    """Local-embedding semantic retriever (drop-in for MarkdownReferenceLibrary).

    Args:
        knowledge_root: Directory containing ``official/`` (and optionally
            ``institutional/``) Markdown reference trees. Matches the positional
            construction of ``MarkdownReferenceLibrary`` so services.py swaps the
            two with no other changes.
        subdirs: Restrict ``official/`` loading to these sub-paths. ``None``
            (default) indexes **all** of ``official/**/*.md`` — a superset of the
            old statistics+R default, so visualization/reporting retrieval
            improves for free.
        store_path: Where the file-based vector store is persisted. Defaults to
            ``<knowledge_root>/.embedding_index/index.json``.
        auto_build: Build (or load) the index at construction. Set ``False`` in
            tests that construct then call :meth:`reindex` explicitly.
    """

    def __init__(
        self,
        knowledge_root: Path | str,
        *,
        subdirs: tuple[str, ...] | None = None,
        store_path: Path | str | None = None,
        auto_build: bool = True,
    ) -> None:
        self._root = Path(knowledge_root)
        self._subdirs = subdirs
        self._store_path = (
            Path(store_path)
            if store_path is not None
            else self._root / ".embedding_index" / "index.json"
        )
        self._vectorizer = TfidfVectorizer()
        self._chunks: list[_Chunk] = []
        self._vectors: list[dict[str, float]] = []
        if auto_build:
            self._load_or_build()

    # ------------------------------------------------------------------
    # Source discovery
    # ------------------------------------------------------------------

    def _source_files(self) -> list[Path]:
        files: list[Path] = []
        official = self._root / "official"
        bases = [official / sd for sd in self._subdirs] if self._subdirs else [official]
        for base in bases:
            if base.exists():
                files.extend(sorted(base.rglob("*.md")))
        institutional = self._root / "institutional"
        if institutional.exists():
            files.extend(sorted(institutional.rglob("*.md")))
        seen: set[Path] = set()
        unique: list[Path] = []
        for f in files:
            if f not in seen:
                seen.add(f)
                unique.append(f)
        return unique

    def _manifest_hash(self, files: list[Path]) -> str:
        h = hashlib.sha256()
        h.update(f"v{_STORE_VERSION}:".encode())
        for f in files:
            try:
                data = f.read_bytes()
            except OSError:
                continue
            rel = f.relative_to(self._root).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(hashlib.sha256(data).hexdigest().encode("ascii"))
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Build / load / persist
    # ------------------------------------------------------------------

    def _load_or_build(self) -> None:
        files = self._source_files()
        manifest = self._manifest_hash(files)
        if self._try_load(manifest):
            return
        self._build(files)
        self._persist(manifest)

    def _try_load(self, manifest: str) -> bool:
        if not self._store_path.exists():
            return False
        try:
            store = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if store.get("version") != _STORE_VERSION:
            return False
        if store.get("manifest_hash") != manifest:
            return False
        chunks: list[_Chunk] = []
        vectors: list[dict[str, float]] = []
        for rec in store.get("records", []):
            chunks.append(
                _Chunk(
                    doc_title=rec["title"],
                    domain=rec["domain"],
                    path=Path(rec["path"]),
                    heading=rec["heading"],
                    content=rec["content"],
                )
            )
            vectors.append(rec["vector"])
        self._vectorizer = TfidfVectorizer(idf=store.get("idf", {}))
        self._chunks = chunks
        self._vectors = vectors
        return True

    def _build(self, files: list[Path]) -> None:
        raw_chunks: list[_Chunk] = []
        embed_texts: list[str] = []
        for md_path in files:
            try:
                text = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            title_match = _TITLE_RE.search(text)
            domain_match = _DOMAIN_RE.search(text)
            doc_title = title_match.group(1) if title_match else md_path.stem
            domain = domain_match.group(1) if domain_match else _infer_domain(md_path)
            for heading, content in chunk_markdown(text):
                raw_chunks.append(
                    _Chunk(
                        doc_title=doc_title,
                        domain=domain,
                        path=md_path,
                        heading=heading,
                        content=content,
                    )
                )
                # Prepend title + heading so the section's topic is part of its
                # embedding even when the body omits the method name.
                embed_texts.append(f"{doc_title}\n{heading}\n{content}")

        self._vectorizer = TfidfVectorizer().fit(embed_texts)
        self._chunks = raw_chunks
        self._vectors = [self._vectorizer.transform(t) for t in embed_texts]

    def _persist(self, manifest: str) -> None:
        store = {
            "version": _STORE_VERSION,
            "manifest_hash": manifest,
            "idf": self._vectorizer.idf,
            "records": [
                {
                    "path": str(chunk.path),
                    "title": chunk.doc_title,
                    "domain": chunk.domain,
                    "heading": chunk.heading,
                    "content": chunk.content,
                    "vector": vec,
                }
                for chunk, vec in zip(self._chunks, self._vectors, strict=True)
            ],
        }
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._store_path.write_text(
                json.dumps(store, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            # Persistence is a cache optimisation — an unwritable knowledge tree
            # must not break in-memory retrieval.
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reindex(self) -> int:
        """Rebuild the index from disk and repersist. Returns the chunk count.

        Called after a knowledge approval (POST /api/knowledge/approve) and by
        POST /api/knowledge/reindex so newly-registered institutional/ entries
        become searchable. The corpus is small, so a full deterministic rebuild
        is both simplest and correct (no partial-update drift).
        """
        files = self._source_files()
        self._build(files)
        self._persist(self._manifest_hash(files))
        return len(self._chunks)

    @property
    def docs(self) -> list[ReferenceDoc]:
        """All indexed chunks as ReferenceDoc (parity with MarkdownReferenceLibrary)."""
        return [
            ReferenceDoc(
                title=c.doc_title, domain=c.domain, path=c.path, content=c.content
            )
            for c in self._chunks
        ]

    def retrieve(self, query_terms: list[str], top_k: int = 4) -> list[ReferenceDoc]:
        """Return the *top_k* most semantically similar reference docs.

        Same contract as ``MarkdownReferenceLibrary.retrieve``: takes
        ``list[str]`` query terms, returns ``list[ReferenceDoc]`` (``.title`` ->
        provenance, list -> message builder). Terms are concatenated into one
        query vector and scored by cosine similarity. Results are de-duplicated
        to the best-scoring chunk per source document. Non-matching queries
        (all scores <= 0) return ``[]`` so the prompt asks for no grounding.
        """
        normalized = [t for t in query_terms if t]
        if not normalized or not self._chunks:
            return []
        qvec = self._vectorizer.transform(" ".join(normalized))
        if not qvec:
            return []

        best_by_path: dict[Path, tuple[float, _Chunk]] = {}
        for chunk, vec in zip(self._chunks, self._vectors, strict=True):
            score = _cosine(qvec, vec)
            if score <= 0.0:
                continue
            prev = best_by_path.get(chunk.path)
            if prev is None or score > prev[0]:
                best_by_path[chunk.path] = (score, chunk)

        ranked = sorted(best_by_path.values(), key=lambda s: (-s[0], s[1].doc_title))
        return [
            ReferenceDoc(
                title=chunk.doc_title,
                domain=chunk.domain,
                path=chunk.path,
                content=chunk.content,
            )
            for _, chunk in ranked[:top_k]
        ]


def _infer_domain(md_path: Path) -> str:
    """Best-effort domain from the path (e.g. official/statistics/... -> statistics)."""
    parts = md_path.parts
    for anchor in ("official", "institutional"):
        if anchor in parts:
            idx = parts.index(anchor)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return "unknown"
