#!/usr/bin/env bash
set -u
PROJECT="${1:-$HOME/PrinnyReverseToolkit}"
REPORT_DIR="$PROJECT/workspace/reports/prinny_stage1_fix"
PID_FILE="$REPORT_DIR/worker.pid"
mkdir -p "$REPORT_DIR"

if [ ! -f "$PROJECT/build_prinny_stage1_v6.py" ]; then
    echo "[오류] 빌드 스크립트 없음: $PROJECT/build_prinny_stage1_v6.py"
    return 0 2>/dev/null || true
fi

if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "이미 작업 중입니다. PID=$OLD_PID"
        RUNNING_PID="$OLD_PID"
    else
        rm -f "$PID_FILE"
    fi
fi

if [ ! -f "$PID_FILE" ]; then
    TS="$(date +%Y%m%d_%H%M%S)"
    LOG="$REPORT_DIR/worker_${TS}.log"
    CMD=(python3 "$PROJECT/build_prinny_stage1_v6.py")
    if command -v systemd-inhibit >/dev/null 2>&1 && systemd-inhibit --list >/dev/null 2>&1; then
        nohup systemd-inhibit --what=sleep --why="Prinny Stage1 Korean patch V6.2 build" "${CMD[@]}" >"$LOG" 2>&1 &
    else
        nohup "${CMD[@]}" >"$LOG" 2>&1 &
    fi
    RUNNING_PID=$!
    printf '%s\n' "$RUNNING_PID" > "$PID_FILE"
    printf '%s\n' "$LOG" > "$REPORT_DIR/latest_log.txt"
    echo "프리니 1 보수적 수정 V6.2 작업을 시작했습니다. PID=$RUNNING_PID"
    echo "로그: $LOG"
fi

MONITOR=(bash "$PROJECT/WATCH_PRINNY_STAGE1_FIX.sh" "$PROJECT")
if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="프리니 1 수정 진행률" -- "${MONITOR[@]}" >/dev/null 2>&1 &
elif command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="프리니 1 수정 진행률" --command="bash '$PROJECT/WATCH_PRINNY_STAGE1_FIX.sh' '$PROJECT'" >/dev/null 2>&1 &
elif command -v konsole >/dev/null 2>&1; then
    konsole --new-tab -p tabtitle="프리니 1 수정 진행률" -e "${MONITOR[@]}" >/dev/null 2>&1 &
elif command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator -T "프리니 1 수정 진행률" -e "${MONITOR[@]}" >/dev/null 2>&1 &
else
    echo "새 터미널을 자동으로 열 수 없어 현재 터미널에서 현황을 표시합니다."
    "${MONITOR[@]}"
fi

echo "현황창을 닫아도 PID $RUNNING_PID 작업은 계속됩니다."
