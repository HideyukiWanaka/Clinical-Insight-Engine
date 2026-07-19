#!/bin/bash
# Double-click to (re)launch stat-consultant: stops any stale backend/frontend
# from a previous run, (re)installs deps if missing, starts both, and opens
# the chat in the browser. Close this window (or Ctrl+C) to stop everything.
set -u
cd "$(dirname "$0")"
ROOT="$(pwd)"

# Only kill a process on the given port if its command line matches our own
# service, so an unrelated process that happens to use the port is untouched.
# -sTCP:LISTEN matters: a plain `lsof -ti tcp:$port` also matches unrelated
# processes with an open *connection* to that port (e.g. a browser tab, or
# this very script's own health-check curl), not just the listener.
kill_stale() {
  local port="$1" pattern="$2" pid
  pid="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null | head -n1 || true)"
  if [ -n "$pid" ] && ps -p "$pid" -o command= 2>/dev/null | grep -q "$pattern"; then
    echo "既存の $pattern (PID $pid, port $port) を停止します"
    kill "$pid" 2>/dev/null
    for _ in 1 2 3 4 5; do
      lsof -ti tcp:"$port" -sTCP:LISTEN >/dev/null 2>&1 || break
      sleep 1
    done
    # Still bound after 5s (e.g. --reload's watcher subprocess) — force it.
    kill -9 "$pid" 2>/dev/null
    sleep 1
  fi
}

kill_stale 8000 "app.main:app"
kill_stale 5173 "vite"

echo "== backend =="
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -e .
fi
.venv/bin/uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!

echo "== frontend =="
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
npm run dev &
FRONTEND_PID=$!

cleanup() {
  echo "停止しています…"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

# frontend が応答するようになるまで待ってからブラウザを開く
for _ in $(seq 1 30); do
  if curl -s -o /dev/null "http://localhost:5173"; then
    open "http://localhost:5173"
    break
  fi
  sleep 1
done

wait
