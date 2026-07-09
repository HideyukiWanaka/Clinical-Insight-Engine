#!/usr/bin/env bash
# CIE Platform — ダブルクリック起動（macOS）
# Finder でこのファイルをダブルクリックすると、ターミナルが開いて
# scripts/dev.sh（API + フロントエンドのワンコマンド起動）が実行されます。
# 停止するにはそのターミナルで Ctrl+C を押してください。
cd "$(dirname "$0")"
exec ./scripts/dev.sh
