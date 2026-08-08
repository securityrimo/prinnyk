#!/usr/bin/env python3
"""Independent postbuild review for the V7.15.11 PSP test ISO."""
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
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_10_title_color_restore/prinny_korean_v7_15_10_title_color_restore.iso"
ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
SYSTEM = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style_resources/SYSTEM.DAT"
TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_11/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_11_pic0_title_style_iso_review"

EXPECTED = {
    BASE_ISO: "e26f628360cac2043338051070acfb1f4586a9e321469f7dc3d578375265badf",
    ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    SYSTEM: "4cab10eec60afcf43ea872bd7c93934f46b7d1af538384218fa822f24bd437e8",
    TITLE: "d3baf482be50ee6ec2c2f10ab94cff3daae847b54807a82e2f62ba31d7f33f35",
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


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.11 사후 검토 입력 해시 불일치: {path}")
    base_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_record = find_iso_file(ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    if (base_record["extent_lba"], base_record["data_length"]) != (final_record["extent_lba"], final_record["data_length"]):
        raise ValueError("SYSTEM.DAT ISO 디렉터리 레코드 변경")
    offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    length = int(base_record["data_length"])
    if hash_range(BASE_ISO, 0, offset) != hash_range(ISO, 0, offset):
        raise ValueError("SYSTEM.DAT 앞 허용 범위 밖 변경")
    if hash_range(BASE_ISO, offset + length, BASE_ISO.stat().st_size) != hash_range(ISO, offset + length, ISO.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 허용 범위 밖 변경")
    base_system = read_iso_file(BASE_ISO, base_record)
    final_system = read_iso_file(ISO, final_record)
    if final_system != SYSTEM.read_bytes():
        raise ValueError("최종 ISO SYSTEM.DAT 재추출 불일치")

    base_rows, final_rows = system_records(base_system), system_records(final_system)
    changed_resources = []
    for old, new in zip(base_rows, final_rows):
        before = base_system[old["data_offset"]:old["data_offset"] + old["size"]]
        after = final_system[new["data_offset"]:new["data_offset"] + new["size"]]
        if before != after or old["size"] != new["size"]:
            changed_resources.append(old["name"].casefold())
    if changed_resources != ["start.lzs"]:
        raise ValueError(f"최종 SYSTEM 변경 자원 불일치: {changed_resources}")
    start_row = next(row for row in final_rows if row["name"].casefold() == "start.lzs")
    final_lzs = final_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    final_start = decompress_buffer(final_lzs)[0]
    if overlap_count(final_lzs) != 0 or hashlib.sha256(final_start).hexdigest() != "0b3616c3b72d12fcac25d2a8ea052795ce45c4926dd6f2fe2fc76fed7cec1623":
        raise ValueError("최종 ISO START 해시 또는 LZS 안전성 불일치")
    archive = StartRuntimeArchive.from_bytes(final_start)
    anime_record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")
    anime = final_start[anime_record.data_offset:anime_record.end_offset]
    title = decode_texture(anime, texture_by_key(anime, (78, 0, 0))).convert("RGBA")
    with Image.open(TITLE) as opened:
        opened.load()
        if title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("최종 ISO PIC0 스타일 타이틀 PNG 왕복 불일치")
    for name in ("replay_icon0.png", "umd_icon0.png", "umd_pic0.png", "prinny_icon0.png"):
        old = next(row for row in base_rows if row["name"].casefold() == name)
        new = next(row for row in final_rows if row["name"].casefold() == name)
        if base_system[old["data_offset"]:old["data_offset"] + old["size"]] != final_system[new["data_offset"]:new["data_offset"] + new["size"]]:
            raise ValueError(f"기존 한글 SYSTEM 이미지 변경: {name}")

    test = subprocess.run(["7z", "t", str(ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("최종 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_11_pic0_title_style_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": sha256_file(ISO)},
        "verified": {"changed_system_resources": changed_resources, "runtime_lzs_overlaps": 0},
        "checks": {
            "only_system_dat_extent_changed": True,
            "system_dat_reextracted_exactly": True,
            "only_start_lzs_changed_in_system": True,
            "pic0_style_title_png_roundtrip_exact": True,
            "runtime_lzs_non_overlap": True,
            "v7_15_10_korean_images_preserved": True,
            "anime_bg_direct_png_inherited_by_outside_range_hash": True,
            "seven_zip_structure_retest": True,
        },
        "status": "pass_v7_15_11_iso_ready_for_ppsspp_runtime_test",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {sha256_file(ISO)}")
    print("SYSTEM-only/PIC0-title/LZS/images/7z: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
