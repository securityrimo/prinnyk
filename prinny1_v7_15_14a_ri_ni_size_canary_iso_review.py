#!/usr/bin/env python3
"""Independent post-build review of the V7.15.14a 리/니 size canary ISO."""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from datetime import datetime
from pathlib import Path

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from scripts.prinny_anime_preview import decode_texture, find_texture_groups, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_14a_ri_ni_size_canary/prinny_korean_v7_15_14a_ri_ni_size_canary.iso"
SEALED_SYSTEM = ROOT / "workspace/build/prinny1_v7_15_14a_ri_ni_size_canary_resources/SYSTEM.DAT"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_14a_ri_ni_size_canary_iso_review"
EXPECTED = {
    BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    OUTPUT_ISO: "7c4d817cbca2b44d1c8cda5ba0d50ca848c2dd411cc0e9f809ee748cf86a2352",
    SEALED_SYSTEM: "8e1d2f04a742065b2877334700b33513b4d07730f1c83fbd735c3f2dc43ce4f3",
}
PATCHES = (
    (0x23D4, (-7, -38, 28, 24), (-7, -38, 56, 48)),
    (0x23E4, (-6, -46, 28, 24), (-6, -46, 56, 48)),
    (0x23F4, (-6, -38, 28, 24), (-6, -38, 56, 48)),
    (0x2404, (39, -50, 24, 24), (39, -50, 48, 48)),
    (0x2414, (39, -58, 24, 24), (39, -58, 48, 48)),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def extract_start(system: bytes) -> tuple[bytes, bytes]:
    row = next(item for item in system_records(system) if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.14a ISO 사후 검토 입력 해시 불일치: {path}")

    base_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_record = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    if (base_record["extent_lba"], base_record["data_length"]) != (final_record["extent_lba"], final_record["data_length"]):
        raise ValueError("SYSTEM.DAT ISO 범위가 변경됨")
    offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    end = offset + int(base_record["data_length"])
    if BASE_ISO.stat().st_size != OUTPUT_ISO.stat().st_size:
        raise ValueError("ISO 크기 변경")
    if hash_range(BASE_ISO, 0, offset) != hash_range(OUTPUT_ISO, 0, offset) or hash_range(BASE_ISO, end, BASE_ISO.stat().st_size) != hash_range(OUTPUT_ISO, end, OUTPUT_ISO.stat().st_size):
        raise ValueError("SYSTEM.DAT 범위 밖 ISO 변경")

    base_system = read_iso_file(BASE_ISO, base_record)
    final_system = read_iso_file(OUTPUT_ISO, final_record)
    if final_system != SEALED_SYSTEM.read_bytes():
        raise ValueError("최종 SYSTEM.DAT이 봉인 자원과 불일치")
    base_start, _base_lzs = extract_start(base_system)
    final_start, final_lzs = extract_start(final_system)
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

    old_record = next(row for row in base_archive.records if row.output_name.casefold() == "anime00.dat")
    new_record = next(row for row in final_archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[old_record.data_offset:old_record.end_offset]
    final_anime = final_start[new_record.data_offset:new_record.end_offset]
    obj = parse_objects(base_anime)[78]
    allowed = set()
    for relative, before_tuple, after_tuple in PATCHES:
        at = obj.offset + relative
        before = struct.pack("<2h2H", *before_tuple)
        after = struct.pack("<2h2H", *after_tuple)
        if base_anime[at:at + 8] != before or final_anime[at:at + 8] != after:
            raise ValueError(f"리/니 transform 행 불일치: 0x{relative:X}")
        allowed.update(at + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    actual = {index for index, pair in enumerate(zip(base_anime, final_anime)) if pair[0] != pair[1]}
    if actual != allowed or len(actual) != 10:
        raise ValueError(f"anime00 허용 범위 밖 변경: {len(actual)}")

    base_texture = find_texture_groups(base_anime, parse_objects(base_anime)[78])[0][0]
    final_texture = find_texture_groups(final_anime, parse_objects(final_anime)[78])[0][0]
    if base_texture != final_texture or decode_texture(base_anime, base_texture).tobytes() != decode_texture(final_anime, final_texture).tobytes():
        raise ValueError("타이틀 텍스처 또는 형광 전경 픽셀이 변경됨")
    test = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.14a ISO 7z 구조 재검사 실패")

    report = {
        "format": "prinny1_v7_15_14a_ri_ni_size_canary_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {
            "changed_start_resources": changed_start,
            "anime_changed_bytes": len(actual),
            "title_texture_byte_identical": True,
            "foreground_rgba_preserved": [0, 255, 0, 255],
            "runtime_lzs_roundtrip_size": len(final_lzs),
        },
        "checks": {
            "only_system_dat_iso_extent_changed": True,
            "sealed_system_reextracted_exactly": True,
            "only_anime00_changed_in_start": True,
            "only_ri_ni_size_fields_changed": True,
            "positions_unchanged": True,
            "title_texture_and_palette_unchanged": True,
            "seven_zip_structure_retest": True,
        },
        "status": "pass_v7_15_14a_iso_ready_for_manual_runtime_measurement",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.15.14a ISO 범위/재추출/텍스처/구조: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
