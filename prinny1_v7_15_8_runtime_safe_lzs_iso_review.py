#!/usr/bin/env python3
"""Independent postbuild review of the V7.15.8 runtime-safe test ISO."""
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
from prinny1_v7_15_3_xdelta_translation_select import load_codebook
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs/prinny_korean_v7_15_8_runtime_safe_lzs.iso"
SYSTEM = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs_resources/SYSTEM.DAT"
START = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs_resources/start.dat"
TITLE_PNG = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized/anime/anime00/object_078/group_00_page_00.png"
BUILD_REPORT = ROOT / "workspace/reports/prinny1_v7_15_8_runtime_safe_lzs_iso/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_8_runtime_safe_lzs_iso_review"
EXPECTED = {
    BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    OUTPUT_ISO: "4ee4198acd01cbb4bda08e7b0d76b1cea3dea7de95e36b295ff6eede90876f6e",
    SYSTEM: "5514a39827488f1103ba02bac0b38ff6e5624abfadb069137c6d8bbe17c7206d",
    START: "50196d74ade8dc7ec187d4e85885df7e25ac325e1d3e298b09d91b3eab1b0215",
    TITLE_PNG: "b1e2c6ca15d2ea69a767f73e222ad88acd7a80de88626521b91898f3cb75db36",
    BUILD_REPORT: "b72566e687ba6a35828b59b7a4552770ce9b08e5a9228cd6bfbee4e584964a68",
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


def decode_xdelta(payload: bytes, codebook: dict[str, str]) -> str:
    payload = payload.split(b"\0", 1)[0]
    output: list[str] = []
    cursor = 0
    while cursor < len(payload):
        lead = payload[cursor]
        if lead < 0x80:
            output.append(chr(lead))
            cursor += 1
            continue
        code = payload[cursor:cursor + 2]
        if len(code) != 2:
            raise ValueError("xdelta 문자열 끝의 불완전 코드")
        key = code.hex().upper()
        output.append(codebook[key] if 0xF0 <= lead <= 0xF5 else code.decode("cp932"))
        cursor += 2
    return "".join(output)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.8 사후 검토 입력 해시 불일치: {path}")
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if build.get("status") != "pass_v7_15_8_test_iso_built_independent_post_review_required":
        raise ValueError("V7.15.8 빌드 상태 불일치")
    if BASE_ISO.stat().st_size != OUTPUT_ISO.stat().st_size:
        raise ValueError("ISO 크기 변경")

    base_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_record = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    if (base_record["extent_lba"], base_record["data_length"]) != (final_record["extent_lba"], final_record["data_length"]):
        raise ValueError("SYSTEM.DAT ISO 레코드 변경")
    left = int(base_record["extent_lba"]) * SECTOR_SIZE
    right = left + int(base_record["data_length"])
    if hash_range(BASE_ISO, 0, left) != hash_range(OUTPUT_ISO, 0, left) or hash_range(BASE_ISO, right, BASE_ISO.stat().st_size) != hash_range(OUTPUT_ISO, right, OUTPUT_ISO.stat().st_size):
        raise ValueError("SYSTEM.DAT 밖 ISO 변경")
    system = read_iso_file(OUTPUT_ISO, final_record)
    if system != SYSTEM.read_bytes():
        raise ValueError("ISO 재추출 SYSTEM.DAT 봉인 불일치")
    lzs_row = next(row for row in system_records(system) if row["name"].casefold() == "start.lzs")
    stream = system[lzs_row["data_offset"]:lzs_row["data_offset"] + lzs_row["size"]]
    start = decompress_buffer(stream)[0]
    if start != START.read_bytes() or overlap_count(stream) != 0:
        raise ValueError("ISO 내부 START 왕복/런타임 겹침 검증 실패")
    archive = StartRuntimeArchive.from_bytes(start)
    anime_record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")
    anime = start[anime_record.data_offset:anime_record.end_offset]
    texture = texture_by_key(anime, (78, 0, 0))
    decoded = decode_texture(anime, texture).convert("RGBA")
    with Image.open(TITLE_PNG) as opened:
        opened.load()
        if decoded.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("ISO 내부 확대 타이틀 PNG 왕복 불일치")

    codebook, _ = load_codebook()
    boot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    sign_slots = ((0xED97C, 10, "타이틀로"), (0xEE9A8, 16, "튜토리얼 가게"))
    decoded_signs = {}
    for offset, length, expected_text in sign_slots:
        actual = decode_xdelta(boot[offset:offset + length], codebook)
        if actual != expected_text:
            raise ValueError(f"푯말 동적 문자열 불일치: {offset:#x}/{actual}")
        decoded_signs[f"0x{offset:X}"] = actual

    seven_zip = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if seven_zip.returncode != 0 or "Everything is Ok" not in seven_zip.stdout:
        raise ValueError("V7.15.8 사후 7z 구조 검사 실패")
    report = {
        "format": "prinny1_v7_15_8_runtime_safe_lzs_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {"iso_size": OUTPUT_ISO.stat().st_size, "runtime_lzs_overlaps": 0, "sign_dynamic_text": decoded_signs, "title_texture": "anime00.dat/object_078/group_00/page_00"},
        "checks": {"output_hash_locked": True, "outside_system_extent_byte_identical": True, "system_start_reextracted_exactly": True, "runtime_lzs_non_overlap": True, "title_png_roundtrip_exact": True, "sign_text_is_already_korean_not_stage_image": True, "seven_zip_structure_test": True},
        "runtime": {"ppsspp_launch": "pending", "user_title_sign_difficulty_screen_confirmation": "pending"},
        "status": "pass_v7_15_8_structural_post_review_runtime_pending",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO SHA-256: {sha256_file(OUTPUT_ISO)}")
    print(f"sign: {decoded_signs}")
    print("LZS overlaps: 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
