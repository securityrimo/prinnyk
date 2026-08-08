#!/usr/bin/env python3
"""Resize and seal the user-approved PNG/UI edits for V7.15.6."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageStat

from core.lzs import compress_buffer_best, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from scripts.prinny_anime_preview import (
    decode_texture,
    find_texture_groups,
    parse_objects,
    repack_texture,
)
import core.font_builder as font_builder


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_5_character_voice/prinny_korean_v7_15_5_character_voice.iso"
WORKSPACE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
INVENTORY = WORKSPACE / "image_inventory.csv"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_6_ui_images_resources"
RESIZED = WORKSPACE / "translated/resized"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_6_ui_image_plan"

INPUTS = {
    "icon_direct": WORKSPACE / "source_png/direct_iso/ICON0.png",
    "pic0_direct": WORKSPACE / "source_png/direct_iso/PIC0.png",
    "icon_system": WORKSPACE / "source_png/system_pack/UMD_ICON0.png",
    "pic0_system": WORKSPACE / "source_png/system_pack/UMD_PIC0.png",
    "replay": WORKSPACE / "source_png/system_pack/REPLAY_ICON0.PNG",
    "prinny": WORKSPACE / "source_png/system_pack/PRINNY_ICON0.PNG",
    "title_atlas": WORKSPACE / "source_png/anime/anime00/object_078/group_00_page_00.png",
    "intro_atlas": WORKSPACE / "source_png/anime/anime96/object_000/group_00_page_00.png",
}
EXPECTED = {
    BASE_ISO: "bf0cd2913bc5149762c22d0336092947b46f64412d1e8706ca06f2581c33400c",
    INVENTORY: "798d7bab443e2df17e1ea5e62b2cbe9c892dc3629cdd3fc8518d775c2b9c91e8",
    INPUTS["icon_direct"]: "ed4d89b19809e65f07e293c4c6870aeb5a976fac9fca738092538fb13864fb08",
    INPUTS["pic0_direct"]: "7fb529379799b875e482553b483ca11fae581a669b37580ac2ac2da4f6f992f7",
    INPUTS["icon_system"]: "ed4d89b19809e65f07e293c4c6870aeb5a976fac9fca738092538fb13864fb08",
    INPUTS["pic0_system"]: "7fb529379799b875e482553b483ca11fae581a669b37580ac2ac2da4f6f992f7",
    INPUTS["replay"]: "9d10aade67c7204f7b7aa640f16071f5f789fecf9d23f803a493f8a8bf34ddd6",
    INPUTS["prinny"]: "1f404defe814c6549b6ca9bc7103c712c5b35fb53090700b6beba2106797608c",
    INPUTS["title_atlas"]: "ea5407d38d4ef2fbd4069f7b4c225a44cc0175c285e7f74fae6b163fd69f9fa1",
    INPUTS["intro_atlas"]: "a559a714e11a37f31174d18626f6578a8ade6a2be3496cce1328a4a7c52e2eb1",
}

TITLE_TEXTURE_KEY = (78, 0, 0)
INTRO_TEXTURE_KEY = (0, 0, 0)
TITLE_GLYPHS = (
    {"text": "프", "source": (273, 181, 303, 212), "target": (266, 174, 310, 219)},
    {"text": "리", "source": (331, 161, 359, 187), "target": (324, 155, 365, 193)},
    {"text": "니", "source": (381, 159, 409, 186), "target": (374, 153, 415, 192)},
)
INTRO_SOURCE_RECT = (0, 25, 512, 47)
INTRO_TARGET_ORIGIN = (0, 23)

ASSETS = (
    {"asset_id": "P1-IMG-V7.15.4-0001", "key": "icon_direct", "target": "ISO/PSP_GAME/ICON0.PNG", "size": (144, 80), "colors": 256, "alpha": "opaque_black", "resized": "direct_iso/ICON0.PNG"},
    {"asset_id": "P1-IMG-V7.15.4-0002", "key": "pic0_direct", "target": "ISO/PSP_GAME/PIC0.PNG", "size": (310, 180), "colors": 256, "alpha": "preserve", "resized": "direct_iso/PIC0.PNG"},
    {"asset_id": "P1-IMG-V7.15.4-0004", "key": "replay", "target": "SYSTEM.DAT/REPLAY_ICON0.PNG", "size": (144, 80), "colors": 256, "alpha": "opaque", "resized": "system_pack/REPLAY_ICON0.PNG"},
    {"asset_id": "P1-IMG-V7.15.4-0005", "key": "icon_system", "target": "SYSTEM.DAT/UMD_ICON0.PNG", "size": (144, 80), "colors": 256, "alpha": "opaque_black", "resized": "system_pack/UMD_ICON0.PNG"},
    {"asset_id": "P1-IMG-V7.15.4-0006", "key": "pic0_system", "target": "SYSTEM.DAT/UMD_PIC0.PNG", "size": (310, 180), "colors": 256, "alpha": "preserve", "resized": "system_pack/UMD_PIC0.PNG"},
    {"asset_id": "P1-IMG-V7.15.4-0008", "key": "prinny", "target": "SYSTEM.DAT/PRINNY_ICON0.PNG", "size": (144, 80), "colors": 96, "alpha": "opaque", "resized": "system_pack/PRINNY_ICON0.PNG"},
)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def resize_png(source: Path, size: tuple[int, int], colors: int, alpha: str) -> tuple[bytes, Image.Image, float]:
    with Image.open(source) as opened:
        edited = opened.convert("RGBA")
    resized = edited.resize(size, Image.Resampling.LANCZOS)
    if alpha == "opaque_black":
        background = Image.new("RGBA", size, (0, 0, 0, 255))
        background.alpha_composite(resized)
        reference = background.convert("RGB")
    elif alpha == "opaque":
        reference = resized.convert("RGB")
    else:
        reference = resized
    method = Image.Quantize.FASTOCTREE if reference.mode == "RGBA" else Image.Quantize.MEDIANCUT
    quantized = reference.quantize(colors=colors, method=method, dither=Image.Dither.FLOYDSTEINBERG)
    output = io.BytesIO()
    quantized.save(output, format="PNG", optimize=True, compress_level=9)
    blob = output.getvalue()
    with Image.open(io.BytesIO(blob)) as verified:
        verified.load()
        reopened = verified.convert("RGBA")
    difference = ImageChops.difference(reference.convert("RGBA"), reopened)
    rms = ImageStat.Stat(difference).rms
    combined = math.sqrt(sum(value * value for value in rms) / 4)
    psnr = 99.0 if combined == 0 else 20 * math.log10(255 / combined)
    return blob, reopened, psnr


def texture_by_key(blob: bytes, key: tuple[int, int, int]):
    for obj in parse_objects(blob):
        for group in find_texture_groups(blob, obj):
            for texture in group:
                if (texture.object_index, texture.group_index, texture.page_index) == key:
                    return texture
    raise ValueError(f"anime 텍스처를 찾지 못했습니다: {key}")


def changed_runs(before: bytes, after: bytes) -> list[tuple[int, int]]:
    if len(before) != len(after):
        raise ValueError("고정 크기 비교 대상 길이가 다릅니다.")
    changed = [offset for offset, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not changed:
        return []
    result: list[tuple[int, int]] = []
    start = previous = changed[0]
    for offset in changed[1:]:
        if offset != previous + 1:
            result.append((start, previous + 1))
            start = offset
        previous = offset
    result.append((start, previous + 1))
    return result


def assert_changes_inside(
    before: Image.Image,
    after: Image.Image,
    rectangles: tuple[tuple[int, int, int, int], ...],
) -> int:
    if before.size != after.size:
        raise ValueError("아틀라스 캔버스가 변경됐습니다.")
    changes = 0
    for y in range(before.height):
        for x in range(before.width):
            if before.getpixel((x, y)) == after.getpixel((x, y)):
                continue
            changes += 1
            if not any(left <= x < right and top <= y < bottom for left, top, right, bottom in rectangles):
                raise ValueError(f"허용 영역 밖 아틀라스 픽셀 변경: ({x},{y})")
    if changes <= 0:
        raise ValueError("승인된 아틀라스 편집에 실제 픽셀 변경이 없습니다.")
    return changes


def enlarge_title_glyphs(original: Image.Image) -> tuple[Image.Image, int]:
    source = original.convert("RGBA")
    if source.size != (512, 512):
        raise ValueError(f"object_078 캔버스 불일치: {source.size}")
    edited = source.copy()
    transparent = source.getpixel((511, 511))
    if transparent[3] != 0:
        raise ValueError("object_078 투명 배경 기준 픽셀이 불투명합니다.")
    allowed = []
    for glyph in TITLE_GLYPHS:
        source_rect = tuple(glyph["source"])
        target_rect = tuple(glyph["target"])
        crop = source.crop(source_rect)
        if crop.getbbox() is None:
            raise ValueError(f"object_078 글리프가 비어 있습니다: {glyph['text']}")
        edited.paste(transparent, target_rect)
        scaled = crop.resize(
            (target_rect[2] - target_rect[0], target_rect[3] - target_rect[1]),
            Image.Resampling.NEAREST,
        )
        edited.paste(scaled, (target_rect[0], target_rect[1]))
        allowed.append(target_rect)
    original_colors = set(source.getdata())
    if not set(edited.getdata()).issubset(original_colors):
        raise ValueError("object_078 확대 중 원본 팔레트 밖 색이 생겼습니다.")
    return edited, assert_changes_inside(source, edited, tuple(allowed))


def tighten_intro_spacing(original: Image.Image) -> tuple[Image.Image, int]:
    source = original.convert("RGBA")
    if source.size != (512, 320):
        raise ValueError(f"anime96 object_000 캔버스 불일치: {source.size}")
    edited = source.copy()
    transparent = source.getpixel((511, 319))
    if transparent[3] != 0:
        raise ValueError("anime96 투명 배경 기준 픽셀이 불투명합니다.")
    line = source.crop(INTRO_SOURCE_RECT)
    allowed = (0, INTRO_TARGET_ORIGIN[1], 512, INTRO_SOURCE_RECT[3])
    edited.paste(transparent, allowed)
    edited.paste(line, INTRO_TARGET_ORIGIN)
    original_colors = set(source.getdata())
    if not set(edited.getdata()).issubset(original_colors):
        raise ValueError("anime96 줄 간격 조정 중 원본 팔레트 밖 색이 생겼습니다.")
    return edited, assert_changes_inside(source, edited, (allowed,))


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.6 입력 해시 불일치: {path}")
    if INPUTS["icon_direct"].read_bytes() != INPUTS["icon_system"].read_bytes():
        raise ValueError("직결/UMD ICON 번역본이 서로 다릅니다.")
    if INPUTS["pic0_direct"].read_bytes() != INPUTS["pic0_system"].read_bytes():
        raise ValueError("직결/UMD PIC0 번역본이 서로 다릅니다.")

    inventory = {row["asset_id"]: row for row in read_csv(INVENTORY)}
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    base_anime_pack = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"]))
    records = system_records(base_system)
    by_name = {record["name"].casefold(): record for record in records}
    anime_records = system_records(base_anime_pack)
    anime_by_name = {record["name"].casefold(): record for record in anime_records}
    generated: dict[str, bytes] = {}
    manifest: list[dict[str, Any]] = []
    previews: list[tuple[str, Image.Image, Image.Image]] = []

    for asset in ASSETS:
        row = inventory[asset["asset_id"]]
        source = INPUTS[asset["key"]]
        expected_size = (int(row["width"]), int(row["height"]))
        if expected_size != tuple(asset["size"]):
            raise ValueError(f"인벤토리 캔버스 불일치: {asset['asset_id']}")
        if asset["target"].startswith("ISO/"):
            name = asset["target"].rsplit("/", 1)[-1]
            original = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", name]))
            capacity = len(original)
        else:
            name = asset["target"].rsplit("/", 1)[-1]
            record = by_name[name.casefold()]
            original = base_system[record["data_offset"]:record["data_offset"] + record["size"]]
            next_offset = records[record["index"] + 1]["data_offset"] if record["index"] + 1 < len(records) else len(base_system)
            capacity = next_offset - record["data_offset"]
        if sha256_bytes(original) != row["raw_source_sha256"]:
            raise ValueError(f"부모 원본 PNG 해시 불일치: {asset['asset_id']}")
        with Image.open(io.BytesIO(original)) as original_image:
            original_image.load()
            if original_image.size != expected_size:
                raise ValueError(f"부모 원본 PNG 크기 불일치: {asset['asset_id']}")
            original_preview = original_image.convert("RGBA")
        blob, preview, psnr = resize_png(source, expected_size, int(asset["colors"]), str(asset["alpha"]))
        if len(blob) > len(original) or len(blob) > capacity:
            raise ValueError(f"축소 PNG가 원본 슬롯을 초과합니다: {asset['asset_id']}/{len(blob)}/{len(original)}/{capacity}")
        with Image.open(io.BytesIO(blob)) as checked:
            checked.load()
            alpha_values = checked.convert("RGBA").getchannel("A").getextrema()
            if checked.size != expected_size or checked.format != "PNG":
                raise ValueError(f"축소 PNG 재개방 실패: {asset['asset_id']}")
            if asset["alpha"] != "preserve" and alpha_values != (255, 255):
                raise ValueError(f"불투명 원본의 알파가 바뀌었습니다: {asset['asset_id']}")
            if asset["alpha"] == "preserve" and alpha_values == (255, 255):
                raise ValueError(f"PIC0 투명 알파가 사라졌습니다: {asset['asset_id']}")
            mode = checked.mode
            used_colors = len(checked.convert("RGBA").getcolors(maxcolors=1 << 24) or [])
        target = RESIZED / asset["resized"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        generated[asset["target"]] = blob
        previews.append((asset["asset_id"], original_preview, preview))
        with Image.open(source) as source_image:
            user_width, user_height = source_image.size
        manifest.append({
            "asset_id": asset["asset_id"], "target": asset["target"],
            "user_source": str(source), "user_source_sha256": sha256_file(source),
            "user_width": user_width, "user_height": user_height,
            "original_png_bytes": len(original), "slot_capacity_bytes": capacity,
            "target_width": expected_size[0], "target_height": expected_size[1],
            "palette_limit": asset["colors"], "output_mode": mode, "output_used_rgba_colors": used_colors,
            "output_png_bytes": len(blob), "output_sha256": sha256_bytes(blob),
            "size_reduction_bytes": source.stat().st_size - len(blob),
            "psnr_vs_unquantized_resize_db": f"{psnr:.3f}", "alpha_policy": asset["alpha"],
            "decision": "resize_to_original_canvas_and_replace",
        })

    if generated["ISO/PSP_GAME/ICON0.PNG"] != generated["SYSTEM.DAT/UMD_ICON0.PNG"]:
        raise ValueError("직결/UMD ICON 축소 결과가 다릅니다.")
    if generated["ISO/PSP_GAME/PIC0.PNG"] != generated["SYSTEM.DAT/UMD_PIC0.PNG"]:
        raise ValueError("직결/UMD PIC0 축소 결과가 다릅니다.")

    title_row = inventory["P1-IMG-V7.15.4-0330"]
    start_entry = font_builder.parse_nispack_start_entry(base_system)
    start_offset = int(start_entry["data_offset"])
    old_lzs_size = int(start_entry["size"])
    old_lzs = base_system[start_offset:start_offset + old_lzs_size]
    base_start, _ = decompress_buffer(old_lzs)
    start_archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    anime00_record = next(
        record for record in start_archive.records
        if record.output_name.casefold() == "anime00.dat"
    )
    base_anime00 = base_start[anime00_record.data_offset:anime00_record.end_offset]
    if sha256_bytes(base_anime00) != title_row["raw_source_sha256"]:
        raise ValueError("부모 anime00.dat가 이미지 인벤토리 기준과 다릅니다.")
    title_texture = texture_by_key(base_anime00, TITLE_TEXTURE_KEY)
    title_original = decode_texture(base_anime00, title_texture)
    with Image.open(INPUTS["title_atlas"]) as opened:
        title_source = opened.convert("RGBA")
    if title_source.tobytes() != title_original.tobytes():
        raise ValueError("object_078 PNG가 부모 anime00.dat 디코드 결과와 다릅니다.")
    title_edited, title_changed_pixels = enlarge_title_glyphs(title_original)
    patched_anime00 = repack_texture(base_anime00, title_texture, title_edited)
    if len(patched_anime00) != len(base_anime00):
        raise ValueError("anime00.dat 크기가 변경됐습니다.")
    title_output = RESIZED / "anime/anime00/object_078/group_00_page_00.png"
    title_output.parent.mkdir(parents=True, exist_ok=True)
    title_edited.save(title_output, optimize=True)
    if decode_texture(patched_anime00, title_texture).tobytes() != title_edited.tobytes():
        raise ValueError("object_078 재패킹 디코드 결과가 편집 PNG와 다릅니다.")
    previews.append(("P1-IMG-V7.15.4-0330", title_original, title_edited))
    manifest.append({
        "asset_id": "P1-IMG-V7.15.4-0330", "target": "START.DAT/anime00.dat/object_078",
        "user_source": str(INPUTS["title_atlas"]), "user_source_sha256": sha256_file(INPUTS["title_atlas"]),
        "user_width": 512, "user_height": 512, "original_png_bytes": INPUTS["title_atlas"].stat().st_size,
        "slot_capacity_bytes": len(base_anime00), "target_width": 512, "target_height": 512,
        "palette_limit": 16, "output_mode": "RGBA", "output_used_rgba_colors": len(set(title_edited.getdata())),
        "output_png_bytes": title_output.stat().st_size, "output_sha256": sha256_file(title_output),
        "size_reduction_bytes": INPUTS["title_atlas"].stat().st_size - title_output.stat().st_size,
        "psnr_vs_unquantized_resize_db": "lossless_existing_palette", "alpha_policy": "preserve",
        "decision": "nearest_enlarge_prinny_glyphs_only", "changed_rgba_pixels": title_changed_pixels,
    })

    intro_row = inventory["P1-IMG-V7.15.4-0738"]
    intro_record = anime_by_name["anime96.dat"]
    base_anime96 = base_anime_pack[
        intro_record["data_offset"]:intro_record["data_offset"] + intro_record["size"]
    ]
    if sha256_bytes(base_anime96) != intro_row["raw_source_sha256"]:
        raise ValueError("부모 anime96.dat가 이미지 인벤토리 기준과 다릅니다.")
    intro_texture = texture_by_key(base_anime96, INTRO_TEXTURE_KEY)
    intro_original = decode_texture(base_anime96, intro_texture)
    with Image.open(INPUTS["intro_atlas"]) as opened:
        intro_source = opened.convert("RGBA")
    if intro_source.tobytes() != intro_original.tobytes():
        raise ValueError("anime96 object_000 PNG가 부모 디코드 결과와 다릅니다.")
    intro_edited, intro_changed_pixels = tighten_intro_spacing(intro_original)
    patched_anime96 = repack_texture(base_anime96, intro_texture, intro_edited)
    if len(patched_anime96) != len(base_anime96):
        raise ValueError("anime96.dat 크기가 변경됐습니다.")
    intro_output = RESIZED / "anime/anime96/object_000/group_00_page_00.png"
    intro_output.parent.mkdir(parents=True, exist_ok=True)
    intro_edited.save(intro_output, optimize=True)
    if decode_texture(patched_anime96, intro_texture).tobytes() != intro_edited.tobytes():
        raise ValueError("anime96 object_000 재패킹 디코드 결과가 편집 PNG와 다릅니다.")
    previews.append(("P1-IMG-V7.15.4-0738", intro_original, intro_edited))
    manifest.append({
        "asset_id": "P1-IMG-V7.15.4-0738", "target": "ANIME.DAT/anime96.dat/object_000",
        "user_source": str(INPUTS["intro_atlas"]), "user_source_sha256": sha256_file(INPUTS["intro_atlas"]),
        "user_width": 512, "user_height": 320, "original_png_bytes": INPUTS["intro_atlas"].stat().st_size,
        "slot_capacity_bytes": len(base_anime96), "target_width": 512, "target_height": 320,
        "palette_limit": 16, "output_mode": "RGBA", "output_used_rgba_colors": len(set(intro_edited.getdata())),
        "output_png_bytes": intro_output.stat().st_size, "output_sha256": sha256_file(intro_output),
        "size_reduction_bytes": INPUTS["intro_atlas"].stat().st_size - intro_output.stat().st_size,
        "psnr_vs_unquantized_resize_db": "lossless_existing_palette", "alpha_policy": "preserve",
        "decision": "move_demon_world_line_up_2px", "changed_rgba_pixels": intro_changed_pixels,
    })

    patched_start = bytearray(base_start)
    patched_start[anime00_record.data_offset:anime00_record.end_offset] = patched_anime00
    new_lzs = compress_buffer_best(bytes(patched_start), old_lzs[:4])
    if decompress_buffer(new_lzs)[0] != bytes(patched_start):
        raise ValueError("수정 START.LZS 압축 왕복 실패")

    patched_anime_pack = bytearray(base_anime_pack)
    patched_anime_pack[
        intro_record["data_offset"]:intro_record["data_offset"] + intro_record["size"]
    ] = patched_anime96

    patched_system = bytearray(base_system)
    writes: list[dict[str, Any]] = []
    sequence = 0
    for asset in ASSETS:
        if not asset["target"].startswith("SYSTEM.DAT/"):
            continue
        name = asset["target"].rsplit("/", 1)[-1]
        record = by_name[name.casefold()]
        next_offset = records[record["index"] + 1]["data_offset"] if record["index"] + 1 < len(records) else len(base_system)
        span = next_offset - record["data_offset"]
        blob = generated[asset["target"]]
        before = base_system[record["data_offset"]:next_offset]
        after = blob + bytes(span - len(blob))
        patched_system[record["data_offset"]:next_offset] = after
        entry_offset = 0x10 + record["index"] * 0x2C
        size_before = base_system[entry_offset + 0x24:entry_offset + 0x28]
        size_after = struct.pack("<I", len(blob))
        patched_system[entry_offset + 0x24:entry_offset + 0x28] = size_after
        sequence += 1
        writes.append({"sequence": sequence, "logical_id": f"P1-V7.15.6-SYSTEM-{name}-DATA", "target": "SYSTEM.DAT", "offset_hex": f"0x{record['data_offset']:X}", "write_span": span, "expected_before_hex": before.hex().upper(), "write_after_hex": after.hex().upper(), "change_kind": "translated_png_resized_data"})
        sequence += 1
        writes.append({"sequence": sequence, "logical_id": f"P1-V7.15.6-SYSTEM-{name}-SIZE", "target": "SYSTEM.DAT", "offset_hex": f"0x{entry_offset + 0x24:X}", "write_span": 4, "expected_before_hex": size_before.hex().upper(), "write_after_hex": size_after.hex().upper(), "change_kind": "nispack_entry_size"})

    start_pack_record = by_name["start.lzs"]
    start_next_offset = records[start_pack_record["index"] + 1]["data_offset"]
    start_capacity = start_next_offset - start_offset
    if len(new_lzs) > start_capacity:
        raise ValueError(f"수정 START.LZS 슬롯 초과: {len(new_lzs)}>{start_capacity}")
    start_span_before = base_system[start_offset:start_next_offset]
    start_span_after = new_lzs + bytes(start_capacity - len(new_lzs))
    patched_system[start_offset:start_next_offset] = start_span_after
    start_size_at = 0x10 + start_pack_record["index"] * 0x2C + 0x24
    start_size_before = base_system[start_size_at:start_size_at + 4]
    start_size_after = struct.pack("<I", len(new_lzs))
    patched_system[start_size_at:start_size_at + 4] = start_size_after
    sequence += 1
    writes.append({"sequence": sequence, "logical_id": "P1-V7.15.6-SYSTEM-START-LZS-DATA", "target": "SYSTEM.DAT", "offset_hex": f"0x{start_offset:X}", "write_span": start_capacity, "expected_before_hex": start_span_before.hex().upper(), "write_after_hex": start_span_after.hex().upper(), "change_kind": "object_078_recompressed_start_lzs"})
    sequence += 1
    writes.append({"sequence": sequence, "logical_id": "P1-V7.15.6-SYSTEM-START-LZS-SIZE", "target": "SYSTEM.DAT", "offset_hex": f"0x{start_size_at:X}", "write_span": 4, "expected_before_hex": start_size_before.hex().upper(), "write_after_hex": start_size_after.hex().upper(), "change_kind": "nispack_entry_size"})

    final_entry = font_builder.parse_nispack_start_entry(bytes(patched_system))
    final_lzs = bytes(patched_system[int(final_entry["data_offset"]):int(final_entry["data_offset"]) + int(final_entry["size"])])
    final_start = decompress_buffer(final_lzs)[0]
    if final_start != bytes(patched_start):
        raise ValueError("수정 SYSTEM.DAT의 START 재추출 불일치")
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    final_records = {record.output_name.casefold(): record for record in final_archive.records}
    for record in start_archive.records:
        final_record = final_records[record.output_name.casefold()]
        before_resource = base_start[record.data_offset:record.end_offset]
        after_resource = final_start[final_record.data_offset:final_record.end_offset]
        if record.output_name.casefold() == "anime00.dat":
            if after_resource != patched_anime00:
                raise ValueError("최종 START anime00.dat 불일치")
        elif after_resource != before_resource:
            raise ValueError(f"비대상 START 자원 변경: {record.output_name}")

    anime_span_before = base_anime_pack[
        intro_record["data_offset"]:intro_record["data_offset"] + intro_record["size"]
    ]
    anime_span_after = bytes(patched_anime_pack[
        intro_record["data_offset"]:intro_record["data_offset"] + intro_record["size"]
    ])
    sequence += 1
    writes.append({"sequence": sequence, "logical_id": "P1-V7.15.6-ANIME-anime96.dat", "target": "ANIME.DAT", "offset_hex": f"0x{intro_record['data_offset']:X}", "write_span": intro_record["size"], "expected_before_hex": anime_span_before.hex().upper(), "write_after_hex": anime_span_after.hex().upper(), "change_kind": "intro_line_spacing_texture"})
    if bytes(patched_anime_pack[:intro_record["data_offset"]]) != base_anime_pack[:intro_record["data_offset"]] or bytes(patched_anime_pack[intro_record["data_offset"] + intro_record["size"]:]) != base_anime_pack[intro_record["data_offset"] + intro_record["size"]:]:
        raise ValueError("ANIME.DAT anime96.dat 밖 데이터가 변경됐습니다.")

    for asset in ASSETS:
        if not asset["target"].startswith("ISO/"):
            continue
        name = asset["target"].rsplit("/", 1)[-1]
        before = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", name]))
        blob = generated[asset["target"]]
        after = blob + bytes(len(before) - len(blob))
        sequence += 1
        writes.append({"sequence": sequence, "logical_id": f"P1-V7.15.6-ISO-{name}", "target": f"PSP_GAME/{name}", "offset_hex": "0x0", "write_span": len(before), "expected_before_hex": before.hex().upper(), "write_after_hex": after.hex().upper(), "change_kind": "translated_png_resized_iso_file"})

    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "SYSTEM.DAT").write_bytes(bytes(patched_system))
    (OUTPUT / "ANIME.DAT").write_bytes(bytes(patched_anime_pack))
    (OUTPUT / "start.dat").write_bytes(bytes(patched_start))
    (OUTPUT / "start.lzs").write_bytes(new_lzs)
    (OUTPUT / "anime00.dat").write_bytes(patched_anime00)
    (OUTPUT / "anime96.dat").write_bytes(patched_anime96)
    for target_name, blob in generated.items():
        safe_name = target_name.rsplit("/", 1)[-1]
        folder = "direct_iso" if target_name.startswith("ISO/") else "system_pack"
        target = OUTPUT / folder / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    write_csv(REPORT_DIR / "resize_manifest.csv", manifest)
    write_csv(REPORT_DIR / "expected_write_confirmed.csv", writes)

    sheet = Image.new("RGB", (620, len(previews) * 100), "#303030")
    draw = ImageDraw.Draw(sheet)
    for index, (asset_id, original, resized) in enumerate(previews):
        y = index * 100
        original.thumbnail((280, 80), Image.Resampling.NEAREST)
        resized.thumbnail((280, 80), Image.Resampling.NEAREST)
        sheet.paste(original.convert("RGB"), (5, y + 15))
        sheet.paste(resized.convert("RGB"), (315, y + 15))
        draw.text((5, y), f"{asset_id} original", fill="white")
        draw.text((315, y), "translated resized", fill="white")
    sheet.save(REPORT_DIR / "comparison_sheet.png")

    report = {
        "format": "prinny1_v7_15_6_ui_image_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_requested_resize_to_original_dimensions_and_replace_2026_08_01",
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "translated_png_count": len(ASSETS) + 2,
            "unique_artwork_count": 6,
            "direct_iso_png_count": 2,
            "system_png_count": 4,
            "anime_texture_count": 2,
            "title_changed_rgba_pixels": title_changed_pixels,
            "intro_changed_rgba_pixels": intro_changed_pixels,
            "anime00_changed_bytes": sum(end - start for start, end in changed_runs(base_anime00, patched_anime00)),
            "anime96_changed_bytes": sum(end - start for start, end in changed_runs(base_anime96, patched_anime96)),
            "start_lzs_size_before": old_lzs_size,
            "start_lzs_size_after": len(new_lzs),
            "start_lzs_capacity": start_capacity,
            "expected_write_count": len(writes),
        },
        "checks": {"all_original_hashes_match_inventory": True, "all_canvases_match_original": True, "all_pngs_fit_original_file_size_and_slot": True, "pic0_alpha_preserved": True, "opaque_icons_remain_opaque": True, "direct_and_umd_pairs_identical": True, "anime_palettes_and_metadata_preserved": True, "only_object_078_changed_in_anime00": True, "only_object_000_changed_in_anime96": True, "v7_15_5_dialogue_and_other_start_resources_preserved": True, "base_iso_modified": False, "iso_created": False},
        "sealed": {
            "SYSTEM.DAT": sha256_bytes(bytes(patched_system)),
            "ANIME.DAT": sha256_bytes(bytes(patched_anime_pack)),
            "start.dat": sha256_bytes(bytes(patched_start)),
            "start.lzs": sha256_bytes(new_lzs),
            "anime00.dat": sha256_bytes(patched_anime00),
            "anime96.dat": sha256_bytes(patched_anime96),
        },
        "artifacts": {"resources": str(OUTPUT), "resized_workspace": str(RESIZED), "manifest": str(REPORT_DIR / "resize_manifest.csv"), "expected_writes": str(REPORT_DIR / "expected_write_confirmed.csv"), "comparison_sheet": str(REPORT_DIR / "comparison_sheet.png")},
        "status": "ui_image_resources_sealed_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"translated PNGs: {len(ASSETS) + 2}, Expected Writes: {len(writes)}")
    for row in manifest:
        print(f"{row['target']}: {row['user_width']}x{row['user_height']} -> {row['target_width']}x{row['target_height']}, {row['output_png_bytes']}/{row['original_png_bytes']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
