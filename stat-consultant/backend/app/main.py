import os
import shutil
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import paths
from .conversation import ConversationStore
from .environment import EnvironmentStore
from .environment_api import router as environment_router
from .models_api import router as models_router
from .references import ReferenceLibrary
from .references_api import router as references_router
from .rstudio import RStudioQueue
from .rstudio_api import router as rstudio_router
from .rstudio_auth import generate_and_write_token
from .settings_api import router as settings_router
from .ws_consult import router as ws_consult_router

__version__ = "0.1.0"

# Where uploads used to live: inside the install tree. A bundled install can't
# write there and a reinstall wipes it, so the folder moved under the state
# directory. Carry any existing files across once, then leave the old folder be.
_LEGACY_REFERENCES_DIR = Path(__file__).resolve().parent.parent / "user_references"


def frontend_dist() -> Path | None:
    """Locate the built frontend, or None when only the API should be served.

    PyInstaller unpacks bundled data under ``sys._MEIPASS``; outside a bundle we
    fall back to the repo's ``frontend/dist`` so a local ``npm run build`` can be
    exercised the same way the shipped app runs.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidate = Path(bundled) / "frontend_dist"
    else:
        candidate = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    return candidate if (candidate / "index.html").is_file() else None


def _migrate_legacy_references() -> None:
    target = paths.references_dir()
    if not _LEGACY_REFERENCES_DIR.is_dir() or any(target.iterdir()):
        return
    for src in _LEGACY_REFERENCES_DIR.glob("*"):
        if src.is_file():
            try:
                shutil.copy2(src, target / src.name)
            except OSError:
                continue
    print(f"[stat-consultant] migrated references to {target}")


_migrate_legacy_references()

app = FastAPI(title="Stat Consultant Backend", version=__version__)

# Process-wide state (single-user, in-process — SPEC 4.1).
app.state.conversations = ConversationStore()
# Single flat folder for the user's uploaded references (SPEC 5.6).
app.state.references = ReferenceLibrary(paths.references_dir())
app.state.rstudio_queue = RStudioQueue()
# Latest RStudio GlobalEnv snapshot (Step 7); consumed by chat grounding (Step 8).
app.state.environment = EnvironmentStore()
# Fresh shared secret each start; the Addin re-reads it every poll (self-heals).
app.state.rstudio_token = generate_and_write_token()

# CORS is off by default. The frontend now talks to the backend over same-origin
# relative URLs — served by this process when bundled, and forwarded by the Vite
# dev proxy otherwise — so neither mode needs it. That matters because
# POST /api/rstudio/insert is deliberately unauthenticated (see rstudio_api.py):
# with permissive CORS, any localhost page the user happens to have open could
# push R code into their editor. Opt back in only for a direct-to-:8000 setup
# that bypasses the proxy.
if os.environ.get("STAT_CONSULTANT_DEV_CORS") == "1":
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(ws_consult_router)
app.include_router(references_router)
app.include_router(models_router)
app.include_router(settings_router)
app.include_router(rstudio_router)
app.include_router(environment_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe, and the Addin's authoritative source for the state dir.

    The R launcher normally pins the location via ``--state-dir``, but that
    can't help when the backend was started by hand or is a leftover process
    from an earlier session. Reporting the resolved directory here means the
    Addin reads the shared secret from wherever this process actually wrote it,
    so the Windows ``~`` divergence (see paths.py) can't strand them.
    """
    return {
        "status": "ok",
        "state_dir": str(paths.state_dir()),
        "version": __version__,
    }


# Serve the built frontend from this same process, so the shipped app is one
# port and one binary — no Node, no Vite, no second window. Registered last:
# Starlette matches routes in order, so every /api and /ws route above wins.
_DIST = frontend_dist()

if _DIST is not None:

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        """Serve a built asset, else index.html (SPA fallback)."""
        # An unmatched /api or /ws path is a genuine 404, not a page request —
        # returning HTML there would turn a typo'd endpoint into a confusing
        # "why did my fetch get markup?" bug.
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404, detail="not found")

        candidate = (_DIST / full_path).resolve()
        # full_path is attacker-controllable; confine it to the dist tree so
        # "../.." can't read outside it.
        if candidate.is_file() and candidate.is_relative_to(_DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
