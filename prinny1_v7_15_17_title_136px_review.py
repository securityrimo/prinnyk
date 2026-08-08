#!/usr/bin/env python3
"""Independent pre-ISO review for the V7.15.17 136 px title canary."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from scripts.prinny_anime_preview import decode_texture, parse_objects, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
BUILD = ROOT / "workspace/build/prinny1_v7_15_17_title_136px_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_17_title_136px_plan/all_report.json"
TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_17/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_17_title_136px_review"
EXPECTED = {
    BASE_ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    BUILD / "SYSTEM.DAT": "23f05e52f4c013ba1f7a686b28c82be75831b64982f2f121efb488194b28b796",
    BUILD / "start.dat": "8e48bd2b3b261523c6936afd5fa7d77f7f721bd300da8564544d8f74615cc94f",
    BUILD / "start.lzs": "f0b2862c0401283822e45098aafbc5b922b97ea6b48c9fde7640f54cb3cc6597",
    BUILD / "anime00.dat": "09726bd89c00dee612a10dd012203b6b1ba933b3701fd2a6648c934f91d9e3bb",
    TITLE: "77f6d4fc99b6da7a598ee14274ba062157c0a6bb163e1a1d13b3ae0ec659ede1",
    PLAN: "788f73dbba25dfae108e9f2b0fbef250bfa0a8517a19a9f026648e7503965fde",
}
FOREGROUND = (0, 255, 0, 255)
TRANSPARENT = (0, 0, 0, 0)
GLYPHS = (
    {"text": "프", "cell": (256, 160, 320, 224), "old": (273, 181, 303, 212), "target": (271, 179, 305, 214), "pixels": 427},
    {"text": "리", "cell": (320, 160, 376, 208), "old": (331, 161, 359, 187), "target": (329, 159, 361, 189), "pixels": 402},
    {"text": "니", "cell": (376, 160, 424, 208), "old": (381, 159, 409, 186), "target": (379, 159, 411, 187), "pixels": 315},
)
TRANSFORMS = (
    (0x23B4, (-63, -29, 32, 32), (-70, -29, 32, 32)),
    (0x23C4, (-63, -37, 32, 32), (-70, -37, 32, 32)),
    (0x23D4, (-7, -38, 28, 24), (-7, -38, 28, 24)),
    (0x23E4, (-6, -46, 28, 24), (-6, -46, 28, 24)),
    (0x23F4, (-6, -38, 28, 24), (-6, -38, 28, 24)),
    (0x2404, (39, -50, 24, 24), (45, -50, 24, 24)),
    (0x2414, (39, -58, 24, 24), (45, -58, 24, 24)),
)


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


def extract_start(system: bytes) -> tuple[bytes, bytes, list[dict]]:
    rows = system_records(system)
    row = next(item for item in rows if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs, rows


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.17 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "title_136px_resources_sealed_independent_review_required":
        raise ValueError("V7.15.17 계획 상태 불일치")
    if plan.get("calculation", {}).get("target_runtime_width_px") != 136:
        raise ValueError("V7.15.17 목표 폭 불일치")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = (BUILD / "SYSTEM.DAT").read_bytes()
    base_start, _base_lzs, base_rows = extract_start(base_system)
    final_start, final_lzs, final_rows = extract_start(final_system)
    if final_start != (BUILD / "start.dat").read_bytes() or final_lzs != (BUILD / "start.lzs").read_bytes():
        raise ValueError("V7.15.17 START/LZS 봉인 불일치")
    if overlap_count(final_lzs):
        raise ValueError("V7.15.17 START.LZS 겹침 역참조")
    if [(row["name"], row["data_offset"]) for row in base_rows] != [(row["name"], row["data_offset"]) for row in final_rows]:
        raise ValueError("SYSTEM 자원 목록 또는 오프셋 변경")
    changed_system = []
    for old, new in zip(base_rows, final_rows):
        before = base_system[old["data_offset"]:old["data_offset"] + old["size"]]
        after = final_system[new["data_offset"]:new["data_offset"] + new["size"]]
        if before != after or old["size"] != new["size"]:
            changed_system.append(old["name"].casefold())
    if changed_system != ["start.lzs"]:
        raise ValueError(f"SYSTEM 변경 자원 불일치: {changed_system}")

    base_archive = StartRuntimeArchive.from_bytes(base_start)
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    changed_start = []
    for old, new in zip(base_archive.records, final_archive.records):
        if (old.output_name, old.data_offset, old.end_offset) != (new.output_name, new.data_offset, new.end_offset):
            raise ValueError("START 자원 경계 변경")
        if base_start[old.data_offset:old.end_offset] != final_start[new.data_offset:new.end_offset]:
            changed_start.append(old.output_name.casefold())
    if changed_start != ["anime00.dat"]:
        raise ValueError(f"START 변경 자원 불일치: {changed_start}")

    base_record = next(row for row in base_archive.records if row.output_name.casefold() == "anime00.dat")
    final_record = next(row for row in final_archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[base_record.data_offset:base_record.end_offset]
    final_anime = final_start[final_record.data_offset:final_record.end_offset]
    if final_anime != (BUILD / "anime00.dat").read_bytes():
        raise ValueError("anime00 봉인본 불일치")
    texture = texture_by_key(base_anime, (78, 0, 0))
    base_title = decode_texture(base_anime, texture).convert("RGBA")
    final_title = decode_texture(final_anime, texture).convert("RGBA")
    with Image.open(TITLE) as opened:
        opened.load()
        if final_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("최종 anime00/PNG 왕복 불일치")
    allowed_rects = []
    for spec in GLYPHS:
        cell, old, target = spec["cell"], spec["old"], spec["target"]
        allowed_rects.append((min(cell[0], old[0], target[0]), min(cell[1], old[1], target[1]), max(cell[2], old[2], target[2]), max(cell[3], old[3], target[3])))
        crop = final_title.crop(cell)
        if set(crop.getdata()) > {TRANSPARENT, FOREGROUND}:
            raise ValueError(f"{spec['text']} 셀 팔레트 불일치")
        if sum(pixel == FOREGROUND for pixel in final_title.crop(target).getdata()) != spec["pixels"]:
            raise ValueError(f"{spec['text']} 형광 전경 픽셀 수 불일치")
    changed_pixels = assert_changes_inside(base_title, final_title, tuple(allowed_rects))
    if changed_pixels != 454:
        raise ValueError(f"타이틀 변경 픽셀 수 불일치: {changed_pixels}")

    obj = parse_objects(base_anime)[78]
    reverted = bytearray(final_anime)
    transform_changed = set()
    for relative, before_tuple, after_tuple in TRANSFORMS:
        at = obj.offset + relative
        before = struct.pack("<2h2H", *before_tuple)
        after = struct.pack("<2h2H", *after_tuple)
        if base_anime[at:at + 8] != before or final_anime[at:at + 8] != after:
            raise ValueError(f"transform 행 불일치: 0x{relative:X}")
        reverted[at:at + 8] = before
        transform_changed.update(at + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    expected_pixel_anime = repack_texture(base_anime, texture, final_title)
    if bytes(reverted) != expected_pixel_anime or len(transform_changed) != 4:
        raise ValueError("텍스처와 네 transform 바이트 밖 anime00 변경")

    report = {
        "format": "prinny1_v7_15_17_title_136px_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verified": {
            "changed_system_resources": changed_system,
            "changed_start_resources": changed_start,
            "changed_title_pixels": changed_pixels,
            "transform_changed_bytes": len(transform_changed),
            "runtime_lzs_overlaps": 0,
            "target_runtime_width_px": 136,
        },
        "checks": {
            "plan_hash_locked": True,
            "lime_foreground_only": True,
            "three_glyph_regions_only": True,
            "sampler_size_and_y_unchanged": True,
            "only_outer_x_transform_changed": True,
            "only_anime00_changed_in_start": True,
            "runtime_safe_lzs_non_overlap": True,
            "v7_15_16_other_resources_preserved": True,
        },
        "status": "pass_v7_15_17_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.15.17 title 136px independent prebuild review: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
