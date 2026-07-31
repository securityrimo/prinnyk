#!/usr/bin/env bash
set -u

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
ROOT="$DRIVE/PSP_Localization_Work"
OUT="$ROOT/reports/prinny_v7_1_parallel"
RUN="$ROOT/work/prinny_v7_1_parallel"
STATUS="$OUT/status.json"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$OUT/run_v7_1_2_$STAMP.log"

mkdir -p "$OUT" "$RUN"
rm -f "$STATUS"

nohup python3 -u "$PROJECT/prinny_parallel_v7_1_1.py" \
    --v7-report "$ROOT/reports/prinny_v7_compatibility/all_report.json" \
    --game2 "$ROOT/inputs/game2.iso" \
    --run-dir "$RUN" \
    --report-dir "$OUT" \
    --status-file "$STATUS" \
    >"$LOG" 2>&1 &

PID=$!
printf '%s\n' "$PID" > "$OUT/worker.pid"

echo "PRINNY V7.1.2 복구 작업을 시작했습니다."
echo "PID    : $PID"
echo "로그   : $LOG"
echo "보고서 : $OUT/index.html"

if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="PRINNY V7.1.2" -- \
        bash "$PROJECT/CHECK_PRINNY_V7_1_STATUS.sh" "$DRIVE" >/dev/null 2>&1 &
elif command -v mate-terminal >/dev/null 2>&1; then
    mate-terminal --title="PRINNY V7.1.2" \
        -e "bash '$PROJECT/CHECK_PRINNY_V7_1_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
elif command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="PRINNY V7.1.2" \
        --command="bash '$PROJECT/CHECK_PRINNY_V7_1_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
elif command -v konsole >/dev/null 2>&1; then
    konsole --new-tab -p tabtitle="PRINNY V7.1.2" \
        -e bash "$PROJECT/CHECK_PRINNY_V7_1_STATUS.sh" "$DRIVE" >/dev/null 2>&1 &
else
    echo "현황 확인: bash '$PROJECT/CHECK_PRINNY_V7_1_STATUS.sh' '$DRIVE'"
fi
