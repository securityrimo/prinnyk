#!/usr/bin/env python3
"""Independent post-build review of the V7.15.18 logo-style title ISO."""
from __future__ import annotations

import hashlib
import json
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
from scripts.prinny_anime_preview import decode_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_18_logo_style_title/prinny_korean_v7_15_18_logo_style_title.iso"
SEALED_SYSTEM = ROOT / "workspace/build/prinny1_v7_15_18_logo_style_title_resources/SYSTEM.DAT"
SEALED_ANIME = ROOT / "workspace/build/prinny1_v7_15_18_logo_style_title_resources/anime00.dat"
TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_18/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_18_logo_style_title_iso_review"
EXPECTED = {
    BASE_ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    OUTPUT_ISO: "a31c2a9938b8d7a64aac6c24352fdc90a6faf050ccbbec284df9be3def377868",
    SEALED_SYSTEM: "f33b250ad4f90874c4f5f901e0ec237f966c77285ddc3e4c2dbba95f02de10d9",
    SEALED_ANIME: "8ee7db07bd7d3b4977d5c5e40e54fba720f61b01940bd263b1100b1b0d72437e",
    TITLE: "416e4f040505838b2d4041bd9ae3489426caa5671f52ff43bf762941e78e200c",
}
BAR_CELL = (424, 160, 464, 192)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def extract_start(system: bytes) -> bytes:
    row = next(item for item in system_records(system) if item["name"].casefold() == "start.lzs")
    return decompress_buffer(system[row["data_offset"]:row["data_offset"] + row["size"]])[0]


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.18 ISO 사후 검토 입력 해시 불일치: {path}")
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
    base_start, final_start = extract_start(base_system), extract_start(final_system)
    ba, fa = StartRuntimeArchive.from_bytes(base_start), StartRuntimeArchive.from_bytes(final_start)
    changed_start = []
    for old, new in zip(ba.records, fa.records):
        if (old.output_name, old.data_offset, old.end_offset) != (new.output_name, new.data_offset, new.end_offset):
            raise ValueError("START 자원 경계 변경")
        if base_start[old.data_offset:old.end_offset] != final_start[new.data_offset:new.end_offset]:
            changed_start.append(old.output_name.casefold())
    if changed_start != ["anime00.dat"]:
        raise ValueError(f"START 변경 자원 불일치: {changed_start}")
    old_row = next(row for row in ba.records if row.output_name.casefold() == "anime00.dat")
    new_row = next(row for row in fa.records if row.output_name.casefold() == "anime00.dat")
    final_anime = final_start[new_row.data_offset:new_row.end_offset]
    if final_anime != SEALED_ANIME.read_bytes():
        raise ValueError("재추출 anime00 봉인 불일치")
    texture = texture_by_key(final_anime, (78, 0, 0))
    title = decode_texture(final_anime, texture).convert("RGBA")
    with Image.open(TITLE) as opened:
        opened.load()
        if title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("재추출 타이틀 PNG 왕복 불일치")
    if any(pixel[3] != 0 for pixel in title.crop(BAR_CELL).getdata()):
        raise ValueError("재추출 타이틀에 일본어 장음표 잔존")
    test = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.18 ISO 7z 구조 재검사 실패")
    report = {
        "format": "prinny1_v7_15_18_logo_style_title_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {"changed_start_resources": changed_start, "title_texture_roundtrip_exact": True, "japanese_long_mark_removed": True, "ppsspp_launched": False},
        "checks": {"only_system_dat_iso_extent_changed": True, "sealed_system_reextracted_exactly": True, "sealed_anime00_reextracted_exactly": True, "only_anime00_changed_in_start": True, "seven_zip_structure_retest": True},
        "status": "pass_v7_15_18_iso_ready_for_manual_title_screen_test",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.15.18 ISO range/reextract/title/structure: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
