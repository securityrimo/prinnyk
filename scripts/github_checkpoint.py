#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

MAX_STAGED_BYTES = 90 * 1024 * 1024

EXCLUDED_DIR_NAMES = {
    ".git",
    "workspace",
    "output",
    "build",
    "dist",
    "PSP_GAME",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

BACKUP_PREFIXES = (
    ".psp_toolkit_update_backup_",
    ".prinny_stage1_fix_backup_",
    ".prinny_stage1_v6_",
    ".policy_checkpoint_backup_",
    ".checkpoint_repair_backup_",
)

FORBIDDEN_PATTERNS = (
    re.compile(r"(^|/)(game2?\.iso)$", re.I),
    re.compile(r"\.(iso|cso|run)$", re.I),
    re.compile(r"(^|/)(workspace|output|build|dist|PSP_GAME)/", re.I),
)


class CheckpointError(RuntimeError):
    pass


def run(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()
        raise CheckpointError(f"{' '.join(args)} 실패: {detail}")
    return process


def normalize_version(raw: str) -> tuple[str, Decimal]:
    value = raw.strip().lower()
    if value.startswith("v"):
        value = value[1:]
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise CheckpointError(f"버전 형식이 올바르지 않습니다: {raw}")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise CheckpointError(f"버전을 해석하지 못했습니다: {raw}") from exc

    normalized = format(number, "f")
    if "." not in normalized:
        normalized += ".0"
    return normalized, number


def is_half_step(number: Decimal) -> bool:
    doubled = number * Decimal("2")
    return doubled == doubled.to_integral_value()


def path_is_backup(path: str) -> bool:
    parts = Path(path.replace("\\", "/")).parts
    return any(
        part.startswith(BACKUP_PREFIXES)
        or (part.startswith(".") and "_backup_" in part)
        for part in parts
    )


def path_is_excluded(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = Path(normalized).parts
    return (
        any(part in EXCLUDED_DIR_NAMES for part in parts)
        or path_is_backup(normalized)
        or any(pattern.search(normalized) for pattern in FORBIDDEN_PATTERNS)
    )


def ensure_gitignore(repo: Path) -> None:
    path = repo / ".gitignore"
    required = [
        "*.iso",
        "*.cso",
        "*.run",
        "*.zip",
        "game.iso",
        "game2.iso",
        "workspace/",
        "output/",
        "build/",
        "dist/",
        "PSP_GAME/",
        "__pycache__/",
        "*.pyc",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        ".psp_toolkit_update_backup_*/",
        ".prinny_stage1_fix_backup_*/",
        ".prinny_stage1_v6_*_backup_*/",
        ".policy_checkpoint_backup_*/",
        ".checkpoint_repair_backup_*/",
        ".env",
        "token",
    ]

    existing = (
        path.read_text(encoding="utf-8", errors="replace")
        if path.exists()
        else ""
    )
    lines = existing.splitlines()
    for item in required:
        if item not in lines:
            lines.append(item)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def null_list(process: subprocess.CompletedProcess[str]) -> list[str]:
    return [entry for entry in process.stdout.split("\0") if entry]


def staged_paths(repo: Path) -> list[str]:
    return null_list(
        run(["git", "diff", "--cached", "--name-only", "-z"], repo)
    )


def tracked_paths(repo: Path) -> list[str]:
    return null_list(run(["git", "ls-files", "-z"], repo))


def unstage_unsafe(repo: Path) -> list[str]:
    removed: list[str] = []
    for relative in staged_paths(repo):
        target = repo / relative
        size = target.stat().st_size if target.is_file() else 0
        if path_is_excluded(relative) or size > MAX_STAGED_BYTES:
            run(
                ["git", "reset", "-q", "HEAD", "--", relative],
                repo,
                check=False,
            )
            removed.append(relative)
    return removed


def compile_active_python(repo: Path) -> list[str]:
    candidates = set(tracked_paths(repo)) | set(staged_paths(repo))
    python_files = sorted(
        relative
        for relative in candidates
        if relative.endswith(".py")
        and not path_is_excluded(relative)
        and (repo / relative).is_file()
    )

    errors: list[str] = []
    for relative in python_files:
        try:
            py_compile.compile(
                str(repo / relative),
                doraise=True,
            )
        except py_compile.PyCompileError as exc:
            errors.append(f"{relative}: {exc.msg}")

    if errors:
        preview = "\n".join(f"  - {item}" for item in errors[:20])
        extra = (
            f"\n  ... 그 외 {len(errors) - 20}개"
            if len(errors) > 20
            else ""
        )
        raise CheckpointError(
            "활성 Python 소스 문법 검사 실패:\n"
            f"{preview}{extra}"
        )

    return python_files


def current_branch(repo: Path) -> str:
    branch = run(["git", "branch", "--show-current"], repo).stdout.strip()
    if not branch:
        raise CheckpointError("현재 브랜치를 확인할 수 없습니다.")
    return branch


def main() -> int:
    parser = argparse.ArgumentParser(
        description="0.5 단위 GitHub 소스 체크포인트"
    )
    parser.add_argument("version", help="예: 6.5 또는 v7.0")
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="로컬 커밋과 태그만 생성",
    )
    parser.add_argument(
        "--message",
        default="",
        help="추가 커밋 메시지",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    version, number = normalize_version(args.version)
    tag = f"v{version}"

    if not is_half_step(number):
        print(f"[건너뜀] {version}은 0.5 단위 체크포인트가 아닙니다.")
        return 0

    if not (repo / ".git").is_dir():
        raise CheckpointError(f"Git 저장소가 아닙니다: {repo}")

    ensure_gitignore(repo)

    remote = run(
        ["git", "remote", "get-url", "origin"],
        repo,
        check=False,
    )
    if remote.returncode != 0:
        raise CheckpointError("Git 원격 origin이 설정되지 않았습니다.")

    # 먼저 스테이징하고, 게임 데이터·산출물·백업을 즉시 제외한다.
    run(["git", "add", "-A"], repo)
    removed = unstage_unsafe(repo)
    for relative in removed:
        print(f"[보호] 스테이징 제외: {relative}")

    checked = compile_active_python(repo)
    print(f"[검사] 활성 Python 소스 {len(checked)}개 통과")

    diff_check = run(["git", "diff", "--cached", "--check"], repo, check=False)
    if diff_check.returncode != 0:
        raise CheckpointError(
            "스테이징된 변경의 공백/충돌 검사 실패: "
            + (diff_check.stdout or diff_check.stderr).strip()
        )

    staged = staged_paths(repo)
    if staged:
        message = f"checkpoint: v{version}"
        if args.message.strip():
            message += f" - {args.message.strip()}"
        run(["git", "commit", "-m", message], repo)
        print(f"[커밋] {message}")
    else:
        print("[커밋] 새로 기록할 소스 변경 없음")

    existing_tag = run(["git", "tag", "--list", tag], repo).stdout.strip()
    if existing_tag:
        tagged_commit = run(["git", "rev-list", "-n", "1", tag], repo).stdout.strip()
        head_commit = run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
        if tagged_commit != head_commit:
            raise CheckpointError(
                f"기존 태그 {tag}가 현재 HEAD와 다릅니다. "
                "태그를 자동 이동하지 않았습니다."
            )
        print(f"[태그] 현재 HEAD의 기존 태그 유지: {tag}")
    else:
        run(
            ["git", "tag", "-a", tag, "-m", f"Korean patch checkpoint {tag}"],
            repo,
        )
        print(f"[태그] {tag}")

    if args.no_push:
        print("[완료] 로컬 커밋과 태그를 생성했습니다.")
        return 0

    branch = current_branch(repo)
    branch_push = run(
        ["git", "push", "origin", branch],
        repo,
        check=False,
    )
    if branch_push.returncode != 0:
        raise CheckpointError(
            "브랜치 푸시 실패. 로컬 커밋과 태그는 유지했습니다: "
            + (branch_push.stderr or branch_push.stdout).strip()
        )

    tag_push = run(
        ["git", "push", "origin", tag],
        repo,
        check=False,
    )
    if tag_push.returncode != 0:
        raise CheckpointError(
            "태그 푸시 실패. 로컬 태그는 유지했습니다: "
            + (tag_push.stderr or tag_push.stdout).strip()
        )

    print(f"[완료] origin/{branch} 및 {tag}를 GitHub에 저장했습니다.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckpointError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        raise SystemExit(2)
