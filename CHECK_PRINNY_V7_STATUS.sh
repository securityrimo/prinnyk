#!/usr/bin/env bash
set -u

DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
STATUS="$DRIVE/PSP_Localization_Work/reports/prinny_v7_compatibility/status.json"

while true; do
    clear
    python3 - "$STATUS" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
print("PRINNY 1 / PRINNY 2 V7.0 · 실시간 현황")
print("=" * 82)

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

        labels = [
            ("실행 상태", data.get("status", "")),
            ("진행률", f"[{bar}] {progress}%"),
            ("현재 단계", data.get("stage", "")),
            ("세부 내용", data.get("detail", "")),
            ("갱신 시각", data.get("updated_at", "")),
            ("PID", data.get("pid", "")),
        ]
        if data.get("grade"):
            labels.append(("호환 등급", data.get("grade")))
        if data.get("verdict"):
            labels.append(("판정", data.get("verdict")))
        if "simultaneous_localization_possible" in data:
            labels.append((
                "동시 진행",
                "가능" if data.get("simultaneous_localization_possible") else "전용 프로필 필요",
            ))
        if data.get("report_html"):
            labels.append(("HTML 보고서", data.get("report_html")))
        if data.get("report_json"):
            labels.append(("JSON 보고서", data.get("report_json")))
        if data.get("error"):
            labels.append(("오류", data.get("error")))

        for key, value in labels:
            print(f"{key:<11}: {value}")

        print("=" * 82)
        print("원본 ISO는 수정하지 않으며 최소 추출본은 분석 후 자동 정리됩니다.")
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
