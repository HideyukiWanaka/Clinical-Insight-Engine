# stat-consultant

See `docs/SPEC.md` (正典) and `docs/BUILD_PROMPTS.md` for the implementation plan.
Built through Step 4 (reference upload + lightweight RAG grounding), plus
multi-provider LLM support (Anthropic / OpenAI / Gemini) with an in-app model
picker and BYOK API-key entry (keys stored in the OS keychain). Later features
(RStudio wiring, environment sync, image/Vision) are not here yet.

## backend (FastAPI + uvicorn)

```
cd stat-consultant/backend
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Check: `curl localhost:8000/health` → `{"status":"ok"}`

API keys are **per-user (BYOK)**: enter them in the app's settings screen (the
gear icon) — they're stored in the OS keychain via `keyring`. Environment
variables (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` |
`GOOGLE_API_KEY`) still work as a fallback for advanced/headless setups.

### models: `GET /api/models`

Returns the curated model list (Anthropic / OpenAI / Gemini) with an `available`
flag per model — true when that provider's key is configured (keychain or env) —
and the `default` id. The chosen model id rides on each chat frame; the WS
rejects a model whose provider key is missing. Edit the list in
`backend/app/models_registry.py` to match each provider's current lineup.

### settings: `GET/POST /api/settings/keys`, `DELETE /api/settings/keys/{provider}`

The BYOK key screen's data source. `GET` returns per-provider `{provider, label,
has_key}` (never the key). `POST {provider, api_key}` cleans the key (strips
whitespace / zero-width chars, rejects non-ASCII) and stores it in the OS keychain
(`app/secrets_store.py`, translated from `cie/core/secrets_store.py`); `DELETE`
clears it. Keys are never echoed back or logged — only `has_key`. Saving a key
takes effect on the next chat turn (the LLM client is built per request).

### chat: `WS /ws/consult`

A single socket carries a multi-turn statistics consultation; the server owns
the running history so later turns keep context. Send one message per turn (a
JSON object, or bare text for quick testing); the reply comes back as a stream
of structured frames (SPEC 4.4) terminated by `done`.

```
# needs the chosen model's provider key in the server's environment
websocat ws://localhost:8000/ws/consult
> {"text": "A群とB群を比較したい", "model": "claude-opus-4-8"}
< {"type":"assistant_text","reason":"...","detail":"..."}
< {"type":"assistant_code","reason":"対応のないt検定／各群の正規性を仮定","language":"r","code":"t.test(...)"}
< {"type":"done"}
```

Client → server frame: `{"text": "...", "conversation_id": "...", "model": "..."}`
(or bare text; `model` falls back to the server default).
Server → client frames:
- `{"type":"assistant_text","reason":<一言>,"detail":<折りたたみ用の詳細>}`
- `{"type":"assistant_code","reason":<一言の理由・前提>,"language":"r","code":<Rコード>}`
  (one reply may carry several; each code block always carries a `reason`)
- `{"type":"done"}` / `{"type":"error","reason":"..."}`

The reply is shaped by an `output_config.format` JSON schema and grounded with an
R method-selection few-shot distilled from `skills/core/statistics/*/SKILL.md`.

### references: `POST /api/references`

Upload a Markdown/text reference (multipart `file`). It is saved to the single
`user_references/` folder and reflected into a lightweight keyword index
(adapted from `cie/knowledge/reference_library.py`). On each chat turn the
backend runs `retrieve(query_terms, top_k=2)` over the latest user message and
folds the top hits into the system prompt, so answers ground on the user's own
material (proper nouns included). No approval flow or hierarchy — individual use.
Non-UTF-8 uploads (e.g. images) are rejected with 415; images are Step 9.

## frontend (Vite + React + TypeScript)

```
cd stat-consultant/frontend
npm install
npm run dev            # start the backend on :8000 first
```

Open the printed local URL. A minimal chat SPA (dark code panels + a dark
RStudio button per the design mockup): message list + input (Enter to send,
Shift+Enter for a newline, IME-safe) + a small model dropdown in the header
(populated from `GET /api/models`; unavailable providers are disabled) + a gear
icon opening the API-key settings modal (paste a key → stored in the OS keychain,
never re-shown; saving re-enables that provider's models in the dropdown). Assistant replies render as `assistant_text`
(一言理由 + click-to-expand detail) and syntax-highlighted `assistant_code` cards,
each with a「RStudioへ送る」button (visual only — wired in Step 5). One attach
button (paperclip) uploads a Markdown/text reference to `POST /api/references`
and shows a toast; images are Step 9. The history sidebar / model select /
settings / auth UI (SPEC 4.5) are intentionally absent.

The UI connects to `ws://<host>:8000/ws/consult`, so run the backend (with
`ANTHROPIC_API_KEY`) first.

## r-addin (RStudio Addin, R package skeleton)

Empty scaffold only (`DESCRIPTION`, `inst/rstudio/addins.dcf`, placeholder function).
No install/run steps yet — implemented starting at BUILD_PROMPTS.md Step 6.
