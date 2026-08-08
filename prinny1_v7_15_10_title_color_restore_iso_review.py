#!/usr/bin/env python3
"""Independent postbuild review for the V7.15.10 PSP test ISO."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_9_safe_images/prinny_korean_v7_15_9_safe_images.iso"
ISO = ROOT / "workspace/build/prinny1_v7_15_10_title_color_restore/prinny_korean_v7_15_10_title_color_restore.iso"
SYSTEM = ROOT / "workspace/build/prinny1_v7_15_10_title_color_restore_resources/SYSTEM.DAT"
XDELTA_BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_10_title_color_restore_iso_review"

EXPECTED = {
    BASE_ISO: "f16cb548f77c094f4e01411c04b5ae5028bcdb3093d8a953727fd62bbae097f1",
    ISO: "e26f628360cac2043338051070acfb1f4586a9e321469f7dc3d578375265badf",
    SYSTEM: "6a2f8865de9effde92e2218509af8d5eb0a80aac1cbf8f7926231c60db0f7eb5",
    XDELTA_BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
}


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


def anime00_from_system(system: bytes) -> tuple[bytes, bytes]:
    row = next(item for item in system_records(system) if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    start = decompress_buffer(lzs)[0]
    archive = StartRuntimeArchive.from_bytes(start)
    anime = next(item for item in archive.records if item.output_name.casefold() == "anime00.dat")
    return start[anime.data_offset:anime.end_offset], lzs


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.10 사후 검토 입력 해시 불일치: {path}")
    base_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_record = find_iso_file(ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    if (base_record["extent_lba"], base_record["data_length"]) != (final_record["extent_lba"], final_record["data_length"]):
        raise ValueError("최종 ISO SYSTEM.DAT 디렉터리 레코드 변경")
    offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    length = int(base_record["data_length"])
    if hash_range(BASE_ISO, 0, offset) != hash_range(ISO, 0, offset):
        raise ValueError("SYSTEM.DAT 앞 허용 범위 밖 변경")
    if hash_range(BASE_ISO, offset + length, BASE_ISO.stat().st_size) != hash_range(ISO, offset + length, ISO.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 허용 범위 밖 변경")
    final_system = read_iso_file(ISO, final_record)
    if final_system != SYSTEM.read_bytes():
        raise ValueError("최종 ISO SYSTEM.DAT 재추출 불일치")

    final_anime, final_lzs = anime00_from_system(final_system)
    xdelta_system = read_iso_file(XDELTA_BASE_ISO, find_iso_file(XDELTA_BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    xdelta_anime, _xdelta_lzs = anime00_from_system(xdelta_system)
    if final_anime != xdelta_anime or overlap_count(final_lzs) != 0:
        raise ValueError("최종 타이틀 anime00 권위 원본 또는 LZS 안전성 불일치")

    base_system = read_iso_file(BASE_ISO, base_record)
    base_rows, final_rows = system_records(base_system), system_records(final_system)
    unchanged_images = ["replay_icon0.png", "umd_icon0.png", "umd_pic0.png", "prinny_icon0.png"]
    for name in unchanged_images:
        old = next(row for row in base_rows if row["name"].casefold() == name)
        new = next(row for row in final_rows if row["name"].casefold() == name)
        if base_system[old["data_offset"]:old["data_offset"] + old["size"]] != final_system[new["data_offset"]:new["data_offset"] + new["size"]]:
            raise ValueError(f"V7.15.9 한글 이미지 보존 실패: {name}")

    test = subprocess.run(["7z", "t", str(ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("최종 ISO 7z 재검사 실패")

    report = {
        "format": "prinny1_v7_15_10_title_color_restore_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": sha256_file(ISO)},
        "verified": {"runtime_lzs_overlaps": 0, "anime00_exact_xdelta": True, "preserved_system_images": unchanged_images},
        "checks": {
            "only_system_dat_extent_changed": True,
            "system_dat_reextracted_exactly": True,
            "title_anime_exact_xdelta_authoritative": True,
            "runtime_lzs_non_overlap": True,
            "v7_15_9_korean_images_preserved": True,
            "anime_bg_direct_png_inherited_by_outside_range_hash": True,
            "seven_zip_structure_retest": True,
        },
        "status": "pass_v7_15_10_iso_ready_for_ppsspp_runtime_test",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {sha256_file(ISO)}")
    print("SYSTEM-only/anime00 exact/LZS/images/7z: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
