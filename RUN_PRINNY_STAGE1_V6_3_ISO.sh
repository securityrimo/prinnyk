#!/usr/bin/env bash
set -u
PROJECT="${1:-$HOME/PrinnyReverseToolkit}"
STATUS="$PROJECT/workspace/reports/prinny_stage1_fix/status.json"
ISO="$(python3 - "$STATUS" <<'PY'
import json,sys
from pathlib import Path
try:
 d=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
 print(d.get('iso',''))
except Exception: print('')
PY
)"
if [ -z "$ISO" ] || [ ! -f "$ISO" ]; then
    echo "[오류] 완성된 V6.3 ISO가 없습니다."
    return 0 2>/dev/null || true
fi
printf '실행 ISO: %s\n' "$ISO"
if command -v flatpak >/dev/null 2>&1 && flatpak info org.ppsspp.PPSSPP >/dev/null 2>&1; then
    flatpak run --filesystem="$(dirname "$ISO"):ro" org.ppsspp.PPSSPP --graphics=software "$ISO"
elif command -v ppsspp >/dev/null 2>&1; then
    ppsspp "$ISO"
elif command -v PPSSPPSDL >/dev/null 2>&1; then
    PPSSPPSDL "$ISO"
else
    echo "[오류] PPSSPP 실행 파일을 찾지 못했습니다."
fi
