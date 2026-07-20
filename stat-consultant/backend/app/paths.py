"""Single resolution point for every user-writable path the backend uses.

Two problems this solves, both of which block distribution:

1. **Windows ``~`` divergence.** Python's ``Path.home()`` follows ``USERPROFILE``
   while R's ``path.expand("~")`` follows ``R_USER``/``HOME``. When those differ
   the Addin looks for the shared secret somewhere the backend never wrote it,
   and the only symptom is an error repeating in the R console every poll cycle.
   ``STAT_CONSULTANT_HOME`` lets the R launcher pin both sides to one directory;
   ``GET /health`` echoes whatever was resolved so the Addin can find it even
   when the backend was started by hand.

2. **Read-only install directories.** User uploads used to land inside the
   install tree (``backend/user_references/``), which a bundled/`Program Files`
   install can't write and a reinstall wipes. Everything user-owned now lives
   under one state directory.

Resolution is deliberately done per call, not at import time. The previous
module-level ``Path.home()`` constants froze the location before ``main`` could
act on any override, which is why the env var approach needed this refactor.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

ENV_HOME = "STAT_CONSULTANT_HOME"


def state_dir() -> Path:
    """Return the user-owned state directory, creating it owner-only.

    ``STAT_CONSULTANT_HOME`` wins when set (the R launcher passes ``--state-dir``,
    which the entry script exports into this variable before the app is imported).
    Otherwise fall back to the historical ``~/.stat-consultant``.
    """
    override = os.environ.get(ENV_HOME, "").strip()
    root = Path(override).expanduser() if override else Path.home() / ".stat-consultant"
    root.mkdir(parents=True, exist_ok=True)
    try:
        # 0700, applied explicitly rather than left to umask so a pre-existing
        # looser directory is tightened too. The token file is already 0600, but
        # the directory holds conversations/ — cleartext JSON of whatever the
        # user typed, which despite the in-app guidance may include PHI — and
        # references/, their uploaded documents. Restricting it here means every
        # writer inherits the restriction instead of each repeating it.
        # chmod is largely inert on Windows; harmless to skip.
        root.chmod(stat.S_IRWXU)
    except OSError:
        pass
    return root


def token_path() -> Path:
    """Path of the RStudio shared-secret file (see rstudio_auth.py)."""
    return state_dir() / "rstudio_token"


def conversations_dir() -> Path:
    """Directory holding the persisted conversation JSON files."""
    return _subdir("conversations")


def references_dir() -> Path:
    """Directory holding the user's uploaded reference documents."""
    return _subdir("references")


def _subdir(name: str) -> Path:
    path = state_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    try:
        # The 0700 parent already blocks traversal; this is belt-and-braces for
        # the case where the state dir is relocated somewhere more permissive.
        path.chmod(stat.S_IRWXU)
    except OSError:
        pass
    return path
