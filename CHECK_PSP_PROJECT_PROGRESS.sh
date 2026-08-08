#!/usr/bin/env bash
set -u

PROJECT="${PROJECT:-$HOME/PrinnyReverseToolkit}"
DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
ROOT="$DRIVE/PSP_Localization_Work"
OUT="$ROOT/reports/project_progress"

while true; do
    python3 "$PROJECT/project_progress.py" \
        --project "$PROJECT" \
        --root "$ROOT" \
        --out "$OUT" >/dev/null 2>&1

    clear
    python3 - "$OUT/project_progress.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
print("PSP 한글화 · 전체 프로젝트 진행률")
print("=" * 94)

if not path.is_file():
    print("전체 진행률 계산을 기다리는 중입니다.")
else:
    data = json.loads(path.read_text(encoding="utf-8"))
    overall = float(data.get("overall_progress", 0))
    blocks = 46
    filled = max(0, min(blocks, round(overall * blocks / 100)))
    bar = "█" * filled + "░" * (blocks - filled)

    print(f"전체 진행률       : [{bar}] {overall:.1f}%")
    print("가중치            : 프리니 1 60% · 프리니 2 25% · 통합툴 15%")
    print("-" * 94)

    for key in ("prinny1", "prinny2", "studio"):
        project = data["projects"][key]
        print(
            f"{project['priority']}순위 {project['name']:<19}: "
            f"{project['progress']:>5.1f}%  "
            f"다음 → {project['next_milestone']}"
        )

    current = data.get("current_task", {})
    print("-" * 94)
    if current:
        print(
            "현재 작업         : "
            f"{current.get('detail', '')}"
        )
        print(
            "현재 작업 자체율   : "
            f"{current.get('task_progress', 0)}% "
            "(전체 진행률과 별도)"
        )
    else:
        print("현재 작업         : 실행 중인 작업 없음")

    print("-" * 94)
    print("V7.6의 18/18은 자동 증거 후보 연결입니다.")
    print("Expected Write 원본 재검증과 실제 빌드·게임 검수 전에는 완료로 보지 않습니다.")
    print(f"갱신 시각         : {data.get('updated_at', '')}")
    print(f"HTML 보고서       : {path.parent / 'index.html'}")
    print("=" * 94)

    p1 = data["projects"]["prinny1"]
    print("\n프리니 1 세부 마일스톤")
    for item in p1["milestones"]:
        mark = "✓" if item["completion"] >= 1 else "△" if item["completion"] > 0 else "·"
        print(
            f" {mark} {item['label']:<30} "
            f"{item['completion'] * 100:>5.1f}%"
        )
PY
    sleep 3
done
