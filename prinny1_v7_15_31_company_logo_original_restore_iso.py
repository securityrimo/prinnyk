#!/usr/bin/env python3
"""Restore the original company-logo anime object on top of V7.15.30."""
from __future__ import annotations

import csv
import json
import os
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE
from prinny1_v7_15_28_title_plaque_korean_iso import (
    changed_start_resources,
    overlap_count,
)
from prinny1_v7_15_29_title_plaque_white_index_iso import (
    extract_anime,
    extract_start,
    extract_system,
    sha256_bytes,
    sha256_file,
)
from scripts.prinny_anime_preview import decode_texture, find_texture_groups, parse_objects


ROOT = Path(__file__).resolve().parent
ORIGINAL_ISO = ROOT / "game.iso"
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_30_title_user_reference"
    / "prinny_korean_v7_15_30_title_user_reference.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_31_company_logo_original_restore"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_31_company_logo_original_restore.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_31_company_logo_original_restore_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_31_company_logo_original_restore"
PREVIEW_DIR = ROOT / "workspace/exports/prinny1_v7_15_31_company_logo_original_restore"

EXPECTED_ORIGINAL_ISO_SHA256 = "af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03"
EXPECTED_BASE_ISO_SHA256 = "cba9e1a7e8cbf49bb01cb9f7d5d8a4a4491b914c20781a89aff32a4394262714"
COMPANY_LOGO_OBJECT_INDEX = 79
TITLE_OBJECT_INDEX = 78
EXPECTED_OBJECT_OFFSET = 4_784_064
EXPECTED_OBJECT_SIZE = 88_304
EXPECTED_ORIGINAL_OBJECT_SHA256 = "2ba384784e31d6ccb8a41f4bca9fb7f8838a15f915112f836960d361d7d4f5b9"
EXPECTED_BASE_OBJECT_SHA256 = "ffe560e86d5796f8668880f91766ec3b1702b8a6e198dd0b45dfc028eded9efb"
EXPECTED_TITLE_OBJECT_SHA256 = "39c980fcf666e898cec7185b2be22d598a9ff94ff0a40488c937da96f05ab46e"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(name: str, report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def object_blob(anime: bytes, index: int) -> tuple[object, bytes]:
    obj = parse_objects(anime)[index]
    return obj, anime[obj.offset:obj.end]


def changed_object_indices(before: bytes, after: bytes) -> list[int]:
    before_objects = parse_objects(before)
    after_objects = parse_objects(after)
    before_layout = [(obj.index, obj.offset, obj.size, obj.end) for obj in before_objects]
    after_layout = [(obj.index, obj.offset, obj.size, obj.end) for obj in after_objects]
    if before_layout != after_layout:
        raise ValueError("anime00 오브젝트 레이아웃이 변경됐습니다")
    return [
        old.index
        for old, new in zip(before_objects, after_objects)
        if before[old.offset:old.end] != after[new.offset:new.end]
    ]


def restore_company_logo(base_anime: bytes, original_anime: bytes) -> tuple[bytes, dict]:
    base_object, base_blob = object_blob(base_anime, COMPANY_LOGO_OBJECT_INDEX)
    original_object, original_blob = object_blob(original_anime, COMPANY_LOGO_OBJECT_INDEX)
    if (base_object.offset, base_object.size) != (
        EXPECTED_OBJECT_OFFSET,
        EXPECTED_OBJECT_SIZE,
    ) or (original_object.offset, original_object.size) != (
        EXPECTED_OBJECT_OFFSET,
        EXPECTED_OBJECT_SIZE,
    ):
        raise ValueError("회사 로고 object_079 위치/크기가 봉인값과 다릅니다")
    if sha256_bytes(base_blob) != EXPECTED_BASE_OBJECT_SHA256:
        raise ValueError("부모 회사 로고 object_079 해시 불일치")
    if sha256_bytes(original_blob) != EXPECTED_ORIGINAL_OBJECT_SHA256:
        raise ValueError("원본 회사 로고 object_079 해시 불일치")
    _title_object, title_blob = object_blob(base_anime, TITLE_OBJECT_INDEX)
    if sha256_bytes(title_blob) != EXPECTED_TITLE_OBJECT_SHA256:
        raise ValueError("V7.15.30 제목 object_078 해시 불일치")
    final_anime = bytearray(base_anime)
    final_anime[base_object.offset:base_object.end] = original_blob
    final_anime_bytes = bytes(final_anime)
    if changed_object_indices(base_anime, final_anime_bytes) != [COMPANY_LOGO_OBJECT_INDEX]:
        raise ValueError("회사 로고 외 anime00 오브젝트가 변경됐습니다")
    _final_title_object, final_title_blob = object_blob(final_anime_bytes, TITLE_OBJECT_INDEX)
    if final_title_blob != title_blob:
        raise ValueError("V7.15.30 제목 object_078이 변경됐습니다")
    _final_object, final_blob = object_blob(final_anime_bytes, COMPANY_LOGO_OBJECT_INDEX)
    if final_blob != original_blob:
        raise ValueError("복원된 회사 로고가 원본 object_079와 다릅니다")
    differing_bytes = sum(old != new for old, new in zip(base_blob, original_blob))
    return final_anime_bytes, {
        "object_index": COMPANY_LOGO_OBJECT_INDEX,
        "object_offset": base_object.offset,
        "object_size": base_object.size,
        "before_sha256": sha256_bytes(base_blob),
        "after_sha256": sha256_bytes(original_blob),
        "differing_bytes": differing_bytes,
        "changed_anime_objects": [COMPANY_LOGO_OBJECT_INDEX],
        "preserved_title_object": TITLE_OBJECT_INDEX,
        "preserved_title_sha256": sha256_bytes(title_blob),
    }


def save_previews(base_anime: bytes, original_anime: bytes, final_anime: bytes) -> dict:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    for label, anime in (
        ("base_corrupt", base_anime),
        ("original_source", original_anime),
        ("restored", final_anime),
    ):
        obj = parse_objects(anime)[COMPANY_LOGO_OBJECT_INDEX]
        groups = find_texture_groups(anime, obj)
        for group_index, group in enumerate(groups):
            for texture in group:
                name = f"{label}_group_{group_index:02d}_page_{texture.page_index:02d}.png"
                path = PREVIEW_DIR / name
                decode_texture(anime, texture).save(
                    path, format="PNG", optimize=True, compress_level=9
                )
                outputs[name] = sha256_file(path)
    if outputs["original_source_group_00_page_00.png"] != outputs[
        "restored_group_00_page_00.png"
    ] or outputs["original_source_group_01_page_00.png"] != outputs[
        "restored_group_01_page_00.png"
    ]:
        raise ValueError("복원 회사 로고 PNG가 원본 디코드와 다릅니다")
    return outputs


def preflight_and_seal() -> dict:
    if sha256_file(ORIGINAL_ISO) != EXPECTED_ORIGINAL_ISO_SHA256:
        raise ValueError("원본 ISO 해시 불일치")
    if sha256_file(BASE_ISO) != EXPECTED_BASE_ISO_SHA256:
        raise ValueError("V7.15.30 부모 ISO 해시 불일치")
    base_system, _base_record = extract_system(BASE_ISO)
    original_system, _original_record = extract_system(ORIGINAL_ISO)
    base_start, base_lzs, row, rows = extract_start(base_system)
    original_start, _original_lzs, _original_row, _original_rows = extract_start(original_system)
    if overlap_count(base_lzs):
        raise ValueError("부모 START.LZS에 PSP 비호환 겹침 역참조가 있습니다")
    base_anime, anime_record = extract_anime(base_start)
    original_anime, _original_anime_record = extract_anime(original_start)
    final_anime, restore_meta = restore_company_logo(base_anime, original_anime)
    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    final_start_bytes = bytes(final_start)
    if changed_start_resources(base_start, final_start_bytes) != ["anime00.dat"]:
        raise ValueError("anime00.dat 외 START 자원이 변경됐습니다")
    header = decompress_buffer(base_lzs)[1]
    final_lzs = compress_buffer_runtime_safe(
        final_start_bytes, base_lzs[:4], int(header["flag"])
    )
    if decompress_buffer(final_lzs)[0] != final_start_bytes or overlap_count(final_lzs):
        raise ValueError("V7.15.31 런타임 안전 LZS 왕복 실패")
    capacity = rows[row["index"] + 1]["data_offset"] - row["data_offset"]
    if len(final_lzs) > capacity:
        raise ValueError("V7.15.31 START.LZS 슬롯 초과")
    final_system = bytearray(base_system)
    final_system[row["data_offset"]:row["data_offset"] + capacity] = bytes(capacity)
    final_system[row["data_offset"]:row["data_offset"] + len(final_lzs)] = final_lzs
    struct.pack_into(
        "<I", final_system, 0x10 + row["index"] * 0x2C + 0x24, len(final_lzs)
    )
    final_system_bytes = bytes(final_system)
    check_start, check_lzs, _check_row, _check_rows = extract_start(final_system_bytes)
    if check_start != final_start_bytes or check_lzs != final_lzs:
        raise ValueError("봉인 SYSTEM.DAT 재추출 불일치")
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "SYSTEM.DAT": final_system_bytes,
        "start.dat": final_start_bytes,
        "start.lzs": final_lzs,
        "anime00.dat": final_anime,
    }
    for name, blob in artifacts.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    previews = save_previews(base_anime, original_anime, final_anime)
    expected_write = {
        "id": "P1-V7.15.31-COMPANY-LOGO-0001",
        "target": "START.DAT/anime00.dat/object_079",
        "operation": "restore_exact_object_from_original_game_iso",
        "offset": EXPECTED_OBJECT_OFFSET,
        "size": EXPECTED_OBJECT_SIZE,
        "before_sha256": EXPECTED_BASE_OBJECT_SHA256,
        "after_sha256": EXPECTED_ORIGINAL_OBJECT_SHA256,
        "preserved_title_object": TITLE_OBJECT_INDEX,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / "expected_writes.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(expected_write))
        writer.writeheader()
        writer.writerow(expected_write)
    report = {
        "format": "prinny1_v7_15_31_company_logo_original_restore_preflight_v1",
        "created_at": now(),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "original_iso": {
            "path": str(ORIGINAL_ISO),
            "sha256": sha256_file(ORIGINAL_ISO),
            "use": "exact_source_for_anime00_object_079_only",
        },
        "expected_write": expected_write,
        "restore": restore_meta,
        "lzs": {
            "old_size": len(base_lzs),
            "new_size": len(final_lzs),
            "capacity": capacity,
            "overlap_backreferences": 0,
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()},
        "previews": previews,
        "checks": {
            "exact_original_object_079": True,
            "object_layout_unchanged": True,
            "only_object_079_changed_in_anime00": True,
            "title_object_078_preserved": True,
            "only_anime00_changed_in_start": True,
            "runtime_safe_lzs_non_overlap": True,
            "external_textures_used": False,
        },
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json("preflight_report.json", report)
    return report


def independent_prebuild_review() -> dict:
    base_system, _base_record = extract_system(BASE_ISO)
    original_system, _original_record = extract_system(ORIGINAL_ISO)
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    base_start, _base_lzs, _base_row, base_rows = extract_start(base_system)
    original_start, _original_lzs, _original_row, _original_rows = extract_start(original_system)
    final_start, final_lzs, _final_row, final_rows = extract_start(final_system)
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes():
        raise ValueError("독립 사전 START 봉인 불일치")
    if final_lzs != (RESOURCE_DIR / "start.lzs").read_bytes() or overlap_count(final_lzs):
        raise ValueError("독립 사전 LZS 봉인/안전성 불일치")
    if [(row["name"], row["data_offset"]) for row in base_rows] != [
        (row["name"], row["data_offset"]) for row in final_rows
    ]:
        raise ValueError("독립 사전 SYSTEM 자원 경계 변경")
    if changed_start_resources(base_start, final_start) != ["anime00.dat"]:
        raise ValueError("독립 사전 START 변경 범위 불일치")
    base_anime, _base_anime_record = extract_anime(base_start)
    original_anime, _original_anime_record = extract_anime(original_start)
    final_anime, _final_anime_record = extract_anime(final_start)
    expected_anime, meta = restore_company_logo(base_anime, original_anime)
    if final_anime != expected_anime or final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("독립 사전 원본 회사 로고 재계산/봉인 불일치")
    report = {
        "format": "prinny1_v7_15_31_company_logo_original_restore_prebuild_review_v1",
        "created_at": now(),
        "verified": meta | {"changed_start_resources": ["anime00.dat"], "lzs_overlaps": 0},
        "checks": {
            "fresh_original_object_extraction": True,
            "sealed_resources_exact": True,
            "only_object_079_changed_in_anime00": True,
            "title_object_078_preserved": True,
            "only_anime00_changed_in_start": True,
        },
        "status": "pass_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    write_json("independent_prebuild_review.json", report)
    return report


def build_iso() -> dict:
    review = json.loads(
        (REPORT_DIR / "independent_prebuild_review.json").read_text(encoding="utf-8")
    )
    if review.get("final_verdict") != "PASS":
        raise ValueError("V7.15.31 독립 사전 검토 미통과")
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.31 출력 ISO가 이미 존재합니다")
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    _base_system, record = extract_system(BASE_ISO)
    if len(final_system) != int(record["data_length"]):
        raise ValueError("SYSTEM.DAT ISO 크기 변경")
    offset = int(record["extent_lba"]) * SECTOR_SIZE
    end = offset + len(final_system)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as handle:
        handle.seek(offset)
        handle.write(final_system)
        handle.flush()
        os.fsync(handle.fileno())
    if (
        temporary.stat().st_size != BASE_ISO.stat().st_size
        or hash_range(BASE_ISO, 0, offset) != hash_range(temporary, 0, offset)
        or hash_range(BASE_ISO, end, BASE_ISO.stat().st_size)
        != hash_range(temporary, end, temporary.stat().st_size)
    ):
        raise ValueError("SYSTEM.DAT 허용 범위 밖 ISO 변경")
    test = subprocess.run(
        ["7z", "t", str(temporary)], capture_output=True, text=True, check=False
    )
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.31 ISO 7z 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_31_company_logo_original_restore_iso_v1",
        "created_at": now(),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "output_iso": {
            "path": str(OUTPUT_ISO),
            "size": OUTPUT_ISO.stat().st_size,
            "sha256": sha256_file(OUTPUT_ISO),
        },
        "checks": {
            "only_system_dat_iso_extent_changed": True,
            "seven_zip_structure_test": True,
            "parent_not_overwritten": True,
        },
        "status": "built_independent_postbuild_review_required",
    }
    write_json("iso_build_report.json", report)
    return report


def independent_postbuild_review() -> dict:
    base_system, base_record = extract_system(BASE_ISO)
    original_system, _original_record = extract_system(ORIGINAL_ISO)
    final_system, final_record = extract_system(OUTPUT_ISO)
    if (base_record["extent_lba"], base_record["data_length"]) != (
        final_record["extent_lba"], final_record["data_length"]
    ):
        raise ValueError("사후 SYSTEM.DAT ISO 범위 변경")
    offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    end = offset + int(base_record["data_length"])
    if (
        BASE_ISO.stat().st_size != OUTPUT_ISO.stat().st_size
        or hash_range(BASE_ISO, 0, offset) != hash_range(OUTPUT_ISO, 0, offset)
        or hash_range(BASE_ISO, end, BASE_ISO.stat().st_size)
        != hash_range(OUTPUT_ISO, end, OUTPUT_ISO.stat().st_size)
    ):
        raise ValueError("사후 SYSTEM.DAT 범위 밖 ISO 변경")
    if final_system != (RESOURCE_DIR / "SYSTEM.DAT").read_bytes():
        raise ValueError("사후 SYSTEM 봉인 불일치")
    base_start, _base_lzs, _base_row, _base_rows = extract_start(base_system)
    original_start, _original_lzs, _original_row, _original_rows = extract_start(original_system)
    final_start, final_lzs, _final_row, _final_rows = extract_start(final_system)
    if overlap_count(final_lzs) or changed_start_resources(base_start, final_start) != ["anime00.dat"]:
        raise ValueError("사후 START 변경 범위/LZS 안전성 불일치")
    base_anime, _base_anime_record = extract_anime(base_start)
    original_anime, _original_anime_record = extract_anime(original_start)
    final_anime, _final_anime_record = extract_anime(final_start)
    expected_anime, meta = restore_company_logo(base_anime, original_anime)
    if final_anime != expected_anime or final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("사후 원본 회사 로고 재계산/anime00 봉인 불일치")
    test = subprocess.run(
        ["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False
    )
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_31_company_logo_original_restore_postbuild_review_v1",
        "created_at": now(),
        "output_iso": {
            "path": str(OUTPUT_ISO),
            "size": OUTPUT_ISO.stat().st_size,
            "sha256": sha256_file(OUTPUT_ISO),
        },
        "verified": meta | {
            "changed_start_resources": ["anime00.dat"],
            "runtime_lzs_overlaps": 0,
            "ppsspp_launched": False,
        },
        "checks": {
            "only_system_dat_iso_extent_changed": True,
            "sealed_system_reextracted_exactly": True,
            "fresh_original_object_recalculation": True,
            "only_object_079_changed_in_anime00": True,
            "title_object_078_preserved": True,
            "seven_zip_structure_retest": True,
            "external_textures_used": False,
        },
        "status": "pass_ready_for_ppsspp_company_logo_runtime_test",
        "final_verdict": "PASS",
    }
    write_json("independent_postbuild_review.json", report)
    return report


def main() -> int:
    preflight_and_seal()
    independent_prebuild_review()
    build = build_iso()
    review = independent_postbuild_review()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print(f"restored: anime00.dat/object_{COMPANY_LOGO_OBJECT_INDEX:03d}")
    print("preflight/prebuild/7z/reextract/postbuild: PASS")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
