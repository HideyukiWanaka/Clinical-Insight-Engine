# stat-consultant

See `docs/SPEC.md` (正典) and `docs/BUILD_PROMPTS.md` for the implementation plan.
Built through Step 1 (minimal chat WebSocket). Later features (structured
code/reason output, references, environment sync, RStudio wiring) are not here yet.

## backend (FastAPI + uvicorn)

```
cd stat-consultant/backend
python3 -m venv .venv
.venv/bin/pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...          # required for /ws/consult
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Check: `curl localhost:8000/health` → `{"status":"ok"}`

### chat: `WS /ws/consult`

A single socket carries a multi-turn statistics consultation; the server owns
the running history so later turns keep context. Send one message per turn (a
JSON object, or bare text for quick testing); the reply streams back as `delta`
frames terminated by `done`.

```
# needs ANTHROPIC_API_KEY in the server's environment
websocat ws://localhost:8000/ws/consult
> t検定のコードを教えて
< {"type":"delta","text":"..."}   (repeated)
< {"type":"done"}
```

Client → server frame: `{"text": "...", "conversation_id": "..."}` (or bare text).
Server → client frames: `{"type":"delta","text":"..."}`, `{"type":"done"}`,
`{"type":"error","reason":"..."}`.

## frontend (Vite + React + TypeScript)

```
cd stat-consultant/frontend
npm install
npm run dev
```

Open the printed local URL in a browser to see the default Vite screen.

## r-addin (RStudio Addin, R package skeleton)

Empty scaffold only (`DESCRIPTION`, `inst/rstudio/addins.dcf`, placeholder function).
No install/run steps yet — implemented starting at BUILD_PROMPTS.md Step 6.
