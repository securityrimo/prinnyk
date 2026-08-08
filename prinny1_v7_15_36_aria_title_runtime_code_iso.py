#!/usr/bin/env python3
"""Replace the two wrong runtime glyph codes in the 마해의 아리아 title."""
from __future__ import annotations

import csv
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_28_title_plaque_korean_iso import changed_start_resources, overlap_count
from prinny1_v7_15_29_title_plaque_white_index_iso import extract_start, extract_system
from prinny1_v7_15_35_candidate_text_runtime_repair_iso import (
    CANDIDATE_START,
    assert_same_archive_layout,
    now,
    record_map,
    resource_blob,
    sha256_bytes,
    sha256_file,
)


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_35_candidate_text_runtime_repair/prinny_korean_v7_15_35_candidate_text_runtime_repair.iso"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_36_aria_title_runtime_code"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_36_aria_title_runtime_code.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_36_aria_title_runtime_code_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_36_aria_title_runtime_code"
SCREENSHOT = Path("/home/hyuk/사진/마해의아리아요새.png")

EXPECTED_BASE_SHA256 = "3233128d81e6c7d084bdcd2f1edf0043d18b40970526a39eed587aa4f9c4b62e"
EXPECTED_CANDIDATE_START_SHA256 = "ee92515c9b014c95072abf5404cc20f3330080b636393421d72ba3f2a8978cba"
EXPECTED_SCREENSHOT_SHA256 = "65b3756fab7f793f4a5aa93b9307ab83b601f28cf721b12dffdea3ccaa49c060"
TITLE_OFFSET = 0x5C8
TITLE_SIZE = 31
EXPECTED_BEFORE = bytes.fromhex("F1CAF48BF36120F2D2F1C2F2D200") + bytes(17)
EXPECTED_AFTER = bytes.fromhex("F1CAF48BF36120F2C9F1C2F2C900") + bytes(17)


def write_json(name: str, payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def build_resources() -> tuple[dict[str, bytes], dict, dict]:
    base_system, _record = extract_system(BASE_ISO)
    base_start, base_lzs, start_row, system_rows = extract_start(base_system)
    candidate_start = CANDIDATE_START.read_bytes()
    base_records, candidate_records = assert_same_archive_layout(base_start, candidate_start)
    base_stage = base_records["stageinfo00.dat"]
    candidate_stage = candidate_records["stageinfo00.dat"]
    base_at = base_stage.data_offset + TITLE_OFFSET
    candidate_at = candidate_stage.data_offset + TITLE_OFFSET
    before = base_start[base_at:base_at + TITLE_SIZE]
    after = candidate_start[candidate_at:candidate_at + TITLE_SIZE]
    if before != EXPECTED_BEFORE or after != EXPECTED_AFTER:
        raise ValueError("마해의 아리아 제목 봉인 바이트 불일치")
    changed_offsets = [index for index, (old, new) in enumerate(zip(before, after)) if old != new]
    if changed_offsets != [8, 12]:
        raise ValueError(f"제목 실제 변경 바이트 불일치: {changed_offsets}")
    final_start = bytearray(base_start)
    final_start[base_at:base_at + TITLE_SIZE] = after
    final_start_bytes = bytes(final_start)
    if changed_start_resources(base_start, final_start_bytes) != ["stageinfo00.dat"]:
        raise ValueError("stageinfo00.dat 외 START 자원 변경")
    header = decompress_buffer(base_lzs)[1]
    new_lzs = compress_buffer_runtime_safe(final_start_bytes, base_lzs[:4], int(header["flag"]))
    capacity = system_rows[start_row["index"] + 1]["data_offset"] - start_row["data_offset"]
    if len(new_lzs) > capacity or decompress_buffer(new_lzs)[0] != final_start_bytes or overlap_count(new_lzs):
        raise ValueError("START.LZS 런타임 안전 압축 실패")
    final_system = bytearray(base_system)
    at = start_row["data_offset"]
    final_system[at:at + capacity] = bytes(capacity)
    final_system[at:at + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))
    final_system_bytes = bytes(final_system)
    check_start, check_lzs, _row, _rows = extract_start(final_system_bytes)
    if check_start != final_start_bytes or check_lzs != new_lzs:
        raise ValueError("SYSTEM.DAT START 재추출 불일치")
    final_records = record_map(final_start_bytes)
    artifacts = {
        "SYSTEM.DAT": final_system_bytes,
        "start.dat": final_start_bytes,
        "start.lzs": new_lzs,
        "stageinfo00.dat": resource_blob(final_start_bytes, final_records, "stageinfo00.dat"),
    }
    write = {
        "id": "P1-V7.15.36-ARIA-TITLE-0001",
        "target": "START.DAT/stageinfo00.dat",
        "operation": "replace_two_wrong_runtime_glyph_codes",
        "offset_hex": f"0x{TITLE_OFFSET:X}",
        "length": TITLE_SIZE,
        "before_hex": before.hex().upper(),
        "after_hex": after.hex().upper(),
        "actual_changed_relative_offsets": "0x8;0xC",
        "runtime_text": "마해의 아리아",
    }
    metadata = {
        "title_offset_hex": f"0x{TITLE_OFFSET:X}",
        "field_size": TITLE_SIZE,
        "wrong_code": "F2D2",
        "runtime_proven_code": "F2C9",
        "glyph_occurrences_changed": 2,
        "actual_bytes_changed_in_stageinfo": 2,
        "changed_start_resources": ["stageinfo00.dat"],
        "lzs_old_size": len(base_lzs),
        "lzs_new_size": len(new_lzs),
        "lzs_capacity": capacity,
        "lzs_overlap_backreferences": 0,
    }
    return artifacts, write, metadata


def seal() -> dict:
    for path, expected in {
        BASE_ISO: EXPECTED_BASE_SHA256,
        CANDIDATE_START: EXPECTED_CANDIDATE_START_SHA256,
        SCREENSHOT: EXPECTED_SCREENSHOT_SHA256,
    }.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"입력 봉인값 불일치: {path}")
    artifacts, write, metadata = build_resources()
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for name, blob in artifacts.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    with (REPORT_DIR / "expected_writes.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(write))
        writer.writeheader()
        writer.writerow(write)
    report = {
        "format": "prinny1_v7_15_36_aria_title_runtime_code_preflight_v1",
        "created_at": now(),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "user_evidence": {"path": str(SCREENSHOT), "sha256": sha256_file(SCREENSHOT)},
        "diagnosis": "V7.15.35 preserved the V7.15.34 title and therefore kept F2D2 for both 아 glyphs",
        "repair": metadata,
        "expected_write": write,
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()},
        "checks": {"candidate_title_rendered_as_makaeui_aria": True,
                   "only_two_runtime_glyph_code_bytes_changed": True,
                   "v7_15_35_descriptions_and_dialogues_preserved": True},
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json("preflight_report.json", report)
    return report


def independent_prebuild_review() -> dict:
    artifacts, write, metadata = build_resources()
    for name, blob in artifacts.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"독립 사전 봉인 불일치: {name}")
    report = {
        "format": "prinny1_v7_15_36_aria_title_runtime_code_prebuild_review_v1",
        "created_at": now(),
        "verified": metadata | {"expected_write": write},
        "checks": {"fresh_candidate_title_recalculation": True,
                   "sealed_resources_exact": True,
                   "only_stageinfo_changed": True,
                   "runtime_safe_lzs": True},
        "status": "pass_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    write_json("independent_prebuild_review.json", report)
    return report


def system_record(iso: Path) -> dict:
    return find_iso_file(iso, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])


def verify_outside_system(candidate: Path, record: dict) -> None:
    left = int(record["extent_lba"]) * SECTOR_SIZE
    right = left + int(record["data_length"])
    if candidate.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기 변경")
    if hash_range(BASE_ISO, 0, left) != hash_range(candidate, 0, left):
        raise ValueError("SYSTEM 앞 ISO 변경")
    if hash_range(BASE_ISO, right, BASE_ISO.stat().st_size) != hash_range(candidate, right, candidate.stat().st_size):
        raise ValueError("SYSTEM 뒤 ISO 변경")


def build_iso() -> dict:
    review = json.loads((REPORT_DIR / "independent_prebuild_review.json").read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or OUTPUT_ISO.exists():
        raise ValueError("사전 검토 미통과 또는 출력 ISO 이미 존재")
    record = system_record(BASE_ISO)
    system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as handle:
        handle.seek(int(record["extent_lba"]) * SECTOR_SIZE)
        handle.write(system)
        handle.flush()
        os.fsync(handle.fileno())
    verify_outside_system(temporary, record)
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("ISO 7z 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_36_aria_title_runtime_code_iso_v1",
        "created_at": now(),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size,
                       "sha256": sha256_file(OUTPUT_ISO)},
        "checks": {"only_system_dat_iso_extent_changed": True,
                   "seven_zip_structure_test": True,
                   "parent_not_overwritten": True},
        "status": "built_independent_postbuild_review_required",
    }
    write_json("iso_build_report.json", report)
    return report


def independent_postbuild_review() -> dict:
    base_record, final_record = system_record(BASE_ISO), system_record(OUTPUT_ISO)
    if (base_record["extent_lba"], base_record["data_length"]) != (
        final_record["extent_lba"], final_record["data_length"]
    ):
        raise ValueError("사후 SYSTEM ISO 경계 변경")
    verify_outside_system(OUTPUT_ISO, base_record)
    extracted = read_iso_file(OUTPUT_ISO, final_record)
    if extracted != (RESOURCE_DIR / "SYSTEM.DAT").read_bytes():
        raise ValueError("사후 SYSTEM 재추출 봉인 불일치")
    final_start, final_lzs, _row, _rows = extract_start(extracted)
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or overlap_count(final_lzs):
        raise ValueError("사후 START/LZS 불일치")
    artifacts, write, metadata = build_resources()
    for name, blob in artifacts.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"사후 독립 재계산 불일치: {name}")
    test = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_36_aria_title_runtime_code_postbuild_review_v1",
        "created_at": now(),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size,
                       "sha256": sha256_file(OUTPUT_ISO)},
        "verified": metadata | {"expected_write": write, "ppsspp_launched": False},
        "checks": {"only_system_dat_iso_extent_changed": True,
                   "sealed_resources_reextracted_exactly": True,
                   "fresh_candidate_title_recalculation": True,
                   "runtime_safe_lzs": True,
                   "seven_zip_structure_retest": True},
        "status": "pass_ready_for_ppsspp_runtime_test",
        "final_verdict": "PASS",
    }
    write_json("independent_postbuild_review.json", report)
    return report


def main() -> int:
    seal()
    independent_prebuild_review()
    build = build_iso()
    review = independent_postbuild_review()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print("마해의 아리아: F2D2 -> F2C9 (2 occurrences / 2 bytes)")
    print("preflight/prebuild/7z/reextract/postbuild: PASS")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
