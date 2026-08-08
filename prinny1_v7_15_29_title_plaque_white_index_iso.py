#!/usr/bin/env python3
"""Switch the embedded Korean plaque title to the runtime-white CLUT index."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from prinny1_v7_15_28_title_plaque_korean_iso import (
    EXPECTED_FOREGROUND_PIXELS,
    TITLE_CENTER,
    TITLE_TEXT,
    changed_start_resources,
    overlap_count,
    render_title_mask,
)
from scripts.prinny_anime_preview import decode_texture
from scripts.prinny_txp_preview import swizzle_psp, unswizzle_psp


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_28_title_plaque_korean"
    / "prinny_korean_v7_15_28_title_plaque_korean.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_29_title_plaque_white_index"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_29_title_plaque_white_index.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_29_title_plaque_white_index_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_29_title_plaque_white_index"
RUNTIME_SCREENSHOT = (
    ROOT / "evidence/prinny1_v7_15_28_runtime/title_screen_final.png"
)
IMAGEGEN_TARGET = (
    ROOT
    / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
    / "style_references/prinny_title_white_runtime_target_imagegen.png"
)

EXPECTED_BASE_SHA256 = "10b4c100dd52bc2404f62e9a7c268c6e1181ff0fbeca394f1733a78b4b52511c"
SOURCE_INDEX = 8
TARGET_INDEX = 15
GREEN_RGBA = (0, 255, 0, 255)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(name: str, report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def extract_system(iso: Path) -> tuple[bytes, dict]:
    record = find_iso_file(iso, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    return read_iso_file(iso, record), record


def extract_start(system: bytes) -> tuple[bytes, bytes, dict, list[dict]]:
    rows = system_records(system)
    row = next(item for item in rows if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs, row, rows


def extract_anime(start: bytes) -> tuple[bytes, object]:
    archive = StartRuntimeArchive.from_bytes(start)
    record = next(
        item for item in archive.records if item.output_name.casefold() == "anime00.dat"
    )
    return start[record.data_offset:record.end_offset], record


def palette(anime: bytes, texture: object) -> list[tuple[int, int, int, int]]:
    return [
        tuple(anime[offset:offset + 4])
        for offset in range(texture.palette_offset, texture.palette_offset + 64, 4)
    ]


def linear_indices(anime: bytes, texture: object) -> list[int]:
    pixel_size = texture.width * texture.height // 2
    packed = anime[texture.pixel_offset:texture.pixel_offset + pixel_size]
    linear = unswizzle_psp(packed, texture.width // 2, texture.height)
    return [nibble for value in linear for nibble in (value & 0x0F, value >> 4)]


def repack_indices(anime: bytes, texture: object, indices: list[int]) -> bytes:
    linear = bytes(
        indices[offset] | (indices[offset + 1] << 4)
        for offset in range(0, len(indices), 2)
    )
    packed = swizzle_psp(linear, texture.width // 2, texture.height)
    result = bytearray(anime)
    result[texture.pixel_offset:texture.pixel_offset + len(packed)] = packed
    return bytes(result)


def title_positions() -> list[int]:
    mask = render_title_mask()
    left = TITLE_CENTER[0] - mask.width // 2
    top = TITLE_CENTER[1] - mask.height // 2
    positions = [
        (top + y) * 512 + left + x
        for y in range(mask.height)
        for x in range(mask.width)
        if mask.getpixel((x, y))
    ]
    if len(positions) != EXPECTED_FOREGROUND_PIXELS:
        raise ValueError("V7.15.29 제목 마스크 픽셀 수 불일치")
    return positions


def patch_title_indices(base_anime: bytes) -> tuple[bytes, dict]:
    texture = texture_by_key(base_anime, (78, 0, 0))
    colors = palette(base_anime, texture)
    if colors[SOURCE_INDEX] != GREEN_RGBA or colors[TARGET_INDEX] != GREEN_RGBA:
        raise ValueError("중복 초록 CLUT 인덱스 기준 불일치")
    before = linear_indices(base_anime, texture)
    positions = title_positions()
    wrong = [(position, before[position]) for position in positions if before[position] != SOURCE_INDEX]
    if wrong:
        raise ValueError(f"제목 원본 인덱스 8 불일치: {wrong[:8]}")
    after = before.copy()
    for position in positions:
        after[position] = TARGET_INDEX
    changed = [index for index, (old, new) in enumerate(zip(before, after)) if old != new]
    if changed != positions:
        raise ValueError("허용 제목 마스크 밖 인덱스 변경")
    final_anime = repack_indices(base_anime, texture, after)
    if decode_texture(final_anime, texture).tobytes() != decode_texture(base_anime, texture).tobytes():
        raise ValueError("8→15 변경으로 정적 RGBA가 달라졌습니다")
    pixel_end = texture.pixel_offset + texture.width * texture.height // 2
    if (
        base_anime[:texture.pixel_offset] != final_anime[:texture.pixel_offset]
        or base_anime[pixel_end:] != final_anime[pixel_end:]
    ):
        raise ValueError("타이틀 픽셀 스트림 밖 anime00 변경")
    changed_bytes = sum(a != b for a, b in zip(base_anime, final_anime))
    return final_anime, {
        "title_text": TITLE_TEXT,
        "source_index": SOURCE_INDEX,
        "target_index": TARGET_INDEX,
        "source_rgba": list(colors[SOURCE_INDEX]),
        "target_rgba": list(colors[TARGET_INDEX]),
        "logical_pixels_changed": len(changed),
        "packed_bytes_changed": changed_bytes,
        "decoded_rgba_changed_pixels": 0,
        "runtime_reason": "index_15_is_existing_white_plaque_outline; index_8_rendered_dark_gray",
    }


def preflight_and_seal() -> dict:
    if sha256_file(BASE_ISO) != EXPECTED_BASE_SHA256:
        raise ValueError("V7.15.29 부모 ISO 해시 불일치")
    if not RUNTIME_SCREENSHOT.is_file() or not IMAGEGEN_TARGET.is_file():
        raise ValueError("V7.15.28 런타임 또는 목표 화면 근거 누락")
    system, _record = extract_system(BASE_ISO)
    start, old_lzs, row, rows = extract_start(system)
    if overlap_count(old_lzs):
        raise ValueError("부모 LZS 겹침 역참조")
    base_anime, anime_record = extract_anime(start)
    final_anime, index_meta = patch_title_indices(base_anime)
    final_start = bytearray(start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    final_start_bytes = bytes(final_start)
    if changed_start_resources(start, final_start_bytes) != ["anime00.dat"]:
        raise ValueError("anime00.dat 외 START 자원 변경")
    header = decompress_buffer(old_lzs)[1]
    new_lzs = compress_buffer_runtime_safe(
        final_start_bytes, old_lzs[:4], int(header["flag"])
    )
    if decompress_buffer(new_lzs)[0] != final_start_bytes or overlap_count(new_lzs):
        raise ValueError("V7.15.29 런타임 안전 LZS 왕복 실패")
    capacity = rows[row["index"] + 1]["data_offset"] - row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError("V7.15.29 START.LZS 슬롯 초과")
    final_system = bytearray(system)
    final_system[row["data_offset"]:row["data_offset"] + capacity] = bytes(capacity)
    final_system[row["data_offset"]:row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into(
        "<I", final_system, 0x10 + row["index"] * 0x2C + 0x24, len(new_lzs)
    )
    final_system_bytes = bytes(final_system)
    check_start, check_lzs, _check_row, _check_rows = extract_start(final_system_bytes)
    if check_start != final_start_bytes or check_lzs != new_lzs:
        raise ValueError("봉인 SYSTEM START 재추출 불일치")

    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "SYSTEM.DAT": final_system_bytes,
        "start.dat": final_start_bytes,
        "start.lzs": new_lzs,
        "anime00.dat": final_anime,
    }
    for name, blob in artifacts.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    expected_write = {
        "id": "P1-V7.15.29-TITLE-0001",
        "target": "START.DAT/anime00.dat/object_078/group_00_page_00",
        "operation": "title_mask_clut_index_8_to_15",
        "logical_pixels": EXPECTED_FOREGROUND_PIXELS,
        "before_anime_sha256": sha256_bytes(base_anime),
        "after_anime_sha256": sha256_bytes(final_anime),
        "decoded_rgba_change": 0,
        "uv_transform_palette_table_change": 0,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / "expected_writes.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(expected_write))
        writer.writeheader()
        writer.writerow(expected_write)
    report = {
        "format": "prinny1_v7_15_29_title_white_index_preflight_v1",
        "created_at": now(),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "runtime_failure_evidence": {
            "path": str(RUNTIME_SCREENSHOT),
            "sha256": sha256_file(RUNTIME_SCREENSHOT),
            "observed": "title_shape_and_position_pass_but_index_8_is_dark_gray",
        },
        "target_reference": {
            "user_image": "/home/hyuk/사진/타이틀화면.png",
            "imagegen_white_only_mockup": str(IMAGEGEN_TARGET),
            "imagegen_white_only_mockup_sha256": sha256_file(IMAGEGEN_TARGET),
        },
        "index_patch": index_meta,
        "expected_write": expected_write,
        "lzs": {
            "old_size": len(old_lzs),
            "new_size": len(new_lzs),
            "capacity": capacity,
            "overlap_backreferences": 0,
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()},
        "checks": {
            "same_rgba_duplicate_indices": True,
            "only_title_mask_indices_changed": True,
            "decoded_texture_byte_identical": True,
            "palette_table_uv_transform_unchanged": True,
            "only_anime00_changed_in_start": True,
            "runtime_safe_lzs_non_overlap": True,
        },
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json("preflight_report.json", report)
    return report


def independent_prebuild_review() -> dict:
    base_system, _record = extract_system(BASE_ISO)
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    base_start, _base_lzs, _base_row, base_rows = extract_start(base_system)
    final_start, final_lzs, _final_row, final_rows = extract_start(final_system)
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes():
        raise ValueError("독립 사전 START 봉인 불일치")
    if final_lzs != (RESOURCE_DIR / "start.lzs").read_bytes() or overlap_count(final_lzs):
        raise ValueError("독립 사전 LZS 봉인/안전성 불일치")
    if [(r["name"], r["data_offset"]) for r in base_rows] != [
        (r["name"], r["data_offset"]) for r in final_rows
    ]:
        raise ValueError("독립 사전 SYSTEM 자원 경계 변경")
    if changed_start_resources(base_start, final_start) != ["anime00.dat"]:
        raise ValueError("독립 사전 비대상 START 자원 변경")
    base_anime, _base_record = extract_anime(base_start)
    final_anime, _final_record = extract_anime(final_start)
    expected_anime, meta = patch_title_indices(base_anime)
    if final_anime != expected_anime or final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("독립 사전 인덱스 재계산/봉인 불일치")
    report = {
        "format": "prinny1_v7_15_29_title_white_index_prebuild_review_v1",
        "created_at": now(),
        "verified": meta | {"changed_start_resources": ["anime00.dat"], "lzs_overlaps": 0},
        "checks": {
            "fresh_base_extraction": True,
            "fresh_index_map_recalculation": True,
            "sealed_resources_exact": True,
            "decoded_rgba_unchanged": True,
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
        raise ValueError("V7.15.29 독립 사전 검토 미통과")
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.29 출력 ISO가 이미 존재합니다")
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
        raise ValueError("V7.15.29 ISO 7z 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_29_title_white_index_iso_v1",
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
    final_start, final_lzs, _final_row, _final_rows = extract_start(final_system)
    if overlap_count(final_lzs) or changed_start_resources(base_start, final_start) != ["anime00.dat"]:
        raise ValueError("사후 START 변경 범위/LZS 안전성 불일치")
    base_anime, _base_anime_record = extract_anime(base_start)
    final_anime, _final_anime_record = extract_anime(final_start)
    expected_anime, meta = patch_title_indices(base_anime)
    if final_anime != expected_anime or final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("사후 재추출 anime00 인덱스/봉인 불일치")
    test = subprocess.run(
        ["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False
    )
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_29_title_white_index_postbuild_review_v1",
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
            "fresh_index_map_recalculation": True,
            "decoded_rgba_unchanged": True,
            "only_anime00_changed_in_start": True,
            "seven_zip_structure_retest": True,
        },
        "status": "pass_ready_for_ppsspp_title_runtime_test",
        "final_verdict": "PASS",
    }
    write_json("independent_postbuild_review.json", report)
    return report


def main() -> int:
    if not BASE_ISO.is_file():
        raise ValueError(f"부모 ISO 누락: {BASE_ISO}")
    preflight_and_seal()
    independent_prebuild_review()
    build = build_iso()
    review = independent_postbuild_review()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print(f"title CLUT indices: {SOURCE_INDEX} -> {TARGET_INDEX} / {EXPECTED_FOREGROUND_PIXELS} px")
    print("preflight/prebuild/7z/reextract/postbuild: PASS")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
