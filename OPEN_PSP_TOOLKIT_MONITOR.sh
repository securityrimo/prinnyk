#!/usr/bin/env bash
set -u
ROOT="${1:-$HOME/PrinnyReverseToolkit}"
MONITOR="$ROOT/PSP_TOOLKIT_MONITOR.sh"
if [[ ! -x "$MONITOR" ]]; then
  echo "모니터 스크립트가 없습니다: $MONITOR"
  return 0 2>/dev/null || true
fi
if command -v gnome-terminal >/dev/null 2>&1; then
  gnome-terminal -- bash "$MONITOR" "$ROOT" >/dev/null 2>&1 &
elif command -v mate-terminal >/dev/null 2>&1; then
  mate-terminal -- bash "$MONITOR" "$ROOT" >/dev/null 2>&1 &
elif command -v xfce4-terminal >/dev/null 2>&1; then
  xfce4-terminal --hold -e "bash '$MONITOR' '$ROOT'" >/dev/null 2>&1 &
elif command -v konsole >/dev/null 2>&1; then
  konsole -e bash "$MONITOR" "$ROOT" >/dev/null 2>&1 &
elif command -v x-terminal-emulator >/dev/null 2>&1; then
  x-terminal-emulator -e bash "$MONITOR" "$ROOT" >/dev/null 2>&1 &
else
  echo "새 터미널 프로그램을 찾지 못했습니다. 현재 터미널에서 실행합니다."
  bash "$MONITOR" "$ROOT"
fi
