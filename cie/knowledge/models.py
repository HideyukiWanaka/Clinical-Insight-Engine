from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Literal


class KnowledgeDomain(str, Enum):
    STATISTICS = "statistics"
    CLINICAL = "clinical"
    REPORTING = "reporting"
    R = "R"
    PYTHON = "Python"
    VISUALIZATION = "visualization"


class TrustLevel(str, Enum):
    REGULATORY = "regulatory"
    PEER_REVIEWED = "peer_reviewed"
    INSTITUTIONAL = "institutional"
    EXPERIMENTAL = "experimental"


class KnowledgeStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    PENDING = "pending"


_ENTRY_ID_PATTERN = re.compile(r"^KE-[0-9]{4}$")


@dataclass
class KnowledgeEntryItem:
    id: str
    statement: str
    direct_quote: str
    confidence: float = 1.0
    caveats: str = ""


@dataclass
class RelatedEntry:
    entry_id: str
    relationship: Literal["supersedes", "superseded_by", "related"]


@dataclass
class SourceInfo:
    title: str
    year: int
    authors: str | None = None
    doi: str | None = None
    url: str | None = None
    section: str | None = None

    def __post_init__(self) -> None:
        if self.doi is None and self.url is None:
            raise ValueError("SourceInfo requires either doi or url for source traceability.")


@dataclass
class KnowledgeEntry:
    entry_id: str
    domain: KnowledgeDomain
    version: str
    status: KnowledgeStatus
    trust_level: TrustLevel
    source_info: SourceInfo
    knowledge_entries: list[KnowledgeEntryItem]
    approved_by_human: bool
    created_by: str
    approved_by: str
    approved_at: datetime
    expires_at: date | None = None
    related_entries: list[RelatedEntry] = field(default_factory=list)
    archived_at: datetime | None = None
    archived_by: str | None = None

    def __post_init__(self) -> None:
        if not self.approved_by_human:
            raise ValueError("approved_by_human must be True; unapproved entries cannot be created.")
        if self.source_info.doi is None and self.source_info.url is None:
            raise ValueError("SourceInfo requires either doi or url for source traceability.")
        if not _ENTRY_ID_PATTERN.match(self.entry_id):
            raise ValueError(f"entry_id must match KE-XXXX (4 digits), got: {self.entry_id!r}")
