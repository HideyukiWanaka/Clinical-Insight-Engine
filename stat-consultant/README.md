# stat-consultant

Step 0 scaffold only. See `docs/SPEC.md` (正典) and `docs/BUILD_PROMPTS.md` for the
implementation plan. No application logic exists yet.

## backend (FastAPI + uvicorn)

```
cd stat-consultant/backend
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Check: `curl localhost:8000/health` → `{"status":"ok"}`

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
