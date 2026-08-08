#!/usr/bin/env python3
"""Rebuild the V7.15.41 subtitle from the game's original bitmap letter style."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw

import prinny1_v7_15_41_title_subtitle_town_runtime_iso as parent
from prinny1_v7_15_29_title_plaque_white_index_iso import extract_anime, extract_start, linear_indices, repack_indices
from prinny1_v7_15_35_candidate_text_runtime_repair_iso import sha256_bytes, sha256_file
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_41_title_subtitle_town_runtime"
    / "prinny_korean_v7_15_41_title_subtitle_town_runtime.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_42_original_subtitle_style"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_42_original_subtitle_style.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_42_original_subtitle_style_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_42_original_subtitle_style"
ORIGINAL_STYLE_SYSTEM = (
    ROOT
    / "workspace/build/prinny1_v7_15_40_town_runtime_orientation_resources"
    / "SYSTEM.DAT"
)

EXPECTED_BASE_SHA256 = "f7ec78a45a5347ec781cc3b5b43b62b93993394c6aeb06eb6ca0eca059369fe1"
EXPECTED_BASE_SYSTEM_SHA256 = "2b00b7801e6ca5949d2e4801438f3399b3ce3c695298c7c76a1833296bc07658"
EXPECTED_BASE_ANIME_SHA256 = "299fdbd5e9eb0314b4ef2a2f9b5f8d89a8e8b6a0fe16b74b40aed558cf3687c0"
EXPECTED_BASE_OBJECT78_SHA256 = "5700ece769d2154ffc98bd3e224a5233dc8e9a8243978df5db33aec75e3253cd"
EXPECTED_BASE_TEXTURE_SHA256 = "2bd420710982717e6ffa7b25c8f072e3f3c204b94112da097ebd28a7801801c5"
EXPECTED_STYLE_SYSTEM_SHA256 = "c5d03f9bae13099feaf5e20b7802f74cdc2f799e404cd3f5f2fc087bc020c342"
EXPECTED_STYLE_ANIME_SHA256 = "f3d61297a552af655ad6d0cee990558ef18cdb1d710af94b9fd2b71c62630452"
ORIGINAL_V40_VERIFY_EMBEDDED_KOREAN = parent.v40.verify_embedded_korean

TARGET_SUBTITLE = "~제가 주인공이여도 되겠슴까?~"
CLEAR_BOX = (29, 131, 264, 160)
TEXT_START_X = 33
TEXT_END_X = 259
CELL_TOP = 131
CELL_BOTTOM = 160

# Exact V7.15.40 bitmap cell boundaries.  These are texture cells, not OCR.
SOURCE_CELLS = {
    "tilde_left": (33, 44),
    "제": (44, 60),
    "가": (60, 76),
    "주": (83, 100),
    "인": (100, 117),
    "공": (117, 134),
    "도": (151, 167),
    "되": (169, 185),
    "겠": (185, 201),
    "슴": (201, 217),
    "까": (217, 233),
    "question": (233, 245),
    "tilde_right": (245, 259),
}
KOREAN_WIDTH = 15
FIRST_SPACE_WIDTH = 7
SECOND_SPACE_WIDTH = 2


def rewrite_versions(value):
    if isinstance(value, str):
        return value.replace("v7_15_41", "v7_15_42").replace("V7.15.41", "V7.15.42")
    if isinstance(value, list):
        return [rewrite_versions(item) for item in value]
    if isinstance(value, dict):
        return {key: rewrite_versions(item) for key, item in value.items()}
    return value


def write_json(name: str, payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(rewrite_versions(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(name: str, rows: list[dict]) -> None:
    rows = rewrite_versions(rows)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def source_style_indices() -> tuple[list[int], bytes]:
    if sha256_file(ORIGINAL_STYLE_SYSTEM) != EXPECTED_STYLE_SYSTEM_SHA256:
        raise ValueError("V7.15.40 원형 부제 SYSTEM 봉인값 불일치")
    system = ORIGINAL_STYLE_SYSTEM.read_bytes()
    start, _lzs, _row, _rows = extract_start(system)
    anime, _record = extract_anime(start)
    if sha256_bytes(anime) != EXPECTED_STYLE_ANIME_SHA256:
        raise ValueError("V7.15.40 원형 부제 anime00 봉인값 불일치")
    texture = texture_by_key(anime, (78, 0, 0))
    return linear_indices(anime, texture), anime


def source_cell(indices: list[int], name: str) -> Image.Image:
    left, right = SOURCE_CELLS[name]
    image = Image.new("L", (right - left, CELL_BOTTOM - CELL_TOP), 0)
    image.putdata([
        indices[y * 512 + x]
        for y in range(CELL_TOP, CELL_BOTTOM)
        for x in range(left, right)
    ])
    return image


def korean_cell(indices: list[int], name: str) -> Image.Image:
    return source_cell(indices, name).resize(
        (KOREAN_WIDTH, CELL_BOTTOM - CELL_TOP), Image.Resampling.NEAREST
    )


def make_i(indices: list[int]) -> Image.Image:
    source_in = source_cell(indices, "인")
    source_ga = source_cell(indices, "가")
    result = Image.new("L", (17, 29), 0)
    # Reuse the exact ㅇ from 인, excluding its bottom ㄴ 받침.
    result.paste(source_in.crop((0, 0, 12, 19)), (0, 0))
    # Reuse the exact vertical vowel stroke from 가.
    result.paste(source_ga.crop((12, 2, 16, 25)), (13, 2))
    return result.resize((KOREAN_WIDTH, 29), Image.Resampling.NEAREST)


def make_yeo(indices: list[int]) -> Image.Image:
    source_in = source_cell(indices, "인")
    result = Image.new("L", (17, 29), 0)
    result.paste(source_in.crop((0, 0, 12, 19)), (0, 0))
    draw = ImageDraw.Draw(result)
    # ㅕ uses the same 8..15 outline/fill convention as the original cells.
    draw.rectangle((12, 3, 16, 24), fill=8)
    draw.rectangle((14, 4, 15, 23), fill=15)
    for y0 in (7, 13):
        draw.rectangle((9, y0, 14, y0 + 4), fill=8)
        draw.rectangle((10, y0 + 1, 14, y0 + 3), fill=15)
    return result.resize((KOREAN_WIDTH, 29), Image.Resampling.NEAREST)


def compose_original_style(indices: list[int]) -> tuple[Image.Image, dict]:
    transparent_first = Image.new("L", (FIRST_SPACE_WIDTH, 29), 0)
    transparent_second = Image.new("L", (SECOND_SPACE_WIDTH, 29), 0)
    pieces = [
        source_cell(indices, "tilde_left"),
        korean_cell(indices, "제"), korean_cell(indices, "가"), transparent_first,
        korean_cell(indices, "주"), korean_cell(indices, "인"), korean_cell(indices, "공"),
        make_i(indices), make_yeo(indices), korean_cell(indices, "도"), transparent_second,
        korean_cell(indices, "되"), korean_cell(indices, "겠"), korean_cell(indices, "슴"),
        korean_cell(indices, "까"), source_cell(indices, "question"),
        source_cell(indices, "tilde_right"),
    ]
    width = sum(piece.width for piece in pieces)
    if width != TEXT_END_X - TEXT_START_X:
        raise ValueError(f"원형 부제 재조판 폭 불일치: {width}")
    result = Image.new("L", (width, 29), 0)
    x = 0
    for piece in pieces:
        result.paste(piece, (x, 0))
        x += piece.width
    used = sorted(set(result.getdata()))
    if any(index not in range(16) for index in used) or not {8, 15}.issubset(used):
        raise ValueError(f"원형 부제 인덱스 범위 불일치: {used}")
    return result, {
        "style_source": "V7.15.40 original Korean subtitle bitmap cells",
        "reused_exact_glyphs": ["제", "가", "주", "인", "공", "도", "되", "겠", "슴", "까", "?", "~"],
        "constructed_glyphs": {
            "이": "인에서 ㄴ 받침 제거 + 가의 세로 모음획",
            "여": "인의 ㅇ + 기존 8..15 계조의 ㅕ 획",
        },
        "fixed_korean_cell_width": KOREAN_WIDTH,
        "composed_width": width,
        "palette_indices": used,
    }


def png_bytes(image: Image.Image, scale: int = 1) -> bytes:
    if scale != 1:
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def patch_original_style(base_anime: bytes) -> tuple[bytes, dict, dict[str, bytes]]:
    if sha256_bytes(base_anime) != EXPECTED_BASE_ANIME_SHA256:
        raise ValueError("V7.15.41 anime00 부모 해시 불일치")
    obj = next(item for item in parse_objects(base_anime) if item.index == 78)
    if sha256_bytes(base_anime[obj.offset:obj.offset + obj.size]) != EXPECTED_BASE_OBJECT78_SHA256:
        raise ValueError("V7.15.41 object_078 부모 해시 불일치")
    texture = texture_by_key(base_anime, (78, 0, 0))
    decoded = decode_texture(base_anime, texture).convert("RGBA")
    output = io.BytesIO()
    decoded.save(output, format="PNG")
    if sha256_bytes(output.getvalue()) != EXPECTED_BASE_TEXTURE_SHA256:
        raise ValueError("V7.15.41 부제 텍스처 부모 해시 불일치")

    source_indices, _source_anime = source_style_indices()
    composed, style_meta = compose_original_style(source_indices)
    before = linear_indices(base_anime, texture)
    after = before.copy()
    left, top, right, bottom = CLEAR_BOX
    for y in range(top, bottom):
        for x in range(left, right):
            after[y * 512 + x] = 0
    for y in range(29):
        for x in range(composed.width):
            after[(CELL_TOP + y) * 512 + TEXT_START_X + x] = composed.getpixel((x, y))

    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    allowed = {y * 512 + x for y in range(top, bottom) for x in range(left, right)}
    if not changed or set(changed) - allowed:
        raise ValueError("원형 부제 허용 사각형 밖 인덱스 변경")
    final_anime = repack_indices(base_anime, texture, after)
    pixel_end = texture.pixel_offset + texture.width * texture.height // 2
    if base_anime[:texture.pixel_offset] != final_anime[:texture.pixel_offset] or base_anime[pixel_end:] != final_anime[pixel_end:]:
        raise ValueError("원형 부제 픽셀 스트림 밖 anime00 변경")

    decoded_after = decode_texture(final_anime, texture).convert("RGBA")
    previews = {
        "title_subtitle_original_style_atlas_preview.png": png_bytes(decoded_after.crop((0, 125, 320, 165)), 4),
        "title_subtitle_original_style_index_preview.png": parent.png_bytes(parent.index_preview(after, (0, 125, 320, 165)), 1),
    }
    metadata = style_meta | {
        "old_visible_text": TARGET_SUBTITLE,
        "target_visible_text": TARGET_SUBTITLE,
        "change_kind": "font_style_only_original_bitmap_reconstruction",
        "clear_box": list(CLEAR_BOX),
        "target_box": [TEXT_START_X, CELL_TOP, TEXT_END_X, CELL_BOTTOM],
        "changed_indices": len(changed),
        "palette_changes": 0,
        "uv_transform_changes": 0,
    }
    return final_anime, metadata, previews


def verify_parent_embedded_korean(base: dict[str, bytes]) -> dict:
    """Validate V7.15.41 while allowing only its sealed title-subtitle delta."""
    style_system = ORIGINAL_STYLE_SYSTEM.read_bytes()
    style_base = dict(base)
    style_base["SYSTEM.DAT"] = style_system
    verified = ORIGINAL_V40_VERIFY_EMBEDDED_KOREAN(style_base)

    style_start, _style_lzs, _style_row, _style_rows = extract_start(style_system)
    parent_start, parent_lzs, _parent_row, _parent_rows = extract_start(base["SYSTEM.DAT"])
    if parent.changed_start_resources(style_start, parent_start) != ["anime00.dat"]:
        raise ValueError("V7.15.41 부모에서 타이틀 anime00.dat 외 START 자원 변경")
    parent_anime, _record = extract_anime(parent_start)
    if sha256_bytes(parent_anime) != EXPECTED_BASE_ANIME_SHA256:
        raise ValueError("V7.15.41 부모 anime00.dat 봉인값 불일치")
    if parent.overlap_count(parent_lzs):
        raise ValueError("V7.15.41 부모 START.LZS 겹침 역참조")
    return verified | {
        "parent_title_subtitle_delta": "sealed V7.15.41 anime00.dat only",
        "parent_anime_sha256": EXPECTED_BASE_ANIME_SHA256,
    }


def configure_parent() -> None:
    parent.BASE_ISO = BASE_ISO
    parent.OUTPUT_DIR = OUTPUT_DIR
    parent.OUTPUT_ISO = OUTPUT_ISO
    parent.RESOURCE_DIR = RESOURCE_DIR
    parent.REPORT_DIR = REPORT_DIR
    parent.EXPECTED_BASE_SHA256 = EXPECTED_BASE_SHA256
    parent.EXPECTED_BASE_FILES = {
        "BOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
        "EBOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
        "SYSTEM.DAT": (4_070_251, EXPECTED_BASE_SYSTEM_SHA256),
        "STAGE.DAT": (155_647_296, "b8d1e8169147b79d89bb1a75ba9548bec4bc8032be1dbfa5edd43149cc54c965"),
    }
    parent.EXPECTED_ANIME00_SHA256 = EXPECTED_BASE_ANIME_SHA256
    parent.EXPECTED_OBJECT78_SHA256 = EXPECTED_BASE_OBJECT78_SHA256
    parent.EXPECTED_TEXTURE_SHA256 = EXPECTED_BASE_TEXTURE_SHA256
    parent.OLD_SUBTITLE = TARGET_SUBTITLE
    parent.TARGET_SUBTITLE = TARGET_SUBTITLE
    parent.patch_subtitle = patch_original_style
    parent.write_json = write_json
    parent.write_csv = write_csv
    parent.v40.verify_embedded_korean = verify_parent_embedded_korean


def main() -> int:
    configure_parent()
    return parent.main()


if __name__ == "__main__":
    raise SystemExit(main())
