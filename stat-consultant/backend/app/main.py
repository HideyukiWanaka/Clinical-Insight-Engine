from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .conversation import ConversationStore
from .environment import EnvironmentStore
from .environment_api import router as environment_router
from .models_api import router as models_router
from .origins import ALLOW_ORIGIN_REGEX
from .references import ReferenceLibrary
from .references_api import router as references_router
from .rstudio import RStudioQueue
from .rstudio_api import router as rstudio_router
from .rstudio_auth import generate_and_write_token
from .settings_api import router as settings_router
from .ws_consult import router as ws_consult_router

# Single flat folder for the user's uploaded references (SPEC 5.6).
REFERENCES_DIR = Path(__file__).resolve().parent.parent / "user_references"

app = FastAPI(title="Stat Consultant Backend")

# Process-wide state (single-user, in-process — SPEC 4.1).
app.state.conversations = ConversationStore()
app.state.references = ReferenceLibrary(REFERENCES_DIR)
app.state.rstudio_queue = RStudioQueue()
# Latest RStudio GlobalEnv snapshot (Step 7); consumed by chat grounding (Step 8).
app.state.environment = EnvironmentStore()
# Fresh shared secret each start; the Addin re-reads it every poll (self-heals).
app.state.rstudio_token = generate_and_write_token()

# The frontend is served from a different localhost port in dev, so the
# reference upload (a cross-origin fetch) needs CORS. Localhost only — the
# allow-rule is shared with the WS handshake / write-endpoint checks so the two
# never drift (see ``origins.py``). This blocks a remote page from *reading*
# our responses; the same rule is re-checked server-side on state-changing
# endpoints to block cross-origin *writes* (which CORS alone does not stop).
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=ALLOW_ORIGIN_REGEX,
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
    return {"status": "ok"}
