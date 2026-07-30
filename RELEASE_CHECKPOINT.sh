#!/usr/bin/env bash
set -u

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${1:-}"

if [ -z "$VERSION" ]; then
    echo "사용법: bash RELEASE_CHECKPOINT.sh <버전> [--no-push]"
    echo "예: bash RELEASE_CHECKPOINT.sh 6.5"
else
    shift
    python3 "$PROJECT/scripts/github_checkpoint.py" "$VERSION" "$@"
fi
