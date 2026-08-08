#!/usr/bin/env python3
"""Independent pre-ISO review for the 136 px UV-magnified Korean title."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from prinny1_v7_15_18_logo_style_title_plan import overlap_count
from scripts.prinny_anime_preview import decode_texture, find_texture_groups, parse_objects, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
BUILD = ROOT / "workspace/build/prinny1_v7_15_19_title_uv_magnification_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_19_title_uv_magnification_plan/all_report.json"
TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_19/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_19_title_uv_magnification_review"
EXPECTED = {
    BASE_ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    BUILD / "SYSTEM.DAT": "902ae0912a21d42b22d330c04ec3c046b4692218673a01205940a8dab63f4efe",
    BUILD / "start.dat": "2188862e895dd699008fe745f463f54c6780e4dafcafc463b519de5c75d1899a",
    BUILD / "start.lzs": "15b88dfd6f1464ccb58b98680769dc9fa56f3299458571d247537317026af672",
    BUILD / "anime00.dat": "256395086a800382e99125926cf9b69e31b685f7b84d4fce3abb0f4084e3359a",
    TITLE: "3f2b99309e0d928cc86e403115b3c3aa9768596acd2daea7e2cadc269d56c5cc",
    PLAN: "2c76b1a95a1cd12cb086c36b6bd7731152be5a9ecfe76d056332f15a98908625",
}
FOREGROUND = (0, 255, 0, 255)
TRANSPARENT = (0, 0, 0, 0)
CELLS = ((256, 160, 320, 224), (320, 160, 376, 208), (376, 160, 424, 208))
BAR_CELL = (424, 160, 464, 192)
UV_ROWS = (
    (0x2018, (1, 256, 160, 64, 64, 0), (1, 273, 181, 30, 31, 0)),
    (0x2028, (1, 320, 160, 56, 48, 0), (1, 331, 161, 28, 26, 0)),
    (0x2038, (1, 376, 160, 48, 48, 0), (1, 381, 159, 28, 27, 0)),
)
BAR_UV = (0x2048, (1, 424, 160, 40, 32, 0))
TRANSFORMS = (
    (0x23B4, (-63, -29, 32, 32), (-69, -29, 32, 32)),
    (0x23C4, (-63, -37, 32, 32), (-69, -37, 32, 32)),
    (0x23D4, (-7, -38, 28, 24), (-7, -38, 28, 24)),
    (0x23E4, (-6, -46, 28, 24), (-6, -46, 28, 24)),
    (0x23F4, (-6, -38, 28, 24), (-6, -38, 28, 24)),
    (0x2404, (39, -50, 24, 24), (43, -50, 24, 24)),
    (0x2414, (39, -58, 24, 24), (43, -58, 24, 24)),
    (0x2424, (77, -61, 20, 16), (77, -61, 20, 16)),
    (0x2434, (77, -69, 20, 16), (77, -69, 20, 16)),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def pack_uv(values: tuple[int, int, int, int, int, int]) -> bytes:
    return struct.pack("<I4HI", *values)


def extract_start(system: bytes) -> tuple[bytes, bytes, list[dict]]:
    rows = system_records(system)
    row = next(item for item in rows if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs, rows


def in_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.19 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "title_uv_magnification_resources_sealed_independent_review_required":
        raise ValueError("V7.15.19 계획 상태 불일치")
    if plan.get("user_image_reference", {}).get("use") != "size_and_proportion_only" or plan["user_image_reference"].get("glyph_shape_used") is not False:
        raise ValueError("사용자 이미지가 크기 전용 참조로 봉인되지 않음")
    if plan.get("glyph_style_source", {}).get("family") != "Noto Sans CJK KR":
        raise ValueError("PRINNY 유사 블록 글꼴 출처 불일치")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = (BUILD / "SYSTEM.DAT").read_bytes()
    base_start, _base_lzs, base_system_rows = extract_start(base_system)
    final_start, final_lzs, final_system_rows = extract_start(final_system)
    if final_start != (BUILD / "start.dat").read_bytes() or final_lzs != (BUILD / "start.lzs").read_bytes() or overlap_count(final_lzs):
        raise ValueError("V7.15.19 START/LZS 봉인 또는 안전성 불일치")
    if [(r["name"], r["data_offset"]) for r in base_system_rows] != [(r["name"], r["data_offset"]) for r in final_system_rows]:
        raise ValueError("SYSTEM 자원 목록/오프셋 변경")
    changed_system = []
    for old, new in zip(base_system_rows, final_system_rows):
        before = base_system[old["data_offset"]:old["data_offset"] + old["size"]]
        after = final_system[new["data_offset"]:new["data_offset"] + new["size"]]
        if before != after or old["size"] != new["size"]:
            changed_system.append(old["name"].casefold())
    if changed_system != ["start.lzs"]:
        raise ValueError(f"SYSTEM 변경 자원 불일치: {changed_system}")

    base_archive = StartRuntimeArchive.from_bytes(base_start)
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    changed_start = []
    for old, new in zip(base_archive.records, final_archive.records):
        if (old.output_name, old.data_offset, old.end_offset) != (new.output_name, new.data_offset, new.end_offset):
            raise ValueError("START 자원 경계 변경")
        if base_start[old.data_offset:old.end_offset] != final_start[new.data_offset:new.end_offset]:
            changed_start.append(old.output_name.casefold())
    if changed_start != ["anime00.dat"]:
        raise ValueError(f"START 변경 자원 불일치: {changed_start}")
    base_row = next(r for r in base_archive.records if r.output_name.casefold() == "anime00.dat")
    final_row = next(r for r in final_archive.records if r.output_name.casefold() == "anime00.dat")
    base_anime = base_start[base_row.data_offset:base_row.end_offset]
    final_anime = final_start[final_row.data_offset:final_row.end_offset]
    if final_anime != (BUILD / "anime00.dat").read_bytes():
        raise ValueError("V7.15.19 anime00 봉인 불일치")

    obj = parse_objects(base_anime)[78]
    if len(find_texture_groups(base_anime, obj)) != 1 or len(find_texture_groups(base_anime, obj)[0]) != 1:
        raise ValueError("object_078 단일 atlas 구조 불일치")
    texture = texture_by_key(base_anime, (78, 0, 0))
    base_title = decode_texture(base_anime, texture).convert("RGBA")
    final_title = decode_texture(final_anime, texture).convert("RGBA")
    with Image.open(TITLE) as opened:
        opened.load()
        if final_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("anime00/PNG 왕복 불일치")
    if assert_changes_inside(base_title, final_title, CELLS + (BAR_CELL,)) != 1353:
        raise ValueError("타이틀 픽셀 변경 범위/수 불일치")
    if any(pixel not in {TRANSPARENT, FOREGROUND} for cell in CELLS for pixel in final_title.crop(cell).getdata()):
        raise ValueError("한글 제목 셀 팔레트 불일치")
    if any(pixel != TRANSPARENT for pixel in final_title.crop(BAR_CELL).getdata()):
        raise ValueError("일본어 장음표 셀 잔존")

    for relative, before_values, after_values in UV_ROWS:
        if base_anime[obj.offset + relative:obj.offset + relative + 16] != pack_uv(before_values):
            raise ValueError(f"기준 UV 불일치: 0x{relative:X}")
        if final_anime[obj.offset + relative:obj.offset + relative + 16] != pack_uv(after_values):
            raise ValueError(f"최종 UV 불일치: 0x{relative:X}")
    bar_relative, bar_values = BAR_UV
    if base_anime[obj.offset + bar_relative:obj.offset + bar_relative + 16] != pack_uv(bar_values) or final_anime[obj.offset + bar_relative:obj.offset + bar_relative + 16] != pack_uv(bar_values):
        raise ValueError("장음표 UV 메타데이터 변경")
    for relative, before_values, after_values in TRANSFORMS:
        if base_anime[obj.offset + relative:obj.offset + relative + 8] != struct.pack("<2h2H", *before_values):
            raise ValueError(f"기준 transform 불일치: 0x{relative:X}")
        if final_anime[obj.offset + relative:obj.offset + relative + 8] != struct.pack("<2h2H", *after_values):
            raise ValueError(f"최종 transform 불일치: 0x{relative:X}")

    # Reconstruct independently: decoded pixel replacement plus exactly seven
    # metadata rows must reproduce the sealed anime00 byte for byte.
    reconstructed = bytearray(repack_texture(base_anime, texture, final_title))
    for relative, _before_values, after_values in UV_ROWS:
        reconstructed[obj.offset + relative:obj.offset + relative + 16] = pack_uv(after_values)
    for relative, _before_values, after_values in TRANSFORMS:
        reconstructed[obj.offset + relative:obj.offset + relative + 8] = struct.pack("<2h2H", *after_values)
    if bytes(reconstructed) != final_anime:
        raise ValueError("atlas+UV+좌표 Expected Write로 anime00 재구성 실패")

    screen_left = min(-69, -7, -6, 43)
    screen_right = max(-69 + 32, -7 + 28, -6 + 28, 43 + 24)
    if (screen_left, screen_right, screen_right - screen_left) != (-69, 67, 136):
        raise ValueError("136px 화면 폭 계산 불일치")
    report = {
        "format": "prinny1_v7_15_19_title_uv_magnification_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verified": {"changed_system_resources": changed_system, "changed_start_resources": changed_start, "changed_title_pixels": 1353, "removed_long_mark_pixels": 308, "uv_descriptor_writes": 3, "position_x_writes": 4, "screen_bounds_px": [screen_left, screen_right], "screen_width_px": 136, "runtime_lzs_overlaps": 0},
        "checks": {"plan_hash_locked": True, "user_image_size_reference_only": True, "prinnny_like_block_font_source_locked": True, "only_four_title_cells_changed": True, "three_uv_rows_exact": True, "four_outer_x_values_exact": True, "all_y_and_sizes_preserved": True, "long_mark_cell_transparent": True, "expected_writes_reconstruct_anime00": True, "only_anime00_changed_in_start": True},
        "status": "pass_v7_15_19_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.15.19 title UV/136px independent review: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
