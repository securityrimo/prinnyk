#!/usr/bin/env python3
"""Restore the xdelta-authoritative title atlas on the V7.15.9 image build."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_9_safe_images/prinny_korean_v7_15_9_safe_images.iso"
XDELTA_BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
RUNTIME_REPORT = ROOT / "workspace/reports/prinny1_v7_15_9_runtime/all_report.json"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_10_title_color_restore_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_10_title_color_restore_plan"
TITLE_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_10/anime/anime00/object_078/group_00_page_00.png"

EXPECTED = {
    BASE_ISO: "f16cb548f77c094f4e01411c04b5ae5028bcdb3093d8a953727fd62bbae097f1",
    XDELTA_BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    RUNTIME_REPORT: "33b178bb220c5cf6d0e02fc598cecbe2cff7fdb865cb10d8045a9116ba15ab4d",
}


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
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.10 입력 해시 불일치: {path}")
    runtime = json.loads(RUNTIME_REPORT.read_text(encoding="utf-8"))
    if runtime.get("status") != "runtime_blocker_title_color_v7_15_9":
        raise ValueError("V7.15.9 타이틀 색상 런타임 근거 불일치")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    xdelta_system = read_iso_file(XDELTA_BASE_ISO, find_iso_file(XDELTA_BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    base_rows = system_records(base_system)
    start_row = next(row for row in base_rows if row["name"].casefold() == "start.lzs")
    old_lzs = base_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    base_start, header = decompress_buffer(old_lzs)
    if overlap_count(old_lzs) != 0:
        raise ValueError("V7.15.9 부모 START.LZS에 겹침 역참조 존재")
    base_archive = StartRuntimeArchive.from_bytes(base_start)
    base_anime_record = next(row for row in base_archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[base_anime_record.data_offset:base_anime_record.end_offset]

    xdelta_start_row = next(row for row in system_records(xdelta_system) if row["name"].casefold() == "start.lzs")
    xdelta_lzs = xdelta_system[xdelta_start_row["data_offset"]:xdelta_start_row["data_offset"] + xdelta_start_row["size"]]
    xdelta_start = decompress_buffer(xdelta_lzs)[0]
    xdelta_archive = StartRuntimeArchive.from_bytes(xdelta_start)
    xdelta_anime_record = next(row for row in xdelta_archive.records if row.output_name.casefold() == "anime00.dat")
    authoritative_anime = xdelta_start[xdelta_anime_record.data_offset:xdelta_anime_record.end_offset]
    if len(authoritative_anime) != len(base_anime) or authoritative_anime == base_anime:
        raise ValueError("권위 타이틀 anime00 크기 또는 차이 불일치")

    final_start = bytearray(base_start)
    final_start[base_anime_record.data_offset:base_anime_record.end_offset] = authoritative_anime
    for row in base_archive.records:
        before = base_start[row.data_offset:row.end_offset]
        after = bytes(final_start[row.data_offset:row.end_offset])
        if row.output_name.casefold() != "anime00.dat" and before != after:
            raise ValueError(f"비대상 START 자원 변경: {row.output_name}")

    new_lzs = compress_buffer_runtime_safe(bytes(final_start), old_lzs[:4], int(header["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start) or overlap_count(new_lzs) != 0:
        raise ValueError("V7.15.10 런타임 안전 LZS 검증 실패")
    next_offset = base_rows[start_row["index"] + 1]["data_offset"]
    capacity = next_offset - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError(f"V7.15.10 START.LZS 슬롯 초과: {len(new_lzs)}>{capacity}")

    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:next_offset] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))
    final_rows = system_records(bytes(final_system))
    final_start_row = next(row for row in final_rows if row["name"].casefold() == "start.lzs")
    extracted = decompress_buffer(bytes(final_system[final_start_row["data_offset"]:final_start_row["data_offset"] + final_start_row["size"]]))[0]
    if extracted != bytes(final_start):
        raise ValueError("최종 SYSTEM.DAT START 재추출 실패")

    texture = texture_by_key(authoritative_anime, (78, 0, 0))
    title = decode_texture(authoritative_anime, texture).convert("RGBA")
    TITLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    title.save(TITLE_OUTPUT, format="PNG", optimize=True, compress_level=9)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "SYSTEM.DAT": bytes(final_system),
        "start.dat": bytes(final_start),
        "start.lzs": new_lzs,
        "anime00.dat": authoritative_anime,
    }
    for name, blob in artifacts.items():
        (OUTPUT / name).write_bytes(blob)
    report = {
        "format": "prinny1_v7_15_10_title_color_restore_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "old_lzs_size": len(old_lzs),
            "new_lzs_size": len(new_lzs),
            "lzs_capacity": capacity,
            "lzs_overlaps": 0,
            "title_source": "exact_xdelta_authoritative_anime00",
            "inherited_v7_15_9_korean_images": True,
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()} | {"title_png": sha256_file(TITLE_OUTPUT)},
        "checks": {
            "only_anime00_changed_inside_start": True,
            "runtime_safe_lzs_non_overlap": True,
            "title_anime_exact_xdelta_authoritative": True,
            "all_other_v7_15_9_images_inherited": True,
            "iso_created": False,
        },
        "status": "title_color_restore_resources_sealed_independent_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"START.LZS: {len(old_lzs)} -> {len(new_lzs)} / {capacity}; overlaps 0")
    print(f"anime00 exact xdelta: {sha256_bytes(authoritative_anime)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
