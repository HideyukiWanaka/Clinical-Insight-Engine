# CIE Frontend (Scaffolding)

This directory will hold the IDE-style Web frontend decided in
`decisions/ADR-0005.md` and specified in `spec/ui/ide-workbench-spec.md`.

No implementation exists yet — this is Phase 0 scaffolding. Implementation
starts in Phase 1.

## Planned direction

- React + TypeScript + Monaco Editor.
- Four-pane, resizable IDE layout (chat / code / console / files), per
  `spec/ui/ide-workbench-spec.md`.
- Talks to `cie/api/` (FastAPI) over REST/WebSocket, per
  `spec/api/rest-api-contract.md`. No direct calls into `cie/agents/` or
  `cie/runtime/`.
- Local-first Web app (localhost-bound) first; a Tauri desktop shell around
  the same React app is a later, optional step (ADR-0005, Principle 1).
