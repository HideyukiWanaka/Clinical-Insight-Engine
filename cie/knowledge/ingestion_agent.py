from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from cie.knowledge.ingestion_guard import IngestionError, IngestionGuard
from cie.knowledge.parsers.base import DocumentParserRegistry, ParsedDocument


@dataclass
class KnowledgeEntryDraft:
    """Transient AI-extraction result stored in knowledge/pending/ for human review."""

    draft_id: str
    source_hash: str
    source_filename: str
    parsed_text: str
    extracted_metadata: dict
    extracted_knowledge_items: list[dict]
    extracted_trust_level: str
    extracted_domain: str
    extraction_limitations: list[str]
    created_at: datetime
    status: str = "pending_review"


# ---------------------------------------------------------------------------
# Rule-based domain / trust-level heuristics
# ---------------------------------------------------------------------------

_DOMAIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "statistics": ("p-value", "regression", "anova", "statistical", "confidence interval", "variance"),
    "clinical": ("patient", "clinical trial", "endpoint", "adverse event", "treatment", "placebo"),
    "reporting": ("manuscript", "abstract", "figure", "table", "consort", "prisma"),
    "R": ("ggplot", "tidyverse", "dplyr", "r package", "cran"),
    "Python": ("python", "pandas", "numpy", "sklearn", "scipy"),
    "visualization": ("chart", "plot", "graph", "visualization", "colour palette"),
}

_REGULATORY_KEYWORDS = ("ich ", "fda ", "ema ", "guideline", "regulatory", "ich-e")
_PEER_REVIEWED_KEYWORDS = ("doi", "journal", "abstract", "methods", "results", "conclusion", "pubmed")

_DOI_PATTERN = re.compile(r"\b(10\.\d{4,}/[^\s,;)>\"]+)")
_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class KnowledgeIngestionAgent:
    """Executes KIP Phase 1 (quarantine) and Phase 2 (extraction).

    Writes exclusively to *pending_dir*. Never writes to official/ or
    institutional/ — that is the sole responsibility of KnowledgeLifecycleService
    (KIP-6, ADR-0003).
    """

    def __init__(
        self,
        ingestion_guard: IngestionGuard,
        parser_registry: DocumentParserRegistry,
        pending_dir: Path,
        source_dir: Path,
    ) -> None:
        self._guard = ingestion_guard
        self._registry = parser_registry
        self._pending_dir = pending_dir
        self._source_dir = source_dir

    async def ingest(
        self,
        file_path: Path,
        file_bytes: bytes,
        uploaded_by: str,
    ) -> KnowledgeEntryDraft:
        """Run the KIP ingestion pipeline for a single uploaded document.

        Phase 1 — quarantine via IngestionGuard (may raise IngestionError).
        Phase 2 — parse via DocumentParserRegistry.
        Phase 3 — rule-based knowledge extraction.
        Phase 4 — persist to pending/.
        Phase 5 — return KnowledgeEntryDraft.
        """
        # Phase 1: quarantine — must happen before any parsing
        inspection = self._guard.inspect(file_path, file_bytes)

        # Phase 2: parse
        suffix = file_path.suffix.lower()
        parser = self._registry.get_parser(suffix)
        parsed_doc = parser.parse(file_path, file_bytes)

        # Phase 3: extract
        extracted = self._extract_knowledge(parsed_doc)

        # Phase 4: build draft and persist
        draft = KnowledgeEntryDraft(
            draft_id=str(uuid.uuid4()),
            source_hash=inspection.sha256,
            source_filename=file_path.name,
            parsed_text=parsed_doc.raw_text,
            extracted_metadata=extracted["source_info"],
            extracted_knowledge_items=extracted["knowledge_items"],
            extracted_trust_level=extracted["trust_level"],
            extracted_domain=extracted["domain"],
            extraction_limitations=extracted["limitations"],
            created_at=datetime.utcnow(),
        )
        self._save_to_pending(draft, file_bytes)

        return draft

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_knowledge(self, parsed_doc: ParsedDocument) -> dict:
        """Rule-based extraction from parsed document text.

        Returns a dict with keys: source_info, domain, trust_level,
        knowledge_items, limitations.  When an LLM is integrated in a
        future phase, this method is the single seam to replace.
        """
        text = parsed_doc.structured_markdown or parsed_doc.raw_text
        text_lower = text.lower()

        doi_match = _DOI_PATTERN.search(text)
        doi = doi_match.group(1) if doi_match else None

        year_match = _YEAR_PATTERN.search(text)
        year = int(year_match.group(0)) if year_match else datetime.utcnow().year

        trust_level = self._infer_trust_level(text_lower)
        domain = self._infer_domain(text_lower)

        sentences = [
            s.strip() for s in _SENTENCE_SPLIT.split(text) if len(s.strip()) > 30
        ][:3]

        knowledge_items = [
            {
                "id": f"item-{i + 1:03d}",
                "statement": sentence,
                "direct_quote": sentence,
                "confidence": 0.5,
                "caveats": "Rule-based extraction — human review required.",
            }
            for i, sentence in enumerate(sentences)
        ]
        if not knowledge_items:
            knowledge_items = [
                {
                    "id": "item-001",
                    "statement": text[:200].strip(),
                    "direct_quote": text[:200].strip(),
                    "confidence": 0.3,
                    "caveats": "Extracted from full text — review required.",
                }
            ]

        return {
            "source_info": {
                "title": "Unknown — requires human review",
                "year": year,
                "doi": doi,
            },
            "domain": domain,
            "trust_level": trust_level,
            "knowledge_items": knowledge_items,
            "limitations": [
                "Rule-based extraction was used; all items require human verification.",
            ],
        }

    @staticmethod
    def _infer_trust_level(text_lower: str) -> str:
        if any(kw in text_lower for kw in _REGULATORY_KEYWORDS):
            return "regulatory"
        if any(kw in text_lower for kw in _PEER_REVIEWED_KEYWORDS):
            return "peer_reviewed"
        return "institutional"

    @staticmethod
    def _infer_domain(text_lower: str) -> str:
        for domain, signals in _DOMAIN_SIGNALS.items():
            if any(sig in text_lower for sig in signals):
                return domain
        return "statistics"

    def _save_to_pending(self, draft: KnowledgeEntryDraft, source_bytes: bytes) -> Path:
        """Write EXTRACTED.md, SOURCE_HASH.txt, and REVIEW_REQUEST.yaml to pending/."""
        draft_dir = self._pending_dir / draft.draft_id
        draft_dir.mkdir(parents=True, exist_ok=True)

        # EXTRACTED.md
        md_lines = [
            "# Extracted Knowledge Entry (Pending Review)\n",
            f"**draft_id**: {draft.draft_id}  ",
            f"**status**: {draft.status}  ",
            f"**created_at**: {draft.created_at.isoformat()}  ",
            "",
            "## Source Info",
            f"- title: {draft.extracted_metadata.get('title', 'Unknown')}",
            f"- year: {draft.extracted_metadata.get('year', '')}",
            f"- doi: {draft.extracted_metadata.get('doi') or 'N/A'}",
            "",
            f"## Domain\n{draft.extracted_domain}",
            "",
            f"## Trust Level\n{draft.extracted_trust_level}",
            "",
            "## Knowledge Items",
        ]
        for item in draft.extracted_knowledge_items:
            md_lines += [
                f"\n### {item['id']}",
                f"**Statement**: {item['statement']}",
                f"**Direct Quote**: {item['direct_quote']}",
                f"**Confidence**: {item['confidence']}",
                f"**Caveats**: {item.get('caveats', '')}",
            ]
        md_lines += [
            "",
            "## Limitations",
            *[f"- {lim}" for lim in draft.extraction_limitations],
        ]
        (draft_dir / "EXTRACTED.md").write_text("\n".join(md_lines), encoding="utf-8")

        # SOURCE_HASH.txt
        (draft_dir / "SOURCE_HASH.txt").write_text(draft.source_hash, encoding="utf-8")

        # REVIEW_REQUEST.yaml
        review_request = {
            "draft_id": draft.draft_id,
            "source_filename": draft.source_filename,
            "source_hash": draft.source_hash,
            "extracted_domain": draft.extracted_domain,
            "extracted_trust_level": draft.extracted_trust_level,
            "created_at": draft.created_at.isoformat(),
            "status": draft.status,
            "knowledge_item_count": len(draft.extracted_knowledge_items),
            "limitations": draft.extraction_limitations,
        }
        (draft_dir / "REVIEW_REQUEST.yaml").write_text(
            yaml.dump(review_request, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

        return draft_dir
