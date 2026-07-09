#!/usr/bin/env bash
# CIE Platform — ワンコマンド起動スクリプト
#
#   ./scripts/dev.sh
#
# やること:
#   1. Python 3.11+ の venv (.venv) が無ければ作成し、依存をインストール
#   2. frontend/node_modules が無ければ npm install
#   3. セッショントークンを frontend/.env.local に永続化（初回のみ生成）
#      → API とフロントが同じトークンを共有するので手動設定は不要
#   4. API (127.0.0.1:8000) と Vite (127.0.0.1:5173) を起動してブラウザを開く
#
# 停止: このターミナルで Ctrl+C（両プロセスをまとめて終了します）
# ダブルクリック起動: リポジトリ直下の「CIE起動.command」がこのスクリプトを呼びます。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
ENV_LOCAL="$ROOT/frontend/.env.local"
LOG_DIR="$ROOT/.dev"
API_PORT="${CIE_API_PORT:-8000}"
VITE_PORT="${VITE_PORT:-5173}"

mkdir -p "$LOG_DIR"

log() { printf '[CIE-dev] %s\n' "$*"; }

# ── 1. Python venv ───────────────────────────────────────────────────────────
find_python() {
  for p in python3.13 python3.12 python3.11; do
    if command -v "$p" > /dev/null 2>&1; then
      echo "$p"
      return
    fi
  done
  # 素の python3 が 3.11 以上ならそれで良い
  if command -v python3 > /dev/null 2>&1 \
    && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo python3
    return
  fi
  return 1
}

if [ ! -x "$VENV/bin/python" ]; then
  PY="$(find_python)" || {
    log "エラー: Python 3.11 以上が見つかりません。https://www.python.org/ からインストールしてください。"
    exit 1
  }
  log "venv を作成しています ($PY)…"
  "$PY" -m venv "$VENV"
fi

if ! "$VENV/bin/python" -c 'import fastapi' > /dev/null 2>&1; then
  log "Python 依存をインストールしています（初回のみ・数分かかります）…"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -e "$ROOT[api,rag]"
fi

# ── 2. frontend 依存 ─────────────────────────────────────────────────────────
if ! command -v npm > /dev/null 2>&1; then
  log "エラー: npm が見つかりません。https://nodejs.org/ から Node.js をインストールしてください。"
  exit 1
fi
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  log "frontend 依存をインストールしています（初回のみ）…"
  (cd "$ROOT/frontend" && npm install --no-audit --no-fund)
fi

# ── 3. セッショントークン（.env.local に永続化・初回のみ生成） ─────────────
TOKEN=""
if [ -f "$ENV_LOCAL" ]; then
  TOKEN="$(sed -n 's/^VITE_CIE_TOKEN=//p' "$ENV_LOCAL" | head -1)"
fi
if [ -z "$TOKEN" ]; then
  TOKEN="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  {
    echo "VITE_CIE_API_BASE=http://127.0.0.1:$API_PORT"
    echo "VITE_CIE_TOKEN=$TOKEN"
  } > "$ENV_LOCAL"
  log "セッショントークンを生成し frontend/.env.local に保存しました。"
fi

# ── 4. 起動 ──────────────────────────────────────────────────────────────────
port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN > /dev/null 2>&1; }

PIDS=()
cleanup() {
  log "停止しています…"
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" > /dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

if port_in_use "$API_PORT"; then
  log "API はすでにポート $API_PORT で起動しています（再利用）。"
else
  log "API を起動しています (http://127.0.0.1:$API_PORT)…"
  (cd "$ROOT" && CIE_API_SESSION_TOKEN="$TOKEN" CIE_API_PORT="$API_PORT" \
    "$VENV/bin/python" -m cie.api.main >> "$LOG_DIR/api.log" 2>&1) &
  PIDS+=($!)
fi

if port_in_use "$VITE_PORT"; then
  log "フロントエンドはすでにポート $VITE_PORT で起動しています（再利用）。"
else
  log "フロントエンドを起動しています (http://127.0.0.1:$VITE_PORT)…"
  (cd "$ROOT/frontend" && VITE_PORT="$VITE_PORT" \
    npm run --silent dev >> "$LOG_DIR/frontend.log" 2>&1) &
  PIDS+=($!)
fi

# 両ポートが開くまで待ってからブラウザを開く（最大30秒）
for _ in $(seq 1 60); do
  if port_in_use "$API_PORT" && port_in_use "$VITE_PORT"; then
    break
  fi
  sleep 0.5
done

if ! port_in_use "$API_PORT"; then
  log "エラー: API が起動しませんでした。ログ: $LOG_DIR/api.log"
  tail -5 "$LOG_DIR/api.log" 2>/dev/null || true
  exit 1
fi
if ! port_in_use "$VITE_PORT"; then
  log "エラー: フロントエンドが起動しませんでした。ログ: $LOG_DIR/frontend.log"
  tail -5 "$LOG_DIR/frontend.log" 2>/dev/null || true
  exit 1
fi

URL="http://127.0.0.1:$VITE_PORT"
log "起動完了: $URL （トークンは自動設定済み）"
if command -v open > /dev/null 2>&1; then
  open "$URL"
fi

if [ "${#PIDS[@]}" -eq 0 ]; then
  # 何も新規起動していない（両方再利用）ならそのまま終了
  trap - EXIT INT TERM
  exit 0
fi

log "終了するには Ctrl+C を押してください。"
wait
