#!/usr/bin/env python3
"""Enlarge only the white-rendered 프 sprite geometry as a runtime canary."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from scripts.prinny_anime_preview import parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_13_title_sprite_geometry_canary_resources"
REPORT = ROOT / "workspace/reports/prinny1_v7_15_13_title_sprite_geometry_canary_plan"
EXPECTED_BASE = "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4"
EXPECTED_ANIME = "df9df6273e3cf8714121fa0e405dd37844251fc036b2b596e01b267b63cefb6a"

# object_078 transform rows 2 and 3 are the two animation states that reference
# image-cell 1 (프).  Keep each center fixed while changing 32x32 to 64x64.
PATCHES = (
    (0x23B4, (-63, -29, 32, 32), (-79, -45, 64, 64)),
    (0x23C4, (-63, -37, 32, 32), (-79, -53, 64, 64)),
)
GEOMETRY_POLICY = "center_preserved"


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


def main() -> int:
    if not BASE_ISO.is_file() or sha256_file(BASE_ISO) != EXPECTED_BASE:
        raise ValueError("V7.15.13 카나리 부모 ISO 해시 불일치")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(base_system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    old_lzs = base_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    base_start, header = decompress_buffer(old_lzs)
    if overlap_count(old_lzs):
        raise ValueError("부모 LZS 겹침 역참조")
    archive = StartRuntimeArchive.from_bytes(base_start)
    anime_record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[anime_record.data_offset:anime_record.end_offset]
    if sha256_bytes(base_anime) != EXPECTED_ANIME:
        raise ValueError("부모 anime00 해시 불일치")
    obj = parse_objects(base_anime)[78]
    patched_anime = bytearray(base_anime)
    expected_offsets: set[int] = set()
    writes = []
    for rel, before_tuple, after_tuple in PATCHES:
        offset = obj.offset + rel
        before = struct.pack("<2h2H", *before_tuple)
        after = struct.pack("<2h2H", *after_tuple)
        if base_anime[offset:offset + 8] != before:
            raise ValueError(f"프 transform 기준 바이트 불일치: 0x{offset:X}")
        patched_anime[offset:offset + 8] = after
        expected_offsets.update(offset + i for i, (a, b) in enumerate(zip(before, after)) if a != b)
        writes.append({
            "relative_offset_hex": f"0x{rel:X}", "absolute_anime_offset_hex": f"0x{offset:X}",
            "before": list(before_tuple), "after": list(after_tuple),
            "before_hex": before.hex().upper(), "after_hex": after.hex().upper(),
        })
    actual_offsets = {i for i, (a, b) in enumerate(zip(base_anime, patched_anime)) if a != b}
    if actual_offsets != expected_offsets or not actual_offsets:
        raise ValueError(f"카나리 변경 범위 불일치: {len(actual_offsets)}")

    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = patched_anime
    for row in archive.records:
        before = base_start[row.data_offset:row.end_offset]
        after = bytes(final_start[row.data_offset:row.end_offset])
        if row.output_name.casefold() != "anime00.dat" and before != after:
            raise ValueError(f"비대상 START 자원 변경: {row.output_name}")
    new_lzs = compress_buffer_runtime_safe(bytes(final_start), old_lzs[:4], int(header["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start) or overlap_count(new_lzs):
        raise ValueError("카나리 LZS 런타임 안전성 실패")
    next_offset = rows[start_row["index"] + 1]["data_offset"]
    capacity = next_offset - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError("카나리 START.LZS 슬롯 초과")
    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:next_offset] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))
    check_entry = font_builder.parse_nispack_start_entry(bytes(final_system))
    check_start = decompress_buffer(bytes(final_system[int(check_entry["data_offset"]):int(check_entry["data_offset"]) + int(check_entry["size"])]))[0]
    if check_start != bytes(final_start):
        raise ValueError("카나리 SYSTEM 왕복 실패")

    artifacts = {"anime00.dat": bytes(patched_anime), "start.dat": bytes(final_start), "start.lzs": new_lzs, "SYSTEM.DAT": bytes(final_system)}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, blob in artifacts.items():
        (OUTPUT / name).write_bytes(blob)
    report = {
        "format": "prinny1_v7_15_13_title_sprite_geometry_canary_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "writes": writes,
        "verified": {"anime_changed_bytes": len(actual_offsets), "lzs_overlaps": 0, "new_lzs_size": len(new_lzs), "capacity": capacity},
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()},
        "checks": {"only_pr_geometry_rows_2_3_changed": True, "geometry_policy": GEOMETRY_POLICY, "texture_pixels_unchanged": True, "only_anime00_changed_in_start": True, "runtime_safe_lzs": True},
        "status": "canary_resources_sealed_independent_review_required",
    }
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"anime changed bytes: {len(actual_offsets)}")
    print(f"START.LZS: {len(old_lzs)} -> {len(new_lzs)} / {capacity}; overlaps 0")
    print(f"geometry rows: {len(PATCHES)}, {GEOMETRY_POLICY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
