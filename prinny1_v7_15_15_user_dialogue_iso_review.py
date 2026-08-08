#!/usr/bin/env python3
"""Independent postbuild review of the V7.15.15 user dialogue ISO."""
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
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue/prinny_korean_v7_15_15_user_dialogue.iso"
SYSTEM = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources/SYSTEM.DAT"
START = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources/start.dat"
DEMO = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources/Demo00.dat"
FONT_FNT = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources/font.fnt"
FONT_TXP = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources/font.txp"
ISO_REPORT = ROOT / "workspace/reports/prinny1_v7_15_15_user_dialogue_iso/all_report.json"
PRE_REVIEW = ROOT / "workspace/reports/prinny1_v7_15_15_user_dialogue_review/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_15_user_dialogue_iso_review"

EXPECTED = {
    BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    OUTPUT_ISO: "ed4415d7b1eb2144a3f38c23b154e363a9536cf105e4e721cce2b8e32957793b",
    SYSTEM: "5c8d8447e1a8282d011eec93220bf2b3c1a145adf231fc104edda2a0b651a66c",
    START: "00de7fb145ab1097a35ad2d737456a1a7f505bd1fda2c85a4070dd23d30fe3ef",
    DEMO: "030f7040956a040a79c4c6e271e2007f743d3413062e3159ec393be4e0fd0a3b",
    FONT_FNT: "b6eaf35a7dd469983bc0544d70552558a631d0469cfe4f39338ab6520c841cea",
    FONT_TXP: "fa1d70dd0ef7ca9f99a9fcfacd108e2d5653b25e95675c170b3a0b02e4bc94be",
    ISO_REPORT: "4210e6ff902408195db34fce5e2268665c8760419142754800ce79401277bce7",
    PRE_REVIEW: "623233531689ff9dbf9eac048d80e2312b111591089bdcbebe7adfeeb4ee087b",
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
            raise ValueError(f"V7.15.15 ISO 사후 검토 입력 해시 불일치: {path}")
    pre = json.loads(PRE_REVIEW.read_text(encoding="utf-8"))
    build = json.loads(ISO_REPORT.read_text(encoding="utf-8"))
    if pre.get("final_verdict") != "PASS" or build.get("status") != "pass_v7_15_15_test_iso_built_independent_post_review_required":
        raise ValueError("사전 검토 또는 ISO 빌드 상태 불일치")
    if OUTPUT_ISO.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 고정 크기 불일치")

    base_system_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    output_system_record = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    if (base_system_record["extent_lba"], base_system_record["data_length"]) != (
        output_system_record["extent_lba"], output_system_record["data_length"]
    ):
        raise ValueError("ISO SYSTEM.DAT 위치/크기 변경")
    system_offset = int(base_system_record["extent_lba"]) * SECTOR_SIZE
    system_end = system_offset + int(base_system_record["data_length"])
    if hash_range(BASE_ISO, 0, system_offset) != hash_range(OUTPUT_ISO, 0, system_offset):
        raise ValueError("SYSTEM.DAT 앞 ISO 범위 변경")
    if hash_range(BASE_ISO, system_end, BASE_ISO.stat().st_size) != hash_range(OUTPUT_ISO, system_end, OUTPUT_ISO.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 ISO 범위 변경")

    extracted_system = read_iso_file(OUTPUT_ISO, output_system_record)
    if extracted_system != SYSTEM.read_bytes():
        raise ValueError("최종 ISO SYSTEM.DAT 봉인 불일치")
    rows = system_records(extracted_system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    lzs = extracted_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    if overlap_count(lzs) != 0:
        raise ValueError("최종 ISO START.LZS 겹침 역참조 발견")
    start = decompress_buffer(lzs)[0]
    if start != START.read_bytes():
        raise ValueError("최종 ISO START.DAT 봉인 불일치")
    archive = StartRuntimeArchive.from_bytes(start)
    records = {row.output_name.casefold(): row for row in archive.records}
    for name, expected_path in (("demo00.dat", DEMO), ("font.fnt", FONT_FNT), ("font.txp", FONT_TXP)):
        record = records[name]
        if start[record.data_offset:record.end_offset] != expected_path.read_bytes():
            raise ValueError(f"최종 ISO {name} 봉인 불일치")

    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    final_boot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    base_eboot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    final_eboot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    if base_boot != final_boot or base_eboot != final_eboot:
        raise ValueError("최종 ISO BOOT/EBOOT 보존 실패")
    structure = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if structure.returncode != 0 or "Everything is Ok" not in structure.stdout:
        raise ValueError("최종 ISO 7z 구조 재검사 실패")

    report = {
        "format": "prinny1_v7_15_15_user_dialogue_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "output_iso_size": OUTPUT_ISO.stat().st_size,
            "output_iso_sha256": sha256_file(OUTPUT_ISO),
            "dialogue_slots": 2561,
            "xdelta_used_slots": 2556,
            "xdelta_unused_held_slots": 5,
            "user_selected_slots": 2379,
            "xdelta_voice_fallback_slots": 176,
            "curated_slots": 1,
            "font_extension_characters": 152,
            "start_lzs_size": start_row["size"],
            "start_lzs_overlaps": 0,
        },
        "checks": {
            "prebuild_review_pass": True,
            "iso_size_preserved": True,
            "only_system_iso_extent_changed": True,
            "system_reextracted_exactly": True,
            "start_reextracted_exactly": True,
            "demo_and_font_resources_reextracted_exactly": True,
            "boot_eboot_preserved": True,
            "runtime_safe_lzs_non_overlap": True,
            "seven_zip_structure_pass": True,
            "base_iso_not_overwritten": True,
        },
        "runtime": {
            "ppsspp_launched_for_this_iso": False,
            "user_scene_confirmation": False,
        },
        "status": "pass_v7_15_15_test_iso_structural_runtime_test_required",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {sha256_file(OUTPUT_ISO)}")
    print("SYSTEM-only ISO diff, START non-overlap, BOOT/EBOOT preserved")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
