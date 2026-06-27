#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

cd "$ROOT_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/logs"

existing_pids="$(pgrep -f "scripts/run_paper.py" 2>/dev/null || true)"
if [[ -n "$existing_pids" ]]; then
  echo "run_paper.py already appears to be running:" >&2
  for pid in $existing_pids; do
    command_text="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    echo "  pid=$pid $command_text" >&2
  done
  echo "Stop the existing paper loop before starting another one." >&2
  exit 1
fi

echo "Starting paper loop; appending logs to logs/trading_bot.log"
exec "$PYTHON_BIN" scripts/run_paper.py 2>&1 | tee -a "$ROOT_DIR/logs/trading_bot.log"
