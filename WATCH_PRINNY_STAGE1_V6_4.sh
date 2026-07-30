#!/usr/bin/env bash
set -u
PROJECT="${1:-$HOME/PrinnyReverseToolkit}"
STATUS="$PROJECT/workspace/reports/prinny_stage1_fix/status_v6_4.json"
PROGRESS="$PROJECT/workspace/reports/prinny_stage1_fix/progress_v6_4.json"
PID_FILE="$PROJECT/workspace/reports/prinny_stage1_fix/worker_v6_4.pid"

render() {
python3 - "$STATUS" "$PROGRESS" "$PID_FILE" <<'PY'
import json, os, sys
from pathlib import Path

def read(path):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception: return {}

s=read(sys.argv[1]); p=read(sys.argv[2])
pid=None
try: pid=int(Path(sys.argv[3]).read_text().strip())
except Exception: pid=s.get('pid') or p.get('pid')
running=False
if pid:
    try: os.kill(int(pid),0); running=True
    except OSError: pass
percent=int(p.get('percent',0) or 0)
width=42
filled=max(0,min(width,round(width*percent/100)))
bar='█'*filled+'░'*(width-filled)
print('PRINNY 1 STAGE 1 TWO-BYTE REPAIR V6.4 · 실시간 현황')
print('='*78)
print(f"실행 상태 : {'작업 중' if running else s.get('status',p.get('status','대기'))}")
print(f"진행률    : [{bar}] {percent:3d}%")
print(f"현재 단계 : {p.get('stage','아직 시작되지 않음')}")
print(f"세부 내용 : {p.get('detail','-')}")
print(f"갱신 시각 : {p.get('updated_at','-')}")
if pid: print(f"PID       : {pid}")
if s.get('iso'): print(f"결과 ISO  : {s['iso']}")
if s.get('report'): print(f"보고서    : {s['report']}")
if s.get('target_count') is not None: print(f"대상 대사 : {s['target_count']}개")
if s.get('changed_count') is not None: print(f"실제 변경 : {s['changed_count']}개 영역")
if s.get('mechanical_adjustment_count') is not None: print(f"기계 조정 : {s['mechanical_adjustment_count']}개 (말투 재번역 아님)")
if s.get('unresolved_ui_group_count') is not None: print(f"UI 후속   : {s['unresolved_ui_group_count']}개 그룹")
if s.get('error'): print(f"오류      : {s['error']}")
print('='*78)
print('V6.4는 ASCII 1바이트 공백·문장부호·숫자를 2바이트 전각 코드로 바꿉니다.')
print('실제 변경이 0개면 성공으로 가장하지 않고 오류로 중단합니다.')
print('Ctrl+C로 현황창만 닫아도 백그라운드 빌드는 계속됩니다.')
print('__RUNNING__='+('1' if running else '0'))
print('__STATUS__='+str(s.get('status',p.get('status',''))))
PY
}

last=""
while true; do
    output="$(render)"
    running="$(printf '%s\n' "$output" | sed -n 's/^__RUNNING__=//p')"
    status="$(printf '%s\n' "$output" | sed -n 's/^__STATUS__=//p')"
    visible="$(printf '%s\n' "$output" | grep -v '^__RUNNING__=' | grep -v '^__STATUS__=')"
    if [ "$visible" != "$last" ]; then
        clear 2>/dev/null || true
        printf '%s\n' "$visible"
        last="$visible"
    fi
    if [ "$running" = "0" ] && { [ "$status" = "complete" ] || [ "$status" = "error" ]; }; then
        echo
        echo "작업이 종료되었습니다. 이 창은 20초 뒤 자동으로 닫힙니다."
        sleep 20
        break
    fi
    sleep 2
done
