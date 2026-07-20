"""Disk persistence for the single ongoing conversation.

Lets the one active conversation survive a backend restart / a new day
(explicitly NOT a multi-conversation history browser — SPEC.md §4.5/§10
excludes that). Home-anchored path, matching the ``~/.stat-consultant/``
precedent in ``rstudio_auth.py`` (independent of where the repo lives).

Tmp-file-then-``os.replace`` write, mirroring the atomic-write pattern used by
``cie/knowledge/lifecycle.py``'s ``_atomic_write_registry`` — no new
dependency, stdlib ``json`` + ``os`` only.
"""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from pathlib import Path

CONV_DIR = Path.home() / ".stat-consultant" / "conversations"


def _mkdir_private(path: Path) -> None:
    """Create *path* (and parents) restricted to the owner (0700).

    Conversations are stored as cleartext JSON and may contain whatever the user
    typed — including, despite the in-app guidance, PHI. Owner-only permissions
    keep other local accounts from reading them. ``chmod`` is inert on Windows;
    the mode is applied explicitly (not just via umask) so a pre-existing,
    looser directory is tightened too.
    """
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(stat.S_IRWXU)  # 0700
    except OSError:
        pass

# conversation_id is client-generated (crypto.randomUUID() on the frontend).
# Validate its shape before using it as a filename — defense in depth against
# a malformed/hostile id attempting path traversal.
_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")


def _path_for(conversation_id: str) -> Path | None:
    if not _ID_RE.match(conversation_id):
        return None
    return CONV_DIR / f"{conversation_id}.json"


def save_turns(conversation_id: str, turns: list[dict]) -> None:
    """Atomically persist ``turns`` for ``conversation_id``. Best-effort."""
    path = _path_for(conversation_id)
    if path is None:
        return
    _mkdir_private(CONV_DIR)
    tmp = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        tmp.write_text(json.dumps({"turns": turns}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)


def load_turns(conversation_id: str) -> list[dict] | None:
    """Return persisted turns for ``conversation_id``, or None if absent/corrupt."""
    path = _path_for(conversation_id)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    turns = data.get("turns")
    return turns if isinstance(turns, list) else None
