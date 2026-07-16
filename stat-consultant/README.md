# stat-consultant

See `docs/SPEC.md` (正典) and `docs/BUILD_PROMPTS.md` for the implementation plan.
Built through Step 3 (chat UI over the structured WebSocket). Later features
(attach button, RStudio wiring, environment sync) are not here yet.

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
JSON object, or bare text for quick testing); the reply comes back as a stream
of structured frames (SPEC 4.4) terminated by `done`.

```
# needs ANTHROPIC_API_KEY in the server's environment
websocat ws://localhost:8000/ws/consult
> A群とB群を比較したい
< {"type":"assistant_text","reason":"...","detail":"..."}
< {"type":"assistant_code","reason":"対応のないt検定／各群の正規性を仮定","language":"r","code":"t.test(...)"}
< {"type":"done"}
```

Client → server frame: `{"text": "...", "conversation_id": "..."}` (or bare text).
Server → client frames:
- `{"type":"assistant_text","reason":<一言>,"detail":<折りたたみ用の詳細>}`
- `{"type":"assistant_code","reason":<一言の理由・前提>,"language":"r","code":<Rコード>}`
  (one reply may carry several; each code block always carries a `reason`)
- `{"type":"done"}` / `{"type":"error","reason":"..."}`

The reply is shaped by an `output_config.format` JSON schema and grounded with an
R method-selection few-shot distilled from `skills/core/statistics/*/SKILL.md`.

## frontend (Vite + React + TypeScript)

```
cd stat-consultant/frontend
npm install
npm run dev            # start the backend on :8000 first
```

Open the printed local URL. A minimal chat SPA (SPEC 4.1/4.2 — Light & Clean,
one Deep Teal accent): message list + input (Enter to send, Shift+Enter for a
newline, IME-safe). Assistant replies render as `assistant_text` (一言理由 +
click-to-expand detail) and syntax-highlighted `assistant_code` cards, each with
a「RStudioへ送る」button (visual only — wired in Step 5). The attach button
(Step 4) and history sidebar / model select / settings / auth UI (SPEC 4.5, never
built) are intentionally absent.

The UI connects to `ws://<host>:8000/ws/consult`, so run the backend (with
`ANTHROPIC_API_KEY`) first.

## r-addin (RStudio Addin, R package skeleton)

Empty scaffold only (`DESCRIPTION`, `inst/rstudio/addins.dcf`, placeholder function).
No install/run steps yet — implemented starting at BUILD_PROMPTS.md Step 6.
