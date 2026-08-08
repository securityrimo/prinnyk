#!/usr/bin/env python3
"""Build a 136 px-wide title canary while preserving the lime runtime mask."""
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
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
PIC0_SOURCE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/source_png/direct_iso/PIC0.png"
V11_TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_11/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_17_title_136px_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_17_title_136px_plan"
TITLE_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_17/anime/anime00/object_078/group_00_page_00.png"
PREVIEW_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_17/title_136px_preview.png"

EXPECTED = {
    BASE_ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    PIC0_SOURCE: "7fb529379799b875e482553b483ca11fae581a669b37580ac2ac2da4f6f992f7",
    V11_TITLE: "d3baf482be50ee6ec2c2f10ab94cff3daae847b54807a82e2f62ba31d7f33f35",
}

# The verified V7.15.11 runtime capture measures approximately 120 PSP pixels
# from the left edge of 프 to the right edge of 니.  136 / 120 = 1.133333.
TARGET_RUNTIME_WIDTH = 136
MEASURED_RUNTIME_WIDTH = 120
SCALE = TARGET_RUNTIME_WIDTH / MEASURED_RUNTIME_WIDTH

GLYPHS = (
    {
        "text": "프",
        "cell": (256, 160, 320, 224),
        "old_target": (273, 181, 303, 212),
        "target": (271, 179, 305, 214),
    },
    {
        "text": "리",
        "cell": (320, 160, 376, 208),
        "old_target": (331, 161, 359, 187),
        "target": (329, 159, 361, 189),
    },
    {
        "text": "니",
        "cell": (376, 160, 424, 208),
        "old_target": (381, 159, 409, 186),
        "target": (379, 159, 411, 187),
    },
)

# Keep the verified sampler width/height and Y values.  Only move the outer
# glyphs apart to account for the 1.133x mask growth.
TRANSFORMS = (
    ("프", 0x23B4, (-63, -29, 32, 32), (-70, -29, 32, 32)),
    ("프", 0x23C4, (-63, -37, 32, 32), (-70, -37, 32, 32)),
    ("리", 0x23D4, (-7, -38, 28, 24), (-7, -38, 28, 24)),
    ("리", 0x23E4, (-6, -46, 28, 24), (-6, -46, 28, 24)),
    ("리", 0x23F4, (-6, -38, 28, 24), (-6, -38, 28, 24)),
    ("니", 0x2404, (39, -50, 24, 24), (45, -50, 24, 24)),
    ("니", 0x2414, (39, -58, 24, 24), (45, -58, 24, 24)),
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


def build_title(source: Image.Image, pic0: Image.Image) -> tuple[Image.Image, list[dict], int, Image.Image]:
    original = source.convert("RGBA")
    edited = original.copy()
    pic0_specs = {row["text"]: row for row in PIC0_GLYPHS}
    preview = Image.new("RGBA", (220, 90), (32, 32, 32, 255))
    preview_x = 8
    manifest = []
    for spec in GLYPHS:
        mask, row = extract_pic0_glyph(pic0, pic0_specs[spec["text"]])
        cell = tuple(spec["cell"])
        target = tuple(spec["target"])
        size = (target[2] - target[0], target[3] - target[1])
        fitted = fit_binary_mask(mask, size)
        glyph = Image.new("RGBA", size, TRANSPARENT)
        glyph.paste(Image.new("RGBA", size, FOREGROUND), (0, 0), fitted)
        edited.paste(TRANSPARENT, cell)
        edited.paste(glyph, target[:2])
        foreground_pixels = sum(value != 0 for value in fitted.getdata())
        row.update({
            "uv_cell": list(cell),
            "old_target_rect": list(spec["old_target"]),
            "target_rect": list(target),
            "target_size": list(size),
            "target_foreground_pixels": foreground_pixels,
        })
        manifest.append(row)
        scaled = fitted.resize((size[0] * 2, size[1] * 2), Image.Resampling.NEAREST)
        colored = Image.new("RGBA", scaled.size, TRANSPARENT)
        colored.paste((255, 255, 255, 255), (0, 0, *scaled.size), scaled)
        preview.alpha_composite(colored, (preview_x, 8))
        preview_x += scaled.width + 8
    if not set(edited.getdata()).issubset(set(original.getdata())):
        raise ValueError("136px 타이틀이 원본 팔레트 밖 색을 생성함")
    allowed_rects = []
    for row in GLYPHS:
        cell = row["cell"]
        old_target = row["old_target"]
        target = row["target"]
        allowed_rects.append((
            min(cell[0], old_target[0], target[0]),
            min(cell[1], old_target[1], target[1]),
            max(cell[2], old_target[2], target[2]),
            max(cell[3], old_target[3], target[3]),
        ))
    changed = assert_changes_inside(original, edited, tuple(allowed_rects))
    return edited, manifest, changed, preview


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.17 입력 해시 불일치: {path}")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(base_system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    old_lzs = base_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    base_start, header = decompress_buffer(old_lzs)
    if overlap_count(old_lzs):
        raise ValueError("V7.15.16 부모 START.LZS에 겹침 역참조 존재")
    archive = StartRuntimeArchive.from_bytes(base_start)
    anime_record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[anime_record.data_offset:anime_record.end_offset]
    texture = texture_by_key(base_anime, (78, 0, 0))
    base_title = decode_texture(base_anime, texture).convert("RGBA")
    with Image.open(V11_TITLE) as opened:
        opened.load()
        if base_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("V7.15.16 부모 타이틀이 정상 V7.15.11 텍스처와 다름")
    with Image.open(PIC0_SOURCE) as opened:
        opened.load()
        pic0 = opened.convert("RGBA")
    final_title, glyph_manifest, changed_pixels, preview = build_title(base_title, pic0)
    pixel_patched = repack_texture(base_anime, texture, final_title)
    if decode_texture(pixel_patched, texture).convert("RGBA").tobytes() != final_title.tobytes():
        raise ValueError("136px 타이틀 텍스처 왕복 실패")

    obj = parse_objects(pixel_patched)[78]
    final_anime = bytearray(pixel_patched)
    transform_manifest = []
    transform_changed_offsets = set()
    for text, relative, before_tuple, after_tuple in TRANSFORMS:
        at = obj.offset + relative
        before = struct.pack("<2h2H", *before_tuple)
        after = struct.pack("<2h2H", *after_tuple)
        if pixel_patched[at:at + 8] != before:
            raise ValueError(f"{text} transform 기준 바이트 불일치: 0x{relative:X}")
        final_anime[at:at + 8] = after
        transform_changed_offsets.update(at + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
        transform_manifest.append({
            "text": text,
            "relative_offset_hex": f"0x{relative:X}",
            "before": list(before_tuple),
            "after": list(after_tuple),
            "changed": before != after,
        })
    if len(transform_changed_offsets) != 4:
        raise ValueError(f"transform 변경 바이트 수 불일치: {len(transform_changed_offsets)}")

    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    for row in archive.records:
        before = base_start[row.data_offset:row.end_offset]
        after = bytes(final_start[row.data_offset:row.end_offset])
        if row.output_name.casefold() != "anime00.dat" and before != after:
            raise ValueError(f"비대상 START 자원 변경: {row.output_name}")
    new_lzs = compress_buffer_runtime_safe(bytes(final_start), old_lzs[:4], int(header["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start) or overlap_count(new_lzs):
        raise ValueError("V7.15.17 런타임 안전 LZS 검증 실패")
    next_offset = rows[start_row["index"] + 1]["data_offset"]
    capacity = next_offset - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError(f"V7.15.17 START.LZS 슬롯 초과: {len(new_lzs)}>{capacity}")
    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:next_offset] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    TITLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final_title.save(TITLE_OUTPUT, format="PNG", optimize=True, compress_level=9)
    preview.save(PREVIEW_OUTPUT, format="PNG", optimize=True, compress_level=9)
    artifacts = {
        "SYSTEM.DAT": bytes(final_system),
        "start.dat": bytes(final_start),
        "start.lzs": new_lzs,
        "anime00.dat": bytes(final_anime),
    }
    for name, blob in artifacts.items():
        (OUTPUT / name).write_bytes(blob)
    report = {
        "format": "prinny1_v7_15_17_title_136px_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "calculation": {
            "measured_runtime_width_px": MEASURED_RUNTIME_WIDTH,
            "target_runtime_width_px": TARGET_RUNTIME_WIDTH,
            "scale": round(SCALE, 6),
            "method": "enlarge_lime_masks_and_spread_outer_sprite_x_only",
        },
        "verified": {
            "glyphs": glyph_manifest,
            "transforms": transform_manifest,
            "changed_title_pixels": changed_pixels,
            "transform_changed_bytes": len(transform_changed_offsets),
            "old_lzs_size": len(old_lzs),
            "new_lzs_size": len(new_lzs),
            "lzs_capacity": capacity,
            "lzs_overlaps": 0,
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()} | {
            "title_png": sha256_file(TITLE_OUTPUT),
            "preview_png": sha256_file(PREVIEW_OUTPUT),
        },
        "checks": {
            "v7_15_16_parent_title_matches_v7_15_11": True,
            "lime_foreground_preserved": True,
            "sampler_width_height_unchanged": True,
            "sprite_y_unchanged": True,
            "only_outer_sprite_x_changed": True,
            "changes_inside_three_uv_cells_only": True,
            "only_anime00_changed_inside_start": True,
            "runtime_safe_lzs_non_overlap": True,
            "iso_created": False,
        },
        "status": "title_136px_resources_sealed_independent_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"title pixels changed: {changed_pixels}; transform bytes: {len(transform_changed_offsets)}")
    print(f"START.LZS: {len(old_lzs)} -> {len(new_lzs)} / {capacity}; overlaps 0")
    for row in glyph_manifest:
        print(f"{row['text']}: {row['target_rect']} / {row['target_size']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
