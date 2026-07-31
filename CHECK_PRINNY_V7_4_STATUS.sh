#!/usr/bin/env bash
set -u

DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
STATUS="$DRIVE/PSP_Localization_Work/reports/prinny_v7_4_confirmation/status.json"

while true; do
    clear
    python3 - "$STATUS" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
print("PRINNY V7.4 · 폰트 시각 확인 + 번역 문맥 + 프리니 1 증거 큐")
print("=" * 96)
if not path.is_file():
    print("상태 파일을 기다리는 중입니다.")
else:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"상태 읽기 오류: {error}")
    else:
        progress = int(data.get("progress", 0))
        blocks = 42
        filled = max(0, min(blocks, round(progress * blocks / 100)))
        bar = "█" * filled + "░" * (blocks - filled)
        fields = [
            ("실행 상태", data.get("status", "")),
            ("진행률", f"[{bar}] {progress}%"),
            ("현재 단계", data.get("stage", "")),
            ("세부 내용", data.get("detail", "")),
            ("갱신 시각", data.get("updated_at", "")),
            ("PID", data.get("pid", "")),
        ]
        optional = [
            ("고우선 폰트", "high_priority_fonts"),
            ("폰트 미리보기", "font_previews"),
            ("번역 묶음", "translation_batch"),
            ("문맥 연결", "context_linked"),
            ("안전 슬롯 연결", "safe_budget_linked"),
            ("프리니 1 오류", "prinny1_issues"),
            ("번역 편집기", "translation_editor_html"),
            ("폰트 미리보기 폴더", "font_preview_directory"),
            ("프리니 1 증거 큐", "prinny1_evidence_queue"),
            ("HTML 보고서", "report_html"),
            ("오류", "error"),
        ]
        for label, key in optional:
            if key in data and data.get(key) not in ("", None):
                fields.append((label, data.get(key)))
        for label, value in fields:
            print(f"{label:<19}: {value}")
        print("=" * 96)
        print("원문·번역문·ISO는 변경하지 않습니다.")
        print("폰트 미리보기는 후보 레이아웃 증거이며 실제 렌더러 확정이 아닙니다.")
        if data.get("status") in {"complete", "error"}:
            print("\n작업이 종료되었습니다. Ctrl+C로 창을 닫으세요.")
            sys.exit(10)
PY
    rc=$?
    if [ "$rc" -eq 10 ]; then
        break
    fi
    sleep 2
done
while true; do sleep 3600; done
