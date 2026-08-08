#!/usr/bin/env bash
set -u

DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
STATUS="$DRIVE/PSP_Localization_Work/reports/prinny1_v7_7_duplicate_audit/status.json"

while true; do
    clear
    python3 - "$STATUS" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
print("PRINNY 1 V7.7 · 중복 매핑 무효화 + 동점 후보 재검증")
print("=" * 100)

if not path.is_file():
    print("상태 파일을 기다리는 중입니다.")
else:
    data = json.loads(path.read_text(encoding="utf-8"))
    progress = int(data.get("progress", 0))
    blocks = 42
    filled = max(0, min(blocks, round(progress * blocks / 100)))
    bar = "█" * filled + "░" * (blocks - filled)

    fields = [
        ("실행 상태", data.get("status", "")),
        ("현재 작업 자체율", f"[{bar}] {progress}%"),
        ("현재 단계", data.get("stage", "")),
        ("세부 내용", data.get("detail", "")),
        ("갱신 시각", data.get("updated_at", "")),
        ("PID", data.get("pid", "")),
    ]
    optional = [
        ("V7.6 고유 선택 위치", "v76_unique_selected_mappings"),
        ("무효화 이슈 링크", "invalidated_issue_links"),
        ("새 원본 일치 후보 행", "fresh_verified_candidate_rows"),
        ("독립 임시 후보", "independent_provisional_links"),
        ("확정 Expected Write", "expected_write_candidates_confirmed"),
        ("HTML 보고서", "report_html"),
        ("이슈 분리 CSV", "disambiguation_csv"),
        ("전체 후보 CSV", "candidate_matrix_csv"),
        ("오류", "error"),
    ]

    for label, key in optional:
        if key in data and data.get(key) not in ("", None):
            fields.append((label, data.get(key)))

    for label, value in fields:
        print(f"{label:<25}: {value}")

    print("=" * 100)
    print("V7.6의 18/18 표시는 무효입니다. 동점 첫 행을 자동 선택하지 않습니다.")
    print("프리니 1만 분석하며 ISO와 통합툴 HTML은 변경하지 않습니다.")

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
