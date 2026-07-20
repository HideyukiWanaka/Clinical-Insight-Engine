# stat-consultant

See `docs/SPEC.md` (正典) and `docs/BUILD_PROMPTS.md` for the implementation plan.
Built through Step 9 (reference figure → ggplot2 code, mapped onto the user's
synced real data), including reference upload + lightweight RAG grounding
(Step 4), the send-to-RStudio queue + clipboard fallback (Step 5), the RStudio
Addin's code insertion (Step 6) and transparent, PII-filtered environment sync
(Step 7) that grounds chat answers in the user's actual GlobalEnv (Step 8),
plus multi-provider LLM support (Anthropic / OpenAI / Gemini) with an in-app
model picker and BYOK API-key entry (keys stored in the OS keychain). See
`docs/TEST_PLAN.md` for the real-machine verification scenarios and
`docs/TEST_FINDINGS.md` for issues found (and fixed) during that testing.

## quick start (再起動含む)

`stat-consultant/start.command`（macOS）/ `start.bat`（Windows）をダブルクリック
すると、backend・frontendを（既存プロセスが残っていれば安全に停止した上で）
まとめて起動し、チャット画面をブラウザで開く。開発中に立ち上げ直したい
ときも、これを再度ダブルクリックすればよい。以下は内部で実行している
コマンドの詳細（手動で個別に動かしたい場合や、スクリプトが使えない環境向け）。

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
R method-selection few-shot distilled from `skills/core/statistics/*/SKILL.md`
(plus a ggplot2 visualization pitfalls section sourced from official ggplot2/R
docs — see `backend/app/fewshot.py`). Every turn also folds in the latest
PII-filtered RStudio environment snapshot (Step 7/8, see below) so method
suggestions and generated code reference the user's real column names, group
levels, and missing-data counts — never invented ones.

### references: `POST /api/references`

Upload a Markdown/text reference (multipart `file`). It is saved to the single
`user_references/` folder and reflected into a lightweight keyword index
(adapted from `cie/knowledge/reference_library.py`). On each chat turn the
backend runs `retrieve(query_terms, top_k=2)` over the latest user message and
folds the top hits into the system prompt, so answers ground on the user's own
material (proper nouns included). No approval flow or hierarchy — individual use.
Non-UTF-8 uploads (e.g. images) are rejected with 415.

### reference figures (Step 9): image attachment in chat

A separate attach path (paperclip in the composer, distinct from the
`/api/references` text-upload above) lets the user attach an image — a plot
from a paper, a style they want reproduced — to a single chat turn. The image
is **never persisted server-side** (no `user_references/` write; it lives only
in the WebSocket frame and the frontend's local display cache). When an image
is present, `IMAGE_INSTRUCTION` (`backend/app/prompts.py`) is appended to the
system prompt for that turn: reproduce the figure's *style* (chart type, axes,
facets, color mapping) using the user's real synced column names, never
fabricate columns that aren't in the synced environment (ask instead), and
never invent the figure's underlying numbers. The generated `ggplot2` code
goes through the same「RStudioへ送る」path as any other code block.

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
each with a「RStudioへ送る」button (wired to the pending-code queue, Step 5/6).
The attach button (paperclip) has two paths: uploading a Markdown/text
reference goes to `POST /api/references` (a toast confirms); attaching an
image sends it inline with the chat turn as a one-off reference figure (Step
9, see backend §"reference figures" above) — a toast confirms that too, and a
thumbnail chip lets the user remove it before sending. The history sidebar /
settings / auth UI (SPEC 4.5) are intentionally absent.

The UI connects to `ws://<host>:8000/ws/consult`, so run the backend (with
`ANTHROPIC_API_KEY`) first.

## r-addin (RStudio Addin: `statConsultantAddin`)

Code insertion (Step 6) + transparent environment sync (Step 7), on one
non-blocking poller (runs on RStudio's idle event loop via `later`, so the
console stays free to run the inserted code). Each ~2s cycle does two things:

- **Code insertion**: polls the backend's pending-code queue and inserts each
  queued block at the cursor of the active source document via
  `rstudioapi::insertText()`.
- **Environment sync**: scans `GlobalEnv` for `data.frame`-like objects and, on
  change only, POSTs an aggregate-only snapshot (column names/types/missing
  counts/factor levels — **never row/cell values**, `inject_raw_data_rows`
  stays `False`) to the backend, which grounds chat answers in the user's real
  data (Step 8). PII columns/values are excluded client-side (`R/pii.R`) and
  double-checked server-side (`app/pii.py`) before anything leaves the
  machine.

Install into RStudio:

```r
install.packages(c("rstudioapi", "httr2", "later"))  # if not already present
remotes::install_local("stat-consultant/r-addin", force = TRUE)  # or devtools::install(...)
```

Then, in RStudio, run the backend first, and use the **Addins** menu:

- **Stat Consultant: 開始** — start polling (code insertion + environment
  sync). Invoke once per session; each「RStudioへ送る」in the chat then
  appears at your cursor within ~2s, and any synced data grounds chat replies.
- **Stat Consultant: 停止** — stop polling.

Auth is zero-config: the backend writes a fresh shared secret to
`~/.stat-consultant/rstudio_token` on every start, and the Addin reads it on
each poll (so a backend restart self-heals — no need to restart the Addin).
Only `GET /api/rstudio/pending` is token-gated; `POST /insert` (the browser's
path) is unchanged. If the token file isn't found, the Addin prints the exact
path it checked — compare it against the absolute path the backend logs at
startup (relevant only on Windows, where R's `~` and Python's home dir can
differ).
