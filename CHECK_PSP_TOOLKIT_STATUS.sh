#!/usr/bin/env bash
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$ROOT/workspace/reports/psp_toolkit_launcher"
PID_FILE="$STATE_DIR/background.pid"
CONFIG="$ROOT/.psp_toolkit_storage.json"

pid=""
[[ -f "$PID_FILE" ]] && pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  echo "상태: 실행 중 (PID $pid)"
else
  echo "상태: 실행 중이 아니거나 완료됨"
fi

REPORT_DIR=""
if [[ -f "$CONFIG" ]]; then
  REPORT_DIR="$(python3 - "$CONFIG" <<'PY' 2>/dev/null
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding='utf-8')).get('report_dir',''))
except Exception:
    pass
PY
)"
fi

if [[ -n "$REPORT_DIR" ]]; then
  echo "D: 보고서: $REPORT_DIR/index.html"
  if [[ -f "$REPORT_DIR/progress.txt" ]]; then
    echo
    cat "$REPORT_DIR/progress.txt"
  fi
  latest="$(find "$REPORT_DIR" -maxdepth 1 -type f -name 'run_*.log' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-)"
  if [[ -n "$latest" && -f "$latest" ]]; then
    echo "최근 로그: $latest"
    echo "------------------------------------------------------------"
    tail -n 35 "$latest"
  fi
elif [[ -f "$STATE_DIR/background_launcher.log" ]]; then
  echo
  echo "D: 준비/실행 로그:"
  tail -n 50 "$STATE_DIR/background_launcher.log"
else
  echo "아직 실행 로그가 없습니다."
fi
return 0 2>/dev/null || exit 0
