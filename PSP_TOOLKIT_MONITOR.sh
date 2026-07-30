#!/usr/bin/env bash
set -u

ROOT="${1:-$HOME/PrinnyReverseToolkit}"
REFRESH="${PSP_MONITOR_REFRESH:-2}"

find_report_dir() {
  python3 - "$ROOT" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
config = root / '.psp_toolkit_storage.json'
if config.is_file():
    try:
        data = json.loads(config.read_text(encoding='utf-8'))
        value = data.get('report_dir')
        if value:
            print(value)
            raise SystemExit
    except Exception:
        pass
print(root / 'workspace/reports/psp_toolkit')
PY
}

count_csv_rows() {
  local path="$1"
  python3 - "$path" <<'PY'
import csv, sys
from pathlib import Path
p=Path(sys.argv[1])
if not p.is_file():
    print(0)
else:
    try:
        with p.open('r', encoding='utf-8-sig', newline='') as f:
            print(sum(1 for _ in csv.DictReader(f)))
    except Exception:
        print(0)
PY
}

status_line() {
  local status_json="$1"
  python3 - "$status_json" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1])
if not p.is_file():
    print('상태 파일 없음')
else:
    try:
        d=json.loads(p.read_text(encoding='utf-8'))
        print(f"[{int(d.get('percent',0)):3d}%] {d.get('stage','')} / {d.get('status','')} — {d.get('message','')}")
    except Exception as e:
        print(f'상태 파일 읽기 오류: {e}')
PY
}

iso_info() {
  python3 - "$ROOT" <<'PY'
import json, sys
from pathlib import Path
root=Path(sys.argv[1])
report=root/'workspace/reports/galmuri14_v5_build_977.json'
fallback=root/'workspace/build/prinny_korean_galmuri14_v5_977.iso'
iso=fallback
if report.is_file():
    try:
        d=json.loads(report.read_text(encoding='utf-8-sig'))
        val=(d.get('outputs') or {}).get('iso')
        if val:
            iso=Path(val)
    except Exception:
        pass
if iso.is_file():
    st=iso.stat()
    from datetime import datetime
    print(f'{iso} | {st.st_size/1024/1024:.1f} MiB | {datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")}')
else:
    print(f'없음: {iso}')
PY
}

while :; do
  REPORT_DIR="$(find_report_dir)"
  QA_DIR="$ROOT/workspace/reports/prinny_qa"
  STATUS_JSON="$REPORT_DIR/status.json"
  PROGRESS_TXT="$REPORT_DIR/progress.txt"
  PID_FILE="$ROOT/workspace/reports/psp_toolkit_launcher/background.pid"
  LATEST_LOG="$REPORT_DIR/latest.log"
  [[ -e "$LATEST_LOG" ]] || LATEST_LOG="$(find "$REPORT_DIR" -maxdepth 1 -type f -name 'run_*.log' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-)"

  clear
  echo "================================================================================"
  echo " PSP TOOLKIT 실시간 현황                                  $(date '+%Y-%m-%d %H:%M:%S')"
  echo "================================================================================"
  echo "프로젝트 : $ROOT"
  echo "보고서   : $REPORT_DIR"
  echo

  running="아니오"
  pid=""
  if [[ -f "$PID_FILE" ]]; then
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      running="예 (PID $pid)"
    fi
  fi
  echo "백그라운드 실행 중 : $running"
  echo "현재 단계          : $(status_line "$STATUS_JSON")"
  if [[ -f "$PROGRESS_TXT" ]]; then
    echo "진행 파일          : $(tr '\n' ' ' < "$PROGRESS_TXT")"
  fi
  echo

  safe_count="$(count_csv_rows "$QA_DIR/safe_fixes_applied.csv")"
  review_count="$(count_csv_rows "$QA_DIR/review_queue.csv")"
  uncovered_count="$(count_csv_rows "$QA_DIR/uncovered_candidates.csv")"
  screenshot_todo="$(python3 - "$QA_DIR/screenshot_findings.csv" <<'PY'
import csv, sys
from pathlib import Path
p=Path(sys.argv[1])
count=0
if p.is_file():
    with p.open('r', encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if (r.get('review_status') or '').strip().lower() != 'done':
                count += 1
print(count)
PY
)"
  exe_candidates="$(count_csv_rows "$REPORT_DIR/game1_executable_strings/strings.csv")"

  echo "[프리니 1 수정/검수 현황]"
  echo "  자동 안전 수정 반영       : ${safe_count}건"
  echo "  START 미번역 검토 대기    : ${uncovered_count}건"
  echo "  전체 검토 대기열          : ${review_count}건"
  echo "  스크린샷 오류 미완료      : ${screenshot_todo}장"
  echo "  BOOT/UI 일본어 후보       : ${exe_candidates}건"
  echo "  V5 ISO                    : $(iso_info)"
  echo

  game2="$(python3 - "$ROOT" <<'PY'
import json, sys
from pathlib import Path
root=Path(sys.argv[1]); c=root/'.psp_toolkit_storage.json'
if c.is_file():
    try:
        print(json.loads(c.read_text(encoding='utf-8')).get('game2_iso',''))
    except Exception: print('')
else: print('')
PY
)"
  if [[ -n "$game2" && -f "$game2" ]]; then
    echo "프리니 2 ISO        : 준비됨 — $game2"
  elif [[ -n "$game2" ]]; then
    echo "프리니 2 ISO        : 없음 — $game2"
  else
    echo "프리니 2 ISO        : 저장장치 설정에서 경로를 찾지 못함"
  fi
  echo

  if [[ -d "$REPORT_DIR" ]]; then
    echo "[저장 공간]"
    df -h "$REPORT_DIR" 2>/dev/null | tail -n 1 || true
    echo
  fi

  echo "[최근 로그 마지막 18줄]"
  echo "--------------------------------------------------------------------------------"
  if [[ -n "$LATEST_LOG" && -f "$LATEST_LOG" ]]; then
    tail -n 18 "$LATEST_LOG"
  else
    echo "실행 로그가 아직 없습니다."
  fi
  echo "--------------------------------------------------------------------------------"
  echo "새로고침: ${REFRESH}초 | 이 현황창만 닫으려면 Ctrl+C"
  sleep "$REFRESH"
done
