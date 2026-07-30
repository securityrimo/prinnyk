#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_DIR="$ROOT/workspace/reports/psp_toolkit_launcher"
mkdir -p "$BOOTSTRAP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
BOOTSTRAP_LOG="$BOOTSTRAP_DIR/launcher_$STAMP.log"

notify_done() {
  local title="$1"
  local body="$2"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "$title" "$body" >/dev/null 2>&1 || true
  fi
}

run_main() {
  cd "$ROOT" || return 1
  echo "PSP Localization Toolkit V3 자동 실행"
  echo "시작: $(date)"
  echo "프로젝트: $ROOT"
  echo

  storage_args=()
  if [[ -n "${PSP_D_ROOT:-}" ]]; then
    storage_args+=(--data-root "$PSP_D_ROOT")
  fi
  echo "[준비] D: 작업 공간 확인 및 game2.iso 안전 이동"
  python3 -u psp_toolkit.py prepare-storage "${storage_args[@]}" || {
    echo
    echo "[중단] D: 작업 공간을 준비하지 못했습니다."
    echo "아무 ISO도 수정하지 않았고, 홈 디스크에서 대용량 분석을 시작하지 않았습니다."
    echo "D:의 Linux 경로를 알면 다음처럼 지정할 수 있습니다:"
    echo "  PSP_D_ROOT=/media/$USER/D bash \"$ROOT/START_PSP_TOOLKIT_BACKGROUND.sh\""
    return 3
  }

  CONFIG="$ROOT/.psp_toolkit_storage.json"
  eval "$(python3 - "$CONFIG" <<'PY'
import json, shlex, sys
p=json.load(open(sys.argv[1], encoding='utf-8'))
for key in ('run_dir','report_dir','game2_iso'):
    print(f"{key.upper()}={shlex.quote(str(p[key]))}")
PY
)"
  mkdir -p "$REPORT_DIR"
  LOG="$REPORT_DIR/run_$STAMP.log"
  LOCK="$REPORT_DIR/.psp_toolkit_run.lock"

  run_toolkit() {
    echo "로그: $LOG"
    echo "작업 공간: $RUN_DIR"
    echo "보고서: $REPORT_DIR"
    echo "프리니 2: $GAME2_ISO"
    echo
    python3 -u psp_toolkit.py all \
      --game1 "$ROOT/game.iso" \
      --game2 "$GAME2_ISO" \
      --run-dir "$RUN_DIR" \
      --report-dir "$REPORT_DIR" \
      "$@"
    rc=$?
    echo
    echo "종료: $(date)"
    echo "종료 코드: $rc"
    echo "진행 상태: $REPORT_DIR/progress.txt"
    echo "최종 보고서: $REPORT_DIR/index.html"
    return "$rc"
  }

  if command -v flock >/dev/null 2>&1; then
    (
      flock -n 9 || {
        echo "이미 PSP Toolkit 작업이 실행 중입니다: $LOCK"
        exit 9
      }
      run_toolkit "$@"
    ) 9>"$LOCK" 2>&1 | tee "$LOG"
    rc=${PIPESTATUS[0]}
  else
    run_toolkit "$@" 2>&1 | tee "$LOG"
    rc=${PIPESTATUS[0]}
  fi

  ln -sfn "$(basename "$LOG")" "$REPORT_DIR/latest.log" 2>/dev/null || cp -f "$LOG" "$REPORT_DIR/latest.log"
  # 오래된 로그는 5개만 남긴다.
  find "$REPORT_DIR" -maxdepth 1 -type f -name 'run_*.log' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | tail -n +6 | cut -d' ' -f2- | while IFS= read -r old; do
        [[ -n "$old" ]] && rm -f -- "$old"
      done

  if [[ "$rc" -eq 0 ]]; then
    notify_done "PSP Toolkit 완료" "프리니 1/2 분석과 V5 빌드가 완료되었습니다."
  else
    notify_done "PSP Toolkit 확인 필요" "작업이 부분 완료 또는 실패했습니다. progress.txt를 확인하세요."
  fi
  return "$rc"
}

run_main "$@" 2>&1 | tee "$BOOTSTRAP_LOG"
rc=${PIPESTATUS[0]}
return "$rc" 2>/dev/null || exit "$rc"
