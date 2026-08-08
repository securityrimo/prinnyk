#!/usr/bin/env python3
"""Build a logo-weight Korean title and remove the residual Japanese long mark."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from scripts.prinny_anime_preview import decode_texture, parse_objects, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
FONT_LICENSE = Path("/usr/share/doc/fonts-noto-cjk/copyright")
JP_REFERENCE = ROOT / "workspace/reports/prinny1_v7_15_0_internal_image_audit/current_anime00/object_078/group_00_page_00.png"
V11_TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_11/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_18_logo_style_title_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_18_logo_style_title_plan"
TITLE_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_18/anime/anime00/object_078/group_00_page_00.png"
PREVIEW_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_18/logo_style_title_preview.png"

EXPECTED = {
    BASE_ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    FONT: "faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb",
    FONT_LICENSE: "849f4ea9c214fa4ac3593b770c699f387534b11ce671264c1b10d85bdcb5997b",
    JP_REFERENCE: "bc4ca61f6da5d1d46b0e522a39f6aa2c58f105d8e5c6341727cb9fb6632f990a",
    V11_TITLE: "d3baf482be50ee6ec2c2f10ab94cff3daae847b54807a82e2f62ba31d7f33f35",
}
FOREGROUND = (0, 255, 0, 255)
TRANSPARENT = (0, 0, 0, 0)

# These rectangles reproduce the occupied bounds of the original Japanese
# title cells, but replace the glyph shapes with Korean Noto Sans CJK Bold.
GLYPHS = (
    {"text": "프", "cell": (256, 160, 320, 224), "target": (263, 166, 318, 219)},
    {"text": "리", "cell": (320, 160, 376, 208), "target": (323, 165, 371, 201)},
    {"text": "니", "cell": (376, 160, 424, 208), "target": (378, 163, 422, 205)},
)
BAR_CELL = (424, 160, 464, 192)
EXPECTED_TRANSFORMS = (
    (0x23B4, (-63, -29, 32, 32)),
    (0x23C4, (-63, -37, 32, 32)),
    (0x23D4, (-7, -38, 28, 24)),
    (0x23E4, (-6, -46, 28, 24)),
    (0x23F4, (-6, -38, 28, 24)),
    (0x2404, (39, -50, 24, 24)),
    (0x2414, (39, -58, 24, 24)),
    (0x2424, (77, -61, 20, 16)),
    (0x2434, (77, -69, 20, 16)),
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


def render_mask(text: str, size: tuple[int, int]) -> Image.Image:
    font = ImageFont.truetype(str(FONT), 160, index=1)
    scratch = Image.new("L", (256, 256), 0)
    draw = ImageDraw.Draw(scratch)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    draw.text((8 - bbox[0], 8 - bbox[1]), text, font=font, fill=255, stroke_width=2, stroke_fill=255)
    trimmed = scratch.crop(scratch.getbbox())
    thick = trimmed.filter(ImageFilter.MaxFilter(3))
    resized = thick.resize(size, Image.Resampling.LANCZOS)
    return resized.point(lambda value: 255 if value >= 96 else 0)


def build_title(source: Image.Image) -> tuple[Image.Image, list[dict], int, int, Image.Image]:
    original = source.convert("RGBA")
    edited = original.copy()
    preview = Image.new("RGBA", (176, 64), (32, 32, 32, 255))
    manifest = []
    for spec in GLYPHS:
        cell, target = tuple(spec["cell"]), tuple(spec["target"])
        size = (target[2] - target[0], target[3] - target[1])
        mask = render_mask(spec["text"], size)
        glyph = Image.new("RGBA", size, TRANSPARENT)
        glyph.paste(Image.new("RGBA", size, FOREGROUND), (0, 0), mask)
        edited.paste(TRANSPARENT, cell)
        edited.paste(glyph, target[:2])
        preview_glyph = Image.new("RGBA", size, TRANSPARENT)
        preview_glyph.paste((255, 255, 255, 255), (0, 0, *size), mask)
        preview.alpha_composite(preview_glyph, (target[0] - 256, target[1] - 160))
        pixels = sum(value != 0 for value in mask.getdata())
        manifest.append({
            "text": spec["text"],
            "cell": list(cell),
            "target_rect": list(target),
            "target_size": list(size),
            "foreground_pixels": pixels,
        })
    old_bar_pixels = sum(pixel[3] != 0 for pixel in original.crop(BAR_CELL).getdata())
    if old_bar_pixels != 308:
        raise ValueError(f"일본어 장음표 픽셀 기준 불일치: {old_bar_pixels}")
    edited.paste(TRANSPARENT, BAR_CELL)
    if not set(edited.getdata()).issubset(set(original.getdata())):
        raise ValueError("로고형 타이틀이 원본 팔레트 밖 색을 생성함")
    changed = assert_changes_inside(original, edited, tuple(spec["cell"] for spec in GLYPHS) + (BAR_CELL,))
    return edited, manifest, changed, old_bar_pixels, preview


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.18 입력 해시 불일치: {path}")
    if "Open Font License" not in FONT_LICENSE.read_text(encoding="utf-8", errors="replace"):
        raise ValueError("Noto CJK OFL 라이선스 근거 누락")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(base_system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    old_lzs = base_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    base_start, header = decompress_buffer(old_lzs)
    if overlap_count(old_lzs):
        raise ValueError("V7.15.16 부모 START.LZS 겹침 역참조")
    archive = StartRuntimeArchive.from_bytes(base_start)
    anime_record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[anime_record.data_offset:anime_record.end_offset]
    texture = texture_by_key(base_anime, (78, 0, 0))
    base_title = decode_texture(base_anime, texture).convert("RGBA")
    with Image.open(V11_TITLE) as opened:
        opened.load()
        if base_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("V7.15.16 부모 타이틀이 정상 V7.15.11 텍스처와 다름")
    obj = parse_objects(base_anime)[78]
    for relative, values in EXPECTED_TRANSFORMS:
        if base_anime[obj.offset + relative:obj.offset + relative + 8] != struct.pack("<2h2H", *values):
            raise ValueError(f"기준 transform 불일치: 0x{relative:X}")
    final_title, glyphs, changed_pixels, removed_bar_pixels, preview = build_title(base_title)
    final_anime = repack_texture(base_anime, texture, final_title)
    if decode_texture(final_anime, texture).convert("RGBA").tobytes() != final_title.tobytes():
        raise ValueError("V7.15.18 타이틀 텍스처 왕복 실패")
    for relative, values in EXPECTED_TRANSFORMS:
        if final_anime[obj.offset + relative:obj.offset + relative + 8] != struct.pack("<2h2H", *values):
            raise ValueError("텍스처 전용 후보에서 transform 변경")

    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    for row in archive.records:
        before = base_start[row.data_offset:row.end_offset]
        after = bytes(final_start[row.data_offset:row.end_offset])
        if row.output_name.casefold() != "anime00.dat" and before != after:
            raise ValueError(f"비대상 START 자원 변경: {row.output_name}")
    new_lzs = compress_buffer_runtime_safe(bytes(final_start), old_lzs[:4], int(header["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start) or overlap_count(new_lzs):
        raise ValueError("V7.15.18 런타임 안전 LZS 검증 실패")
    next_offset = rows[start_row["index"] + 1]["data_offset"]
    capacity = next_offset - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError(f"V7.15.18 START.LZS 슬롯 초과: {len(new_lzs)}>{capacity}")
    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:next_offset] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    TITLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final_title.save(TITLE_OUTPUT, format="PNG", optimize=True, compress_level=9)
    preview.resize((704, 256), Image.Resampling.NEAREST).save(PREVIEW_OUTPUT, format="PNG", optimize=True, compress_level=9)
    artifacts = {"SYSTEM.DAT": bytes(final_system), "start.dat": bytes(final_start), "start.lzs": new_lzs, "anime00.dat": final_anime}
    for name, blob in artifacts.items():
        (OUTPUT / name).write_bytes(blob)
    report = {
        "format": "prinny1_v7_15_18_logo_style_title_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "font": {"family": "Noto Sans CJK KR", "style": "Bold", "collection_index": 1, "license": "SIL Open Font License"},
        "verified": {
            "glyphs": glyphs,
            "changed_title_pixels": changed_pixels,
            "removed_long_mark_pixels": removed_bar_pixels,
            "long_mark_cell": list(BAR_CELL),
            "old_lzs_size": len(old_lzs),
            "new_lzs_size": len(new_lzs),
            "lzs_capacity": capacity,
            "lzs_overlaps": 0,
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()} | {"title_png": sha256_file(TITLE_OUTPUT), "preview_png": sha256_file(PREVIEW_OUTPUT)},
        "checks": {
            "original_japanese_cell_bounds_reused": True,
            "lime_and_transparent_palette_only": True,
            "japanese_long_mark_removed": True,
            "sprite_geometry_byte_identical": True,
            "only_four_title_cells_changed": True,
            "only_anime00_changed_inside_start": True,
            "runtime_safe_lzs_non_overlap": True,
            "iso_created": False,
        },
        "status": "logo_style_title_resources_sealed_independent_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"title changed pixels: {changed_pixels}; long mark removed: {removed_bar_pixels}")
    print(f"START.LZS: {len(old_lzs)} -> {len(new_lzs)} / {capacity}; overlaps 0")
    for row in glyphs:
        print(f"{row['text']}: {row['target_rect']} / {row['foreground_pixels']} px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
