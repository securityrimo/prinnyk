#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
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


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-report",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports/prinny1_v7_14_3_iso_build"
            / "all_report.json"
        ),
    )
    parser.add_argument(
        "--boot-log",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports/prinny1_v7_14_3_iso_build"
            / "ppsspp_boot.log"
        ),
    )
    parser.add_argument(
        "--glyph-report",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports"
            / "prinny1_v7_14_4_postbuild_glyph_validation"
            / "all_report.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports"
            / "prinny1_v7_14_5_runtime_boot"
        ),
    )
    arguments = parser.parse_args()

    build_path = arguments.build_report.expanduser().resolve()
    log_path = arguments.boot_log.expanduser().resolve()
    glyph_path = arguments.glyph_report.expanduser().resolve()
    output = arguments.output.expanduser().resolve()

    for required in (build_path, log_path, glyph_path):
        if not required.is_file():
            raise FileNotFoundError(f"필수 입력이 없습니다: {required}")

    build = json.loads(build_path.read_text(encoding="utf-8"))
    glyph = json.loads(glyph_path.read_text(encoding="utf-8"))
    log = log_path.read_text(encoding="utf-8", errors="replace")
    output_iso = Path(build.get("output_iso", {}).get("path", "")).resolve()

    if not output_iso.is_file():
        raise FileNotFoundError(f"빌드 ISO가 없습니다: {output_iso}")

    version_match = re.search(r"PPSSPP v([0-9.]+)", log)
    boot_lines = [
        line
        for line in log.splitlines()
        if " Booted " in line and str(output_iso) in line
    ]
    fatal_markers = [
        marker
        for marker in (
            "Failed to identify file",
            "Could not load executable",
            "Invalid or corrupted ISO",
            "Unhandled exception",
        )
        if marker.casefold() in log.casefold()
    ]

    checks: dict[str, bool] = {
        "build_report_pass": (
            build.get("status") == "build_pass_runtime_test_required"
        ),
        "build_fresh_reextract_pass": (
            build.get("fresh_reextract_verification") == "pass"
        ),
        "build_seven_zip_pass": build.get("seven_zip_test") == "pass",
        "iso_hash_matches_build_report": (
            sha256_file(output_iso)
            == build.get("output_iso", {}).get("sha256")
        ),
        "postbuild_font_lineage_pass": (
            glyph.get("conclusion")
            == "runtime_font_mapping_and_glyphs_valid"
            and bool(glyph.get("all_glyphs_match"))
        ),
        "ppsspp_version_detected": version_match is not None,
        "ppsspp_boot_marker_detected": len(boot_lines) == 1,
        "fatal_boot_marker_absent": not fatal_markers,
    }
    boot_pass = all(checks.values())
    status = (
        "boot_pass_target_scene_visual_qa_required"
        if boot_pass
        else "boot_validation_failed"
    )
    row: dict[str, Any] = {
        "created_at": now(),
        "output_iso": str(output_iso),
        "output_iso_sha256": sha256_file(output_iso),
        "ppsspp_version": (
            version_match.group(1) if version_match else ""
        ),
        "ppsspp_boot_status": "pass" if boot_pass else "fail",
        "boot_marker_count": len(boot_lines),
        "fatal_boot_markers": "|".join(fatal_markers),
        "postbuild_font_status": glyph.get("conclusion", ""),
        "target_scene_visual_status": "not_run_no_save_state",
        "status": status,
        "next_action": (
            "세이브 상태 또는 수동 조작으로 Demo00.dat+0x1E27 장면을 "
            "표시하고 문구와 마침표 렌더링을 화면 확인합니다."
        ),
    }

    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "runtime_boot_validation.csv"
    json_path = output / "all_report.json"
    write_csv(csv_path, [row], list(row.keys()))
    write_json(
        json_path,
        {
            "format": "prinny1_v7_14_5_runtime_boot_report_v1",
            **row,
            "checks": checks,
            "boot_log": {
                "path": str(log_path),
                "sha256": sha256_file(log_path),
                "line_count": len(log.splitlines()),
                "boot_line": boot_lines[0] if boot_lines else "",
            },
            "build_report": {
                "path": str(build_path),
                "sha256": sha256_file(build_path),
            },
            "postbuild_glyph_report": {
                "path": str(glyph_path),
                "sha256": sha256_file(glyph_path),
            },
        },
    )

    print(f"PPSSPP 버전            : {row['ppsspp_version']}")
    print(f"부팅 판정              : {row['ppsspp_boot_status']}")
    print(f"사후 폰트 판정         : {row['postbuild_font_status']}")
    print(f"대상 장면 화면 QA      : {row['target_scene_visual_status']}")
    print(f"최종 상태              : {status}")

    return 0 if boot_pass else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
