#!/usr/bin/env bash
set -u

DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
STATUS="$DRIVE/PSP_Localization_Work/reports/prinny_v7_2_curation/status.json"

while true; do
    clear
    python3 - "$STATUS" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
print("PRINNY V7.2.1 · 프리니 2 번역 후보 정제 + 폰트 후보 분석")
print("=" * 92)

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
            ("원시 후보", "raw_candidates"),
            ("고유 문자열", "unique_strings"),
            ("번역 후보", "translate_candidates"),
            ("검토 후보", "review_candidates"),
            ("제외 후보", "rejected_candidates"),
            ("중복 발생", "duplicate_occurrences"),
            ("겹침 후보 쌍", "overlap_pairs"),
            ("폰트 후보", "font_candidates"),
            ("번역 CSV", "translation_memory"),
            ("검토 CSV", "review_queue"),
            ("폰트 순위", "font_ranking"),
            ("HTML 보고서", "report_html"),
            ("오류", "error"),
        ]
        for label, key in optional:
            if key in data and data.get(key) not in ("", None):
                fields.append((label, data.get(key)))

        for label, value in fields:
            print(f"{label:<16}: {value}")

        print("=" * 92)
        print("원문·번역문·캐릭터 말투를 변경하지 않고 후보를 분류만 합니다.")
        print("폰트 순위는 메타데이터 기반이며 실제 폰트 확정이 아닙니다.")

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
