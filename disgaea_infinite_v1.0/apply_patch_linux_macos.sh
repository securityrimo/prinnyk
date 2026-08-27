#!/bin/sh
set -eu

SOURCE_SHA256="32de3247bed3c78fdb66a9fe6d6a973ac808982d2472f569a90809135df9cce5"
OUTPUT_SHA256="234e9f3bfac930e88cabf779ccc33abe343b4061896634b960c3d3b8deb07f86"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PATCH="$SCRIPT_DIR/Disgaea_Infinite_ULJS00286_KR_v1.0.xdelta"

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "사용법: sh apply_patch_linux_macos.sh 원본.iso [출력.iso]" >&2
  exit 2
fi

SOURCE=$1
OUTPUT=${2:-"$SCRIPT_DIR/Disgaea_Infinite_ULJS00286_KR_v1.0.iso"}

if ! command -v xdelta3 >/dev/null 2>&1; then
  echo "오류: xdelta3가 설치되어 있지 않습니다." >&2
  exit 2
fi

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL_SOURCE=$(sha256sum "$SOURCE" | awk '{print $1}')
else
  ACTUAL_SOURCE=$(shasum -a 256 "$SOURCE" | awk '{print $1}')
fi

if [ "$ACTUAL_SOURCE" != "$SOURCE_SHA256" ]; then
  echo "오류: 지원하지 않는 원본 ISO입니다." >&2
  echo "예상: $SOURCE_SHA256" >&2
  echo "실제: $ACTUAL_SOURCE" >&2
  exit 1
fi

xdelta3 -d -s "$SOURCE" "$PATCH" "$OUTPUT"

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL_OUTPUT=$(sha256sum "$OUTPUT" | awk '{print $1}')
else
  ACTUAL_OUTPUT=$(shasum -a 256 "$OUTPUT" | awk '{print $1}')
fi

if [ "$ACTUAL_OUTPUT" != "$OUTPUT_SHA256" ]; then
  echo "오류: 결과 ISO 검증에 실패했습니다." >&2
  echo "예상: $OUTPUT_SHA256" >&2
  echo "실제: $ACTUAL_OUTPUT" >&2
  exit 1
fi

echo "완료: $OUTPUT"
echo "SHA-256: $ACTUAL_OUTPUT"
