#!/usr/bin/env bash
set -u

DRIVE="${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
APP="$DRIVE/PSP_Localization_Work/reports/psp_localization_studio_v7_5/index.html"

if [ ! -f "$APP" ]; then
    echo "[오류] PSP Localization Studio V7.5를 찾지 못했습니다: $APP"
    exit 2
fi

if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$APP" >/dev/null 2>&1 &
elif command -v gio >/dev/null 2>&1; then
    gio open "$APP" >/dev/null 2>&1 &
else
    echo "브라우저 실행 명령을 찾지 못했습니다."
    echo "$APP"
fi
