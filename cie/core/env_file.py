"""CIE Platform — minimal ``.env`` line updater.

Used by the LLM settings endpoint to persist the active provider choice
(``CIE_ACTIVE_AI_PROVIDER``) across restarts. API keys never go through this
module — those are OS-keyring secrets (``cie.core.secrets_store``), not
plaintext file content.
"""

from __future__ import annotations

from pathlib import Path

import cie

_REPO_ROOT = Path(cie.__file__).resolve().parent.parent
DEFAULT_ENV_PATH = _REPO_ROOT / ".env"


def set_env_var(key: str, value: str, env_path: Path = DEFAULT_ENV_PATH) -> None:
    """Set ``key=value`` in a ``.env`` file, replacing the line if present.

    Preserves every other line (including comments) verbatim. Appends a new
    line if the key is not already present. Creates the file if missing.
    """
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    prefix = f"{key}="
    new_line = f"{key}={value}"
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["DEFAULT_ENV_PATH", "set_env_var"]
