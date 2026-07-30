#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$ROOT/workspace/reports/psp_toolkit_launcher"
mkdir -p "$STATE_DIR"
PID_FILE="$STATE_DIR/background.pid"
LAUNCH_LOG="$STATE_DIR/background_launcher.log"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "이미 백그라운드 작업이 실행 중입니다. PID: $old_pid"
    echo "상태 확인: bash \"$ROOT/CHECK_PSP_TOOLKIT_STATUS.sh\""
    return 0 2>/dev/null || exit 0
  fi
fi

cd "$ROOT" || {
  echo "프로젝트 폴더 접근 실패: $ROOT" >&2
  return 1 2>/dev/null || exit 1
}
nohup bash "$ROOT/RUN_PSP_TOOLKIT.sh" "$@" >"$LAUNCH_LOG" 2>&1 < /dev/null &
pid=$!
echo "$pid" > "$PID_FILE"
echo "PSP Toolkit V3 작업을 백그라운드에서 시작했습니다. PID: $pid"
echo "D: 작업 공간을 자동 탐지하고 game2.iso를 검증 후 이동합니다."
echo "홈 디스크에는 대용량 추출본을 남기지 않습니다."
echo "상태 확인: bash \"$ROOT/CHECK_PSP_TOOLKIT_STATUS.sh\""
return 0 2>/dev/null || exit 0
