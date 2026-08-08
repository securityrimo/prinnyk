#!/usr/bin/env bash
set -euo pipefail

REPO="${PRINNY_REPO:-$HOME/PrinnyReverseToolkit}"
ORCHESTRATOR="$REPO/ai_coordination/bin/prinny_ai_team.py"

if [ ! -f "$ORCHESTRATOR" ]; then
    echo "[오류] 오케스트레이터가 없습니다: $ORCHESTRATOR"
    exit 2
fi

exec python3 "$ORCHESTRATOR" "$@"
