#!/usr/bin/env bash
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
ROOT="$DRIVE/PSP_Localization_Work"
OUT="$ROOT/reports/prinny1_v7_6_evidence_link"
RUN="$ROOT/work/prinny1_v7_6_evidence_link"
STATUS="$OUT/status.json"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$OUT/run_$STAMP.log"

mkdir -p "$OUT" "$RUN"
rm -f "$STATUS"

nohup python3 -u "$PROJECT/prinny1_v7_6_evidence_link.py" \
    --project "$PROJECT" \
    --work-root "$ROOT" \
    --game "$ROOT/inputs/game.iso" \
    --queue "$ROOT/reports/prinny_v7_4_confirmation/prinny1_runtime_evidence_queue.csv" \
    --run-dir "$RUN" \
    --out "$OUT" \
    --status-file "$STATUS" \
    >"$LOG" 2>&1 &

PID=$!
printf '%s\n' "$PID" > "$OUT/worker.pid"

echo "PRINNY 1 V7.6 실제 증거 연결을 시작했습니다."
echo "PID    : $PID"
echo "로그   : $LOG"
echo "보고서 : $OUT/index.html"

if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="PRINNY 1 V7.6" -- \
        bash "$PROJECT/CHECK_PRINNY1_V7_6_STATUS.sh" "$DRIVE" >/dev/null 2>&1 &
elif command -v mate-terminal >/dev/null 2>&1; then
    mate-terminal --title="PRINNY 1 V7.6" \
        -e "bash '$PROJECT/CHECK_PRINNY1_V7_6_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
elif command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="PRINNY 1 V7.6" \
        --command="bash '$PROJECT/CHECK_PRINNY1_V7_6_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
elif command -v konsole >/dev/null 2>&1; then
    konsole --new-tab -p tabtitle="PRINNY 1 V7.6" \
        -e bash "$PROJECT/CHECK_PRINNY1_V7_6_STATUS.sh" "$DRIVE" >/dev/null 2>&1 &
else
    echo "현황 확인: bash '$PROJECT/CHECK_PRINNY1_V7_6_STATUS.sh' '$DRIVE'"
fi
