#!/usr/bin/env python3
"""Korean town direction signs and the Ultimate Dessert countdown overlay."""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.font_runtime import FontRuntime
from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_28_title_plaque_korean_iso import changed_start_resources, overlap_count
from prinny1_v7_15_29_title_plaque_white_index_iso import extract_start, extract_system
from prinny1_v7_15_35_candidate_text_runtime_repair_iso import (
    now,
    record_map,
    resource_blob,
    sha256_bytes,
    sha256_file,
)
from scripts.prinny_anime_preview import decode_texture, find_texture_groups, parse_objects
from scripts.prinny_txp_preview import swizzle_psp, unswizzle_psp


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_38_dessert_terminology_dialogue"
    / "prinny_korean_v7_15_38_dessert_terminology_dialogue.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_39_town_sign_deadline_korean"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_39_town_sign_deadline_korean.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_39_town_sign_deadline_korean_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_39_town_sign_deadline_korean"
KOREAN_FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
TUTORIAL_SOURCE_PNG = (
    ROOT
    / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/source_png"
    / "anime/anime00/object_082/group_00_page_00.png"
)

EXPECTED_BASE_SHA256 = "223ad68119353033a1f72fe927581341781ef2f359355d632b1327b94b2a904f"
EXPECTED_BASE_SIZE = 500_465_664
EXPECTED_EVIDENCE = (
    (Path("/home/hyuk/사진/다음스테이지 간판.png"), "ba8c1fac22b380f29e402a1f6161b2c96f3973963f74087a888b8977bf95e2e2"),
    (Path("/home/hyuk/사진/마왕 간판.png"), "bf93e6c5d3e4d802918606dc8080d4fb98b37aa8f452e4bf98c77ca4fa5c5003"),
    (Path("/home/hyuk/사진/푯말.png"), "f0352b4552406f662fd3596533d0a7987d6d7d8cefef59451b016c2a83ff3753"),
    (Path("/home/hyuk/사진/마을 미번역 마계시.png"), "e1db32ba763652cb1b1f2db929766f81e32d5919b428f0018e0d20fabcb951b9"),
)
EXPECTED_TUTORIAL_PNG_SHA256 = "ff9c70f4346a7c9c30d858eedb4e1c2ab11be1739d56a9cd3ea740707a0f802e"
EXPECTED_ANIME00_SHA256 = "f3d61297a552af655ad6d0cee990558ef18cdb1d710af94b9fd2b71c62630452"
EXPECTED_ANIME00_OBJECT82_SHA256 = "2395680a4fa188b9ea7a0d5c6e36238c16713645472ba2f073f75a077189c161"

ISO_FILES = {
    "BOOT.BIN": ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
    "EBOOT.BIN": ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
    "SYSTEM.DAT": ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    "STAGE.DAT": ["PSP_GAME", "USRDIR", "STAGE.DAT"],
}
EXPECTED_BASE_FILES = {
    "BOOT.BIN": (1_128_036, "149f29aaeb4014c0dd2825473e4b5079bdacdd6879d9649b224acce48c0ea4dd"),
    "EBOOT.BIN": (1_128_036, "149f29aaeb4014c0dd2825473e4b5079bdacdd6879d9649b224acce48c0ea4dd"),
    "STAGE.DAT": (155_647_296, "09e373171069b3ff9402eef0fd4b86e1d21a3c1ea6597265038a305c8935f717"),
}

# Every town st000 model carries the same 256x128 direction-sign texture at slot 6.
SIGN_TEXTURES = (
    ("st000_10.GM3", 0x004BE800, 0xA3BF0),
    ("st000_27.GM3", 0x01866000, 0x9C7D0),
    ("st000_22.GM3", 0x01BB7800, 0x9C7D0),
    ("st000_03.GM3", 0x02F79800, 0x9DA60),
    ("st000_06.GM3", 0x03034000, 0x9EB40),
    ("st000_01.GM3", 0x032D1800, 0x9D3A0),
    ("st000_04.GM3", 0x035D0000, 0x9DB80),
    ("st000_25.GM3", 0x038C0000, 0x9C7D0),
    ("st000_08.GM3", 0x03DD9800, 0x9E750),
    ("st000_02.GM3", 0x042CB000, 0x9D790),
    ("st000_23.GM3", 0x053FE800, 0x9C7D0),
    ("st000_07.GM3", 0x054B8000, 0x9DDC0),
    ("st000_05.GM3", 0x0691E800, 0x9EAF0),
    ("st000_26.GM3", 0x07151800, 0x9C7D0),
    ("st000_24.GM3", 0x0775E000, 0x9C7D0),
    ("st000_21.GM3", 0x087CA000, 0x9C7D0),
    ("st000_09.GM3", 0x0903A000, 0x9E7E0),
)
SIGN_BLOCK_SIZE = 16 + 1024 + 256 * 128
EXPECTED_SIGN_BLOCK_SHA256 = "37f6903168d22511e793757c82a1967332443f37bcaa7f31728bc91728ae4f51"

NONPAREN_OFFSETS = {10: 0xF0ADB, 9: 0xF0AEC, 8: 0xF0AFC, 7: 0xF0B0C, 6: 0xF0B1C,
                    5: 0xF0B2C, 4: 0xF0B3C, 3: 0xF0B4C, 2: 0xF0B5C, 1: 0xF0B6C}
OLD_NONPAREN_OFFSETS = {10: 0xF0ADC, **{number: offset for number, offset in NONPAREN_OFFSETS.items() if number != 10}}
PAREN_OFFSETS = {10: 0xEE6C0, 9: 0xEE6D4, 8: 0xEE6E8, 7: 0xEE6FC, 6: 0xEE710, 5: 0xEE724}
COUNTDOWN_POINTERS = tuple(range(0xDCECC, 0xDCEF4, 4))
LOAD_BASE = 0x08804000
ELF_FILE_BIAS = 0x54

KOREAN_CODES = {
    "남": bytes.fromhex("F0C2"), "은": bytes.fromhex("F35D"),
    "시": bytes.fromhex("F2B2"), "간": bytes.fromhex("F042"),
    "궁": bytes.fromhex("F076"), "극": bytes.fromhex("F07C"),
    "의": bytes.fromhex("F361"), "디": bytes.fromhex("F169"),
    "저": bytes.fromhex("F379"), "트": bytes.fromhex("F45F"),
    "완": bytes.fromhex("F342"), "성": bytes.fromhex("F28F"),
    "기": bytes.fromhex("F087"), "한": bytes.fromhex("F486"),
    "까": bytes.fromhex("F09D"), "지": bytes.fromhex("F3A8"),
}
SOURCE_HEADER = "究極のスイーツ作成期限まで"
TARGET_HEADER = "궁극의 디저트 완성 기한까지"
TARGET_WORDS = ("궁극의", "디저트", "완성", "기한까지")
SACRIFICIAL_CHAR = "戮"
EXPECTED_LIMIT_TABLE_INDEX = 0x91F
EXPECTED_SACRIFICIAL_TABLE_INDEX = 0x1562
EXPECTED_SACRIFICIAL_GLYPH = 0x8F8


def write_json(name: str, payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_csv(name: str, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Expected Write 표가 비었습니다")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def runtime_from_blobs(fnt: bytes, txp: bytes) -> FontRuntime:
    return FontRuntime(
        Path("font.fnt"), Path("font.txp"), FontRuntime._parse_fnt(fnt), txp,
        FontRuntime._parse_txp(txp),
    )


def runtime_from_start(start: bytes) -> tuple[FontRuntime, dict[str, object]]:
    records = record_map(start)
    return runtime_from_blobs(
        resource_blob(start, records, "font.fnt"),
        resource_blob(start, records, "font.txp"),
    ), records


def encode_korean(text: str) -> bytes:
    output = bytearray()
    for character in text:
        if character == " ":
            output.append(0x20)
        elif character in KOREAN_CODES:
            output.extend(KOREAN_CODES[character])
        elif character.isascii():
            output.extend(character.encode("ascii"))
        else:
            raise ValueError(f"등록되지 않은 한글 코드: {character}")
    return bytes(output)


def decode_runtime_bytes(runtime: FontRuntime, blob: bytes) -> list[int | str]:
    output: list[int | str] = []
    index = 0
    while index < len(blob):
        value = blob[index]
        if value == 0:
            output.append("NUL")
            index += 1
        elif value < 0x80:
            output.append(chr(value))
            index += 1
        else:
            code = blob[index:index + 2]
            if len(code) != 2:
                raise ValueError("2바이트 글리프 경계 실패")
            table_index = runtime.table_index_from_sjis(code)
            if table_index >= len(runtime.table):
                raise ValueError(f"폰트 테이블 범위 초과: {code.hex()}")
            glyph = runtime.table[table_index]
            if glyph >= runtime.txp["glyph_count"]:
                raise ValueError(f"폰트 글리프 범위 초과: {code.hex()}")
            output.append(glyph)
            index += 2
    return output


def make_countdown(number: int, parenthesized: bool = False) -> bytes:
    text = f"남은 시간 {number}시간"
    if parenthesized:
        text = f"({text})"
    return encode_korean(text) + b"\0"


def pointer_for_file_offset(offset: int) -> int:
    return LOAD_BASE + offset - ELF_FILE_BIAS


def patch_boot(base: bytes) -> tuple[bytes, dict]:
    if len(base) != EXPECTED_BASE_FILES["BOOT.BIN"][0]:
        raise ValueError("BOOT 크기 불일치")
    final = bytearray(base)

    # Verify the existing pointer table before moving only the two-digit entry back one byte.
    old_pointer_values = [struct.unpack_from("<I", base, offset)[0] for offset in COUNTDOWN_POINTERS]
    expected_old = [pointer_for_file_offset(OLD_NONPAREN_OFFSETS[number]) for number in range(10, 0, -1)]
    if old_pointer_values != expected_old:
        raise ValueError(f"카운트다운 포인터 기준 불일치: {old_pointer_values!r}")

    table_left, table_right = NONPAREN_OFFSETS[10], 0xF0B7C
    final[table_left:table_right] = bytes(table_right - table_left)
    for number in range(10, 0, -1):
        raw = make_countdown(number)
        offset = NONPAREN_OFFSETS[number]
        next_offset = NONPAREN_OFFSETS.get(number - 1, table_right)
        if len(raw) > next_offset - offset:
            raise ValueError(f"카운트다운 슬롯 초과: {number}")
        final[offset:offset + len(raw)] = raw
    struct.pack_into("<I", final, COUNTDOWN_POINTERS[0], pointer_for_file_offset(NONPAREN_OFFSETS[10]))

    for number, offset in PAREN_OFFSETS.items():
        raw = make_countdown(number, parenthesized=True)
        if len(raw) > 20:
            raise ValueError(f"괄호 카운트다운 슬롯 초과: {number}")
        final[offset:offset + 20] = raw.ljust(20, b"\0")

    final_bytes = bytes(final)
    for number, offset in NONPAREN_OFFSETS.items():
        raw = make_countdown(number)
        if final_bytes[offset:offset + len(raw)] != raw:
            raise ValueError(f"카운트다운 재검증 실패: {number}")
    for number, offset in PAREN_OFFSETS.items():
        raw = make_countdown(number, parenthesized=True)
        if final_bytes[offset:offset + 20] != raw.ljust(20, b"\0"):
            raise ValueError(f"괄호 카운트다운 재검증 실패: {number}")
    return final_bytes, {
        "nonparenthesized_text": [f"남은 시간 {number}시간" for number in range(10, 0, -1)],
        "parenthesized_text": [f"(남은 시간 {number}시간)" for number in range(10, 4, -1)],
        "first_pointer_old_file_offset": "0xF0ADC",
        "first_pointer_new_file_offset": "0xF0ADB",
    }


def encode_glyph(image: Image.Image) -> bytes:
    if image.mode != "L" or image.size != (20, 14):
        raise ValueError("글리프 이미지는 20x14 L이어야 합니다")
    output = bytearray()
    for y in range(14):
        for x in range(0, 20, 2):
            left = int(round(image.getpixel((x, y)) / 17))
            right = int(round(image.getpixel((x + 1, y)) / 17))
            if not (0 <= left <= 15 and 0 <= right <= 15):
                raise ValueError("4bpp 글리프 범위 초과")
            output.append(left | (right << 4))
    if len(output) != 140:
        raise ValueError("글리프 인코딩 크기 불일치")
    return bytes(output)


def target_header_strip(runtime: FontRuntime) -> Image.Image:
    glyphs: dict[str, Image.Image] = {}
    for character in "".join(TARGET_WORDS):
        code = KOREAN_CODES[character]
        table_index = runtime.table_index_from_sjis(code)
        glyph = runtime.table[table_index]
        image = runtime.decode_glyph(glyph)
        bbox = image.getbbox()
        if bbox is None:
            raise ValueError(f"빈 한글 글리프: {character}")
        glyphs[character] = image.crop((bbox[0], 0, bbox[2], 14))

    pieces: list[Image.Image | int] = []
    for word_index, word in enumerate(TARGET_WORDS):
        for char_index, character in enumerate(word):
            if char_index:
                pieces.append(3)
            pieces.append(glyphs[character])
        if word_index + 1 < len(TARGET_WORDS):
            pieces.append(12)
    width = sum(piece if isinstance(piece, int) else piece.width for piece in pieces)
    if width != 234:
        raise ValueError(f"카운트다운 첫 줄 폭 불일치: {width}")
    strip = Image.new("L", (260, 14), 0)
    x = (260 - width) // 2
    for piece in pieces:
        if isinstance(piece, int):
            x += piece
        else:
            strip.paste(piece, (x, 0))
            x += piece.width
    if x != (260 - width) // 2 + width:
        raise ValueError("카운트다운 첫 줄 합성 경계 불일치")
    return strip


def patch_countdown_header_font(base_start: bytes) -> tuple[bytes, dict, bytes]:
    runtime, records = runtime_from_start(base_start)
    base_fnt = resource_blob(base_start, records, "font.fnt")
    base_txp = resource_blob(base_start, records, "font.txp")
    final_fnt = bytearray(base_fnt)
    final_txp = bytearray(base_txp)

    source_mappings = [runtime.mapping_for_char(character) for character in SOURCE_HEADER]
    if len(source_mappings) != 13:
        raise ValueError("일본어 카운트다운 첫 줄 글리프 수 불일치")
    limit = runtime.mapping_for_char("限")
    sacrifice = runtime.mapping_for_char(SACRIFICIAL_CHAR)
    if (limit["table_index"], sacrifice["table_index"], sacrifice["glyph_index"]) != (
        EXPECTED_LIMIT_TABLE_INDEX, EXPECTED_SACRIFICIAL_TABLE_INDEX, EXPECTED_SACRIFICIAL_GLYPH
    ):
        raise ValueError("限 충돌 회피용 폰트 매핑 기준 불일치")
    if runtime.table.count(EXPECTED_SACRIFICIAL_GLYPH) != 1:
        raise ValueError("희생 글리프가 단독 참조가 아닙니다")

    # Protect the complete custom Korean F0-F5 alias region, not just the twelve
    # glyphs used by this phrase.  In the current font 限 shares glyph 0x395 with
    # the Korean alias F4F3 (얀), which is why 限 is remapped before tile writes.
    protected_custom_glyphs: dict[bytes, int] = {}
    for lead in range(0xF0, 0xF6):
        for trail in range(0x40, 0xFD):
            code = bytes((lead, trail))
            table_index = runtime.table_index_from_sjis(code)
            if table_index < len(runtime.table):
                protected_custom_glyphs[code] = runtime.table[table_index]
    source_glyphs = [int(mapping["glyph_index"]) for mapping in source_mappings]
    collisions = set(source_glyphs) & set(protected_custom_glyphs.values())
    expected_collision = {int(limit["glyph_index"])}
    if collisions != expected_collision:
        raise ValueError(f"일본어/한글 글리프 충돌 기준 불일치: {collisions}")

    # Point 限 away from its Korean alias before writing the 11th strip cell.
    struct.pack_into("<H", final_fnt, int(limit["table_offset"]), EXPECTED_SACRIFICIAL_GLYPH)
    strip = target_header_strip(runtime)
    patched_glyphs: list[int] = []
    for index, mapping in enumerate(source_mappings):
        glyph = EXPECTED_SACRIFICIAL_GLYPH if mapping["character"] == "限" else int(mapping["glyph_index"])
        tile = strip.crop((index * 20, 0, (index + 1) * 20, 14))
        offset = int(runtime.txp["pixel_offset"]) + glyph * int(runtime.txp["bytes_per_glyph"])
        final_txp[offset:offset + 140] = encode_glyph(tile)
        patched_glyphs.append(glyph)
    if len(set(patched_glyphs)) != 13:
        raise ValueError("카운트다운 첫 줄 대상 글리프 중복")

    final_runtime = runtime_from_blobs(bytes(final_fnt), bytes(final_txp))
    rendered = Image.new("L", (260, 14), 0)
    for index, character in enumerate(SOURCE_HEADER):
        mapping = final_runtime.mapping_for_char(character)
        rendered.paste(final_runtime.decode_glyph(int(mapping["glyph_index"])), (index * 20, 0))
    if rendered.tobytes() != strip.tobytes():
        raise ValueError("카운트다운 첫 줄 13칸 재렌더링 불일치")

    for code, glyph in protected_custom_glyphs.items():
        if final_runtime.decode_glyph(glyph).tobytes() != runtime.decode_glyph(glyph).tobytes():
            raise ValueError(f"원본 한글 글리프가 변경됨: {code.hex().upper()}")

    final_start = bytearray(base_start)
    fnt_record, txp_record = records["font.fnt"], records["font.txp"]
    final_start[fnt_record.data_offset:fnt_record.end_offset] = final_fnt
    final_start[txp_record.data_offset:txp_record.end_offset] = final_txp
    if changed_start_resources(base_start, bytes(final_start)) != ["font.fnt", "font.txp"]:
        raise ValueError("START 변경 자원 범위 불일치")

    preview = strip.resize((1040, 56), Image.Resampling.NEAREST)
    out = io.BytesIO()
    preview.save(out, format="PNG")
    return bytes(final_start), {
        "source_runtime_cells": SOURCE_HEADER,
        "target_visual_text": TARGET_HEADER,
        "target_words": list(TARGET_WORDS),
        "patched_glyph_indices": patched_glyphs,
        "limit_original_glyph": int(limit["glyph_index"]),
        "limit_remapped_glyph": EXPECTED_SACRIFICIAL_GLYPH,
        "protected_korean_glyphs_unchanged": True,
        "runtime_status": "static_font_reconstruction_pass_runtime_screen_pending",
    }, out.getvalue()


def palette_from_sign_block(block: bytes) -> list[tuple[int, int, int, int]]:
    return [tuple(block[16 + index * 4:20 + index * 4]) for index in range(256)]


def decode_sign_block(block: bytes) -> tuple[Image.Image, list[int]]:
    if len(block) != SIGN_BLOCK_SIZE:
        raise ValueError("표지판 텍스처 블록 크기 불일치")
    width, height = struct.unpack_from("<HH", block, 4)
    if (width, height) != (256, 128):
        raise ValueError(f"표지판 텍스처 크기 불일치: {width}x{height}")
    packed = block[1040:1040 + width * height]
    indices = list(unswizzle_psp(packed, width, height))
    colors = palette_from_sign_block(block)
    rgba = b"".join(bytes(colors[index]) for index in indices)
    return Image.frombytes("RGBA", (width, height), rgba), indices


def draw_centered(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], font: ImageFont.FreeTypeFont) -> None:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=1)
    x = (box[0] + box[2] - (bbox[2] - bbox[0])) // 2 - bbox[0]
    y = (box[1] + box[3] - (bbox[3] - bbox[1])) // 2 - bbox[1]
    draw.text(
        (x, y), text, font=font, fill=(250, 246, 230, 255),
        stroke_width=1, stroke_fill=(42, 34, 29, 255),
    )


def sign_target_image(source: Image.Image) -> Image.Image:
    if source.size != (256, 128) or source.mode != "RGBA":
        raise ValueError("표지판 원본 이미지 형식 불일치")
    result = source.copy()
    # Rebuild only the opaque upper planks; the original alpha silhouette is retained.
    for x0, x1 in ((20, 114), (120, 220)):
        for y in range(7, 40):
            base = ((177, 140, 79), (184, 146, 83), (169, 132, 75), (181, 142, 80))[(y // 4) % 4]
            for x in range(x0, x1):
                if source.getpixel((x, y))[3] == 0:
                    continue
                noise = ((x * 17 + y * 31) % 11) - 5
                result.putpixel((x, y), tuple(max(0, min(255, value + noise)) for value in base) + (255,))
        for y, color in ((26, (143, 106, 62, 255)), (27, (200, 164, 96, 255))):
            for x in range(x0, x1):
                if source.getpixel((x, y))[3]:
                    result.putpixel((x, y), color)

    # Restore the colored arrows and a two-pixel outline neighbourhood exactly.
    arrow_mask = Image.new("L", source.size, 0)
    mask_pixels = arrow_mask.load()
    source_pixels = source.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, _alpha = source_pixels[x, y]
            is_red = red > 100 and red > green * 1.35 and red > blue * 1.5
            is_green = green > 65 and green > red * 1.18 and green > blue * 1.2
            if is_red or is_green:
                mask_pixels[x, y] = 255
    arrow_mask = arrow_mask.filter(ImageFilter.MaxFilter(5))
    result.paste(source, (0, 0), arrow_mask)

    draw = ImageDraw.Draw(result)
    font = ImageFont.truetype(str(KOREAN_FONT), 12)
    draw_centered(draw, "마왕성으로", (20, 9, 115, 39), font)
    draw_centered(draw, "다음 구역으로", (120, 9, 220, 39), font)
    return result


def nearest_palette_index(color: tuple[int, int, int, int], palette: list[tuple[int, int, int, int]]) -> int:
    candidates = [index for index, item in enumerate(palette) if item[3] == color[3]]
    if not candidates:
        candidates = list(range(len(palette)))
    return min(candidates, key=lambda index: sum((palette[index][channel] - color[channel]) ** 2 for channel in range(4)))


def patch_sign_block(base_block: bytes) -> tuple[bytes, Image.Image, dict]:
    source, before_indices = decode_sign_block(base_block)
    target = sign_target_image(source)
    palette = palette_from_sign_block(base_block)
    cache: dict[tuple[int, int, int, int], int] = {}
    after_indices = before_indices.copy()
    for position, (before_rgba, after_rgba) in enumerate(zip(source.getdata(), target.getdata())):
        if before_rgba == after_rgba:
            continue
        color = tuple(after_rgba)
        if color not in cache:
            cache[color] = nearest_palette_index(color, palette)
        after_indices[position] = cache[color]
    linear = bytes(after_indices)
    packed = swizzle_psp(linear, 256, 128)
    final = bytearray(base_block)
    final[1040:1040 + len(packed)] = packed
    final_bytes = bytes(final)
    preview, decoded_indices = decode_sign_block(final_bytes)
    if decoded_indices != after_indices or final_bytes[:1040] != base_block[:1040]:
        raise ValueError("표지판 팔레트/헤더 또는 스위즐 왕복 불일치")
    changed_pixels = sum(left != right for left, right in zip(before_indices, after_indices))
    if changed_pixels <= 0:
        raise ValueError("표지판 실제 변경 픽셀이 없습니다")
    return final_bytes, preview, {
        "left_text": "마왕성으로", "right_text": "다음 구역으로",
        "changed_logical_pixels": changed_pixels,
        "changed_packed_bytes": sum(left != right for left, right in zip(base_block, final_bytes)),
        "header_palette_unchanged": True,
    }


def patch_stage(base_stage: bytes) -> tuple[bytes, bytes, dict, list[dict]]:
    blocks = []
    for name, record_offset, texture_offset in SIGN_TEXTURES:
        start = record_offset + texture_offset
        block = base_stage[start:start + SIGN_BLOCK_SIZE]
        if sha256_bytes(block) != EXPECTED_SIGN_BLOCK_SHA256:
            raise ValueError(f"표지판 기준 블록 불일치: {name}@0x{start:X}")
        blocks.append((name, start, block))
    if len({block for _name, _start, block in blocks}) != 1:
        raise ValueError("17개 표지판 기준 블록이 동일하지 않습니다")
    final_block, preview, metadata = patch_sign_block(blocks[0][2])
    final_stage = bytearray(base_stage)
    writes = []
    for sequence, (name, start, block) in enumerate(blocks, 1):
        final_stage[start:start + SIGN_BLOCK_SIZE] = final_block
        writes.append({
            "id": f"P1-V7.15.39-SIGN-{sequence:02d}", "target": f"STAGE.DAT/{name}/texture_06",
            "operation": "replace_direction_sign_pixel_stream_only", "offset_hex": f"0x{start + 1040:X}",
            "length": 256 * 128, "before_sha256": sha256_bytes(block[1040:]),
            "after_sha256": sha256_bytes(final_block[1040:]), "boundary": "256x128_8bpp_swizzled_pixels",
        })
    out = io.BytesIO()
    preview.resize((1024, 512), Image.Resampling.NEAREST).save(out, format="PNG")
    return bytes(final_stage), out.getvalue(), metadata | {"patched_copies": len(blocks)}, writes


def tutorial_checks(start: bytes) -> dict:
    records = record_map(start)
    anime = resource_blob(start, records, "anime00.dat")
    if sha256_bytes(anime) != EXPECTED_ANIME00_SHA256:
        raise ValueError("튜토리얼 표지판을 포함한 anime00 기준 해시 불일치")
    objects = parse_objects(anime)
    obj = next(item for item in objects if item.index == 82)
    blob = anime[obj.offset:obj.offset + obj.size]
    if sha256_bytes(blob) != EXPECTED_ANIME00_OBJECT82_SHA256:
        raise ValueError("튜토리얼 object_082 기준 해시 불일치")
    texture = next(
        texture for group in find_texture_groups(anime, obj) for texture in group
        if texture.group_index == 0 and texture.page_index == 0
    )
    decoded = decode_texture(anime, texture)
    with Image.open(TUTORIAL_SOURCE_PNG) as source:
        expected = source.convert("RGBA")
    if decoded.size != expected.size or decoded.tobytes() != expected.tobytes():
        raise ValueError("현재 튜토리얼 한글 표지판 픽셀 불일치")
    if sha256_file(TUTORIAL_SOURCE_PNG) != EXPECTED_TUTORIAL_PNG_SHA256:
        raise ValueError("튜토리얼 한글 PNG 봉인값 불일치")
    return {
        "text": "튜토리얼", "status": "preserved_pixel_exact",
        "anime00_sha256": sha256_bytes(anime), "object_082_sha256": sha256_bytes(blob),
        "source_png_sha256": sha256_file(TUTORIAL_SOURCE_PNG),
    }


def diff_runs(before: bytes, after: bytes) -> list[tuple[int, int]]:
    if len(before) != len(after):
        raise ValueError("diff_runs 크기 불일치")
    runs: list[tuple[int, int]] = []
    start = None
    for index, (left, right) in enumerate(zip(before, after)):
        if left != right and start is None:
            start = index
        elif left == right and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(before)))
    return runs


def exact_iso_records(iso: Path) -> dict[str, dict]:
    return {name: find_iso_file(iso, path) for name, path in ISO_FILES.items()}


def iso_blob(iso: Path, name: str, records: dict[str, dict] | None = None) -> bytes:
    if records is None:
        records = exact_iso_records(iso)
    return read_iso_file(iso, records[name])


def build_resources() -> tuple[dict[str, bytes], list[dict], dict, dict[str, bytes]]:
    records = exact_iso_records(BASE_ISO)
    base = {name: iso_blob(BASE_ISO, name, records) for name in ISO_FILES}
    for name, (size, digest) in EXPECTED_BASE_FILES.items():
        if len(base[name]) != size or sha256_bytes(base[name]) != digest:
            raise ValueError(f"부모 {name} 봉인값 불일치")
    if base["BOOT.BIN"] != base["EBOOT.BIN"]:
        raise ValueError("부모 BOOT/EBOOT 미러 불일치")

    final_boot, boot_meta = patch_boot(base["BOOT.BIN"])
    base_start, base_lzs, start_row, system_rows = extract_start(base["SYSTEM.DAT"])
    tutorial = tutorial_checks(base_start)
    final_start, header_meta, header_preview = patch_countdown_header_font(base_start)
    header = decompress_buffer(base_lzs)[1]
    final_lzs = compress_buffer_runtime_safe(final_start, base_lzs[:4], int(header["flag"]))
    capacity = system_rows[start_row["index"] + 1]["data_offset"] - start_row["data_offset"]
    if len(final_lzs) > capacity or decompress_buffer(final_lzs)[0] != final_start or overlap_count(final_lzs):
        raise ValueError("START.LZS PSP 런타임 안전 재압축 실패")
    final_system = bytearray(base["SYSTEM.DAT"])
    final_system[start_row["data_offset"]:start_row["data_offset"] + capacity] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(final_lzs)] = final_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(final_lzs))
    check_start, check_lzs, _check_row, _check_rows = extract_start(bytes(final_system))
    if check_start != final_start or check_lzs != final_lzs:
        raise ValueError("SYSTEM에서 START 재추출 불일치")
    if tutorial_checks(final_start) != tutorial:
        raise ValueError("튜토리얼 표지판 보존 검증 실패")

    final_stage, sign_preview, sign_meta, writes = patch_stage(base["STAGE.DAT"])
    final = {
        "BOOT.BIN": final_boot, "EBOOT.BIN": final_boot,
        "SYSTEM.DAT": bytes(final_system), "STAGE.DAT": final_stage,
        "start.dat": final_start, "start.lzs": final_lzs,
        "font.fnt": resource_blob(final_start, record_map(final_start), "font.fnt"),
        "font.txp": resource_blob(final_start, record_map(final_start), "font.txp"),
    }

    # Add the executable and logical START writes to the sealed Expected Write table.
    for target in ("BOOT.BIN", "EBOOT.BIN"):
        for sequence, (left, right) in enumerate(diff_runs(base[target], final[target]), 1):
            writes.append({
                "id": f"P1-V7.15.39-{target.split('.')[0]}-{sequence:02d}", "target": target,
                "operation": "countdown_remaining_time_runtime_string_or_pointer", "offset_hex": f"0x{left:X}",
                "length": right - left, "before_sha256": sha256_bytes(base[target][left:right]),
                "after_sha256": sha256_bytes(final[target][left:right]), "boundary": "sealed_diff_run",
            })
    base_records = record_map(base_start)
    for resource_name in ("font.fnt", "font.txp"):
        before = resource_blob(base_start, base_records, resource_name)
        after = final[resource_name]
        for sequence, (left, right) in enumerate(diff_runs(before, after), 1):
            writes.append({
                "id": f"P1-V7.15.39-{resource_name.replace('.', '-').upper()}-{sequence:02d}",
                "target": f"START.DAT/{resource_name}", "operation": "countdown_header_fixed_cell_glyph_strip",
                "offset_hex": f"0x{left:X}", "length": right - left,
                "before_sha256": sha256_bytes(before[left:right]), "after_sha256": sha256_bytes(after[left:right]),
                "boundary": "font_resource_diff_run",
            })
    writes.sort(key=lambda row: row["id"])
    metadata = {
        "direction_signs": sign_meta,
        "countdown_header": header_meta,
        "countdown_dynamic_lines": boot_meta,
        "tutorial_sign": tutorial,
        "changed_start_resources": changed_start_resources(base_start, final_start),
        "lzs_old_size": len(base_lzs), "lzs_new_size": len(final_lzs),
        "lzs_capacity": capacity, "lzs_overlap_backreferences": 0,
        "boot_eboot_mirror": True,
    }
    previews = {"direction_signs_preview.png": sign_preview, "countdown_header_preview.png": header_preview}
    return final, writes, metadata, previews


def input_seal() -> None:
    if not BASE_ISO.is_file() or BASE_ISO.stat().st_size != EXPECTED_BASE_SIZE or sha256_file(BASE_ISO) != EXPECTED_BASE_SHA256:
        raise ValueError("V7.15.38 부모 ISO 봉인값 불일치")
    if not KOREAN_FONT.is_file():
        raise FileNotFoundError(KOREAN_FONT)
    for path, digest in EXPECTED_EVIDENCE:
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"사용자 캡처 봉인값 불일치: {path}")


def seal() -> dict:
    input_seal()
    final, writes, metadata, previews = build_resources()
    if OUTPUT_ISO.exists() or RESOURCE_DIR.exists() or REPORT_DIR.exists():
        raise ValueError("V7.15.39 출력 또는 보고서 경로가 이미 존재합니다")
    RESOURCE_DIR.mkdir(parents=True)
    REPORT_DIR.mkdir(parents=True)
    for name, blob in final.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    for name, blob in previews.items():
        (REPORT_DIR / name).write_bytes(blob)
    write_csv("expected_writes.csv", writes)
    report = {
        "format": "prinny1_v7_15_39_town_sign_deadline_korean_preflight_v1",
        "created_at": now(),
        "authorization": "user_requested_four_town_ui_translations_and_corrected_tutorial_spelling_2026_08_08",
        "base_iso": {"path": str(BASE_ISO), "size": BASE_ISO.stat().st_size, "sha256": sha256_file(BASE_ISO)},
        "evidence": [{"path": str(path), "sha256": digest} for path, digest in EXPECTED_EVIDENCE],
        "sealed_resources": {name: {"size": len(blob), "sha256": sha256_bytes(blob)} for name, blob in final.items()},
        "sealed_previews": {name: sha256_bytes(blob) for name, blob in previews.items()},
        "expected_write_rows": len(writes), "repair": metadata,
        "checks": {
            "original_game_iso_not_written": True, "parent_iso_not_overwritten": True,
            "direction_sign_headers_palettes_preserved": True,
            "dynamic_countdown_number_slots_preserved": True,
            "tutorial_exact_spelling_preserved": "튜토리얼",
            "external_textures_used": False,
        },
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json("preflight.json", report)
    return report


def independent_prebuild() -> dict:
    input_seal()
    final, writes, metadata, previews = build_resources()
    for name, blob in final.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"독립 사전 봉인 자원 불일치: {name}")
    for name, blob in previews.items():
        if (REPORT_DIR / name).read_bytes() != blob:
            raise ValueError(f"독립 사전 미리보기 불일치: {name}")
    with (REPORT_DIR / "expected_writes.csv").open(encoding="utf-8-sig") as handle:
        sealed_rows = list(csv.DictReader(handle))
    if len(sealed_rows) != len(writes):
        raise ValueError("독립 사전 Expected Write 수 불일치")
    report = {
        "format": "prinny1_v7_15_39_town_sign_deadline_korean_prebuild_v1",
        "created_at": now(), "verified": metadata,
        "checks": {
            "fresh_base_recalculation": True, "sealed_resources_exact": True,
            "sealed_expected_writes_exact_count": True, "runtime_safe_lzs": True,
            "boot_eboot_mirror": True, "tutorial_spelling_pixel_exact": "튜토리얼",
        },
        "status": "pass_iso_build_ready_automatic_approval", "final_verdict": "PASS",
    }
    write_json("independent_prebuild.json", report)
    return report


def verify_iso_outside_ranges(candidate: Path, records: dict[str, dict]) -> None:
    intervals = sorted(
        (int(record["extent_lba"]) * SECTOR_SIZE,
         int(record["extent_lba"]) * SECTOR_SIZE + int(record["data_length"]))
        for record in records.values()
    )
    if candidate.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기 변경")
    cursor = 0
    for left, right in intervals:
        if hash_range(BASE_ISO, cursor, left) != hash_range(candidate, cursor, left):
            raise ValueError(f"허용 ISO 범위 앞 변경: 0x{cursor:X}..0x{left:X}")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(candidate, cursor, candidate.stat().st_size):
        raise ValueError("마지막 허용 ISO 범위 뒤 변경")


def build_iso() -> dict:
    review = json.loads((REPORT_DIR / "independent_prebuild.json").read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or OUTPUT_ISO.exists():
        raise ValueError("독립 사전 검토 미통과 또는 출력 ISO 존재")
    records = exact_iso_records(BASE_ISO)
    OUTPUT_DIR.mkdir(parents=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        raise ValueError("임시 ISO가 이미 존재합니다")
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as handle:
        for name in ISO_FILES:
            blob = (RESOURCE_DIR / name).read_bytes()
            record = records[name]
            if len(blob) != int(record["data_length"]):
                raise ValueError(f"ISO 자원 크기 변경: {name}")
            handle.seek(int(record["extent_lba"]) * SECTOR_SIZE)
            handle.write(blob)
        handle.flush()
        os.fsync(handle.fileno())
    verify_iso_outside_ranges(temporary, records)
    check = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if check.returncode != 0 or "Everything is Ok" not in check.stdout:
        raise ValueError("ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_39_town_sign_deadline_korean_iso_v1", "created_at": now(),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "checks": {"only_four_sealed_iso_extents_changed": True, "seven_zip_structure_test": True,
                   "parent_not_overwritten": True},
        "status": "built_independent_postbuild_review_required",
    }
    write_json("build_report.json", report)
    return report


def independent_postbuild() -> dict:
    base_records = exact_iso_records(BASE_ISO)
    final_records = exact_iso_records(OUTPUT_ISO)
    for name in ISO_FILES:
        if (base_records[name]["extent_lba"], base_records[name]["data_length"]) != (
            final_records[name]["extent_lba"], final_records[name]["data_length"]
        ):
            raise ValueError(f"사후 ISO 자원 경계 변경: {name}")
    verify_iso_outside_ranges(OUTPUT_ISO, base_records)
    for name in ISO_FILES:
        if iso_blob(OUTPUT_ISO, name, final_records) != (RESOURCE_DIR / name).read_bytes():
            raise ValueError(f"사후 ISO 재추출 불일치: {name}")
    if iso_blob(OUTPUT_ISO, "BOOT.BIN", final_records) != iso_blob(OUTPUT_ISO, "EBOOT.BIN", final_records):
        raise ValueError("사후 BOOT/EBOOT 미러 불일치")

    final_system = iso_blob(OUTPUT_ISO, "SYSTEM.DAT", final_records)
    final_start, final_lzs, _row, _rows = extract_start(final_system)
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or overlap_count(final_lzs):
        raise ValueError("사후 START/LZS 검증 실패")
    tutorial = tutorial_checks(final_start)

    recalculated, writes, metadata, previews = build_resources()
    for name, blob in recalculated.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"사후 독립 재계산 불일치: {name}")
    for name, blob in previews.items():
        if (REPORT_DIR / name).read_bytes() != blob:
            raise ValueError(f"사후 미리보기 재계산 불일치: {name}")
    check = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if check.returncode != 0 or "Everything is Ok" not in check.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_39_town_sign_deadline_korean_postbuild_v1", "created_at": now(),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": metadata | {"expected_write_rows": len(writes), "ppsspp_launched": False,
                                "tutorial_sign": tutorial},
        "checks": {
            "only_four_sealed_iso_extents_changed": True, "sealed_resources_reextracted_exactly": True,
            "fresh_parent_recalculation": True, "runtime_safe_lzs": True,
            "boot_eboot_mirror": True, "direction_sign_texture_copies_exact": 17,
            "tutorial_exact_spelling_preserved": "튜토리얼", "seven_zip_structure_retest": True,
        },
        "status": "pass_ready_for_ppsspp_runtime_test", "final_verdict": "PASS",
    }
    write_json("independent_postbuild.json", report)
    return report


def main() -> int:
    seal()
    independent_prebuild()
    build = build_iso()
    review = independent_postbuild()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print("sign textures: 17 / tutorial: 튜토리얼 preserved / PPSSPP: not launched")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
