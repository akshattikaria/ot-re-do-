#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
repo_root="$PWD"
if [[ ! -x .venv/bin/python || ! -d 'OT project/frontend/node_modules' ]]; then
  echo 'Run bash scripts/setup.sh first.' >&2
  exit 1
fi
cd 'OT project'
"$repo_root/.venv/bin/python" -m uvicorn api.server:app --host 127.0.0.1 --port 8000 &
api_pid=$!
cd frontend
node "$repo_root/OT project/frontend/node_modules/vite/bin/vite.js" --host 127.0.0.1 --strictPort &
web_pid=$!
cleanup() {
  kill "$api_pid" "$web_pid" 2>/dev/null || true
  wait "$api_pid" "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
wait -n "$api_pid" "$web_pid"
