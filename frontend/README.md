# CIE Frontend — IDE Workbench (Phase 2 shell)

IDE-style web frontend decided in `decisions/ADR-0005.md` and specified in
`spec/ui/ide-workbench-spec.md`. Built with **React + TypeScript + Vite +
Monaco**. Talks to `cie/api/` (FastAPI) over REST/WebSocket per
`spec/api/rest-api-contract.md` — never directly into `cie/agents/` or
`cie/runtime/`.

## Status: Phase 2 (`prompts/redesign/phase2_frontend_shell.md`)

Implemented in this phase:

- ✅ 4-pane + header layout, resizable (`react-resizable-panels`), light/dark.
- ✅ API client (`src/api/client.ts`): `X-CIE-Token` header, base URL
  `http://127.0.0.1:8000` (override with `VITE_CIE_API_BASE`), and it
  propagates the `{error_code,message,detail}` envelope + `r_script_provenance.reason`
  to the UI so a failure is never silent (spec §5).
- ✅ Left chat pane: input → `POST /api/intent` → (on confirm) `POST /api/propose`.
  Renders `explanation_markdown` as a bubble and each `code_candidates[]` as a
  code block.
- ✅ Monaco editor (offline: bundled from the local `monaco-editor` package via
  `src/monaco-setup.ts`, no CDN — honours the `offline_first` invariant).

Deferred to Phase 3+ (rendered as labelled placeholders):

- ❌ "✓ 挿入" / "▶ 実行" real behavior, `WS /ws/console` streaming, figure
  display, file tree, workspace variables, report format panel.

Note: `spec/ui/ide-workbench-spec.md` §3.5 bundles *Workspace/Data* and
*Output & Format* into one right-bottom pane; that is implemented as
`WorkspacePane.tsx` with two tabs (rather than a separate `FormatPane.tsx`).

## Develop

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173 (127.0.0.1-bound, ADR-0005)
```

Connect to the API: start `cie/api` (it prints `[CIE-API] X-CIE-Token=…` once),
then paste that token into the chat pane's connection field, or export
`VITE_CIE_TOKEN` before `npm run dev`.

## Verify

```bash
npm run build      # tsc -b + vite build (typecheck)
npm run test:e2e   # Playwright: 4-pane render + intent→propose + failure-reason
```

The Playwright config points at the environment's pre-installed Chromium
(`/opt/pw-browsers/chromium-1194/…`); override with `CIE_CHROMIUM_PATH` if the
path differs. The E2E test stubs the Phase 1 API (route interception), per the
phase prompt ("Phase 1 の実物 or スタブサーバに接続").
