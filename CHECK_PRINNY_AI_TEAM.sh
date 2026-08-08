#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-$HOME/PrinnyReverseToolkit}"
WORK_ROOT="${2:-/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd/PSP_Localization_Work}"

cd "$REPO"

echo "===== 경로 ====="
printf 'codex  : '; command -v codex
printf 'gemini : '; command -v gemini
printf 'claude : '; command -v claude

echo
echo "===== 버전 ====="
codex --version
gemini --version
claude --version

echo
echo "===== 인증·비대화형 검사 ====="

codex exec \
  -C "$REPO" \
  -s read-only \
  "응답을 정확히 CODEX_READY 한 줄로만 출력하라. 파일과 명령은 사용하지 마라."

gemini \
  -p "응답을 정확히 GEMINI_READY 한 줄로만 출력하라. 파일과 도구는 사용하지 마라." \
  --approval-mode plan \
  --output-format text \
  --skip-trust \
  --include-directories "$WORK_ROOT/reports"

claude \
  -p "응답을 정확히 CLAUDE_READY 한 줄로만 출력하라. 파일과 도구는 사용하지 마라." \
  --permission-mode plan \
  --max-turns 1 \
  --output-format text \
  --add-dir "$WORK_ROOT/reports"

echo
echo "세 AI 실행 검사 완료"
