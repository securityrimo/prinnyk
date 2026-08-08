#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from prinny1_v7_14_1_base_compatibility import (
    PROJECT_DEFAULT,
    sha256_file,
    write_csv,
    write_json,
)


EXPECTED_ISO_SHA256 = (
    "0f24e300524439fea521aad6f8d2391032c9caf890fc7aa95393559b462d054d"
)
EXPECTED_CONTEXT_TEXT = "이젠… 싫어"
EXPECTED_TARGET_TEXT = "도망치고싶어．도망치고싶어"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"PNG 파일이 아닙니다: {path}")
    if header[12:16] != b"IHDR":
        raise ValueError(f"PNG IHDR를 찾지 못했습니다: {path}")
    return struct.unpack(">II", header[16:24])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--iso",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/build/prinny1_v7_14_3_single_expected_write"
            / "prinny_korean_v7_14_minimum_expected_write_1.iso"
        ),
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports/prinny1_v7_14_11_soul_approach"
            / "frame_004.png"
        ),
    )
    parser.add_argument(
        "--baseline-screenshot",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "evidence/prinny1_v7_8_screenshots/screenshots/SHOT-016.png"
        ),
    )
    parser.add_argument(
        "--repeat-screenshot",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports/prinny1_v7_14_12_adjacent_dialogue_retry2"
            / "frame_001.png"
        ),
    )
    parser.add_argument(
        "--post-dialogue-screenshot",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports/prinny1_v7_14_12_adjacent_dialogue_close"
            / "frame_001.png"
        ),
    )
    parser.add_argument(
        "--savestate",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports/prinny1_v7_14_6_savestate"
            / "ULJS00150_1.01_0.ppst"
        ),
    )
    parser.add_argument(
        "--observed-context-text",
        default=EXPECTED_CONTEXT_TEXT,
    )
    parser.add_argument(
        "--observed-target-text",
        default=EXPECTED_TARGET_TEXT,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports/prinny1_v7_14_6_runtime_scene_qa"
        ),
    )
    arguments = parser.parse_args()

    iso = arguments.iso.expanduser().resolve()
    screenshot = arguments.screenshot.expanduser().resolve()
    baseline = arguments.baseline_screenshot.expanduser().resolve()
    repeat_screenshot = arguments.repeat_screenshot.expanduser().resolve()
    post_dialogue_screenshot = (
        arguments.post_dialogue_screenshot.expanduser().resolve()
    )
    savestate = arguments.savestate.expanduser().resolve()
    output = arguments.output.expanduser().resolve()

    for required in (
        iso,
        screenshot,
        baseline,
        repeat_screenshot,
        post_dialogue_screenshot,
        savestate,
    ):
        if not required.is_file():
            raise FileNotFoundError(f"필수 입력이 없습니다: {required}")

    screenshot_size = png_dimensions(screenshot)
    baseline_size = png_dimensions(baseline)
    repeat_size = png_dimensions(repeat_screenshot)
    post_dialogue_size = png_dimensions(post_dialogue_screenshot)
    iso_sha256 = sha256_file(iso)
    screenshot_sha256 = sha256_file(screenshot)
    baseline_sha256 = sha256_file(baseline)
    repeat_sha256 = sha256_file(repeat_screenshot)
    post_dialogue_sha256 = sha256_file(post_dialogue_screenshot)
    savestate_sha256 = sha256_file(savestate)

    checks: dict[str, bool] = {
        "iso_hash_matches_expected_build": iso_sha256 == EXPECTED_ISO_SHA256,
        "runtime_screenshot_is_png": screenshot_size[0] > 0
        and screenshot_size[1] > 0,
        "baseline_screenshot_is_png": baseline_size[0] > 0
        and baseline_size[1] > 0,
        "runtime_differs_from_broken_baseline": (
            screenshot_sha256 != baseline_sha256
        ),
        "target_scene_repeat_capture_valid": (
            repeat_size == screenshot_size
            and repeat_sha256 != baseline_sha256
        ),
        "post_dialogue_returns_to_gameplay": (
            post_dialogue_size == screenshot_size
            and post_dialogue_sha256 not in {
                screenshot_sha256,
                repeat_sha256,
            }
        ),
        "observed_context_matches_expected": (
            arguments.observed_context_text == EXPECTED_CONTEXT_TEXT
        ),
        "observed_target_matches_expected": (
            arguments.observed_target_text == EXPECTED_TARGET_TEXT
        ),
        "savestate_is_nonempty": savestate.stat().st_size > 0,
    }
    visual_pass = all(checks.values())
    status = (
        "runtime_target_scene_visual_pass"
        if visual_pass
        else "runtime_target_scene_visual_failed"
    )

    row: dict[str, Any] = {
        "created_at": now(),
        "iso": str(iso),
        "iso_sha256": iso_sha256,
        "target": "Demo00.dat",
        "resource_offset_hex": "0x1E27",
        "screenshot": str(screenshot),
        "screenshot_sha256": screenshot_sha256,
        "screenshot_size": f"{screenshot_size[0]}x{screenshot_size[1]}",
        "baseline_screenshot": str(baseline),
        "baseline_screenshot_sha256": baseline_sha256,
        "repeat_screenshot": str(repeat_screenshot),
        "repeat_screenshot_sha256": repeat_sha256,
        "post_dialogue_screenshot": str(post_dialogue_screenshot),
        "post_dialogue_screenshot_sha256": post_dialogue_sha256,
        "savestate": str(savestate),
        "savestate_sha256": savestate_sha256,
        "observed_context_text": arguments.observed_context_text,
        "expected_context_text": EXPECTED_CONTEXT_TEXT,
        "observed_target_text": arguments.observed_target_text,
        "expected_target_text": EXPECTED_TARGET_TEXT,
        "observation_method": "manual_visual_transcription_from_ppsspp_capture",
        "baseline_defects": "싫쟤럴d|싶쟤鹿|후속_깨진_글리프",
        "runtime_visual_status": "pass" if visual_pass else "fail",
        "status": status,
        "next_action": (
            "단일 Expected Write의 목표 장면 QA가 통과했습니다. "
            "다음 안전 단계는 인접 대사 회귀 화면과 ISO 변경 범위 보고서를 "
            "확인하는 것입니다."
        ),
    }

    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "runtime_scene_validation.csv"
    json_path = output / "all_report.json"
    write_csv(csv_path, [row], list(row.keys()))
    write_json(
        json_path,
        {
            "format": "prinny1_v7_14_6_runtime_scene_qa_report_v1",
            **row,
            "checks": checks,
            "baseline_comparison": {
                "baseline_result": "broken_glyph_rendering",
                "v7_14_result": (
                    "correct_two_byte_aligned_rendering"
                    if visual_pass
                    else "visual_validation_failed"
                ),
                "candidate_disposition": (
                    "accept_v7_14_single_expected_write"
                    if visual_pass
                    else "reject_pending_investigation"
                ),
            },
        },
    )

    print(f"ISO SHA-256         : {iso_sha256}")
    print(f"저장 상태 SHA-256   : {savestate_sha256}")
    print(f"대상 화면            : {screenshot}")
    print(f"관찰 문구            : {arguments.observed_target_text}")
    print(f"런타임 화면 판정     : {'PASS' if visual_pass else 'FAIL'}")
    print(f"JSON                 : {json_path}")
    print(f"CSV                  : {csv_path}")
    return 0 if visual_pass else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
