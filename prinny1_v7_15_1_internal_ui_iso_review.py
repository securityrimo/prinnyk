#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_1_internal_ui_iso import BASE_ISO, OUTPUT_ISO, REPORT_DIR as BUILD_REPORT_DIR
from prinny1_v7_15_1_internal_ui_plan import OUTPUT as RESOURCE_DIR, sha256_file


ROOT = Path(__file__).resolve().parent
BUILD_REPORT = BUILD_REPORT_DIR / "all_report.json"
PRE_REVIEW = ROOT / "workspace/reports/prinny1_v7_15_1_internal_ui_review/all_report.json"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_1_internal_ui_iso_review"


def main() -> int:
    for path in (BASE_ISO, OUTPUT_ISO, BUILD_REPORT, PRE_REVIEW, RESOURCE_DIR / "SYSTEM.DAT", RESOURCE_DIR / "start.dat"):
        if not path.is_file():
            raise FileNotFoundError(path)
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    pre = json.loads(PRE_REVIEW.read_text(encoding="utf-8"))
    if sha256_file(OUTPUT_ISO) != build["output_iso"]["sha256"]:
        raise ValueError("V7.15.1 ISO 보고 해시 불일치")
    if pre.get("final_verdict") != "PASS":
        raise ValueError("V7.15.1 자원 사전 검토 미통과")

    base_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_record = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    system_offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    system_end = system_offset + int(base_record["data_length"])
    if hash_range(BASE_ISO, 0, system_offset) != hash_range(OUTPUT_ISO, 0, system_offset):
        raise ValueError("SYSTEM.DAT 앞 ISO 범위 독립 비교 실패")
    if hash_range(BASE_ISO, system_end, BASE_ISO.stat().st_size) != hash_range(OUTPUT_ISO, system_end, OUTPUT_ISO.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 ISO 범위 독립 비교 실패")
    if int(final_record["data_length"]) != int(base_record["data_length"]):
        raise ValueError("SYSTEM.DAT ISO 레코드 크기 변경")

    final_system = read_iso_file(OUTPUT_ISO, final_record)
    if final_system != (RESOURCE_DIR / "SYSTEM.DAT").read_bytes():
        raise ValueError("최종 SYSTEM.DAT가 봉인 자원과 다릅니다.")
    entry = font_builder.parse_nispack_start_entry(final_system)
    final_start, _ = decompress_buffer(
        final_system[int(entry["data_offset"]):int(entry["data_offset"]) + int(entry["size"])]
    )
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes():
        raise ValueError("최종 START.DAT가 봉인 자원과 다릅니다.")
    for parts in (["PSP_GAME", "SYSDIR", "BOOT.BIN"], ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]):
        if read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, parts)) != read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, parts)):
            raise ValueError(f"V7.15.0 실행 파일 회귀: {parts[-1]}")

    report = {
        "format": "prinny1_v7_15_1_internal_ui_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(OUTPUT_ISO), "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {
            "approved_internal_ui_targets": 5,
            "expected_write_runs": int(pre["verified"]["expected_write_runs"]),
            "anime_changed_bytes": int(pre["verified"]["anime_changed_bytes"]),
            "excluded_nonapproved_candidate_pixels": int(pre["verified"]["excluded_nonapproved_candidate_pixels"]),
        },
        "checks": {
            "output_hash_recomputed": True,
            "iso_outside_system_byte_identical": True,
            "system_exactly_matches_sealed_resource": True,
            "start_reextracted_exactly": True,
            "boot_eboot_preserved": True,
            "prebuild_pixel_scope_review_pass": True,
        },
        "status": "pass_v7_15_1_structural_runtime_test_required",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {report['output_iso']['sha256']}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
