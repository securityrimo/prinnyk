#!/usr/bin/env python3
"""Restyle the in-game title glyphs from the Korean PIC0 logo."""
from __future__ import annotations

import hashlib
import json
import struct
from collections import deque
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from scripts.prinny_anime_preview import decode_texture, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_10_title_color_restore/prinny_korean_v7_15_10_title_color_restore.iso"
PIC0_SOURCE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/source_png/direct_iso/PIC0.png"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_11_pic0_title_style_plan"
TITLE_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_11/anime/anime00/object_078/group_00_page_00.png"
GLYPH_PREVIEW = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_11/pic0_title_glyph_preview.png"

EXPECTED = {
    BASE_ISO: "e26f628360cac2043338051070acfb1f4586a9e321469f7dc3d578375265badf",
    PIC0_SOURCE: "7fb529379799b875e482553b483ca11fae581a669b37580ac2ac2da4f6f992f7",
}

# PIC0의 빨간 명패 안에서 각 한글 글자만 포함하는 고해상도 영역이다.
# 경계에 닿는 흰색 로고/명패 외곽선은 연결 요소 검사로 제외한다.
PIC0_GLYPHS = (
    {"text": "프", "crop": (990, 570, 1420, 980), "components": 2, "target": (273, 181, 303, 212)},
    {"text": "리", "crop": (1330, 440, 1760, 860), "components": 1, "target": (331, 161, 359, 187)},
    {"text": "니", "crop": (1680, 320, 2120, 750), "components": 1, "target": (381, 159, 409, 186)},
)
WHITE_THRESHOLD = 215
MASK_THRESHOLD = 96
FOREGROUND = (0, 255, 0, 255)
TRANSPARENT = (0, 0, 0, 0)


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


def connected_components(mask: Image.Image) -> list[set[tuple[int, int]]]:
    width, height = mask.size
    remaining = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if mask.getpixel((x, y))
    }
    components: list[set[tuple[int, int]]] = []
    while remaining:
        seed = remaining.pop()
        queue = deque([seed])
        component = {seed}
        while queue:
            x, y = queue.popleft()
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if point in remaining:
                    remaining.remove(point)
                    component.add(point)
                    queue.append(point)
        components.append(component)
    return components


def extract_pic0_glyph(pic0: Image.Image, spec: dict) -> tuple[Image.Image, dict]:
    crop = pic0.crop(tuple(spec["crop"])).convert("RGB")
    mask = Image.new("L", crop.size, 0)
    for y in range(crop.height):
        for x in range(crop.width):
            if min(crop.getpixel((x, y))) >= WHITE_THRESHOLD:
                mask.putpixel((x, y), 255)
    interior = []
    for component in connected_components(mask):
        touches_edge = any(
            x in (0, crop.width - 1) or y in (0, crop.height - 1)
            for x, y in component
        )
        if not touches_edge:
            interior.append(component)
    interior.sort(key=len, reverse=True)
    selected = interior[: int(spec["components"])]
    if len(selected) != int(spec["components"]):
        raise ValueError(f"PIC0 글리프 연결 요소 부족: {spec['text']}")
    selected_mask = Image.new("L", crop.size, 0)
    for component in selected:
        for point in component:
            selected_mask.putpixel(point, 255)
    bbox = selected_mask.getbbox()
    if bbox is None:
        raise ValueError(f"PIC0 글리프가 비었습니다: {spec['text']}")
    trimmed = selected_mask.crop(bbox)
    return trimmed, {
        "text": spec["text"],
        "source_crop": list(spec["crop"]),
        "selected_components": len(selected),
        "component_pixels": [len(component) for component in selected],
        "trimmed_size": list(trimmed.size),
    }


def fit_binary_mask(mask: Image.Image, size: tuple[int, int]) -> Image.Image:
    inner_width, inner_height = size[0] - 2, size[1] - 2
    scale = min(inner_width / mask.width, inner_height / mask.height)
    fitted_size = (
        max(1, round(mask.width * scale)),
        max(1, round(mask.height * scale)),
    )
    resized = mask.resize(fitted_size, Image.Resampling.LANCZOS)
    binary = resized.point(lambda value: 255 if value >= MASK_THRESHOLD else 0)
    output = Image.new("L", size, 0)
    origin = ((size[0] - fitted_size[0]) // 2, (size[1] - fitted_size[1]) // 2)
    output.paste(binary, origin)
    return output


def restyle_title(original: Image.Image, pic0: Image.Image) -> tuple[Image.Image, list[dict], int, Image.Image]:
    source = original.convert("RGBA")
    if source.size != (512, 512) or pic0.size != (2700, 1568):
        raise ValueError("타이틀 아틀라스 또는 PIC0 캔버스 불일치")
    if source.getpixel((511, 511)) != TRANSPARENT or FOREGROUND not in set(source.getdata()):
        raise ValueError("타이틀 팔레트 기준 불일치")
    edited = source.copy()
    manifest = []
    preview = Image.new("RGBA", (192, 72), (32, 32, 32, 255))
    preview_x = 8
    for spec in PIC0_GLYPHS:
        mask, row = extract_pic0_glyph(pic0, spec)
        target = tuple(spec["target"])
        target_size = (target[2] - target[0], target[3] - target[1])
        fitted = fit_binary_mask(mask, target_size)
        glyph = Image.new("RGBA", target_size, TRANSPARENT)
        glyph.paste(Image.new("RGBA", target_size, FOREGROUND), (0, 0), fitted)
        edited.paste(TRANSPARENT, target)
        edited.paste(glyph, target[:2])
        row.update({
            "target_rect": list(target),
            "target_size": list(target_size),
            "target_foreground_pixels": sum(1 for value in fitted.getdata() if value),
        })
        if row["target_foreground_pixels"] < 100:
            raise ValueError(f"PIC0 축소 글리프 가독성 픽셀 부족: {spec['text']}")
        manifest.append(row)
        scaled_preview = fitted.resize((target_size[0] * 2, target_size[1] * 2), Image.Resampling.NEAREST)
        colored = Image.new("RGBA", scaled_preview.size, (255, 255, 255, 0))
        colored.paste((255, 255, 255, 255), (0, 0, *scaled_preview.size), scaled_preview)
        preview.alpha_composite(colored, (preview_x, 5))
        preview_x += scaled_preview.width + 8
    if not set(edited.getdata()).issubset(set(source.getdata())):
        raise ValueError("PIC0 타이틀 변환 중 기존 팔레트 밖 색 생성")
    changed = assert_changes_inside(
        source,
        edited,
        tuple(tuple(spec["target"]) for spec in PIC0_GLYPHS),
    )
    return edited, manifest, changed, preview


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.11 입력 해시 불일치: {path}")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(base_system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    old_lzs = base_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    base_start, header = decompress_buffer(old_lzs)
    if overlap_count(old_lzs) != 0:
        raise ValueError("V7.15.10 부모 LZS에 겹침 역참조 존재")
    archive = StartRuntimeArchive.from_bytes(base_start)
    anime_record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[anime_record.data_offset:anime_record.end_offset]
    texture = texture_by_key(base_anime, (78, 0, 0))
    original_title = decode_texture(base_anime, texture)
    with Image.open(PIC0_SOURCE) as opened:
        opened.load()
        pic0 = opened.convert("RGBA")
    final_title, glyph_manifest, changed_pixels, preview = restyle_title(original_title, pic0)
    final_anime = repack_texture(base_anime, texture, final_title)
    if decode_texture(final_anime, texture).convert("RGBA").tobytes() != final_title.tobytes():
        raise ValueError("PIC0 스타일 타이틀 아틀라스 왕복 실패")

    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    for row in archive.records:
        before = base_start[row.data_offset:row.end_offset]
        after = bytes(final_start[row.data_offset:row.end_offset])
        if row.output_name.casefold() != "anime00.dat" and before != after:
            raise ValueError(f"비대상 START 자원 변경: {row.output_name}")
    new_lzs = compress_buffer_runtime_safe(bytes(final_start), old_lzs[:4], int(header["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start) or overlap_count(new_lzs) != 0:
        raise ValueError("V7.15.11 런타임 안전 LZS 검증 실패")
    next_offset = rows[start_row["index"] + 1]["data_offset"]
    capacity = next_offset - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError(f"V7.15.11 START.LZS 슬롯 초과: {len(new_lzs)}>{capacity}")

    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:next_offset] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))
    verified_row = next(row for row in system_records(bytes(final_system)) if row["name"].casefold() == "start.lzs")
    verified_start = decompress_buffer(bytes(final_system[verified_row["data_offset"]:verified_row["data_offset"] + verified_row["size"]]))[0]
    if verified_start != bytes(final_start):
        raise ValueError("최종 SYSTEM.DAT START 재추출 실패")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    TITLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final_title.save(TITLE_OUTPUT, format="PNG", optimize=True, compress_level=9)
    preview.save(GLYPH_PREVIEW, format="PNG", optimize=True, compress_level=9)
    artifacts = {
        "SYSTEM.DAT": bytes(final_system),
        "start.dat": bytes(final_start),
        "start.lzs": new_lzs,
        "anime00.dat": final_anime,
    }
    for name, blob in artifacts.items():
        (OUTPUT / name).write_bytes(blob)
    report = {
        "format": "prinny1_v7_15_11_pic0_title_style_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "pic0_usage": "glyph_shape_source_only_not_runtime_background",
            "glyphs": glyph_manifest,
            "changed_title_pixels": changed_pixels,
            "old_lzs_size": len(old_lzs),
            "new_lzs_size": len(new_lzs),
            "lzs_capacity": capacity,
            "lzs_overlaps": 0,
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()} | {
            "title_png": sha256_file(TITLE_OUTPUT),
            "glyph_preview": sha256_file(GLYPH_PREVIEW),
        },
        "checks": {
            "pic0_white_glyph_components_extracted": True,
            "original_uv_cells_preserved": True,
            "changes_inside_three_original_cells_only": True,
            "original_anime_palette_only": True,
            "only_anime00_changed_inside_start": True,
            "runtime_safe_lzs_non_overlap": True,
            "all_v7_15_10_other_images_inherited": True,
            "iso_created": False,
        },
        "status": "pic0_title_style_resources_sealed_independent_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"title changed pixels: {changed_pixels}")
    print(f"START.LZS: {len(old_lzs)} -> {len(new_lzs)} / {capacity}; overlaps 0")
    for row in glyph_manifest:
        print(f"{row['text']}: {row['trimmed_size']} -> {row['target_size']} / {row['target_foreground_pixels']} pixels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
