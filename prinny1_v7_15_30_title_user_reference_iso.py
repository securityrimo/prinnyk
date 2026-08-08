#!/usr/bin/env python3
"""Rebuild the plaque title from the exact user-supplied white glyph mask."""
from __future__ import annotations

import csv
import json
import os
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE
from prinny1_v7_15_28_title_plaque_korean_iso import (
    TITLE_TEXT,
    changed_start_resources,
    overlap_count,
)
from prinny1_v7_15_29_title_plaque_white_index_iso import (
    extract_anime,
    extract_start,
    extract_system,
    linear_indices,
    palette,
    repack_indices,
    sha256_bytes,
    sha256_file,
    title_positions,
)
from scripts.prinny_anime_preview import decode_texture
from prinny1_v7_15_6_ui_image_plan import texture_by_key


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_29_title_plaque_white_index"
    / "prinny_korean_v7_15_29_title_plaque_white_index.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_30_title_user_reference"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_30_title_user_reference.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_30_title_user_reference_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_30_title_user_reference"
PREVIEW_DIR = (
    ROOT
    / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
    / "translated/resized_v7_15_30/anime/anime00/object_078"
)
TITLE_PNG = PREVIEW_DIR / "group_00_page_00.png"
TITLE_PREVIEW = PREVIEW_DIR / "user_reference_plaque_preview_4x.png"
USER_REFERENCE = Path("/home/hyuk/사진/타이틀화면.png")
V29_RUNTIME = ROOT / "evidence/prinny1_v7_15_29_runtime_title.png"

EXPECTED_BASE_SHA256 = "f720efb1d1101370d8c6dd625b914dfac8852aa03b58ef5101244c9f527c052b"
EXPECTED_USER_REFERENCE_SHA256 = "97dde8dce233c87ca3a4d009ceeb202262ed23a56f274912454be7859793fe67"
FILL_INDEX = 6
WHITE_INDEX = 15
FILL_RGBA = (249, 198, 197, 255)
WHITE_SOURCE_RGBA = (0, 255, 0, 255)
SCREEN_PLAQUE_RED_BBOX = (288, 68, 742, 309)
ATLAS_PLAQUE_FILL_BBOX = (19, 172, 246, 293)
REFERENCE_ROI = (315, 85, 680, 285)
REFERENCE_COMPONENTS = {
    (4937, (445, 140, 550, 236)),
    (4101, (542, 108, 648, 204)),
    (3193, (350, 173, 442, 246)),
    (1372, (367, 234, 455, 276)),
}
EXPECTED_TARGET_BBOX = (50, 192, 199, 277)
EXPECTED_TARGET_PIXELS = 3658


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(name: str, report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def white_reference_components() -> list[set[tuple[int, int]]]:
    image = Image.open(USER_REFERENCE).convert("RGB")
    left, top, right, bottom = REFERENCE_ROI
    remaining = set()
    for y in range(top, bottom):
        for x in range(left, right):
            red, green, blue = image.getpixel((x, y))
            if min(red, green, blue) > 215 and max(red, green, blue) - min(red, green, blue) < 45:
                remaining.add((x, y))
    selected: list[set[tuple[int, int]]] = []
    while remaining:
        seed = remaining.pop()
        queue = [seed]
        component = {seed}
        for x, y in queue:
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if point in remaining:
                    remaining.remove(point)
                    component.add(point)
                    queue.append(point)
        xs = [x for x, _y in component]
        ys = [y for _x, y in component]
        signature = (
            len(component),
            (min(xs), min(ys), max(xs) + 1, max(ys) + 1),
        )
        if signature in REFERENCE_COMPONENTS:
            selected.append(component)
    signatures = {
        (
            len(component),
            (
                min(x for x, _y in component),
                min(y for _x, y in component),
                max(x for x, _y in component) + 1,
                max(y for _x, y in component) + 1,
            ),
        )
        for component in selected
    }
    if signatures != REFERENCE_COMPONENTS:
        raise ValueError("사용자 시안의 네 한글 연결 요소가 봉인값과 다릅니다")
    return selected


def target_positions() -> tuple[list[int], Image.Image]:
    screen_left, screen_top, screen_right, screen_bottom = SCREEN_PLAQUE_RED_BBOX
    atlas_left, atlas_top, atlas_right, atlas_bottom = ATLAS_PLAQUE_FILL_BBOX
    scale_x = (screen_right - screen_left) / (atlas_right - atlas_left)
    scale_y = (screen_bottom - screen_top) / (atlas_bottom - atlas_top)
    mask = Image.new("L", (512, 512), 0)
    for component in white_reference_components():
        for x, y in component:
            atlas_x = round(atlas_left + (x - screen_left) / scale_x)
            atlas_y = round(atlas_top + (y - screen_top) / scale_y)
            if not (0 <= atlas_x < 512 and 0 <= atlas_y < 512):
                raise ValueError("역투영한 사용자 글자 좌표가 아틀라스를 벗어납니다")
            mask.putpixel((atlas_x, atlas_y), 255)
    positions = [
        y * 512 + x
        for y in range(512)
        for x in range(512)
        if mask.getpixel((x, y))
    ]
    if mask.getbbox() != EXPECTED_TARGET_BBOX or len(positions) != EXPECTED_TARGET_PIXELS:
        raise ValueError(
            f"사용자 글자 역투영 불일치: {mask.getbbox()}/{len(positions)}"
        )
    return positions, mask


def patch_user_title(base_anime: bytes) -> tuple[bytes, dict, Image.Image]:
    texture = texture_by_key(base_anime, (78, 0, 0))
    colors = palette(base_anime, texture)
    if colors[FILL_INDEX] != FILL_RGBA or colors[WHITE_INDEX] != WHITE_SOURCE_RGBA:
        raise ValueError("명패 채움/런타임 흰색 CLUT 기준 불일치")
    before = linear_indices(base_anime, texture)
    old_positions = title_positions()
    new_positions, target_mask = target_positions()
    if any(before[position] != WHITE_INDEX for position in old_positions):
        raise ValueError("V7.15.29 기존 흰 제목 인덱스 불일치")
    after = before.copy()
    for position in old_positions:
        after[position] = FILL_INDEX
    if any(after[position] != FILL_INDEX for position in new_positions):
        bad = [(position, after[position]) for position in new_positions if after[position] != FILL_INDEX]
        raise ValueError(f"사용자 글자가 명패 채움 영역 밖을 침범합니다: {bad[:8]}")
    for position in new_positions:
        after[position] = WHITE_INDEX
    allowed = set(old_positions) | set(new_positions)
    changed = [position for position, (old, new) in enumerate(zip(before, after)) if old != new]
    if set(changed) - allowed:
        raise ValueError("현재/목표 제목 합집합 밖 인덱스 변경")
    final_anime = repack_indices(base_anime, texture, after)
    pixel_end = texture.pixel_offset + texture.width * texture.height // 2
    if (
        base_anime[:texture.pixel_offset] != final_anime[:texture.pixel_offset]
        or base_anime[pixel_end:] != final_anime[pixel_end:]
    ):
        raise ValueError("타이틀 픽셀 스트림 밖 anime00 변경")
    final_title = decode_texture(final_anime, texture).convert("RGBA")
    decoded_changed = sum(
        a != b
        for a, b in zip(
            decode_texture(base_anime, texture).convert("RGBA").getdata(),
            final_title.getdata(),
        )
    )
    return final_anime, {
        "title_text": TITLE_TEXT,
        "user_reference_sha256": sha256_file(USER_REFERENCE),
        "old_mask_bbox": [59, 191, 202, 266],
        "old_mask_pixels": len(old_positions),
        "target_mask_bbox": list(target_mask.getbbox()),
        "target_mask_pixels": len(new_positions),
        "logical_pixels_changed": len(changed),
        "decoded_rgba_changed_pixels": decoded_changed,
        "fill_index": FILL_INDEX,
        "runtime_white_index": WHITE_INDEX,
        "palette_table_changes": 0,
        "uv_transform_changes": 0,
    }, final_title


def preflight_and_seal() -> dict:
    if sha256_file(BASE_ISO) != EXPECTED_BASE_SHA256:
        raise ValueError("V7.15.30 부모 ISO 해시 불일치")
    if sha256_file(USER_REFERENCE) != EXPECTED_USER_REFERENCE_SHA256:
        raise ValueError("사용자 타이틀 시안 해시 불일치")
    if not V29_RUNTIME.is_file():
        raise ValueError("V7.15.29 런타임 캡처 누락")
    system, _record = extract_system(BASE_ISO)
    start, old_lzs, row, rows = extract_start(system)
    if overlap_count(old_lzs):
        raise ValueError("부모 LZS 겹침 역참조")
    base_anime, anime_record = extract_anime(start)
    final_anime, mask_meta, final_title = patch_user_title(base_anime)
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
        raise ValueError("V7.15.30 런타임 안전 LZS 왕복 실패")
    capacity = rows[row["index"] + 1]["data_offset"] - row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError("V7.15.30 START.LZS 슬롯 초과")
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
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "SYSTEM.DAT": final_system_bytes,
        "start.dat": final_start_bytes,
        "start.lzs": new_lzs,
        "anime00.dat": final_anime,
    }
    for name, blob in artifacts.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    final_title.save(TITLE_PNG, format="PNG", optimize=True, compress_level=9)
    final_title.crop((0, 160, 260, 305)).resize(
        (1040, 580), Image.Resampling.NEAREST
    ).save(TITLE_PREVIEW, format="PNG", optimize=True, compress_level=9)
    expected_write = {
        "id": "P1-V7.15.30-TITLE-0001",
        "target": "START.DAT/anime00.dat/object_078/group_00_page_00",
        "operation": "replace_v29_title_mask_with_user_reference_mask",
        "old_pixels": mask_meta["old_mask_pixels"],
        "target_pixels": mask_meta["target_mask_pixels"],
        "before_anime_sha256": sha256_bytes(base_anime),
        "after_anime_sha256": sha256_bytes(final_anime),
        "palette_uv_transform_changes": 0,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / "expected_writes.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(expected_write))
        writer.writeheader()
        writer.writerow(expected_write)
    report = {
        "format": "prinny1_v7_15_30_user_reference_title_preflight_v1",
        "created_at": now(),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "user_reference": {
            "path": str(USER_REFERENCE),
            "sha256": sha256_file(USER_REFERENCE),
            "use": "exact_white_title_glyph_mask_and_plaque_relative_geometry",
        },
        "v29_runtime": {"path": str(V29_RUNTIME), "sha256": sha256_file(V29_RUNTIME)},
        "mask_patch": mask_meta,
        "expected_write": expected_write,
        "lzs": {
            "old_size": len(old_lzs),
            "new_size": len(new_lzs),
            "capacity": capacity,
            "overlap_backreferences": 0,
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()}
        | {"title_png": sha256_file(TITLE_PNG), "preview_png": sha256_file(TITLE_PREVIEW)},
        "checks": {
            "exact_user_mask_components_locked": True,
            "target_mask_inside_plaque_fill": True,
            "runtime_white_index_preserved": True,
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
    expected_anime, meta, _title = patch_user_title(base_anime)
    if final_anime != expected_anime or final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("독립 사전 사용자 마스크 재계산/봉인 불일치")
    report = {
        "format": "prinny1_v7_15_30_user_reference_title_prebuild_review_v1",
        "created_at": now(),
        "verified": meta | {"changed_start_resources": ["anime00.dat"], "lzs_overlaps": 0},
        "checks": {
            "fresh_user_reference_extraction": True,
            "fresh_mask_projection": True,
            "sealed_resources_exact": True,
            "palette_uv_transform_unchanged": True,
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
        raise ValueError("V7.15.30 독립 사전 검토 미통과")
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.30 출력 ISO가 이미 존재합니다")
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
        raise ValueError("V7.15.30 ISO 7z 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_30_user_reference_title_iso_v1",
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
    expected_anime, meta, _title = patch_user_title(base_anime)
    if final_anime != expected_anime or final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("사후 사용자 마스크 재계산/anime00 봉인 불일치")
    test = subprocess.run(
        ["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False
    )
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_30_user_reference_title_postbuild_review_v1",
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
            "fresh_user_reference_mask_recalculation": True,
            "palette_uv_transform_unchanged": True,
            "only_anime00_changed_in_start": True,
            "seven_zip_structure_retest": True,
        },
        "status": "pass_ready_for_ppsspp_title_runtime_test",
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
    print(f"user title mask: {EXPECTED_TARGET_PIXELS} px / {EXPECTED_TARGET_BBOX}")
    print("preflight/prebuild/7z/reextract/postbuild: PASS")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
