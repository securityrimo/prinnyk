#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent
PLAN_SCRIPT = REPO / "prinny1_v7_14_8_prologue_repair_plan.py"
BUILD_SCRIPT = REPO / "prinny1_v7_14_minimum_test_iso.py"
PLAN_DIR = REPO / "workspace/reports/prinny1_v7_14_8_prologue_repair_plan"
BUILD_DIR = REPO / "workspace/build/prinny1_v7_14_9_prologue_full_punctuation"
REPORT_DIR = REPO / "workspace/reports/prinny1_v7_14_9_iso_build"
ISO = BUILD_DIR / "prinny_korean_v7_14_9_prologue_full_punctuation_28.iso"
FAILED_SPACING_REPORT = (
    REPO / "workspace/reports/prinny1_v7_14_10_spacing_patch/all_report.json"
)
NEXT_PLAN_REPORT = (
    REPO
    / "workspace/reports/prinny1_v7_14_11_speaker_ligature_plan/all_report.json"
)
BASE_ISO = Path(
    "/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd/"
    "PSP_Localization_Work/build/prinny_stage1_hotfix_v6_2/"
    "prinny_korean_stage1_hotfix_v6_2_977.iso"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> int:
    return subprocess.run(command, cwd=REPO, check=False).returncode


def status() -> int:
    print("Prinny 1 V7.14.9 상태 (V7.14.10 자간 후보 제외)")
    print("=" * 48)
    print(f"저장소 : {REPO}")
    print(f"계획   : {PLAN_DIR / 'all_report.json'}")
    print(f"보고서 : {REPORT_DIR / 'all_report.json'}")
    print(f"ISO    : {ISO}")
    if ISO.is_file():
        print(f"SHA256 : {sha256_file(ISO)}")
    else:
        print("ISO 상태: 아직 생성되지 않음")
    return 0


def plan() -> int:
    return run([sys.executable, str(PLAN_SCRIPT)])


def resume() -> int:
    result = status()
    print("\n재부팅 후 이어서 할 지점")
    print("=" * 48)
    print("완료    : V7.14.9 프롤로그 문장·이름 데이터 28개 반영")
    print("제외    : V7.14.10 전역 자간 후보 (런타임 실패)")
    print("다음    : V7.14.11 이름 전용 `대원` 결합 글리프 런타임 시험")
    print(f"실패보고: {FAILED_SPACING_REPORT}")
    print(f"다음계획: {NEXT_PLAN_REPORT}")
    print("원본·기존 ISO는 수정하지 않음")
    return result


def build() -> int:
    print("V6.2 기준 새 ISO에 확정 Expected Write 28개를 적용합니다.")
    answer = input("계속하려면 BUILD를 입력하세요: ").strip()
    if answer != "BUILD":
        print("취소했습니다.")
        return 1
    return run(
        [
            sys.executable,
            str(BUILD_SCRIPT),
            "--base-iso",
            str(BASE_ISO),
            "--v7134",
            str(PLAN_DIR),
            "--output",
            str(BUILD_DIR),
            "--report",
            str(REPORT_DIR),
            "--output-name",
            ISO.name,
            "--allow-iso-build",
        ]
    )


def ppsspp() -> int:
    if not ISO.is_file():
        print(f"ISO가 없습니다: {ISO}")
        return 2
    return run(
        [
            "flatpak",
            "run",
            "--command=PPSSPPSDL",
            "org.ppsspp.PPSSPP",
            str(ISO),
        ]
    )


def interactive() -> int:
    actions = {
        "1": ("재부팅 후 작업 이어보기", resume),
        "2": ("현재 상태·ISO 해시", status),
        "3": ("Expected Write 계획 재검증", plan),
        "4": ("안정 V7.14.9 ISO 다시 빌드", build),
        "5": ("PPSSPP로 안정 V7.14.9 실행", ppsspp),
        "0": ("종료", lambda: 0),
    }
    while True:
        print("\nPrinny Reverse Toolkit CLI")
        for key, (label, _action) in actions.items():
            print(f"  {key}. {label}")
        selected = input("선택: ").strip()
        if selected not in actions:
            print("잘못된 선택입니다.")
            continue
        if selected == "0":
            return 0
        result = actions[selected][1]()
        print(f"종료 코드: {result}")


def continue_work() -> int:
    resume()
    return interactive()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        nargs="?",
        choices=("continue", "resume", "status", "plan", "build", "ppsspp"),
    )
    arguments = parser.parse_args()
    if arguments.command is None:
        return interactive()
    return {
        "continue": continue_work,
        "resume": resume,
        "status": status,
        "plan": plan,
        "build": build,
        "ppsspp": ppsspp,
    }[arguments.command]()


if __name__ == "__main__":
    raise SystemExit(main())
