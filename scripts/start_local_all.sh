#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_PORT="${1:-8011}"

cd "$ROOT_DIR"

if ! [[ "$WEB_PORT" =~ ^[0-9]+$ ]] || (( WEB_PORT < 1 || WEB_PORT > 65535 )); then
  echo "Invalid Web Admin port: $WEB_PORT" >&2
  echo "Usage: ./scripts/start_local_all.sh [1-65535]" >&2
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This one-click launcher currently supports macOS Terminal windows only." >&2
  echo "Please start the services separately:" >&2
  echo "  ./scripts/start_web.sh ${WEB_PORT}" >&2
  echo "  ./scripts/start_radar_loop.sh" >&2
  echo "  ./scripts/start_paper.sh" >&2
  exit 1
fi

if ! command -v osascript >/dev/null 2>&1; then
  echo "osascript is required to open separate Terminal windows on macOS." >&2
  exit 1
fi

quote_for_applescript() {
  # AppleScript 字符串需要转义反斜杠和双引号，避免路径或命令内容被截断。
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "$value"
}

quote_for_shell() {
  # Terminal 执行的是 shell 命令，路径和端口先做 shell 层转义再交给 AppleScript。
  printf '%q' "$1"
}

open_terminal_window() {
  local title="$1"
  local command="$2"
  local escaped_command
  escaped_command="$(quote_for_applescript "$command")"

  osascript <<APPLESCRIPT
tell application "Terminal"
  activate
  do script "$escaped_command"
  set custom title of front window to "$title"
end tell
APPLESCRIPT
}

ROOT_DIR_Q="$(quote_for_shell "$ROOT_DIR")"
WEB_PORT_Q="$(quote_for_shell "$WEB_PORT")"

open_terminal_window "Trading Bot Web Admin" "cd $ROOT_DIR_Q && ./scripts/start_web.sh $WEB_PORT_Q"
open_terminal_window "Trading Bot Alert Radar" "cd $ROOT_DIR_Q && ./scripts/start_radar_loop.sh"
open_terminal_window "Trading Bot Paper Loop" "cd $ROOT_DIR_Q && ./scripts/start_paper.sh"

echo "Opened local Trading Bot windows. Check each Terminal window for startup status:"
echo "  Web Admin: ./scripts/start_web.sh ${WEB_PORT}"
echo "  Alert Radar: ./scripts/start_radar_loop.sh"
echo "  Paper Loop: ./scripts/start_paper.sh"
