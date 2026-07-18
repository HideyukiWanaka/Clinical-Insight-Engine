"""In-process store for the latest RStudio environment snapshot (Step 7).

Mirrors ``rstudio.py``'s ``RStudioQueue``: a single in-memory slot for a
single-user, single-process, localhost-bound app (SPEC §4.1). The Addin pushes
a fresh (PII-filtered) snapshot whenever the user's GlobalEnv changes; Step 8
will read ``latest`` to ground chat answers in the real data.
"""

from __future__ import annotations


class EnvironmentStore:
    """Holds the most recent environment snapshot (last-write-wins).

    Not thread-safe by design: single-process, localhost-bound app (SPEC §4.1).
    """

    def __init__(self) -> None:
        self._latest: dict | None = None

    def update(self, snapshot: dict) -> None:
        """Replace the stored snapshot with *snapshot* (already PII-filtered)."""
        self._latest = snapshot

    @property
    def latest(self) -> dict | None:
        """The most recent snapshot, or ``None`` before the first sync."""
        return self._latest
