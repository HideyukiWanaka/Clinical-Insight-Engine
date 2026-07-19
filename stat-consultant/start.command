#!/bin/bash
# Double-click to (re)launch stat-consultant: stops any stale backend/frontend
# from a previous run, (re)installs deps if missing, then opens backend and
# frontend each in their OWN Terminal window (not backgrounded in this one),
# and opens the chat in the browser. This keeps backend log lines (startup
# token message, environment-sync lines used in docs/TEST_PLAN.md §S7) fully
# visible instead of interleaved with Vite's dev-server output. Close a
# window (or Ctrl+C inside it) to stop that process.
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

echo "== backend 準備 =="
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -e .
fi

echo "== frontend 準備 =="
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install
fi

# backend と frontend をそれぞれ独立した Terminal ウィンドウで起動する。
# 1つの端末に混在させると、TEST_PLAN.md が確認対象とするbackendのログ行
# （起動時のトークン出力、環境同期ログ等）がVite側の出力に埋もれてしまうため。
osascript <<EOF
tell application "Terminal"
  activate
  set backendWin to do script "cd '$ROOT/backend' && .venv/bin/uvicorn app.main:app --reload --port 8000"
  set custom title of backendWin to "stat-consultant: backend"
  set frontendWin to do script "cd '$ROOT/frontend' && npm run dev"
  set custom title of frontendWin to "stat-consultant: frontend"
end tell
EOF

# frontend が応答するようになるまで待ってからブラウザを開く
for _ in $(seq 1 30); do
  if curl -s -o /dev/null "http://localhost:5173"; then
    open "http://localhost:5173"
    break
  fi
  sleep 1
done

echo "backend / frontend はそれぞれ別のTerminalウィンドウで起動しました。"
echo "backendのログ（環境同期など）は「stat-consultant: backend」ウィンドウで確認できます。"
echo "止めるには各ウィンドウを閉じるか、そのウィンドウでCtrl+Cしてください。"
