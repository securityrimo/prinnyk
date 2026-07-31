#!/usr/bin/env bash
set -u

DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
STATUS="$DRIVE/PSP_Localization_Work/reports/prinny_v7_3_font_and_editor/status.json"

while true; do
    clear
    python3 - "$STATUS" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
print("PRINNY V7.3 · 프리니 2 폰트 증거 검증 + 번역 편집기")
print("=" * 94)
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
            ("폰트 후보", "font_candidates"),
            ("높은 우선순위", "high_priority_fonts"),
            ("중간 우선순위", "medium_priority_fonts"),
            ("번역 묶음", "translation_batch"),
            ("폰트 증거 CSV", "font_evidence_csv"),
            ("번역 CSV", "translation_batch_csv"),
            ("번역 편집기", "translation_editor_html"),
            ("HTML 보고서", "report_html"),
            ("오류", "error"),
        ]
        for label, key in optional:
            if key in data and data.get(key) not in ("", None):
                fields.append((label, data.get(key)))
        for label, value in fields:
            print(f"{label:<17}: {value}")
        print("=" * 94)
        print("폰트 후보는 실행 파일 연결 근거까지 검증하기 전에는 패치 대상으로 확정하지 않습니다.")
        print("번역 편집기는 번역 자료만 내보내며 게임 데이터에 자동 적용하지 않습니다.")
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
