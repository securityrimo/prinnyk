#!/usr/bin/env bash
set -u

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
ROOT="$DRIVE/PSP_Localization_Work"
SOURCE73="$ROOT/reports/prinny_v7_3_font_and_editor"
SOURCE72="$ROOT/reports/prinny_v7_2_curation"
SOURCE71="$ROOT/reports/prinny_v7_1_parallel"
OUT="$ROOT/reports/prinny_v7_4_confirmation"
STATUS="$OUT/status.json"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$OUT/run_$STAMP.log"

mkdir -p "$OUT"
rm -f "$STATUS"

ARGS=(
    --evidence "$SOURCE73/font_candidate_evidence.json"
    --blobs "$SOURCE73/font_candidate_blobs"
    --batch "$SOURCE73/prinny2_translation_batch_001.csv"
    --occurrences "$SOURCE72/occurrences_all.csv"
    --out "$OUT"
    --status-file "$STATUS"
)

if [ -f "$SOURCE71/prinny1_runtime_repair_queue.csv" ]; then
    ARGS+=(--prinny1-queue "$SOURCE71/prinny1_runtime_repair_queue.csv")
fi

nohup python3 -u "$PROJECT/prinny_v7_4_confirmation.py" \
    "${ARGS[@]}" >"$LOG" 2>&1 &

PID=$!
printf '%s\n' "$PID" > "$OUT/worker.pid"
echo "PRINNY V7.4 작업을 시작했습니다."
echo "PID    : $PID"
echo "로그   : $LOG"
echo "보고서 : $OUT/index.html"

if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="PRINNY V7.4" -- \
        bash "$PROJECT/CHECK_PRINNY_V7_4_STATUS.sh" "$DRIVE" >/dev/null 2>&1 &
elif command -v mate-terminal >/dev/null 2>&1; then
    mate-terminal --title="PRINNY V7.4" \
        -e "bash '$PROJECT/CHECK_PRINNY_V7_4_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
elif command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="PRINNY V7.4" \
        --command="bash '$PROJECT/CHECK_PRINNY_V7_4_STATUS.sh' '$DRIVE'" >/dev/null 2>&1 &
elif command -v konsole >/dev/null 2>&1; then
    konsole --new-tab -p tabtitle="PRINNY V7.4" \
        -e bash "$PROJECT/CHECK_PRINNY_V7_4_STATUS.sh" "$DRIVE" >/dev/null 2>&1 &
else
    echo "현황 확인: bash '$PROJECT/CHECK_PRINNY_V7_4_STATUS.sh' '$DRIVE'"
fi
