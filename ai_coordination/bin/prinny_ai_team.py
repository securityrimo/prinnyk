#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_REPO = Path.home() / "PrinnyReverseToolkit"
DEFAULT_WORK_ROOT = Path(
    "/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd"
) / "PSP_Localization_Work"

OFFICIAL_REMOTE = {
    "https://github.com/sizz1214-lang/prinnyk",
    "https://github.com/sizz1214-lang/prinnyk.git",
    "git@github.com:sizz1214-lang/prinnyk.git",
}

FORBIDDEN_PATTERNS = (
    re.compile(r"(^|/)(workspace|reports|build)(/|$)", re.I),
    re.compile(r"\.(iso|cso)$", re.I),
    re.compile(r"(^|/)(game|game2)\.iso$", re.I),
    re.compile(r"(^|/)\.env($|/)", re.I),
    re.compile(r"(token|secret|api[_-]?key|credential)", re.I),
)

VERDICT_RE = re.compile(
    r"FINAL_VERDICT\s*:\s*(PASS|WARNING|BLOCKER)",
    re.I,
)

ACTIVE_REVIEWERS: tuple[str, ...] = ()


def stamp() -> str:
    return dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def run_command(
    command: list[str],
    *,
    cwd: Path,
    stdin_text: str | None = None,
    timeout_seconds: int = 2700,
) -> dict[str, Any]:
    started = dt.datetime.now().astimezone().isoformat()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            input=stdin_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
            env=os.environ.copy(),
        )
        return {
            "command": command,
            "started_at": started,
            "returncode": completed.returncode,
            "output": completed.stdout,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return {
            "command": command,
            "started_at": started,
            "returncode": 124,
            "output": output + "\n[TIMEOUT]\n",
            "timed_out": True,
        }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_policy(repo: Path) -> str:
    path = repo / "ai_coordination/policies/PRINNY_TEAM_POLICY.md"
    if not path.is_file():
        raise FileNotFoundError(f"정책 파일이 없습니다: {path}")
    return path.read_text(encoding="utf-8")


def ensure_tools() -> dict[str, str]:
    paths: dict[str, str] = {}
    missing: list[str] = []
    for name in ("codex", *ACTIVE_REVIEWERS, "git"):
        found = shutil.which(name)
        if found:
            paths[name] = found
        else:
            missing.append(name)
    if missing:
        raise RuntimeError("필수 명령이 없습니다: " + ", ".join(missing))
    return paths


def smoke_test(
    tools: dict[str, str],
    repo: Path,
    work_root: Path,
    run_dir: Path,
) -> dict[str, Any]:
    tests = {
        "codex": run_command(
            [
                tools["codex"],
                "exec",
                "-C",
                str(repo),
                "-s",
                "read-only",
                "응답을 정확히 CODEX_READY 한 줄로만 출력하라. "
                "파일과 명령은 사용하지 마라.",
            ],
            cwd=repo,
            timeout_seconds=300,
        ),
    }
    write_json(run_dir / "01_SMOKE_TEST.json", tests)

    expected = {
        "codex": "CODEX_READY",
    }
    failures: list[str] = []
    for name, result in tests.items():
        if (
            result["returncode"] != 0
            or expected[name] not in result["output"]
        ):
            failures.append(name)

    if failures:
        raise RuntimeError(
            "AI 인증 또는 비대화형 실행 검사 실패: "
            + ", ".join(failures)
            + f"\n상세: {run_dir / '01_SMOKE_TEST.json'}"
        )
    return tests


def git_capture(
    tools: dict[str, str],
    repo: Path,
    run_dir: Path,
    prefix: str,
) -> None:
    commands = {
        "status": [tools["git"], "status", "--short", "--branch"],
        "diff": [tools["git"], "diff", "--"],
        "diff_stat": [tools["git"], "diff", "--stat", "--"],
        "log": [tools["git"], "log", "--oneline", "-10"],
    }
    for name, command in commands.items():
        result = run_command(command, cwd=repo, timeout_seconds=120)
        write_text(
            run_dir / f"{prefix}_{name.upper()}.txt",
            result["output"],
        )


def codex_run(
    tools: dict[str, str],
    repo: Path,
    reports: Path,
    prompt: str,
    run_dir: Path,
    filename: str,
    *,
    read_only: bool,
) -> dict[str, Any]:
    command = [
        tools["codex"],
        "exec",
        "-C",
        str(repo),
        "-s",
        "read-only" if read_only else "workspace-write",
    ]
    if not read_only:
        command.extend(["--add-dir", str(reports)])
    command.append("-")
    result = run_command(
        command,
        cwd=repo,
        stdin_text=prompt,
        timeout_seconds=3600,
    )
    write_text(run_dir / filename, result["output"])
    write_json(run_dir / (filename + ".meta.json"), result)
    return result


def reviewer_prompt(
    reviewer_name: str,
    policy: str,
    task: str,
    run_dir: Path,
    phase: str,
) -> str:
    return f"""당신은 {reviewer_name}이며 Prinny 프로젝트의 읽기 전용 검토자다.

아래 공통 정책을 최우선으로 적용한다.

----- POLICY -----
{policy}
----- END POLICY -----

원래 작업:
----- TASK -----
{task}
----- END TASK -----

검토 단계: {phase}

다음 자료를 읽어 독립 검토한다.
- 저장소의 현재 코드
- {run_dir / '10_CODEX_IMPLEMENTATION.txt'}
- {run_dir / '11_GIT_DIFF.txt'}
- 존재한다면 {run_dir / '30_CODEX_REVISION.txt'}
- 존재한다면 {run_dir / '31_GIT_DIFF_AFTER_REVISION.txt'}

검토 항목:
1. 작업 목표를 실제로 구현했는가
2. 원본 ISO나 기존 ISO를 변경했는가
3. 미확정 후보를 패치 가능 상태로 승격했는가
4. 바이너리 경계, 종료, 패딩, 슬롯, 오프셋 검증이 충분한가
5. 번역 문구나 캐릭터 말투를 자동 변경했는가
6. 회귀·예외·테스트 누락이 있는가
7. Git 금지 파일 또는 비밀정보 위험이 있는가
8. 보고된 증거 단계가 실제 결과와 일치하는가

파일을 수정하지 말고 검토 결과만 출력한다.
구체적인 파일과 근거를 제시한다.
답변 마지막에는 아래 셋 중 정확히 하나를 한 줄로 출력한다.

FINAL_VERDICT: PASS
FINAL_VERDICT: WARNING
FINAL_VERDICT: BLOCKER
"""


def run_reviewers(
    tools: dict[str, str],
    repo: Path,
    reports: Path,
    run_dir: Path,
    policy: str,
    task: str,
    phase: str,
    prefix: str,
) -> dict[str, dict[str, Any]]:
    # 사용자가 Claude와 Gemini를 모두 제외하도록 지시했다. 인자는 향후
    # 보고서 형식 호환성을 위해 유지하지만 외부 프로세스는 실행하지 않는다.
    return {}


def verdict(result: dict[str, Any]) -> str:
    if result.get("returncode") != 0:
        return "BLOCKER"
    match = VERDICT_RE.search(result.get("output", ""))
    if not match:
        return "BLOCKER"
    return match.group(1).upper()


def changed_files(tools: dict[str, str], repo: Path) -> list[str]:
    result = run_command(
        [tools["git"], "status", "--porcelain"],
        cwd=repo,
        timeout_seconds=120,
    )
    files: list[str] = []
    for line in result["output"].splitlines():
        if len(line) >= 4:
            files.append(line[3:])
    return files


def forbidden_files(files: list[str]) -> list[str]:
    bad: list[str] = []
    for name in files:
        normalized = name.replace("\\", "/")
        if any(pattern.search(normalized) for pattern in FORBIDDEN_PATTERNS):
            bad.append(name)
    return bad


def compile_changed_python(
    tools: dict[str, str],
    repo: Path,
    files: list[str],
    run_dir: Path,
) -> bool:
    python_files = [
        repo / name
        for name in files
        if name.endswith(".py") and (repo / name).is_file()
    ]
    if not python_files:
        write_text(run_dir / "50_PY_COMPILE.txt", "변경 Python 파일 없음\n")
        return True
    result = run_command(
        [
            sys.executable,
            "-m",
            "py_compile",
            *[str(path) for path in python_files],
        ],
        cwd=repo,
        timeout_seconds=300,
    )
    write_text(run_dir / "50_PY_COMPILE.txt", result["output"])
    return result["returncode"] == 0


def remote_ok(tools: dict[str, str], repo: Path) -> tuple[bool, str]:
    result = run_command(
        [tools["git"], "remote", "get-url", "origin"],
        cwd=repo,
        timeout_seconds=60,
    )
    remote = result["output"].strip()
    return remote in OFFICIAL_REMOTE, remote


def checkpoint(
    tools: dict[str, str],
    repo: Path,
    run_dir: Path,
    version: str,
    files: list[str],
) -> dict[str, Any]:
    ok, remote = remote_ok(tools, repo)
    if not ok:
        raise RuntimeError(f"공식 origin이 아닙니다: {remote}")

    bad = forbidden_files(files)
    if bad:
        raise RuntimeError(
            "Git 금지 파일이 변경 목록에 있습니다: " + ", ".join(bad)
        )

    add_result = run_command(
        [tools["git"], "add", "--", *files],
        cwd=repo,
        timeout_seconds=120,
    )
    if add_result["returncode"] != 0:
        raise RuntimeError("git add 실패:\n" + add_result["output"])

    staged = run_command(
        [tools["git"], "diff", "--cached", "--name-only"],
        cwd=repo,
        timeout_seconds=120,
    )
    staged_files = [
        line.strip()
        for line in staged["output"].splitlines()
        if line.strip()
    ]
    staged_bad = forbidden_files(staged_files)
    if staged_bad:
        run_command(
            [tools["git"], "restore", "--staged", "--", *staged_files],
            cwd=repo,
            timeout_seconds=120,
        )
        raise RuntimeError(
            "스테이징 금지 파일 감지: " + ", ".join(staged_bad)
        )

    message = f"checkpoint: {version}"
    commit = run_command(
        [tools["git"], "commit", "-m", message],
        cwd=repo,
        timeout_seconds=300,
    )
    if commit["returncode"] != 0:
        raise RuntimeError("git commit 실패:\n" + commit["output"])

    commit_hash = run_command(
        [tools["git"], "rev-parse", "HEAD"],
        cwd=repo,
        timeout_seconds=60,
    )["output"].strip()

    tag_created = False
    tag_result: dict[str, Any] | None = None
    if re.fullmatch(r"v?\d+\.(0|5)(?:\.\d+)?", version):
        tag = version if version.startswith("v") else "v" + version
        existing = run_command(
            [tools["git"], "tag", "--list", tag],
            cwd=repo,
            timeout_seconds=60,
        )["output"].strip()
        if existing:
            raise RuntimeError(f"태그가 이미 존재합니다: {tag}")
        tag_result = run_command(
            [tools["git"], "tag", tag],
            cwd=repo,
            timeout_seconds=60,
        )
        if tag_result["returncode"] != 0:
            raise RuntimeError("태그 생성 실패:\n" + tag_result["output"])
        tag_created = True

    push_main = run_command(
        [tools["git"], "push", "origin", "HEAD:main"],
        cwd=repo,
        timeout_seconds=600,
    )
    if push_main["returncode"] != 0:
        raise RuntimeError("origin/main push 실패:\n" + push_main["output"])

    push_tag = None
    if tag_created:
        tag = version if version.startswith("v") else "v" + version
        push_tag = run_command(
            [tools["git"], "push", "origin", tag],
            cwd=repo,
            timeout_seconds=600,
        )
        if push_tag["returncode"] != 0:
            raise RuntimeError("태그 push 실패:\n" + push_tag["output"])

    result = {
        "remote": remote,
        "commit": commit_hash,
        "message": message,
        "files": staged_files,
        "tag_created": tag_created,
        "push_main": push_main,
        "push_tag": push_tag,
    }
    write_json(run_dir / "70_CHECKPOINT.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prinny Codex 단독 작업 오케스트레이터"
    )
    parser.add_argument("lane", choices=("p1", "p2", "studio"))
    parser.add_argument("task_file", type=Path)
    parser.add_argument(
        "--repo", type=Path, default=DEFAULT_REPO
    )
    parser.add_argument(
        "--work-root", type=Path, default=DEFAULT_WORK_ROOT
    )
    parser.add_argument(
        "--checkpoint",
        default="",
        help="정상 완료 후 체크포인트 버전. 예: v8.0",
    )
    parser.add_argument(
        "--skip-smoke-test",
        action="store_true",
    )
    args = parser.parse_args()

    repo = args.repo.expanduser().resolve()
    work_root = args.work_root.expanduser().resolve()
    reports = work_root / "reports"
    task_file = args.task_file.expanduser().resolve()

    if not (repo / ".git").exists():
        raise RuntimeError(f"Git 저장소가 아닙니다: {repo}")
    if not task_file.is_file():
        raise FileNotFoundError(f"작업 파일이 없습니다: {task_file}")
    reports.mkdir(parents=True, exist_ok=True)

    run_dir = repo / "ai_coordination/runs" / (
        f"{stamp()}_{args.lane}"
    )
    run_dir.mkdir(parents=True, exist_ok=False)

    tools = ensure_tools()
    policy = load_policy(repo)
    task = task_file.read_text(encoding="utf-8")
    write_text(run_dir / "00_TASK.md", task)
    write_text(run_dir / "00_POLICY.md", policy)
    write_json(
        run_dir / "00_CONTEXT.json",
        {
            "lane": args.lane,
            "repo": str(repo),
            "work_root": str(work_root),
            "reports": str(reports),
            "checkpoint": args.checkpoint,
            "tools": tools,
        },
    )

    print(f"실행 폴더: {run_dir}")
    print("[1/7] CLI 및 인증 확인")
    if not args.skip_smoke_test:
        smoke_test(tools, repo, work_root, run_dir)

    print("[2/7] 작업 전 Git 상태 저장")
    git_capture(tools, repo, run_dir, "02_BEFORE")

    lane_mode = {
        "p1": "Prinny 1 활성 구현 작업",
        "p2": "Prinny 2 읽기 전용 분석 작업",
        "studio": "PSP 종합 도구 읽기 전용 분석 작업",
    }[args.lane]
    read_only = args.lane != "p1"

    implementation_prompt = f"""아래 공통 정책과 작업을 수행하라.

----- POLICY -----
{policy}
----- END POLICY -----

작업 레인: {lane_mode}

----- TASK -----
{task}
----- END TASK -----

지시:
- 계획만 보고하고 멈추지 마라.
- 관련 파일과 최신 보고서를 읽고 실제 작업을 수행하라.
- 안전한 범위에서 코드를 구현 또는 수정하고 검증하라.
- 기존 사용자 변경을 되돌리지 마라.
- ISO를 생성, 수정, 삭제, 이동하지 마라.
- 번역 문구와 캐릭터 말투를 변경하지 마라.
- p2와 studio 레인에서는 파일을 수정하지 말고 분석 보고만 하라.
- 실행 명령, 변경 파일, 테스트, 증거 수준, 남은 차단 사유를 기록하라.
- 새 ISO 생성이 필요해지면 구현을 멈추고 승인 필요 상태로 보고하라.
"""

    print("[3/7] Codex 메인 작업")
    implementation = codex_run(
        tools,
        repo,
        reports,
        implementation_prompt,
        run_dir,
        "10_CODEX_IMPLEMENTATION.txt",
        read_only=read_only,
    )
    if implementation["returncode"] != 0:
        raise RuntimeError(
            "Codex 메인 작업 실패. "
            f"상세: {run_dir / '10_CODEX_IMPLEMENTATION.txt'}"
        )

    git_capture(tools, repo, run_dir, "11_GIT")

    print("[4/7] 외부 AI 검토 생략 (사용자 지시)")
    first_reviews = run_reviewers(
        tools,
        repo,
        reports,
        run_dir,
        policy,
        task,
        "1차 검토",
        "20",
    )
    first_verdicts = {
        name: verdict(result)
        for name, result in first_reviews.items()
    }
    write_json(run_dir / "20_VERDICTS.json", first_verdicts)

    need_revision = any(
        value in {"BLOCKER", "WARNING"}
        for value in first_verdicts.values()
    )

    if need_revision and not read_only:
        print("[5/7] Codex 검토 반영 수정")
        review_output = "\n\n".join(
            f"{name} 검토:\n{result['output']}"
            for name, result in first_reviews.items()
        )
        revision_prompt = f"""아래 작업의 구현 결과를 외부 검토자가 검토했다.

----- POLICY -----
{policy}
----- END POLICY -----

----- TASK -----
{task}
----- END TASK -----

{review_output}

지시:
- 검토의 구체적 근거를 확인한다.
- 타당한 BLOCKER와 WARNING을 최소 변경으로 해결한다.
- 반영하지 않는 의견은 근거를 명시한다.
- 관련 테스트를 다시 실행한다.
- ISO는 생성하거나 수정하지 않는다.
- 번역 문구와 캐릭터 말투는 변경하지 않는다.
"""
        revision = codex_run(
            tools,
            repo,
            reports,
            revision_prompt,
            run_dir,
            "30_CODEX_REVISION.txt",
            read_only=False,
        )
        if revision["returncode"] != 0:
            raise RuntimeError(
                "Codex 수정 단계 실패. "
                f"상세: {run_dir / '30_CODEX_REVISION.txt'}"
            )
        git_capture(tools, repo, run_dir, "31_GIT_DIFF_AFTER_REVISION")
    else:
        write_text(
            run_dir / "30_CODEX_REVISION.txt",
            "수정 단계 없음\n",
        )

    print("[6/7] Codex 최종 로컬 검증")
    final_reviews = run_reviewers(
        tools,
        repo,
        reports,
        run_dir,
        policy,
        task,
        "최종 검토",
        "40_FINAL",
    )
    final_verdicts = {
        name: verdict(result)
        for name, result in final_reviews.items()
    }
    write_json(run_dir / "40_FINAL_VERDICTS.json", final_verdicts)

    files = changed_files(tools, repo)
    bad_files = forbidden_files(files)
    py_compile_ok = compile_changed_python(
        tools, repo, files, run_dir
    )
    has_blocker = any(
        value == "BLOCKER"
        for value in final_verdicts.values()
    )

    summary = {
        "lane": args.lane,
        "run_dir": str(run_dir),
        "first_verdicts": first_verdicts,
        "final_verdicts": final_verdicts,
        "changed_files": files,
        "forbidden_files": bad_files,
        "python_compile_ok": py_compile_ok,
        "checkpoint_requested": args.checkpoint,
        "checkpoint_performed": False,
        "status": "PASS",
    }

    if has_blocker:
        summary["status"] = "BLOCKED_BY_REVIEW"
    elif bad_files:
        summary["status"] = "BLOCKED_FORBIDDEN_FILES"
    elif not py_compile_ok:
        summary["status"] = "BLOCKED_PY_COMPILE"

    if args.checkpoint:
        if read_only:
            summary["status"] = "BLOCKED_READ_ONLY_LANE_CHECKPOINT"
        elif summary["status"] == "PASS":
            print("[7/7] GitHub 체크포인트")
            cp_result = checkpoint(
                tools,
                repo,
                run_dir,
                args.checkpoint,
                files,
            )
            summary["checkpoint_performed"] = True
            summary["checkpoint_result"] = cp_result
        else:
            print("[7/7] 체크포인트 차단")
    else:
        print("[7/7] 체크포인트 요청 없음")

    write_json(run_dir / "90_SUMMARY.json", summary)

    print()
    print("완료")
    print(f"상태             : {summary['status']}")
    print(f"1차 판정         : {first_verdicts}")
    print(f"최종 판정        : {final_verdicts}")
    print(f"변경 파일        : {len(files)}")
    print(f"금지 파일        : {len(bad_files)}")
    print(f"Python 문법 검사 : {py_compile_ok}")
    print(f"체크포인트       : {summary['checkpoint_performed']}")
    print(f"결과 폴더        : {run_dir}")
    print(f"요약 JSON        : {run_dir / '90_SUMMARY.json'}")

    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        raise SystemExit(2)
