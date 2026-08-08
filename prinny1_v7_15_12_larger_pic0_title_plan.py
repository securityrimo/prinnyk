#!/usr/bin/env python3
"""Enlarge the PIC0-style title glyphs inside their verified UV cells."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from prinny1_v7_15_11_pic0_title_style_plan import (
    FOREGROUND,
    PIC0_GLYPHS,
    TRANSPARENT,
    extract_pic0_glyph,
    fit_binary_mask,
)
from scripts.prinny_anime_preview import decode_texture, parse_objects, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
PIC0_SOURCE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/source_png/direct_iso/PIC0.png"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_12_larger_pic0_title_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_12_larger_pic0_title_plan"
TITLE_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_12/anime/anime00/object_078/group_00_page_00.png"
GLYPH_PREVIEW = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_12/pic0_title_glyph_preview.png"

EXPECTED = {
    BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    PIC0_SOURCE: "7fb529379799b875e482553b483ca11fae581a669b37580ac2ac2da4f6f992f7",
}

# object_078의 0x2018부터 확인한 텍스처 셀 정의와 그 안의 확대 영역이다.
LARGER_GLYPHS = (
    {"text": "프", "cell": (256, 160, 320, 224), "target": (262, 166, 314, 218), "table_rel": 0x2018, "table_hex": "010000000001A0004000400000000000"},
    {"text": "리", "cell": (320, 160, 376, 208), "target": (325, 164, 371, 204), "table_rel": 0x2028, "table_hex": "010000004001A0003800300000000000"},
    {"text": "니", "cell": (376, 160, 424, 208), "target": (380, 164, 420, 204), "table_rel": 0x2038, "table_hex": "010000007801A0003000300000000000"},
)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def overlap_count(stream: bytes) -> int:
    _raw, header = decompress_buffer(stream)
    flag = int(header["flag"])
    cursor, end = 0x10, int(header["compressed_end"])
    overlaps = 0
    while cursor < end:
        token = stream[cursor]
        cursor += 1
        if token != flag:
            continue
        second = stream[cursor]
        cursor += 1
        if second == flag:
            continue
        length = stream[cursor]
        cursor += 1
        distance = second if second < flag else second - 1
        overlaps += int(length > distance)
    return overlaps


def enlarge_inside_cells(original: Image.Image, pic0: Image.Image, anime: bytes) -> tuple[Image.Image, list[dict], int, Image.Image]:
    source = original.convert("RGBA")
    edited = source.copy()
    obj = parse_objects(anime)[78]
    source_specs = {spec["text"]: spec for spec in PIC0_GLYPHS}
    preview = Image.new("RGBA", (328, 112), (32, 32, 32, 255))
    preview_x = 8
    manifest = []
    for spec in LARGER_GLYPHS:
        expected_table = bytes.fromhex(spec["table_hex"])
        table_offset = obj.offset + int(spec["table_rel"])
        if anime[table_offset:table_offset + 16] != expected_table:
            raise ValueError(f"object_078 UV 셀 메타데이터 불일치: {spec['text']}")
        cell, target = tuple(spec["cell"]), tuple(spec["target"])
        if not (cell[0] < target[0] < target[2] < cell[2] and cell[1] < target[1] < target[3] < cell[3]):
            raise ValueError(f"확대 글리프가 UV 셀 안전 여백을 벗어남: {spec['text']}")
        mask, source_row = extract_pic0_glyph(pic0, source_specs[spec["text"]])
        target_size = (target[2] - target[0], target[3] - target[1])
        fitted = fit_binary_mask(mask, target_size)
        glyph = Image.new("RGBA", target_size, TRANSPARENT)
        glyph.paste(Image.new("RGBA", target_size, FOREGROUND), (0, 0), fitted)
        edited.paste(TRANSPARENT, cell)
        edited.paste(glyph, target[:2])
        foreground_pixels = sum(1 for value in fitted.getdata() if value)
        source_row.update({
            "uv_cell": list(cell),
            "target_rect": list(target),
            "target_size": list(target_size),
            "target_foreground_pixels": foreground_pixels,
            "cell_fill_ratio": round(foreground_pixels / ((cell[2] - cell[0]) * (cell[3] - cell[1])), 6),
        })
        manifest.append(source_row)
        scaled_preview = fitted.resize((target_size[0] * 2, target_size[1] * 2), Image.Resampling.NEAREST)
        colored = Image.new("RGBA", scaled_preview.size, (255, 255, 255, 0))
        colored.paste((255, 255, 255, 255), (0, 0, *scaled_preview.size), scaled_preview)
        preview.alpha_composite(colored, (preview_x, 5))
        preview_x += scaled_preview.width + 8
    if not set(edited.getdata()).issubset(set(source.getdata())):
        raise ValueError("확대 타이틀에 원본 팔레트 밖 색 생성")
    changed = assert_changes_inside(source, edited, tuple(tuple(spec["cell"]) for spec in LARGER_GLYPHS))
    return edited, manifest, changed, preview


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.12 입력 해시 불일치: {path}")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(base_system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    old_lzs = base_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    base_start, header = decompress_buffer(old_lzs)
    if overlap_count(old_lzs) != 0:
        raise ValueError("V7.15.11 부모 LZS에 겹침 역참조 존재")
    archive = StartRuntimeArchive.from_bytes(base_start)
    anime_record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[anime_record.data_offset:anime_record.end_offset]
    texture = texture_by_key(base_anime, (78, 0, 0))
    original_title = decode_texture(base_anime, texture)
    with Image.open(PIC0_SOURCE) as opened:
        opened.load()
        pic0 = opened.convert("RGBA")
    final_title, glyph_manifest, changed_pixels, preview = enlarge_inside_cells(original_title, pic0, base_anime)
    final_anime = repack_texture(base_anime, texture, final_title)
    if decode_texture(final_anime, texture).convert("RGBA").tobytes() != final_title.tobytes():
        raise ValueError("확대 PIC0 타이틀 아틀라스 왕복 실패")

    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    for row in archive.records:
        before = base_start[row.data_offset:row.end_offset]
        after = bytes(final_start[row.data_offset:row.end_offset])
        if row.output_name.casefold() != "anime00.dat" and before != after:
            raise ValueError(f"비대상 START 자원 변경: {row.output_name}")
    new_lzs = compress_buffer_runtime_safe(bytes(final_start), old_lzs[:4], int(header["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start) or overlap_count(new_lzs) != 0:
        raise ValueError("V7.15.12 런타임 안전 LZS 검증 실패")
    next_offset = rows[start_row["index"] + 1]["data_offset"]
    capacity = next_offset - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError(f"V7.15.12 START.LZS 슬롯 초과: {len(new_lzs)}>{capacity}")
    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:next_offset] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    TITLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final_title.save(TITLE_OUTPUT, format="PNG", optimize=True, compress_level=9)
    preview.save(GLYPH_PREVIEW, format="PNG", optimize=True, compress_level=9)
    artifacts = {"SYSTEM.DAT": bytes(final_system), "start.dat": bytes(final_start), "start.lzs": new_lzs, "anime00.dat": final_anime}
    for name, blob in artifacts.items():
        (OUTPUT / name).write_bytes(blob)
    report = {
        "format": "prinny1_v7_15_12_larger_pic0_title_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "glyphs": glyph_manifest,
            "changed_title_pixels": changed_pixels,
            "old_lzs_size": len(old_lzs),
            "new_lzs_size": len(new_lzs),
            "lzs_capacity": capacity,
            "lzs_overlaps": 0,
            "scale_decision": "approximately_80_percent_of_each_verified_uv_cell",
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()} | {"title_png": sha256_file(TITLE_OUTPUT), "glyph_preview": sha256_file(GLYPH_PREVIEW)},
        "checks": {
            "uv_cell_metadata_byte_exact": True,
            "one_or_more_pixel_transparent_cell_margin": True,
            "changes_inside_three_uv_cells_only": True,
            "original_palette_only": True,
            "only_anime00_changed_inside_start": True,
            "runtime_safe_lzs_non_overlap": True,
            "all_v7_15_11_other_images_inherited": True,
            "iso_created": False,
        },
        "status": "larger_pic0_title_resources_sealed_independent_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"title changed pixels: {changed_pixels}")
    print(f"START.LZS: {len(old_lzs)} -> {len(new_lzs)} / {capacity}; overlaps 0")
    for row in glyph_manifest:
        print(f"{row['text']}: cell {row['uv_cell']} target {row['target_size']} / {row['target_foreground_pixels']} pixels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
