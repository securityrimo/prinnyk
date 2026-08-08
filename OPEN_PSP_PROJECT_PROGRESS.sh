#!/usr/bin/env bash
set -euo pipefail

PROJECT="${PROJECT:-$HOME/PrinnyReverseToolkit}"
DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
ROOT="$DRIVE/PSP_Localization_Work"
OUT="$ROOT/reports/project_progress"

python3 "$PROJECT/project_progress.py" \
    --project "$PROJECT" \
    --root "$ROOT" \
    --out "$OUT"

if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$OUT/index.html" >/dev/null 2>&1 &
fi

bash "$PROJECT/CHECK_PSP_PROJECT_PROGRESS.sh" "$DRIVE"
