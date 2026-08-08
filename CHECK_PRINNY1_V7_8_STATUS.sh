#!/usr/bin/env bash
set -u
DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
STATUS="$DRIVE/PSP_Localization_Work/reports/prinny1_v7_8_context_disambiguation/status.json"
while true; do
    clear
    python3 - "$STATUS" <<'PY'
import json, sys
from pathlib import Path
path=Path(sys.argv[1])
print("PRINNY 1 V7.8 · 스크린샷 문맥 전역 배정")
print("="*100)
if not path.is_file():
    print("상태 파일을 기다리는 중입니다.")
else:
    data=json.loads(path.read_text(encoding="utf-8"))
    progress=int(data.get("progress",0))
    filled=round(progress*42/100)
    bar="█"*filled+"░"*(42-filled)
    fields=[
        ("실행 상태",data.get("status","")),
        ("현재 작업 자체율",f"[{bar}] {progress}%"),
        ("현재 단계",data.get("stage","")),
        ("세부 내용",data.get("detail","")),
        ("강한 문맥",data.get("context_strong","")),
        ("임시 문맥",data.get("context_provisional","")),
        ("모호",data.get("context_ambiguous","")),
        ("미배정/충돌",data.get("unassigned_or_conflict","")),
        ("확정 Expected Write",data.get("expected_write_candidates_confirmed","")),
        ("HTML 보고서",data.get("report_html","")),
        ("배정 CSV",data.get("assignment_csv","")),
        ("오류",data.get("error","")),
    ]
    for label,value in fields:
        if value not in ("",None):
            print(f"{label:<25}: {value}")
    print("="*100)
    print("스크린샷 문맥을 사용하지만 Expected Write는 아직 자동 확정하지 않습니다.")
    if data.get("status") in {"complete","error"}:
        print("\n작업이 종료되었습니다. Ctrl+C로 창을 닫으세요.")
        sys.exit(10)
PY
    rc=$?
    if [ "$rc" -eq 10 ]; then break; fi
    sleep 2
done
while true; do sleep 3600; done
