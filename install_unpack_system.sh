#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${1:-$HOME/PrinnyReverseToolkit}"
PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_ROOT="$PROJECT_ROOT/.unpack_system_backup_$STAMP"
INSTALLED=0

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

restore_on_failure() {
    local status=$?
    if [ "$status" -ne 0 ] && [ "$INSTALLED" -eq 0 ]; then
        printf '\n설치 실패. 백업을 복원합니다.\n' >&2
        if [ -f "$BACKUP_ROOT/toolkit.py" ]; then
            cp "$BACKUP_ROOT/toolkit.py" "$PROJECT_ROOT/toolkit.py"
        fi

        if [ -f "$BACKUP_ROOT/core/system_unpack.py" ]; then
            cp "$BACKUP_ROOT/core/system_unpack.py" \
                "$PROJECT_ROOT/core/system_unpack.py"
        else
            rm -f "$PROJECT_ROOT/core/system_unpack.py"
        fi

        if [ -f "$BACKUP_ROOT/tests/test_system_unpack.py" ]; then
            cp "$BACKUP_ROOT/tests/test_system_unpack.py" \
                "$PROJECT_ROOT/tests/test_system_unpack.py"
        else
            rm -f "$PROJECT_ROOT/tests/test_system_unpack.py"
        fi
    fi
}
trap restore_on_failure EXIT

[ -d "$PROJECT_ROOT" ] || fail "프로젝트 폴더 없음: $PROJECT_ROOT"
[ -f "$PROJECT_ROOT/toolkit.py" ] || fail "toolkit.py 없음"
[ -f "$PROJECT_ROOT/core/nispack.py" ] || fail "core/nispack.py 없음"
[ -f "$PROJECT_ROOT/core/lzs.py" ] || fail "core/lzs.py 없음"
[ -f "$PROJECT_ROOT/core/start_runtime.py" ] || fail "core/start_runtime.py 없음"
[ -f "$PACKAGE_ROOT/core/system_unpack.py" ] || fail "패키지 모듈 없음"
[ -f "$PACKAGE_ROOT/tests/test_system_unpack.py" ] || fail "패키지 테스트 없음"

mkdir -p "$BACKUP_ROOT/core" "$BACKUP_ROOT/tests"
cp "$PROJECT_ROOT/toolkit.py" "$BACKUP_ROOT/toolkit.py"
[ ! -f "$PROJECT_ROOT/core/system_unpack.py" ] || \
    cp "$PROJECT_ROOT/core/system_unpack.py" "$BACKUP_ROOT/core/system_unpack.py"
[ ! -f "$PROJECT_ROOT/tests/test_system_unpack.py" ] || \
    cp "$PROJECT_ROOT/tests/test_system_unpack.py" "$BACKUP_ROOT/tests/test_system_unpack.py"

mkdir -p "$PROJECT_ROOT/core" "$PROJECT_ROOT/tests"
cp "$PACKAGE_ROOT/core/system_unpack.py" "$PROJECT_ROOT/core/system_unpack.py"
cp "$PACKAGE_ROOT/tests/test_system_unpack.py" "$PROJECT_ROOT/tests/test_system_unpack.py"

python3 - "$PROJECT_ROOT/toolkit.py" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

import_block = '''from core.system_unpack import (
    DEFAULT_MANIFEST as DEFAULT_SYSTEM_MANIFEST,
    DEFAULT_OUTPUT as DEFAULT_SYSTEM_OUTPUT,
    DEFAULT_SYSTEM,
    run_unpack as run_system_unpack,
)
'''

start_import_anchor = '''from core.start_runtime import (
    DEFAULT_MANIFEST as DEFAULT_START_MANIFEST,
    DEFAULT_OUTPUT as DEFAULT_START_OUTPUT,
    DEFAULT_START,
    StartRuntimeError,
    run_extract as run_start_extract,
)
'''

if "from core.system_unpack import (" not in text:
    if text.count(start_import_anchor) != 1:
        raise SystemExit(
            "toolkit.py의 start_runtime import 위치를 "
            "정확히 찾지 못했습니다."
        )
    text = text.replace(
        start_import_anchor,
        start_import_anchor + import_block,
        1,
    )

parser_block = '''    unpack_system_parser = commands.add_parser(
        "unpack-system",
        help=(
            "SYSTEM.DAT에서 start.lzs를 추출하고 "
            "start.dat으로 압축 해제합니다."
        ),
    )
    unpack_system_parser.add_argument(
        "--system",
        type=Path,
        default=DEFAULT_SYSTEM,
        help=(
            "SYSTEM.DAT 경로 "
            f"(기본값: {DEFAULT_SYSTEM})"
        ),
    )
    unpack_system_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SYSTEM_OUTPUT,
        help=(
            "start.lzs/start.dat 출력 디렉터리 "
            f"(기본값: {DEFAULT_SYSTEM_OUTPUT})"
        ),
    )
    unpack_system_parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_SYSTEM_MANIFEST,
        help=(
            "manifest JSON 경로 "
            f"(기본값: {DEFAULT_SYSTEM_MANIFEST})"
        ),
    )
    unpack_system_parser.add_argument(
        "--force",
        action="store_true",
        help="기존 출력이 다를 때 덮어씁니다.",
    )
    unpack_system_parser.set_defaults(
        handler=run_unpack_system,
    )

'''

if '"unpack-system"' not in text:
    parser_anchor = "    font_parser = commands.add_parser(\n"
    if text.count(parser_anchor) != 1:
        raise SystemExit(
            "toolkit.py의 font parser 위치를 "
            "정확히 찾지 못했습니다."
        )
    text = text.replace(
        parser_anchor,
        parser_block + parser_anchor,
        1,
    )

handler_block = '''def run_unpack_system(
    args: argparse.Namespace,
) -> int:
    return run_system_unpack(
        args
    )


'''

if "def run_unpack_system(" not in text:
    handler_anchor = "def load_font_runtime(\n"
    if text.count(handler_anchor) != 1:
        raise SystemExit(
            "toolkit.py의 handler 위치를 "
            "정확히 찾지 못했습니다."
        )
    text = text.replace(
        handler_anchor,
        handler_block + handler_anchor,
        1,
    )

path.write_text(text, encoding="utf-8")
PY

cd "$PROJECT_ROOT"
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
find . -type f -name '*.pyc' -delete

printf '[1/3] 문법 검사\n'
python3 -m compileall -q toolkit.py core/system_unpack.py tests/test_system_unpack.py

printf '[2/3] 단위 테스트\n'
python3 -m unittest tests.test_system_unpack -v

printf '[3/3] CLI 확인\n'
HELP_OUTPUT="$(python3 toolkit.py -h)"
printf '%s\n' "$HELP_OUTPUT"
grep -q "unpack-system" <<< "$HELP_OUTPUT"

INSTALLED=1
printf '\n============================================================\n'
printf 'unpack-system 통합 완료\n'
printf '============================================================\n'
printf '프로젝트: %s\n' "$PROJECT_ROOT"
printf '백업:     %s\n' "$BACKUP_ROOT"
printf '\n실행:\n'
printf 'python3 toolkit.py unpack-system\n'
printf 'python3 toolkit.py unpack-start\n'
