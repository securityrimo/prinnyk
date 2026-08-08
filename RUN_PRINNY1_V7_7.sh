#!/usr/bin/env bash
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
ROOT="$DRIVE/PSP_Localization_Work"
SOURCE="$ROOT/reports/prinny1_v7_6_evidence_link"
OUT="$ROOT/reports/prinny1_v7_7_duplicate_audit"
RUN="$ROOT/work/prinny1_v7_7_duplicate_audit"
STATUS="$OUT/status.json"
STAMP="$(date +%Y%m%d_%H%M%S)"
RUN_LOG="$OUT/run_$STAMP.log"

mkdir -p "$OUT" "$RUN"
rm -f "$STATUS"

nohup python3 -u "$PROJECT/prinny1_v7_7_duplicate_audit.py" \
    --game "$ROOT/inputs/game.iso" \
    --links "$SOURCE/prinny1_issue_evidence_links.csv" \
    --expected "$SOURCE/expected_write_candidates.csv" \
    --top-candidates "$SOURCE/top_candidates_by_issue.json" \
    --run-dir "$RUN" \
    --out "$OUT" \
    --status-file "$STATUS" \
    >"$RUN_LOG" 2>&1 &

PID=$!
printf '%s\n' "$PID" > "$OUT/worker.pid"

echo "PRINNY 1 V7.7 중복 감사 작업을 시작했습니다."
echo "PID    : $PID"
echo "로그   : $RUN_LOG"
echo "보고서 : $OUT/index.html"

if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="PRINNY 1 V7.7 중복 감사" -- \
        bash "$PROJECT/CHECK_PRINNY1_V7_7_STATUS.sh" "$DRIVE" >/dev/null 2>&1 &
elif command -v mate-terminal >/dev/null 2>&1; then
    mate-terminal --title="PRINNY 1 V7.7 중복 감사" \
        -e "bash '$PROJECT/CHECK_PRINNY1_V7_7_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
elif command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="PRINNY 1 V7.7 중복 감사" \
        --command="bash '$PROJECT/CHECK_PRINNY1_V7_7_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
else
    echo "현황 확인:"
    echo "bash '$PROJECT/CHECK_PRINNY1_V7_7_STATUS.sh' '$DRIVE'"
fi
