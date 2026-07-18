"""In-process RStudio send queue (Step 5).

Mirrors ``references.py``'s ``ReferenceLibrary``: a single in-memory store for
a single-user, single-process, localhost-bound app (SPEC 4.1). No persistence,
no auth — the shared-secret scheme is Step 6's concern once a real Addin
exists to poll this queue.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class PendingCode:
    """One code block queued for insertion into the user's RStudio session."""

    id: str
    code: str
    language: str
    queued_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "code": self.code,
            "language": self.language,
            "queued_at": self.queued_at,
        }


class RStudioQueue:
    """FIFO queue of code blocks awaiting insertion.

    Not thread-safe by design: single-process, localhost-bound app (SPEC 4.1).
    """

    def __init__(self) -> None:
        self._items: list[PendingCode] = []

    def push(self, code: str, language: str) -> PendingCode:
        item = PendingCode(
            id=uuid.uuid4().hex,
            code=code,
            language=language,
            queued_at=datetime.now(timezone.utc).isoformat(),
        )
        self._items.append(item)
        return item

    def drain(self) -> list[PendingCode]:
        """Return all pending items and clear the queue (poll-and-consume)."""
        items, self._items = self._items, []
        return items

    def __len__(self) -> int:
        return len(self._items)
