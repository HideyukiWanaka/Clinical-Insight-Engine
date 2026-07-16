from fastapi import FastAPI

from .conversation import ConversationStore
from .ws_consult import router as ws_consult_router

app = FastAPI(title="Stat Consultant Backend")

# Process-wide running-conversation registry (single-user, in-process — SPEC 4.1).
app.state.conversations = ConversationStore()

app.include_router(ws_consult_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
