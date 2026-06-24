#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-8011}"
HOST="${HOST:-127.0.0.1}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

cd "$ROOT_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

existing_pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$existing_pids" ]]; then
  for pid in $existing_pids; do
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | awk '/^n/ {print substr($0, 2); exit}')"
    command_text="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$cwd" == "$ROOT_DIR" && "$command_text" == *"uvicorn"* && "$command_text" == *"app.web.server:app"* ]]; then
      echo "Stopping existing Trading Bot Web Admin on $HOST:$PORT (pid=$pid)"
      kill "$pid"
      sleep 1
    else
      echo "Port $PORT is occupied by a non-matching process (pid=$pid)." >&2
      echo "Command: $command_text" >&2
      exit 1
    fi
  done
fi

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is still occupied after stop attempt." >&2
  exit 1
fi

echo "Starting Trading Bot Web Admin: http://$HOST:$PORT"
exec "$PYTHON_BIN" -m uvicorn app.web.server:app --host "$HOST" --port "$PORT"
