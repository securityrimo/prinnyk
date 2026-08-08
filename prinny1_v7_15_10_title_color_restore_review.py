#!/usr/bin/env python3
"""Independent prebuild review for the V7.15.10 title color restore."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_9_safe_images/prinny_korean_v7_15_9_safe_images.iso"
XDELTA_BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_10_title_color_restore_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_10_title_color_restore_plan/all_report.json"
TITLE_PNG = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_10/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_10_title_color_restore_review"

EXPECTED = {
    BASE_ISO: "f16cb548f77c094f4e01411c04b5ae5028bcdb3093d8a953727fd62bbae097f1",
    XDELTA_BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    RESOURCE_DIR / "SYSTEM.DAT": "6a2f8865de9effde92e2218509af8d5eb0a80aac1cbf8f7926231c60db0f7eb5",
    RESOURCE_DIR / "start.dat": "1a230abd89106a8847547fe7b91be3f21a2968fe0fc50168b65b368e127d68b2",
    RESOURCE_DIR / "start.lzs": "31194007f94630047271826f5c70184bc9db590ed788144d238bfb48c2c87a87",
    RESOURCE_DIR / "anime00.dat": "4db8d10bc5c6ccc0e0d6f392d91f82cddcffae573e5a477c47646a4cfa71f55e",
    TITLE_PNG: "b2f6cb452e34956737f269a74c35f64e05755008898d79be1548db47131c9100",
    PLAN: "c417d41f945fe3d983142b7954be412a71cb4c3c697975977f8d66fe0c610b5e",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("고정 크기 비교 길이 불일치")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


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


def extract_start(system: bytes) -> tuple[bytes, bytes, dict, list[dict]]:
    rows = system_records(system)
    row = next(item for item in rows if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs, row, rows


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.10 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "title_color_restore_resources_sealed_independent_review_required":
        raise ValueError("V7.15.10 계획 상태 불일치")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    base_start, _base_lzs, base_row, base_rows = extract_start(base_system)
    final_start, final_lzs, final_row, final_rows = extract_start(final_system)
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or final_lzs != (RESOURCE_DIR / "start.lzs").read_bytes() or overlap_count(final_lzs) != 0:
        raise ValueError("최종 START/LZS 봉인 또는 안전성 불일치")
    if [(r["name"], r["data_offset"]) for r in base_rows] != [(r["name"], r["data_offset"]) for r in final_rows]:
        raise ValueError("SYSTEM 자원 목록/오프셋 변경")
    changed_system_resources = []
    for old, new in zip(base_rows, final_rows):
        old_blob = base_system[old["data_offset"]:old["data_offset"] + old["size"]]
        new_blob = final_system[new["data_offset"]:new["data_offset"] + new["size"]]
        if old_blob != new_blob or old["size"] != new["size"]:
            changed_system_resources.append(old["name"].casefold())
    if changed_system_resources != ["start.lzs"]:
        raise ValueError(f"SYSTEM 변경 자원 불일치: {changed_system_resources}")

    base_archive, final_archive = StartRuntimeArchive.from_bytes(base_start), StartRuntimeArchive.from_bytes(final_start)
    if [(r.output_name, r.data_offset, r.end_offset) for r in base_archive.records] != [(r.output_name, r.data_offset, r.end_offset) for r in final_archive.records]:
        raise ValueError("START 자원 경계 변경")
    changed_start_resources = []
    for old, new in zip(base_archive.records, final_archive.records):
        if base_start[old.data_offset:old.end_offset] != final_start[new.data_offset:new.end_offset]:
            changed_start_resources.append(old.output_name.casefold())
    if changed_start_resources != ["anime00.dat"]:
        raise ValueError(f"START 변경 자원 불일치: {changed_start_resources}")
    final_anime_record = next(r for r in final_archive.records if r.output_name.casefold() == "anime00.dat")
    final_anime = final_start[final_anime_record.data_offset:final_anime_record.end_offset]
    if final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("최종 anime00 봉인본 불일치")

    xdelta_system = read_iso_file(XDELTA_BASE_ISO, find_iso_file(XDELTA_BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    xdelta_start = extract_start(xdelta_system)[0]
    xdelta_archive = StartRuntimeArchive.from_bytes(xdelta_start)
    xdelta_anime_record = next(r for r in xdelta_archive.records if r.output_name.casefold() == "anime00.dat")
    xdelta_anime = xdelta_start[xdelta_anime_record.data_offset:xdelta_anime_record.end_offset]
    if final_anime != xdelta_anime:
        raise ValueError("anime00가 xdelta 권위 원본과 다름")
    texture = texture_by_key(final_anime, (78, 0, 0))
    decoded = decode_texture(final_anime, texture).convert("RGBA")
    with Image.open(TITLE_PNG) as opened:
        opened.load()
        if decoded.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("권위 타이틀 PNG 왕복 불일치")

    next_offset = base_rows[base_row["index"] + 1]["data_offset"]
    allowed = set(range(base_row["data_offset"], next_offset))
    entry = 0x10 + base_row["index"] * 0x2C
    allowed.update(range(entry + 0x24, entry + 0x28))
    if not changed_offsets(base_system, final_system) <= allowed:
        raise ValueError("SYSTEM START 슬롯 밖 변경")

    report = {
        "format": "prinny1_v7_15_10_title_color_restore_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "changed_system_resources": changed_system_resources,
            "changed_start_resources": changed_start_resources,
            "runtime_lzs_overlaps": 0,
            "anime00_exact_xdelta": True,
        },
        "checks": {
            "plan_hash_locked": True,
            "only_start_lzs_changed_in_system": True,
            "only_anime00_changed_in_start": True,
            "dialogue_preserved": True,
            "title_exact_xdelta_authoritative": True,
            "title_png_roundtrip_exact": True,
            "runtime_lzs_non_overlap": True,
            "system_changes_bounded": True,
        },
        "status": "pass_v7_15_10_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SYSTEM: start.lzs only; START: anime00.dat only")
    print("anime00 exact xdelta; LZS overlaps: 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
