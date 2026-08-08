#!/usr/bin/env python3
"""Build a Korean title that magnifies the proven white-rendering source cells."""
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
from prinny1_v7_15_18_logo_style_title_plan import (
    FONT,
    FONT_LICENSE,
    FOREGROUND,
    TRANSPARENT,
    overlap_count,
    render_mask,
    sha256_file,
)
from scripts.prinny_anime_preview import decode_texture, find_texture_groups, parse_objects, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
V11_TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_11/anime/anime00/object_078/group_00_page_00.png"
ORIGINAL_TITLE = ROOT / "workspace/exports/prinny1_v7_15_18_original_title/original_anime00_object_078_group_00_page_00.png"
SIZE_REFERENCE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/style_references/prinny_size_reference_user.png"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_19_title_uv_magnification_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_19_title_uv_magnification_plan"
TITLE_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_19/anime/anime00/object_078/group_00_page_00.png"
PREVIEW_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_19/title_uv_magnification_preview.png"

EXPECTED = {
    BASE_ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    V11_TITLE: "d3baf482be50ee6ec2c2f10ab94cff3daae847b54807a82e2f62ba31d7f33f35",
    ORIGINAL_TITLE: "1d1ef70633dbf415bb5e4dd0ad6c8d0cd501cff08c3290a36a4485f9325ac4ef",
    SIZE_REFERENCE: "907e01bc7cf7e5c4fd26fded06ea6920fbde691c98a5bdf9a587b27304453d9b",
    FONT: "faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb",
    FONT_LICENSE: "849f4ea9c214fa4ac3593b770c699f387534b11ce671264c1b10d85bdcb5997b",
}

# UV regions proven to render uniformly white in V7.15.11. The glyph is kept
# inside each small source rectangle and the UV table magnifies that rectangle
# to the original sprite geometry.
GLYPHS = (
    {"text": "프", "cell": (256, 160, 320, 224), "uv": (273, 181, 30, 31), "inner": (274, 182, 28, 29), "uv_rel": 0x2018, "base_uv": (1, 256, 160, 64, 64, 0)},
    {"text": "리", "cell": (320, 160, 376, 208), "uv": (331, 161, 28, 26), "inner": (332, 162, 26, 24), "uv_rel": 0x2028, "base_uv": (1, 320, 160, 56, 48, 0)},
    {"text": "니", "cell": (376, 160, 424, 208), "uv": (381, 159, 28, 27), "inner": (382, 160, 26, 25), "uv_rel": 0x2038, "base_uv": (1, 376, 160, 48, 48, 0)},
)
BAR_CELL = (424, 160, 464, 192)
BAR_UV_REL = 0x2048
BAR_UV = (1, 424, 160, 40, 32, 0)
TRANSFORMS = (
    (0x23B4, (-63, -29, 32, 32)), (0x23C4, (-63, -37, 32, 32)),
    (0x23D4, (-7, -38, 28, 24)), (0x23E4, (-6, -46, 28, 24)),
    (0x23F4, (-6, -38, 28, 24)), (0x2404, (39, -50, 24, 24)),
    (0x2414, (39, -58, 24, 24)), (0x2424, (77, -61, 20, 16)),
    (0x2434, (77, -69, 20, 16)),
)
POSITION_WRITES = (
    ("프", 0x23B4, (-63, -29, 32, 32), (-69, -29, 32, 32)),
    ("프", 0x23C4, (-63, -37, 32, 32), (-69, -37, 32, 32)),
    ("니", 0x2404, (39, -50, 24, 24), (43, -50, 24, 24)),
    ("니", 0x2414, (39, -58, 24, 24), (43, -58, 24, 24)),
)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def pack_uv(values: tuple[int, int, int, int, int, int]) -> bytes:
    return struct.pack("<I4HI", *values)


def build_title(source: Image.Image) -> tuple[Image.Image, list[dict], int, int, Image.Image]:
    original = source.convert("RGBA")
    edited = original.copy()
    rows: list[dict] = []
    for spec in GLYPHS:
        edited.paste(TRANSPARENT, spec["cell"])
        x, y, width, height = spec["inner"]
        mask = render_mask(spec["text"], (width, height))
        glyph = Image.new("RGBA", (width, height), TRANSPARENT)
        glyph.paste(Image.new("RGBA", (width, height), FOREGROUND), (0, 0), mask)
        edited.alpha_composite(glyph, (x, y))
        rows.append({
            "text": spec["text"],
            "cell": list(spec["cell"]),
            "uv_source_rect": list(spec["uv"]),
            "glyph_rect": list(spec["inner"]),
            "foreground_pixels": sum(value != 0 for value in mask.getdata()),
        })
    old_bar_pixels = sum(pixel[3] != 0 for pixel in original.crop(BAR_CELL).getdata())
    if old_bar_pixels != 308:
        raise ValueError(f"일본어 장음표 기준 불일치: {old_bar_pixels}")
    edited.paste(TRANSPARENT, BAR_CELL)
    if not set(edited.getdata()).issubset(set(original.getdata())):
        raise ValueError("타이틀이 부모 atlas 팔레트 밖 색을 생성함")
    changed = assert_changes_inside(original, edited, tuple(spec["cell"] for spec in GLYPHS) + (BAR_CELL,))

    # Static UV preview: enlarge each tight sample rectangle to its original UV
    # dimensions. This is an approximation; final color/blending needs PPSSPP.
    preview = Image.new("RGBA", (208, 64), (30, 30, 30, 255))
    cursor = 0
    for spec in GLYPHS:
        ux, uy, uw, uh = spec["uv"]
        _one, _bx, _by, bw, bh, _zero = spec["base_uv"]
        sampled = edited.crop((ux, uy, ux + uw, uy + uh)).resize((bw, bh), Image.Resampling.NEAREST)
        white = Image.new("RGBA", sampled.size, (255, 255, 255, 0))
        white.putalpha(sampled.getchannel("A"))
        preview.alpha_composite(white, (cursor, 0))
        cursor += bw
    return edited, rows, changed, old_bar_pixels, preview


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.19 입력 해시 불일치: {path}")
    if "Open Font License" not in FONT_LICENSE.read_text(encoding="utf-8", errors="replace"):
        raise ValueError("Noto CJK OFL 라이선스 근거 누락")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    system_rows = system_records(base_system)
    start_row = next(row for row in system_rows if row["name"].casefold() == "start.lzs")
    old_lzs = base_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    base_start, header = decompress_buffer(old_lzs)
    if overlap_count(old_lzs):
        raise ValueError("V7.15.16 부모 START.LZS 겹침 역참조")
    archive = StartRuntimeArchive.from_bytes(base_start)
    anime_record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[anime_record.data_offset:anime_record.end_offset]
    objects = parse_objects(base_anime)
    obj = objects[78]
    groups = find_texture_groups(base_anime, obj)
    if len(groups) != 1 or len(groups[0]) != 1:
        raise ValueError("object_078가 단일 512x512 atlas가 아님")
    texture = texture_by_key(base_anime, (78, 0, 0))
    base_title = decode_texture(base_anime, texture).convert("RGBA")
    with Image.open(V11_TITLE) as opened:
        opened.load()
        if base_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("부모 타이틀이 V7.15.11 흰색 정상 기준과 다름")
    for spec in GLYPHS:
        before = base_anime[obj.offset + spec["uv_rel"]:obj.offset + spec["uv_rel"] + 16]
        if before != pack_uv(spec["base_uv"]):
            raise ValueError(f"기준 UV 불일치: {spec['text']}")
    if base_anime[obj.offset + BAR_UV_REL:obj.offset + BAR_UV_REL + 16] != pack_uv(BAR_UV):
        raise ValueError("장음표 기준 UV 불일치")
    for relative, values in TRANSFORMS:
        if base_anime[obj.offset + relative:obj.offset + relative + 8] != struct.pack("<2h2H", *values):
            raise ValueError(f"기준 transform 불일치: 0x{relative:X}")

    final_title, glyph_rows, changed_pixels, removed_bar_pixels, preview = build_title(base_title)
    final_anime = bytearray(repack_texture(base_anime, texture, final_title))
    uv_writes = []
    for spec in GLYPHS:
        relative = spec["uv_rel"]
        before = bytes(final_anime[obj.offset + relative:obj.offset + relative + 16])
        ux, uy, uw, uh = spec["uv"]
        after = pack_uv((1, ux, uy, uw, uh, 0))
        final_anime[obj.offset + relative:obj.offset + relative + 16] = after
        uv_writes.append({"text": spec["text"], "object_relative_offset": f"0x{relative:X}", "before_hex": before.hex().upper(), "after_hex": after.hex().upper()})
    position_writes = []
    for text, relative, before_values, after_values in POSITION_WRITES:
        before = bytes(final_anime[obj.offset + relative:obj.offset + relative + 8])
        if before != struct.pack("<2h2H", *before_values):
            raise ValueError(f"좌표 쓰기 전 transform 불일치: 0x{relative:X}")
        after = struct.pack("<2h2H", *after_values)
        final_anime[obj.offset + relative:obj.offset + relative + 8] = after
        position_writes.append({"text": text, "object_relative_offset": f"0x{relative:X}", "before": list(before_values), "after": list(after_values)})
    final_anime = bytes(final_anime)
    if decode_texture(final_anime, texture).convert("RGBA").tobytes() != final_title.tobytes():
        raise ValueError("V7.15.19 atlas 왕복 실패")
    position_by_offset = {relative: after for _text, relative, _before, after in POSITION_WRITES}
    for relative, values in TRANSFORMS:
        expected_values = position_by_offset.get(relative, values)
        if final_anime[obj.offset + relative:obj.offset + relative + 8] != struct.pack("<2h2H", *expected_values):
            raise ValueError("V7.15.19 transform 결과 불일치")

    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    for row in archive.records:
        if row.output_name.casefold() != "anime00.dat" and base_start[row.data_offset:row.end_offset] != final_start[row.data_offset:row.end_offset]:
            raise ValueError(f"비대상 START 자원 변경: {row.output_name}")
    new_lzs = compress_buffer_runtime_safe(bytes(final_start), old_lzs[:4], int(header["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start) or overlap_count(new_lzs):
        raise ValueError("V7.15.19 런타임 안전 LZS 검증 실패")
    next_offset = system_rows[start_row["index"] + 1]["data_offset"]
    capacity = next_offset - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError(f"START.LZS 슬롯 초과: {len(new_lzs)}>{capacity}")
    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:next_offset] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    TITLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final_title.save(TITLE_OUTPUT, format="PNG", optimize=True, compress_level=9)
    preview.resize((832, 256), Image.Resampling.NEAREST).save(PREVIEW_OUTPUT, format="PNG", optimize=True, compress_level=9)
    artifacts = {"SYSTEM.DAT": bytes(final_system), "start.dat": bytes(final_start), "start.lzs": new_lzs, "anime00.dat": final_anime}
    for name, blob in artifacts.items():
        (OUTPUT / name).write_bytes(blob)
    report = {
        "format": "prinny1_v7_15_19_title_uv_magnification_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "glyph_style_source": {"kind": "installed_font", "family": "Noto Sans CJK KR", "style": "Bold", "collection_index": 1, "license": "SIL Open Font License", "reason": "closest installed Korean heavy block style to the PRINNY logo"},
        "user_image_reference": {"path": str(SIZE_REFERENCE), "sha256": sha256_file(SIZE_REFERENCE), "use": "size_and_proportion_only", "glyph_shape_used": False},
        "title_scene_asset_audit": {
            "japanese_title_glyph_source": "START.DAT/anime00.dat/object_078/group_00_page_00",
            "object_078_texture_pages": 1,
            "other_composited_assets": ["object_078 red plaque and PRINNY logo", "object_079 board/effect layers", "object_080 title background"],
            "xmb_pic0_is_not_ingame_title_source": True,
            "separate_white_japanese_title_bitmap_found": False,
        },
        "verified": {"glyphs": glyph_rows, "uv_writes": uv_writes, "position_writes": position_writes, "calculated_screen_bounds_px": [-69, 67], "calculated_screen_width_px": 136, "changed_title_pixels": changed_pixels, "removed_long_mark_pixels": removed_bar_pixels, "old_lzs_size": len(old_lzs), "new_lzs_size": len(new_lzs), "lzs_capacity": capacity, "lzs_overlaps": 0},
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()} | {"title_png": sha256_file(TITLE_OUTPUT), "preview_png": sha256_file(PREVIEW_OUTPUT)},
        "checks": {"only_proven_small_source_regions_used": True, "three_uv_descriptors_changed": True, "only_four_outer_x_coordinates_changed": True, "all_y_and_size_values_unchanged": True, "calculated_title_width_136px": True, "japanese_long_mark_removed": True, "only_four_title_cells_changed": True, "only_anime00_changed_inside_start": True, "runtime_safe_lzs_non_overlap": True, "iso_created": False},
        "status": "title_uv_magnification_resources_sealed_independent_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"title pixels changed: {changed_pixels}; long mark removed: {removed_bar_pixels}")
    print(f"START.LZS: {len(old_lzs)} -> {len(new_lzs)} / {capacity}; overlaps 0")
    for row in uv_writes:
        print(f"{row['text']} UV {row['before_hex']} -> {row['after_hex']}")
    print("screen title bounds: -69..67 = 136 px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
