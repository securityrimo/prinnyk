#!/usr/bin/env bash
set -u

echo "V7.6 작업 상태 대신 전체 프로젝트 진행률을 표시합니다."
echo "현재 작업 자체 진행률은 보조 정보로만 표시됩니다."
sleep 1

exec bash "$HOME/PrinnyReverseToolkit/CHECK_PSP_PROJECT_PROGRESS.sh" \
    "${1:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd}"
