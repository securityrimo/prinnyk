#!/usr/bin/env python3
"""Match only the title subtitle font to the user's smooth reference image."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import prinny1_v7_15_41_title_subtitle_town_runtime_iso as parent
import prinny1_v7_15_43_npc_name_standardization_iso as v43
from prinny1_v7_15_29_title_plaque_white_index_iso import extract_anime, extract_start, linear_indices, repack_indices
from prinny1_v7_15_34_text_suffix_repair_iso import records
from prinny1_v7_15_35_candidate_text_runtime_repair_iso import sha256_bytes, sha256_file
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_43_npc_name_standardization"
    / "prinny_korean_v7_15_43_npc_name_standardization.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_44_smooth_reference_subtitle"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_44_smooth_reference_subtitle.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_44_smooth_reference_subtitle_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_44_smooth_reference_subtitle"
REFERENCE_IMAGE = Path("/home/hyuk/사진/타이틀화면.png")
FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")

EXPECTED_BASE_SHA256 = "44c088f331aaed4f52203f5a34287ba5a82a61c356d76572879a7d1754dd88c9"
EXPECTED_BASE_START_SHA256 = "0acae357386e446bb4446304e8e469cdd536aadc2f0d51162e51d66ac5d42d69"
EXPECTED_BASE_ANIME_SHA256 = "3c02bb05a3c85ab7cd640014e99d9bb9b22d75ac58292392584c6becfeceda7d"
EXPECTED_BASE_OBJECT78_SHA256 = "e0f2f97a3c48afcae06fa031d3643f9767cc01972f3dcce5a059ee177b590b4f"
EXPECTED_BASE_TEXTURE_SHA256 = "719c008df0b48c658d5a67f6a735277ecd8de41c1495a844a3653afe4f7f73b8"
EXPECTED_REFERENCE_SHA256 = "a5f7d2f4834a56f26bbdc0f40ebac3ce861dde3d451e7e2b40303376f33411cf"
EXPECTED_BASE_FILES = {
    "BOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
    "EBOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
    "SYSTEM.DAT": (4_070_251, "aaf3b0f44abcbe3ba286fff2eb5ef01abf359fc21fe8da700b8fe55efd40abcb"),
    "STAGE.DAT": (155_647_296, "b8d1e8169147b79d89bb1a75ba9548bec4bc8032be1dbfa5edd43149cc54c965"),
}

TARGET_SUBTITLE = "~제가 주인공이여도 되겠슴까?~"
CLEAR_BOX = (29, 131, 264, 160)
TARGET_BOX = (33, 132, 259, 159)
FONT_SIZE = 21
STROKE_WIDTH = 2
OUTLINE_INDEX = 8
FILL_INDEX = 15


def rewrite_report(value):
    key_replacements = {
        "v7_15_40_stage_dat_exact": "v7_15_43_stage_dat_exact",
        "v7_15_40_stage_dat_preserved": "v7_15_43_stage_dat_preserved",
    }
    if isinstance(value, str):
        value = value.replace("v7_15_41", "v7_15_44").replace("V7.15.41", "V7.15.44")
        if value == "user_requested_exact_title_subtitle_replacement_2026_08_08":
            return "user_requested_smooth_reference_subtitle_only_2026_08_08"
        return value
    if isinstance(value, list):
        return [rewrite_report(item) for item in value]
    if isinstance(value, dict):
        return {
            key_replacements.get(key, key): rewrite_report(item)
            for key, item in value.items()
        }
    return value


def write_json(name: str, payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(rewrite_report(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(name: str, rows: list[dict]) -> None:
    rows = rewrite_report(rows)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def subtitle_mask() -> Image.Image:
    if not FONT.is_file() or sha256_file(REFERENCE_IMAGE) != EXPECTED_REFERENCE_SHA256:
        raise ValueError("부제 글꼴 또는 사용자 기준 이미지 봉인값 불일치")
    font = ImageFont.truetype(str(FONT), FONT_SIZE)
    bbox = font.getbbox(TARGET_SUBTITLE, stroke_width=STROKE_WIDTH)
    natural = Image.new("L", (bbox[2] - bbox[0], bbox[3] - bbox[1]), 0)
    draw = ImageDraw.Draw(natural)
    draw.text(
        (-bbox[0], -bbox[1]),
        TARGET_SUBTITLE,
        font=font,
        fill=255,
        stroke_width=STROKE_WIDTH,
        stroke_fill=1,
    )
    target_width = TARGET_BOX[2] - TARGET_BOX[0]
    target_height = TARGET_BOX[3] - TARGET_BOX[1]
    fitted = natural.resize(
        (target_width, min(target_height, natural.height)),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("L", (512, 512), 0)
    y = TARGET_BOX[1] + (target_height - fitted.height) // 2
    canvas.paste(fitted, (TARGET_BOX[0], y))
    bbox = canvas.getbbox()
    if bbox is None or not (
        CLEAR_BOX[0] <= bbox[0] < bbox[2] <= CLEAR_BOX[2]
        and CLEAR_BOX[1] <= bbox[1] < bbox[3] <= CLEAR_BOX[3]
    ):
        raise ValueError(f"부드러운 부제 마스크 경계 불일치: {bbox}")
    return canvas


def mask_value_to_index(value: int) -> int:
    if value <= 0:
        return 0
    if value <= 16:
        return OUTLINE_INDEX
    return min(FILL_INDEX, OUTLINE_INDEX + (value * 8 // 256))


def png_bytes(image: Image.Image, scale: int = 1) -> bytes:
    if scale != 1:
        image = image.resize(
            (image.width * scale, image.height * scale),
            Image.Resampling.NEAREST,
        )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def patch_subtitle(base_anime: bytes) -> tuple[bytes, dict, dict[str, bytes]]:
    if sha256_bytes(base_anime) != EXPECTED_BASE_ANIME_SHA256:
        raise ValueError("V7.15.43 anime00.dat 봉인값 불일치")
    obj = next(item for item in parse_objects(base_anime) if item.index == 78)
    if sha256_bytes(base_anime[obj.offset:obj.offset + obj.size]) != EXPECTED_BASE_OBJECT78_SHA256:
        raise ValueError("V7.15.43 object_078 봉인값 불일치")
    texture = texture_by_key(base_anime, (78, 0, 0))
    decoded_before = decode_texture(base_anime, texture).convert("RGBA")
    encoded = io.BytesIO()
    decoded_before.save(encoded, format="PNG")
    if sha256_bytes(encoded.getvalue()) != EXPECTED_BASE_TEXTURE_SHA256:
        raise ValueError("V7.15.43 타이틀 텍스처 봉인값 불일치")

    before = linear_indices(base_anime, texture)
    after = before.copy()
    left, top, right, bottom = CLEAR_BOX
    for y in range(top, bottom):
        for x in range(left, right):
            after[y * 512 + x] = 0
    mask = subtitle_mask()
    drawn = 0
    for y in range(top, bottom):
        for x in range(left, right):
            value = mask.getpixel((x, y))
            if value:
                after[y * 512 + x] = mask_value_to_index(value)
                drawn += 1
    if drawn < 1_200:
        raise ValueError(f"부드러운 부제 픽셀 수 부족: {drawn}")

    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    allowed = {
        y * 512 + x
        for y in range(top, bottom)
        for x in range(left, right)
    }
    if not changed or set(changed) - allowed:
        raise ValueError("부제 사각형 밖 픽셀 인덱스 변경")
    final_anime = repack_indices(base_anime, texture, after)
    pixel_end = texture.pixel_offset + texture.width * texture.height // 2
    if (
        base_anime[:texture.pixel_offset] != final_anime[:texture.pixel_offset]
        or base_anime[pixel_end:] != final_anime[pixel_end:]
    ):
        raise ValueError("타이틀 픽셀 스트림 밖 anime00.dat 변경")

    decoded_after = decode_texture(final_anime, texture).convert("RGBA")
    previews = {
        "title_subtitle_smooth_reference_atlas_preview.png": png_bytes(
            decoded_after.crop((0, 125, 320, 165)), 4
        ),
        "title_subtitle_smooth_reference_index_preview.png": png_bytes(
            parent.index_preview(after, (0, 125, 320, 165))
        ),
    }
    metadata = {
        "target_visible_text": TARGET_SUBTITLE,
        "reference_image": str(REFERENCE_IMAGE),
        "reference_image_sha256": EXPECTED_REFERENCE_SHA256,
        "style": "Noto Sans CJK Bold smooth gothic with thick outline",
        "font_size": FONT_SIZE,
        "stroke_width": STROKE_WIDTH,
        "clear_box": list(CLEAR_BOX),
        "target_box": list(TARGET_BOX),
        "mask_bbox": list(mask.getbbox()),
        "drawn_pixels": drawn,
        "changed_indices": len(changed),
        "outline_index": OUTLINE_INDEX,
        "fill_index": FILL_INDEX,
        "palette_changes": 0,
        "uv_transform_changes": 0,
        "logo_plaque_menu_pixels_outside_subtitle_exact": True,
    }
    return final_anime, metadata, previews


def verify_v43_parent(base: dict[str, bytes]) -> None:
    start, lzs, _row, _rows = extract_start(base["SYSTEM.DAT"])
    if sha256_bytes(start) != EXPECTED_BASE_START_SHA256 or parent.overlap_count(lzs):
        raise ValueError("V7.15.43 START/LZS 봉인값 불일치")
    table = records(start)
    if v43.count_occurrences(start, table, v43.OLD_TUTORIAL):
        raise ValueError("V7.15.43에 튜토리얼상 잔존")
    if v43.count_occurrences(start, table, v43.OLD_SAVE):
        raise ValueError("V7.15.43에 세이브 담당 잔존")
    if len(v43.count_occurrences(start, table, v43.NEW_TUTORIAL)) != 6:
        raise ValueError("V7.15.43 튜토리얼씨 봉인 수 불일치")
    if len(v43.count_occurrences(start, table, v43.NEW_SAVE)) != 3:
        raise ValueError("V7.15.43 세이브씨 봉인 수 불일치")


def build_resources() -> tuple[dict[str, bytes], list[dict], dict, dict[str, bytes]]:
    iso_records = parent.exact_iso_records(BASE_ISO)
    base = {name: parent.iso_blob(BASE_ISO, name, iso_records) for name in parent.v40.ISO_FILES}
    for name, (size, digest) in EXPECTED_BASE_FILES.items():
        if len(base[name]) != size or sha256_bytes(base[name]) != digest:
            raise ValueError(f"V7.15.43 부모 {name} 봉인값 불일치")
    verify_v43_parent(base)
    final_system, artifacts, metadata, previews = parent.patch_system(base["SYSTEM.DAT"])
    final = dict(base)
    final["SYSTEM.DAT"] = final_system
    final.update(artifacts)
    for name in ("BOOT.BIN", "EBOOT.BIN", "STAGE.DAT"):
        if final[name] != base[name]:
            raise ValueError(f"비대상 ISO 자원 변경: {name}")
    writes = [{
        "id": "P1-V7.15.44-TITLE-SUBTITLE-01",
        "target": "START.DAT/anime00.dat/object_078/group_00_page_00",
        "operation": "replace_subtitle_only_with_smooth_reference_font",
        "old_text": TARGET_SUBTITLE,
        "target_text": TARGET_SUBTITLE,
        "boundary": str(CLEAR_BOX),
        "before_anime_sha256": EXPECTED_BASE_ANIME_SHA256,
        "after_anime_sha256": sha256_bytes(artifacts["anime00.dat"]),
    }]
    return final, writes, metadata, previews


def configure_parent() -> None:
    parent.BASE_ISO = BASE_ISO
    parent.OUTPUT_DIR = OUTPUT_DIR
    parent.OUTPUT_ISO = OUTPUT_ISO
    parent.RESOURCE_DIR = RESOURCE_DIR
    parent.REPORT_DIR = REPORT_DIR
    parent.FONT = FONT
    parent.EXPECTED_BASE_SHA256 = EXPECTED_BASE_SHA256
    parent.EXPECTED_BASE_FILES = EXPECTED_BASE_FILES
    parent.OLD_SUBTITLE = TARGET_SUBTITLE
    parent.TARGET_SUBTITLE = TARGET_SUBTITLE
    parent.patch_subtitle = patch_subtitle
    parent.build_resources = build_resources
    parent.write_json = write_json
    parent.write_csv = write_csv


def main() -> int:
    configure_parent()
    parent.seal()
    parent.independent_prebuild()
    build = parent.build_iso()
    review = parent.independent_postbuild()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print(f"subtitle: {TARGET_SUBTITLE}")
    print("scope: subtitle pixels only")
    print("PPSSPP: not launched")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
