#!/usr/bin/env bash
set -u
PROJECT="${1:-$HOME/PrinnyReverseToolkit}"
LOCAL_STATUS="$PROJECT/workspace/reports/prinny_stage1_fix/status.json"
LOCAL_PROGRESS="$PROJECT/workspace/reports/prinny_stage1_fix/progress.json"
PID_FILE="$PROJECT/workspace/reports/prinny_stage1_fix/worker.pid"

render() {
python3 - "$LOCAL_STATUS" "$LOCAL_PROGRESS" "$PID_FILE" <<'PY'
import json, os, sys
from datetime import datetime
from pathlib import Path

status_path=Path(sys.argv[1]); progress_path=Path(sys.argv[2]); pid_path=Path(sys.argv[3])
def read(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return {}
s=read(status_path); p=read(progress_path)
pid=None
try:pid=int(pid_path.read_text().strip())
except Exception:pid=s.get('pid') or p.get('pid')
running=False
if pid:
    try:os.kill(int(pid),0); running=True
    except OSError:pass
percent=int(p.get('percent',0) or 0)
width=42
filled=max(0,min(width,round(width*percent/100)))
bar='█'*filled+'░'*(width-filled)
print('PRINNY 1 STAGE 1 FIX V6.2 · 실시간 현황')
print('='*72)
print(f"실행 상태 : {'작업 중' if running else s.get('status',p.get('status','대기'))}")
print(f"진행률    : [{bar}] {percent:3d}%")
print(f"현재 단계 : {p.get('stage','아직 시작되지 않음')}")
print(f"세부 내용 : {p.get('detail','-')}")
print(f"갱신 시각 : {p.get('updated_at','-')}")
if pid: print(f"PID       : {pid}")
if s.get('iso'): print(f"결과 ISO  : {s['iso']}")
if s.get('report'): print(f"보고서    : {s['report']}")
if s.get('fix_count') is not None: print(f"자동 수정 : {s['fix_count']}개")
if s.get('review_only_count') is not None: print(f"검토 대기 : {s['review_only_count']}개 (자동 적용 안 함)")
if s.get('unresolved_ui_group_count') is not None: print(f"UI 후속   : {s['unresolved_ui_group_count']}개 그룹")
if s.get('error'): print(f"오류      : {s['error']}")
print('='*72)
print('이 창은 실제 작업 상태 파일이 바뀔 때만 진행률이 변합니다.')
print('Ctrl+C로 현황창만 닫아도 백그라운드 빌드는 계속됩니다.')
print('__RUNNING__='+('1' if running else '0'))
print('__STATUS__='+str(s.get('status',p.get('status',''))))
PY
}

last=""
while true; do
    output="$(render)"
    marker_running="$(printf '%s\n' "$output" | sed -n 's/^__RUNNING__=//p')"
    marker_status="$(printf '%s\n' "$output" | sed -n 's/^__STATUS__=//p')"
    visible="$(printf '%s\n' "$output" | grep -v '^__RUNNING__=' | grep -v '^__STATUS__=')"
    if [ "$visible" != "$last" ]; then
        clear 2>/dev/null || true
        printf '%s\n' "$visible"
        last="$visible"
    fi
    if [ "$marker_running" = "0" ] && { [ "$marker_status" = "complete" ] || [ "$marker_status" = "error" ]; }; then
        echo
        echo "작업이 종료되었습니다. 이 창은 20초 뒤 자동으로 닫힙니다."
        sleep 20
        break
    fi
    sleep 2
done
