#!/usr/bin/env python3
"""Independent post-build review of the V7.15.17 136 px title ISO."""
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
from scripts.prinny_anime_preview import decode_texture, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_17_title_136px/prinny_korean_v7_15_17_title_136px.iso"
SEALED_SYSTEM = ROOT / "workspace/build/prinny1_v7_15_17_title_136px_resources/SYSTEM.DAT"
SEALED_ANIME = ROOT / "workspace/build/prinny1_v7_15_17_title_136px_resources/anime00.dat"
TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_17/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_17_title_136px_iso_review"
EXPECTED = {
    BASE_ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    OUTPUT_ISO: "cffab3793987f2eab06b1467dc73ad4cc03e80d24f552fa85df8485902350c5e",
    SEALED_SYSTEM: "23f05e52f4c013ba1f7a686b28c82be75831b64982f2f121efb488194b28b796",
    SEALED_ANIME: "09726bd89c00dee612a10dd012203b6b1ba933b3701fd2a6648c934f91d9e3bb",
    TITLE: "77f6d4fc99b6da7a598ee14274ba062157c0a6bb163e1a1d13b3ae0ec659ede1",
}
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


def extract_start(system: bytes) -> bytes:
    row = next(item for item in system_records(system) if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0]


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.17 ISO 사후 검토 입력 해시 불일치: {path}")
    base_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_record = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    if (base_record["extent_lba"], base_record["data_length"]) != (final_record["extent_lba"], final_record["data_length"]):
        raise ValueError("SYSTEM.DAT ISO 범위 변경")
    offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    end = offset + int(base_record["data_length"])
    if BASE_ISO.stat().st_size != OUTPUT_ISO.stat().st_size:
        raise ValueError("ISO 크기 변경")
    if hash_range(BASE_ISO, 0, offset) != hash_range(OUTPUT_ISO, 0, offset) or hash_range(BASE_ISO, end, BASE_ISO.stat().st_size) != hash_range(OUTPUT_ISO, end, OUTPUT_ISO.stat().st_size):
        raise ValueError("SYSTEM.DAT 범위 밖 ISO 변경")
    base_system = read_iso_file(BASE_ISO, base_record)
    final_system = read_iso_file(OUTPUT_ISO, final_record)
    if final_system != SEALED_SYSTEM.read_bytes():
        raise ValueError("재추출 SYSTEM.DAT 봉인 불일치")
    base_start = extract_start(base_system)
    final_start = extract_start(final_system)
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
    base_row = next(row for row in base_archive.records if row.output_name.casefold() == "anime00.dat")
    final_row = next(row for row in final_archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[base_row.data_offset:base_row.end_offset]
    final_anime = final_start[final_row.data_offset:final_row.end_offset]
    if final_anime != SEALED_ANIME.read_bytes():
        raise ValueError("재추출 anime00 봉인 불일치")
    texture = texture_by_key(final_anime, (78, 0, 0))
    final_title = decode_texture(final_anime, texture).convert("RGBA")
    with Image.open(TITLE) as opened:
        opened.load()
        if final_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("재추출 타이틀 PNG 왕복 불일치")
    if (0, 255, 0, 255) not in set(final_title.getdata()):
        raise ValueError("형광 녹색 전경 팔레트 누락")
    base_obj = parse_objects(base_anime)[78]
    for relative, before_tuple, after_tuple in TRANSFORMS:
        at = base_obj.offset + relative
        if base_anime[at:at + 8] != struct.pack("<2h2H", *before_tuple) or final_anime[at:at + 8] != struct.pack("<2h2H", *after_tuple):
            raise ValueError(f"최종 transform 불일치: 0x{relative:X}")
    test = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.17 ISO 7z 구조 재검사 실패")
    report = {
        "format": "prinny1_v7_15_17_title_136px_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {
            "changed_start_resources": changed_start,
            "target_runtime_width_px": 136,
            "title_texture_roundtrip_exact": True,
            "lime_foreground_preserved": True,
            "ppsspp_launched": False,
        },
        "checks": {
            "only_system_dat_iso_extent_changed": True,
            "sealed_system_reextracted_exactly": True,
            "sealed_anime00_reextracted_exactly": True,
            "only_anime00_changed_in_start": True,
            "final_coordinates_exact": True,
            "seven_zip_structure_retest": True,
        },
        "status": "pass_v7_15_17_iso_ready_for_manual_title_screen_test",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.15.17 ISO range/reextract/title/structure: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
