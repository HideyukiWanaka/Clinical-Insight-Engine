from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import yaml

from cie.core.exceptions import KnowledgeError
from cie.knowledge.models import (
    KnowledgeDomain,
    KnowledgeEntry,
    KnowledgeEntryItem,
    KnowledgeStatus,
    RelatedEntry,
    SourceInfo,
    TrustLevel,
)


@dataclass
class ExpiryWarning:
    entry_id: str
    level: Literal["expired", "expiring_soon", "superseded"]
    message: str


@dataclass(frozen=True)
class FrozenKnowledgeSet:
    """Immutable snapshot of all active knowledge entries for a single execution.

    PROJECT_RULES.md Section 12: "Knowledge is immutable during execution."
    ``frozen=True`` prevents any attribute assignment after construction.
    ``entries`` is a tuple so callers cannot append to it.
    """

    loaded_at: datetime
    execution_id: str
    entries: tuple[KnowledgeEntry, ...]
    expiry_warnings: tuple[ExpiryWarning, ...]

    def get_by_domain(self, domain: KnowledgeDomain) -> tuple[KnowledgeEntry, ...]:
        """Return entries whose domain matches *domain*."""
        return tuple(e for e in self.entries if e.domain == domain)

    def reload(self) -> None:
        """Raise unconditionally — reloading during execution is forbidden.

        ADR-0003 Layer 5 / PROJECT_RULES.md Section 12.
        """
        raise KnowledgeError(
            "KNOWLEDGE_RELOAD_DURING_EXECUTION_FORBIDDEN",
            error_code="KNOWLEDGE_RELOAD_DURING_EXECUTION_FORBIDDEN",
        )


class KnowledgeLoader:
    """Loads official and institutional knowledge at workflow start.

    Called once per execution by the Orchestrator before dispatching any agent.
    Never called again during execution (enforced via FrozenKnowledgeSet.reload()).
    """

    _EXPIRY_SOON_DAYS = 90

    def __init__(self, official_dir: Path, institutional_dir: Path) -> None:
        self._official = official_dir
        self._institutional = institutional_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_for_execution(self, execution_id: str) -> FrozenKnowledgeSet:
        """Snapshot all active knowledge entries for *execution_id*.

        ① Loads official/ entries (immutable reference knowledge).
        ② Loads institutional/ active entries only (via REGISTRY.yaml).
        ③ Marks superseded entries with ExpiryWarning(level="superseded").
        ④ Returns FrozenKnowledgeSet (immutable for the life of the execution).
        """
        entries: list[KnowledgeEntry] = []

        # ① official/ — look for structured METADATA.yaml files
        entries.extend(self._load_from_metadata_dir(self._official))

        # ② institutional/ — active entries via REGISTRY.yaml
        entries.extend(self._load_institutional_active())

        # ③ Superseded warnings
        warnings: list[ExpiryWarning] = []
        for entry in entries:
            for rel in entry.related_entries:
                if rel.relationship == "superseded_by":
                    warnings.append(
                        ExpiryWarning(
                            entry_id=entry.entry_id,
                            level="superseded",
                            message=(
                                f"⚠️ Entry {entry.entry_id} has been superseded by "
                                f"{rel.entry_id}. New analyses should use the newer version."
                            ),
                        )
                    )

        # Expiry warnings (ADR-0003 principle 7)
        warnings.extend(self.check_expiry_warnings(entries))

        return FrozenKnowledgeSet(
            loaded_at=datetime.now(timezone.utc),
            execution_id=execution_id,
            entries=tuple(entries),
            expiry_warnings=tuple(warnings),
        )

    def check_expiry_warnings(self, entries: list[KnowledgeEntry]) -> list[ExpiryWarning]:
        """Return expiry alerts for UI display.

        On-demand check at UI load time — no batch jobs or schedulers needed
        (ADR-0003 principle 7).
        """
        today = date.today()
        warnings: list[ExpiryWarning] = []
        for entry in entries:
            if entry.expires_at is None:
                continue
            delta = (entry.expires_at - today).days
            if delta < 0:
                warnings.append(
                    ExpiryWarning(
                        entry_id=entry.entry_id,
                        level="expired",
                        message=(
                            f"⚠️ Entry {entry.entry_id} expired on {entry.expires_at}. "
                            "Please verify against the latest guidelines."
                        ),
                    )
                )
            elif delta <= self._EXPIRY_SOON_DAYS:
                warnings.append(
                    ExpiryWarning(
                        entry_id=entry.entry_id,
                        level="expiring_soon",
                        message=(
                            f"📅 Entry {entry.entry_id} expires on {entry.expires_at} "
                            f"({delta} days remaining)."
                        ),
                    )
                )
        return warnings

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_from_metadata_dir(self, base_dir: Path) -> list[KnowledgeEntry]:
        """Recursively find METADATA.yaml files under *base_dir* and load active entries."""
        if not base_dir.exists():
            return []
        entries = []
        for metadata_path in base_dir.rglob("METADATA.yaml"):
            try:
                entry = self._parse_metadata(metadata_path)
                if entry.status == KnowledgeStatus.ACTIVE:
                    entries.append(entry)
            except Exception:
                pass  # skip malformed / incompatible entries
        return entries

    def _load_institutional_active(self) -> list[KnowledgeEntry]:
        """Load active institutional entries using REGISTRY.yaml as the index."""
        registry_path = self._institutional / "REGISTRY.yaml"
        if not registry_path.exists():
            return []
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        active_ids = [
            e["entry_id"]
            for e in registry.get("entries", [])
            if e.get("status") == "active"
        ]
        entries = []
        for entry_id in active_ids:
            metadata_path = self._institutional / entry_id / "METADATA.yaml"
            if not metadata_path.exists():
                continue
            try:
                entry = self._parse_metadata(metadata_path)
                if entry.status == KnowledgeStatus.ACTIVE:
                    entries.append(entry)
            except Exception:
                pass
        return entries

    @staticmethod
    def _parse_metadata(metadata_path: Path) -> KnowledgeEntry:
        meta = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}

        src_raw = meta.get("source_info", {})
        source_info = SourceInfo(
            title=src_raw.get("title", "Unknown"),
            year=int(src_raw.get("year", 2000)),
            authors=src_raw.get("authors"),
            doi=src_raw.get("doi"),
            url=src_raw.get("url"),
            section=src_raw.get("section"),
        )

        raw_items = meta.get("knowledge_entries", [])
        items = [
            KnowledgeEntryItem(
                id=item.get("id", f"item-{i + 1:03d}"),
                statement=item.get("statement", ""),
                direct_quote=item.get("direct_quote", ""),
                confidence=float(item.get("confidence", 1.0)),
                caveats=item.get("caveats", ""),
            )
            for i, item in enumerate(raw_items)
        ]
        if not items:
            items = [
                KnowledgeEntryItem(
                    id="item-001",
                    statement="See source document.",
                    direct_quote="N/A",
                    confidence=1.0,
                )
            ]

        related = [
            RelatedEntry(
                entry_id=r["entry_id"],
                relationship=r["relationship"],
            )
            for r in meta.get("related_entries", [])
        ]

        approved_at_raw = meta.get("approved_at", "")
        try:
            approved_at = datetime.fromisoformat(str(approved_at_raw))
        except (ValueError, TypeError):
            approved_at = datetime.now(timezone.utc)

        expires_at: date | None = None
        expires_at_raw = meta.get("expires_at")
        if expires_at_raw and not str(expires_at_raw).lower() in ("null", "none", ""):
            try:
                expires_at = date.fromisoformat(str(expires_at_raw))
            except (ValueError, TypeError):
                pass

        return KnowledgeEntry(
            entry_id=meta["entry_id"],
            domain=KnowledgeDomain(meta.get("domain", "statistics")),
            version=meta.get("version", "1.0.0"),
            status=KnowledgeStatus(meta.get("status", "active")),
            trust_level=TrustLevel(meta.get("trust_level", "institutional")),
            source_info=source_info,
            knowledge_entries=items,
            approved_by_human=True,
            created_by=meta.get("created_by", "system"),
            approved_by=meta.get("approved_by", "system"),
            approved_at=approved_at,
            expires_at=expires_at,
            related_entries=related,
        )
