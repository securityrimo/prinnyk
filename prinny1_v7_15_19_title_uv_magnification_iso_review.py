#!/usr/bin/env python3
"""Independent post-build review of the V7.15.19 title test ISO."""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from prinny1_v7_15_18_logo_style_title_plan import overlap_count
from scripts.prinny_anime_preview import decode_texture, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_19_title_uv_magnification/prinny_korean_v7_15_19_title_uv_magnification.iso"
SEALED_SYSTEM = ROOT / "workspace/build/prinny1_v7_15_19_title_uv_magnification_resources/SYSTEM.DAT"
SEALED_ANIME = ROOT / "workspace/build/prinny1_v7_15_19_title_uv_magnification_resources/anime00.dat"
TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_19/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_19_title_uv_magnification_iso_review"
EXPECTED = {
    BASE_ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    OUTPUT_ISO: "4d14eb517e62ff4f85d3f714ba50f32fe5cb31607cc943383220574cf139184c",
    SEALED_SYSTEM: "902ae0912a21d42b22d330c04ec3c046b4692218673a01205940a8dab63f4efe",
    SEALED_ANIME: "256395086a800382e99125926cf9b69e31b685f7b84d4fce3abb0f4084e3359a",
    TITLE: "3f2b99309e0d928cc86e403115b3c3aa9768596acd2daea7e2cadc269d56c5cc",
}
UV_ROWS = (
    (0x2018, (1, 273, 181, 30, 31, 0)),
    (0x2028, (1, 331, 161, 28, 26, 0)),
    (0x2038, (1, 381, 159, 28, 27, 0)),
)
TRANSFORMS = (
    (0x23B4, (-69, -29, 32, 32)), (0x23C4, (-69, -37, 32, 32)),
    (0x23D4, (-7, -38, 28, 24)), (0x23E4, (-6, -46, 28, 24)),
    (0x23F4, (-6, -38, 28, 24)), (0x2404, (43, -50, 24, 24)),
    (0x2414, (43, -58, 24, 24)), (0x2424, (77, -61, 20, 16)),
    (0x2434, (77, -69, 20, 16)),
)
BAR_CELL = (424, 160, 464, 192)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def extract(system: bytes) -> tuple[bytes, bytes]:
    row = next(item for item in system_records(system) if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.19 ISO 사후 검토 입력 해시 불일치: {path}")
    base_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_record = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    if (base_record["extent_lba"], base_record["data_length"]) != (final_record["extent_lba"], final_record["data_length"]):
        raise ValueError("SYSTEM.DAT ISO 범위 변경")
    offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    end = offset + int(base_record["data_length"])
    if BASE_ISO.stat().st_size != OUTPUT_ISO.stat().st_size or hash_range(BASE_ISO, 0, offset) != hash_range(OUTPUT_ISO, 0, offset) or hash_range(BASE_ISO, end, BASE_ISO.stat().st_size) != hash_range(OUTPUT_ISO, end, OUTPUT_ISO.stat().st_size):
        raise ValueError("SYSTEM.DAT 범위 밖 ISO 변경")
    base_system = read_iso_file(BASE_ISO, base_record)
    final_system = read_iso_file(OUTPUT_ISO, final_record)
    if final_system != SEALED_SYSTEM.read_bytes():
        raise ValueError("재추출 SYSTEM.DAT 봉인 불일치")
    base_start, _base_lzs = extract(base_system)
    final_start, final_lzs = extract(final_system)
    if overlap_count(final_lzs):
        raise ValueError("재추출 START.LZS 겹침 역참조")
    base_archive = StartRuntimeArchive.from_bytes(base_start)
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    changed = []
    for old, new in zip(base_archive.records, final_archive.records):
        if (old.output_name, old.data_offset, old.end_offset) != (new.output_name, new.data_offset, new.end_offset):
            raise ValueError("START 자원 경계 변경")
        if base_start[old.data_offset:old.end_offset] != final_start[new.data_offset:new.end_offset]:
            changed.append(old.output_name.casefold())
    if changed != ["anime00.dat"]:
        raise ValueError(f"START 변경 자원 불일치: {changed}")
    anime_row = next(row for row in final_archive.records if row.output_name.casefold() == "anime00.dat")
    anime = final_start[anime_row.data_offset:anime_row.end_offset]
    if anime != SEALED_ANIME.read_bytes():
        raise ValueError("재추출 anime00 봉인 불일치")
    texture = texture_by_key(anime, (78, 0, 0))
    title = decode_texture(anime, texture).convert("RGBA")
    with Image.open(TITLE) as opened:
        opened.load()
        if title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("재추출 타이틀 PNG 왕복 불일치")
    if any(pixel[3] != 0 for pixel in title.crop(BAR_CELL).getdata()):
        raise ValueError("일본어 장음표 잔존")
    obj = parse_objects(anime)[78]
    for relative, values in UV_ROWS:
        if anime[obj.offset + relative:obj.offset + relative + 16] != struct.pack("<I4HI", *values):
            raise ValueError(f"재추출 UV 불일치: 0x{relative:X}")
    for relative, values in TRANSFORMS:
        if anime[obj.offset + relative:obj.offset + relative + 8] != struct.pack("<2h2H", *values):
            raise ValueError(f"재추출 transform 불일치: 0x{relative:X}")
    test = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.19 ISO 7z 구조 재검사 실패")
    report = {
        "format": "prinny1_v7_15_19_title_uv_magnification_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {"changed_start_resources": changed, "title_texture_roundtrip_exact": True, "uv_rows_exact": 3, "screen_width_px": 136, "japanese_long_mark_removed": True, "runtime_lzs_overlaps": 0, "ppsspp_launched": False},
        "checks": {"only_system_dat_iso_extent_changed": True, "sealed_system_reextracted_exactly": True, "sealed_anime00_reextracted_exactly": True, "only_anime00_changed_in_start": True, "seven_zip_structure_retest": True},
        "status": "pass_v7_15_19_iso_ready_for_manual_title_screen_test",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.15.19 ISO range/reextract/UV/title/structure: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
