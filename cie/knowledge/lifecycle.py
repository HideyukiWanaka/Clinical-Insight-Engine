from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from cie.core.audit import AuditEvent, AuditEventSeverity, AuditService
from cie.core.exceptions import KnowledgeError, PermissionDeniedError
from cie.knowledge.ingestion_agent import KnowledgeEntryDraft
from cie.knowledge.models import (
    KnowledgeDomain,
    KnowledgeEntry,
    KnowledgeEntryItem,
    KnowledgeStatus,
    RelatedEntry,
    SourceInfo,
    TrustLevel,
)

_ENTRY_ID_RE = re.compile(r"^KE-(\d{4})$")
_AGENT_ID = "knowledge_lifecycle_service"


# ---------------------------------------------------------------------------
# Audit event descriptors
# ---------------------------------------------------------------------------


@dataclass
class KnowledgeRegistrationEvent:
    entry_id: str
    domain: str
    approved_by: str
    trust_level: str
    event_type: str = "KnowledgeRegistrationEvent"


@dataclass
class KnowledgeArchivedEvent:
    entry_id: str
    archived_by: str
    reason: str
    event_type: str = "KnowledgeArchivedEvent"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class KnowledgeLifecycleService:
    """Sole writer to knowledge/institutional/.

    All registration and archival operations on institutional knowledge entries
    are gated through this service. No other code path may write to
    institutional/ (ADR-0003, PROJECT_RULES.md S.12).

    Physical deletion is never implemented here. Soft Delete (status: archived)
    is the only removal mechanism.
    """

    def __init__(
        self,
        institutional_dir: Path,
        pending_dir: Path,
        audit_service: AuditService,
        schema_path: Path | None = None,
    ) -> None:
        self._institutional = institutional_dir
        self._pending = pending_dir
        self._audit = audit_service
        self._registry_path = institutional_dir / "REGISTRY.yaml"
        self._schema: dict | None = None
        if schema_path is not None and schema_path.exists():
            self._schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register_knowledge(
        self,
        draft: KnowledgeEntryDraft,
        approved_by: str,
        created_by: str,
        domain: str,
        trust_level: str,
        source_info: dict,
        knowledge_items: list[dict],
        expires_at: date | None = None,
        related_entries: list[dict] | None = None,
    ) -> KnowledgeEntry:
        """Register a human-approved draft into institutional/.

        Steps ①–⑪ as defined in ADR-0003 Phase 4.
        """
        related_entries = related_entries or []

        # ① Allocate entry_id
        entry_id = self._allocate_entry_id()
        now = datetime.now(timezone.utc)

        # ② Assemble KnowledgeEntry (approved_by_human always True)
        src_info = SourceInfo(
            title=source_info.get("title", "Unknown"),
            year=source_info.get("year", now.year),
            authors=source_info.get("authors"),
            doi=source_info.get("doi"),
            url=source_info.get("url"),
            section=source_info.get("section"),
        )
        items = [
            KnowledgeEntryItem(
                id=item.get("id", f"item-{i + 1:03d}"),
                statement=item["statement"],
                direct_quote=item["direct_quote"],
                confidence=float(item.get("confidence", 1.0)),
                caveats=item.get("caveats", ""),
            )
            for i, item in enumerate(knowledge_items)
        ]
        related = [
            RelatedEntry(
                entry_id=r["entry_id"],
                relationship=r["relationship"],
            )
            for r in related_entries
        ]
        entry = KnowledgeEntry(
            entry_id=entry_id,
            domain=KnowledgeDomain(domain),
            version="1.0.0",
            status=KnowledgeStatus.ACTIVE,
            trust_level=TrustLevel(trust_level),
            source_info=src_info,
            knowledge_entries=items,
            approved_by_human=True,
            created_by=created_by,
            approved_by=approved_by,
            approved_at=now,
            expires_at=expires_at,
            related_entries=related,
        )

        # ③ JSON-schema validation (if schema is available)
        if self._schema is not None:
            self._validate_schema(entry, now)

        # ④ Create institutional/{entry_id}/
        entry_dir = self._institutional / entry_id
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / "versions").mkdir(exist_ok=True)
        (entry_dir / "source").mkdir(exist_ok=True)

        # ⑤ Write KNOWLEDGE.md
        (entry_dir / "KNOWLEDGE.md").write_text(
            self._render_knowledge_md(entry), encoding="utf-8"
        )

        # ⑥ Write METADATA.yaml
        metadata = self._entry_to_metadata_dict(entry)
        (entry_dir / "METADATA.yaml").write_text(
            yaml.dump(metadata, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

        # ⑦ source/ already created; original bytes would be copied here by
        #    the caller when available (draft has hash, not bytes)

        # ⑧ Bidirectional related-entry links
        if related_entries:
            self._update_related_entries(entry_id, related_entries)

        # ⑨ Update REGISTRY.yaml atomically
        self._update_registry(entry)

        # ⑩ Remove pending draft directory
        pending_draft_dir = self._pending / draft.draft_id
        if pending_draft_dir.exists():
            shutil.rmtree(pending_draft_dir)

        # ⑪ Audit
        evt = KnowledgeRegistrationEvent(
            entry_id=entry_id,
            domain=domain,
            approved_by=approved_by,
            trust_level=trust_level,
        )
        await self._write_audit("KNOWLEDGE_REGISTERED", evt.__dict__)

        return entry

    async def archive_entry(
        self,
        entry_id: str,
        archived_by: str,
        current_user_id: str,
        current_user_role: str,
        reason: str = "",
    ) -> None:
        """Soft-delete an institutional knowledge entry.

        Physical deletion is never performed. The entry files are preserved
        in versions/ and the status is set to 'archived' in METADATA.yaml
        and REGISTRY.yaml.
        """
        entry_dir = self._institutional / entry_id
        metadata_path = entry_dir / "METADATA.yaml"
        if not metadata_path.exists():
            raise KnowledgeError(
                f"Entry '{entry_id}' not found in institutional/.",
                error_code="ENTRY_NOT_FOUND",
            )

        metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
        entry_created_by: str = metadata.get("created_by", "")
        entry_version: str = metadata.get("version", "1.0.0")

        # Permission check (ADR-0003)
        authorized = current_user_id == entry_created_by or current_user_role == "admin"
        if not authorized:
            raise PermissionDeniedError(
                f"User '{current_user_id}' is not authorized to archive '{entry_id}'.",
                required_permission="ARCHIVE_NOT_AUTHORIZED",
                actor=current_user_id,
            )

        now = datetime.now(timezone.utc)
        archived_at_str = now.strftime("%Y%m%dT%H%M%S")

        # ① + ② Update METADATA.yaml (in-place; files are never deleted)
        metadata["status"] = "archived"
        metadata["archived_at"] = now.isoformat()
        metadata["archived_by"] = archived_by

        # ③ Snapshot current version to versions/ before updating
        version_snapshot_dir = entry_dir / "versions" / f"{entry_version}_{archived_at_str}"
        version_snapshot_dir.mkdir(parents=True, exist_ok=True)
        for src_file in ("KNOWLEDGE.md", "METADATA.yaml"):
            src = entry_dir / src_file
            if src.exists():
                shutil.copy2(src, version_snapshot_dir / src_file)

        # Write updated METADATA.yaml
        metadata_path.write_text(
            yaml.dump(metadata, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

        # ④ Update REGISTRY.yaml
        self._update_registry_status(entry_id, "archived", now.isoformat(), archived_by)

        # ⑤ Audit
        evt = KnowledgeArchivedEvent(
            entry_id=entry_id,
            archived_by=archived_by,
            reason=reason,
        )
        await self._write_audit("KNOWLEDGE_ARCHIVED", evt.__dict__)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _allocate_entry_id(self) -> str:
        registry = self._load_registry()
        entries = registry.get("entries", [])
        max_num = 0
        for e in entries:
            m = _ENTRY_ID_RE.match(e.get("entry_id", ""))
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"KE-{max_num + 1:04d}"

    def _load_registry(self) -> dict:
        if not self._registry_path.exists():
            return {"schema_version": "1.0", "entries": []}
        return yaml.safe_load(self._registry_path.read_text(encoding="utf-8")) or {
            "schema_version": "1.0",
            "entries": [],
        }

    def _update_registry(self, entry: KnowledgeEntry) -> None:
        registry = self._load_registry()
        entries: list[dict] = registry.setdefault("entries", [])
        entries.append(
            {
                "entry_id": entry.entry_id,
                "domain": entry.domain.value,
                "version": entry.version,
                "status": entry.status.value,
                "trust_level": entry.trust_level.value,
                "approved_by": entry.approved_by,
                "approved_by_human": True,
                "approved_at": entry.approved_at.isoformat(),
                "created_by": entry.created_by,
            }
        )
        self._atomic_write_registry(registry)

    def _update_registry_status(
        self, entry_id: str, status: str, archived_at: str, archived_by: str
    ) -> None:
        registry = self._load_registry()
        for e in registry.get("entries", []):
            if e.get("entry_id") == entry_id:
                e["status"] = status
                e["archived_at"] = archived_at
                e["archived_by"] = archived_by
                break
        self._atomic_write_registry(registry)

    def _atomic_write_registry(self, registry: dict) -> None:
        tmp_path = self._registry_path.parent / f".registry_tmp_{uuid.uuid4().hex}.yaml"
        try:
            tmp_path.write_text(
                yaml.dump(registry, allow_unicode=True, default_flow_style=False),
                encoding="utf-8",
            )
            os.replace(tmp_path, self._registry_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def _update_related_entries(
        self, new_entry_id: str, related_entries: list[dict]
    ) -> None:
        inverse = {"supersedes": "superseded_by", "superseded_by": "supersedes", "related": "related"}
        for rel in related_entries:
            peer_id = rel["entry_id"]
            peer_metadata_path = self._institutional / peer_id / "METADATA.yaml"
            if not peer_metadata_path.exists():
                continue
            try:
                peer_meta = yaml.safe_load(peer_metadata_path.read_text(encoding="utf-8")) or {}
                peer_related: list[dict] = peer_meta.setdefault("related_entries", [])
                new_link = {
                    "entry_id": new_entry_id,
                    "relationship": inverse.get(rel["relationship"], "related"),
                }
                if new_link not in peer_related:
                    peer_related.append(new_link)
                peer_metadata_path.write_text(
                    yaml.dump(peer_meta, allow_unicode=True, default_flow_style=False),
                    encoding="utf-8",
                )
            except Exception:
                pass  # best-effort; caller should handle failures

    def _entry_to_metadata_dict(self, entry: KnowledgeEntry) -> dict:
        return {
            "entry_id": entry.entry_id,
            "domain": entry.domain.value,
            "version": entry.version,
            "status": entry.status.value,
            "trust_level": entry.trust_level.value,
            "source_info": {
                "title": entry.source_info.title,
                "year": entry.source_info.year,
                "authors": entry.source_info.authors,
                "doi": entry.source_info.doi,
                "url": entry.source_info.url,
                "section": entry.source_info.section,
            },
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
            "related_entries": [
                {"entry_id": r.entry_id, "relationship": r.relationship}
                for r in entry.related_entries
            ],
            "knowledge_entries": [
                {
                    "id": item.id,
                    "statement": item.statement,
                    "direct_quote": item.direct_quote,
                    "confidence": item.confidence,
                    "caveats": item.caveats,
                }
                for item in entry.knowledge_entries
            ],
            "approved_by_human": True,
            "created_by": entry.created_by,
            "approved_by": entry.approved_by,
            "approved_at": entry.approved_at.isoformat(),
            "archived_at": entry.archived_at.isoformat() if entry.archived_at else None,
            "archived_by": entry.archived_by,
        }

    @staticmethod
    def _render_knowledge_md(entry: KnowledgeEntry) -> str:
        lines = [
            f"# Knowledge Entry: {entry.entry_id}\n",
            f"**Domain**: {entry.domain.value}  ",
            f"**Trust Level**: {entry.trust_level.value}  ",
            f"**Version**: {entry.version}  ",
            f"**Approved By**: {entry.approved_by}  ",
            f"**Approved At**: {entry.approved_at.isoformat()}  ",
            "",
            "## Source",
            f"- Title: {entry.source_info.title}",
            f"- Year: {entry.source_info.year}",
            f"- DOI: {entry.source_info.doi or 'N/A'}",
            f"- URL: {entry.source_info.url or 'N/A'}",
            "",
            "## Knowledge Entries",
        ]
        for item in entry.knowledge_entries:
            lines += [
                f"\n### {item.id}",
                f"**Statement**: {item.statement}",
                f"**Direct Quote**: {item.direct_quote}",
                f"**Confidence**: {item.confidence}",
                f"**Caveats**: {item.caveats}",
            ]
        return "\n".join(lines)

    def _validate_schema(self, entry: KnowledgeEntry, approved_at: datetime) -> None:
        import jsonschema

        payload = self._entry_to_metadata_dict(entry)
        try:
            jsonschema.validate(payload, self._schema)
        except jsonschema.ValidationError as exc:
            raise KnowledgeError(
                f"KnowledgeEntry failed schema validation: {exc.message}",
                error_code="KNOWLEDGE_SCHEMA_VALIDATION_FAILED",
            ) from exc

    async def _write_audit(self, action: str, payload: dict) -> None:
        event = AuditEvent(
            execution_id=str(uuid.uuid4()),
            agent_id=_AGENT_ID,
            action=action,
            status="success",
            severity=AuditEventSeverity.INFO,
            payload=payload,
        )
        try:
            await self._audit.write(event)
        except Exception:
            pass  # audit failure must not block registration (swallow, per BaseAgent pattern)
