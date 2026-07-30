#!/usr/bin/env bash
set -u

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
WORK_ROOT="$DRIVE/PSP_Localization_Work"
INPUT="$WORK_ROOT/inputs"
RUN_DIR="$WORK_ROOT/work/prinny_v7_compatibility"
REPORT_DIR="$WORK_ROOT/reports/prinny_v7_compatibility"
STATUS="$REPORT_DIR/status.json"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$REPORT_DIR/run_$STAMP.log"

mkdir -p "$RUN_DIR" "$REPORT_DIR"
rm -f "$STATUS"

nohup python3 -u "$PROJECT/prinny_v7_compatibility.py" \
    --game1 "$INPUT/game.iso" \
    --game2 "$INPUT/game2.iso" \
    --run-dir "$RUN_DIR" \
    --report-dir "$REPORT_DIR" \
    --status-file "$STATUS" \
    >"$LOG" 2>&1 &

PID=$!
printf '%s\n' "$PID" > "$REPORT_DIR/worker.pid"

echo "PRINNY V7.0 분석을 시작했습니다."
echo "PID    : $PID"
echo "로그   : $LOG"
echo "보고서 : $REPORT_DIR/index.html"

MONITOR=(bash "$PROJECT/CHECK_PRINNY_V7_STATUS.sh" "$DRIVE")
if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="PRINNY V7.0 호환성" -- "${MONITOR[@]}" >/dev/null 2>&1 &
elif command -v mate-terminal >/dev/null 2>&1; then
    mate-terminal --title="PRINNY V7.0 호환성" -e "bash '$PROJECT/CHECK_PRINNY_V7_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
elif command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="PRINNY V7.0 호환성" --command="bash '$PROJECT/CHECK_PRINNY_V7_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
elif command -v konsole >/dev/null 2>&1; then
    konsole --new-tab -p tabtitle="PRINNY V7.0 호환성" -e bash "$PROJECT/CHECK_PRINNY_V7_STATUS.sh" "$DRIVE" >/dev/null 2>&1 &
else
    echo "별도 터미널을 자동으로 열 수 없습니다."
    echo "현황 확인: bash '$PROJECT/CHECK_PRINNY_V7_STATUS.sh' '$DRIVE'"
fi
