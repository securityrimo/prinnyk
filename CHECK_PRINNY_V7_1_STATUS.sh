#!/usr/bin/env bash
set -u

DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
STATUS="$DRIVE/PSP_Localization_Work/reports/prinny_v7_1_parallel/status.json"

while true; do
    clear
    python3 - "$STATUS" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
print("PRINNY V7.1.2 · 프리니 1 수정 + 프리니 2 전용 프로필")
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
        items = [
            ("실행 상태", data.get("status", "")),
            ("진행률", f"[{bar}] {progress}%"),
            ("현재 단계", data.get("stage", "")),
            ("세부 내용", data.get("detail", "")),
            ("갱신 시각", data.get("updated_at", "")),
            ("PID", data.get("pid", "")),
        ]
        optional = [
            ("START 자원", "start_resources"),
            ("프리니 2 후보", "prinny2_catalog_entries"),
            ("프리니 2 후보 자원", "prinny2_catalog_resources"),
            ("폰트 위치", "font_location"),
            ("프리니 1 오류 큐", "prinny1_issue_queue"),
            ("HTML 보고서", "report_html"),
            ("번역 CSV", "catalog_csv"),
            ("전용 프로필", "profile_json"),
            ("폰트 탐색 보고서", "font_discovery_json"),
            ("오류", "error"),
        ]
        for label, key in optional:
            if key in data and data.get(key) not in ("", None):
                items.append((label, data.get(key)))
        if "parallel_development_possible" in data:
            items.append((
                "병행 진행",
                "가능" if data.get("parallel_development_possible") else "추가 연구 필요",
            ))
        for label, value in items:
            print(f"{label:<16}: {value}")
        print("=" * 92)
        print("폰트 위치 미확정은 발견 단계의 보류 항목이며 START/번역 후보 추출을 중단하지 않습니다.")
        print("프리니 1 대사 문구와 캐릭터 말투는 변경하지 않습니다.")
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
