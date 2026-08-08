#!/usr/bin/env python3
"""Independent prebuild review for the V7.15.6 UI/image resources."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from scripts.prinny_anime_preview import decode_texture, find_texture_groups, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_5_character_voice/prinny_korean_v7_15_5_character_voice.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_6_ui_images_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_6_ui_image_plan/all_report.json"
WRITES = ROOT / "workspace/reports/prinny1_v7_15_6_ui_image_plan/expected_write_confirmed.csv"
RESIZED = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_6_ui_image_review"
EXPECTED_BASE_SHA256 = "bf0cd2913bc5149762c22d0336092947b46f64412d1e8706ca06f2581c33400c"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def texture_by_key(blob: bytes, key: tuple[int, int, int]):
    for obj in parse_objects(blob):
        for group in find_texture_groups(blob, obj):
            for texture in group:
                if (texture.object_index, texture.group_index, texture.page_index) == key:
                    return texture
    raise ValueError(f"텍스처 누락: {key}")


def changed_pixels_inside(before: Image.Image, after: Image.Image, rectangles) -> int:
    changed = 0
    for y in range(before.height):
        for x in range(before.width):
            if before.getpixel((x, y)) == after.getpixel((x, y)):
                continue
            changed += 1
            if not any(left <= x < right and top <= y < bottom for left, top, right, bottom in rectangles):
                raise ValueError(f"승인 사각형 밖 픽셀 변경: ({x},{y})")
    if changed <= 0:
        raise ValueError("아틀라스 실제 변경이 없습니다.")
    return changed


def main() -> int:
    csv.field_size_limit(sys.maxsize)
    if not BASE_ISO.is_file() or sha256_file(BASE_ISO) != EXPECTED_BASE_SHA256:
        raise ValueError("V7.15.5 부모 ISO 해시 불일치")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "ui_image_resources_sealed_independent_review_required":
        raise ValueError("V7.15.6 계획 상태 불일치")
    for name, expected in plan["sealed"].items():
        path = RESOURCE_DIR / name
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"봉인 자원 해시 불일치: {name}")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    base_anime = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"]))
    base_icon = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "ICON0.PNG"]))
    base_pic0 = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "PIC0.PNG"]))
    reconstructed = {
        "SYSTEM.DAT": bytearray(base_system),
        "ANIME.DAT": bytearray(base_anime),
        "PSP_GAME/ICON0.PNG": bytearray(base_icon),
        "PSP_GAME/PIC0.PNG": bytearray(base_pic0),
    }
    intervals: dict[str, list[tuple[int, int]]] = {name: [] for name in reconstructed}
    with WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for expected_sequence, row in enumerate(rows, 1):
        if int(row["sequence"]) != expected_sequence:
            raise ValueError("Expected Write 순서 불일치")
        target = row["target"]
        offset = int(row["offset_hex"], 16)
        length = int(row["write_span"])
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if len(before) != length or len(after) != length:
            raise ValueError(f"Expected Write 길이 불일치: {row['logical_id']}")
        end = offset + length
        if end > len(reconstructed[target]):
            raise ValueError(f"Expected Write 범위 초과: {row['logical_id']}")
        if any(not (end <= left or offset >= right) for left, right in intervals[target]):
            raise ValueError(f"Expected Write 중복: {row['logical_id']}")
        if bytes(reconstructed[target][offset:end]) != before:
            raise ValueError(f"Expected Before 불일치: {row['logical_id']}")
        reconstructed[target][offset:end] = after
        intervals[target].append((offset, end))

    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    final_anime = (RESOURCE_DIR / "ANIME.DAT").read_bytes()
    if bytes(reconstructed["SYSTEM.DAT"]) != final_system:
        raise ValueError("Expected Write로 SYSTEM.DAT 재구성 실패")
    if bytes(reconstructed["ANIME.DAT"]) != final_anime:
        raise ValueError("Expected Write로 ANIME.DAT 재구성 실패")
    for name in ("ICON0.PNG", "PIC0.PNG"):
        bare = (RESOURCE_DIR / "direct_iso" / name).read_bytes()
        rebuilt = bytes(reconstructed[f"PSP_GAME/{name}"])
        if rebuilt[:len(bare)] != bare or any(rebuilt[len(bare):]):
            raise ValueError(f"직결 PNG 고정 영역 재구성 실패: {name}")
        with Image.open(io.BytesIO(bare)) as image:
            image.load()

    base_entry = font_builder.parse_nispack_start_entry(base_system)
    final_entry = font_builder.parse_nispack_start_entry(final_system)
    base_start = decompress_buffer(base_system[int(base_entry["data_offset"]):int(base_entry["data_offset"]) + int(base_entry["size"])])[0]
    final_start = decompress_buffer(final_system[int(final_entry["data_offset"]):int(final_entry["data_offset"]) + int(final_entry["size"])])[0]
    base_archive = StartRuntimeArchive.from_bytes(base_start)
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    final_start_records = {record.output_name.casefold(): record for record in final_archive.records}
    for record in base_archive.records:
        final_record = final_start_records[record.output_name.casefold()]
        before = base_start[record.data_offset:record.end_offset]
        after = final_start[final_record.data_offset:final_record.end_offset]
        if record.output_name.casefold() != "anime00.dat" and before != after:
            raise ValueError(f"비대상 START 자원 변경: {record.output_name}")
    base_anime00_record = next(record for record in base_archive.records if record.output_name.casefold() == "anime00.dat")
    final_anime00_record = final_start_records["anime00.dat"]
    base_anime00 = base_start[base_anime00_record.data_offset:base_anime00_record.end_offset]
    final_anime00 = final_start[final_anime00_record.data_offset:final_anime00_record.end_offset]
    title_texture = texture_by_key(base_anime00, (78, 0, 0))
    if title_texture != texture_by_key(final_anime00, (78, 0, 0)):
        raise ValueError("object_078 텍스처 메타데이터 변경")
    pixel_end = title_texture.pixel_offset + title_texture.width * title_texture.height // 2
    if base_anime00[:title_texture.pixel_offset] != final_anime00[:title_texture.pixel_offset] or base_anime00[pixel_end:] != final_anime00[pixel_end:]:
        raise ValueError("object_078 픽셀 배열 밖 anime00.dat 변경")
    title_before = decode_texture(base_anime00, title_texture)
    title_after = decode_texture(final_anime00, title_texture)
    title_png = Image.open(RESIZED / "anime/anime00/object_078/group_00_page_00.png").convert("RGBA")
    if title_after.tobytes() != title_png.tobytes():
        raise ValueError("object_078 결과 PNG와 재디코드 불일치")
    title_changed = changed_pixels_inside(title_before, title_after, ((266, 174, 310, 219), (324, 155, 365, 193), (374, 153, 415, 192)))

    base_anime_records = {row["name"].casefold(): row for row in system_records(base_anime)}
    final_anime_records = {row["name"].casefold(): row for row in system_records(final_anime)}
    intro_entry = base_anime_records["anime96.dat"]
    if intro_entry != final_anime_records["anime96.dat"]:
        raise ValueError("ANIME.DAT 목차 변경")
    left, right = intro_entry["data_offset"], intro_entry["data_offset"] + intro_entry["size"]
    if base_anime[:left] != final_anime[:left] or base_anime[right:] != final_anime[right:]:
        raise ValueError("anime96.dat 밖 ANIME.DAT 변경")
    base_anime96, final_anime96 = base_anime[left:right], final_anime[left:right]
    intro_texture = texture_by_key(base_anime96, (0, 0, 0))
    if intro_texture != texture_by_key(final_anime96, (0, 0, 0)):
        raise ValueError("anime96 object_000 텍스처 메타데이터 변경")
    intro_pixel_end = intro_texture.pixel_offset + intro_texture.width * intro_texture.height // 2
    if base_anime96[:intro_texture.pixel_offset] != final_anime96[:intro_texture.pixel_offset] or base_anime96[intro_pixel_end:] != final_anime96[intro_pixel_end:]:
        raise ValueError("anime96 object_000 픽셀 배열 밖 변경")
    intro_before = decode_texture(base_anime96, intro_texture)
    intro_after = decode_texture(final_anime96, intro_texture)
    intro_png = Image.open(RESIZED / "anime/anime96/object_000/group_00_page_00.png").convert("RGBA")
    if intro_after.tobytes() != intro_png.tobytes():
        raise ValueError("anime96 결과 PNG와 재디코드 불일치")
    intro_changed = changed_pixels_inside(intro_before, intro_after, ((0, 23, 512, 47),))
    if intro_after.crop((0, 23, 512, 45)).tobytes() != intro_before.crop((0, 25, 512, 47)).tobytes():
        raise ValueError("anime96 마계 줄 2px 이동 불일치")

    report = {
        "format": "prinny1_v7_15_6_ui_image_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {"base_iso": sha256_file(BASE_ISO), "plan": sha256_file(PLAN), "expected_writes": sha256_file(WRITES)},
        "verified": {"expected_writes": len(rows), "title_changed_rgba_pixels": title_changed, "intro_changed_rgba_pixels": intro_changed},
        "checks": {
            "sealed_resource_hashes_match": True,
            "expected_writes_reconstruct_all_four_iso_targets": True,
            "direct_pngs_decode": True,
            "object_078_only_approved_glyph_rectangles_changed": True,
            "object_078_palette_and_metadata_preserved": True,
            "anime96_line_moved_up_exactly_2px": True,
            "anime96_palette_and_metadata_preserved": True,
            "all_other_start_resources_preserved_including_v7_15_5_dialogue": True,
            "all_other_anime_resources_preserved": True,
        },
        "status": "pass_v7_15_6_ui_image_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Expected Writes: {len(rows)}")
    print(f"object_078 changed pixels: {title_changed}")
    print(f"anime96 changed pixels: {intro_changed}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
