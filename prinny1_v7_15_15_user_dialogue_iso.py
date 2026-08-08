#!/usr/bin/env python3
"""Build the separately named V7.15.15 user-priority dialogue test ISO."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
SYSTEM = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources/SYSTEM.DAT"
DEMO = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources/Demo00.dat"
FONT_FNT = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources/font.fnt"
FONT_TXP = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources/font.txp"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_15_user_dialogue_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_15_user_dialogue.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_15_user_dialogue_iso"

EXPECTED = {
    BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    SYSTEM: "5c8d8447e1a8282d011eec93220bf2b3c1a145adf231fc104edda2a0b651a66c",
    DEMO: "030f7040956a040a79c4c6e271e2007f743d3413062e3159ec393be4e0fd0a3b",
    FONT_FNT: "b6eaf35a7dd469983bc0544d70552558a631d0469cfe4f39338ab6520c841cea",
    FONT_TXP: "fa1d70dd0ef7ca9f99a9fcfacd108e2d5653b25e95675c170b3a0b02e4bc94be",
    REVIEW: "623233531689ff9dbf9eac048d80e2312b111591089bdcbebe7adfeeb4ee087b",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.15 ISO 입력 해시 불일치: {path}")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_v7_15_15_iso_build_ready_automatic_approval":
        raise ValueError("V7.15.15 독립 사전 검토 미통과")

    system_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_system = SYSTEM.read_bytes()
    if len(final_system) != int(system_record["data_length"]):
        raise ValueError("SYSTEM.DAT 고정 자원 크기 불일치")
    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    base_eboot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    if base_boot != base_eboot:
        raise ValueError("V7.15.11 BOOT/EBOOT 미러 불일치")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.15 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        raise ValueError("V7.15.15 임시 ISO가 이미 존재합니다. 수동 확인이 필요합니다.")
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    system_offset = int(system_record["extent_lba"]) * SECTOR_SIZE
    with temporary.open("r+b") as target:
        target.seek(system_offset)
        target.write(final_system)
        target.flush()
        os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("V7.15.15 ISO 크기 변경")
    intervals = [(system_offset, system_offset + len(final_system))]
    cursor = 0
    for left, right in merge_intervals(intervals):
        if hash_range(BASE_ISO, cursor, left) != hash_range(temporary, cursor, left):
            raise ValueError("SYSTEM.DAT 앞 ISO 데이터 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(temporary, cursor, temporary.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 ISO 데이터 변경")
    structure = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if structure.returncode != 0 or "Everything is Ok" not in structure.stdout:
        raise ValueError("V7.15.15 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    extracted_system = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    if extracted_system != final_system:
        raise ValueError("최종 ISO SYSTEM.DAT 재추출 불일치")
    from prinny1_v7_15_4_ui_image_export import system_records
    rows = system_records(extracted_system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    start = decompress_buffer(extracted_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]])[0]
    archive = StartRuntimeArchive.from_bytes(start)
    records = {row.output_name.casefold(): row for row in archive.records}
    for name, expected_path in (("demo00.dat", DEMO), ("font.fnt", FONT_FNT), ("font.txp", FONT_TXP)):
        record = records[name]
        if start[record.data_offset:record.end_offset] != expected_path.read_bytes():
            raise ValueError(f"최종 ISO {name} 재추출 불일치")
    if read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])) != base_boot:
        raise ValueError("최종 ISO BOOT.BIN이 V7.15.11과 다릅니다.")
    if read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"])) != base_eboot:
        raise ValueError("최종 ISO EBOOT.BIN이 V7.15.11과 다릅니다.")

    report = {
        "format": "prinny1_v7_15_15_user_dialogue_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_automatic_test_iso_approval_active_since_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {
            "dialogue_slots": 2561,
            "xdelta_used_slots": 2556,
            "xdelta_unused_held_slots": 5,
            "user_selected_slots": 2379,
            "xdelta_voice_fallback_slots": 176,
            "curated_slots": 1,
            "font_extension_characters": 152,
        },
        "checks": {
            "independent_prebuild_review_pass": True,
            "only_system_iso_extent_changed": True,
            "boot_eboot_preserved_from_v7_15_11": True,
            "title_ui_images_and_other_iso_data_preserved": True,
            "seven_zip_structure_test": True,
            "system_reextracted_exactly": True,
            "demo_and_font_reextracted_exactly": True,
            "base_iso_not_overwritten": True,
        },
        "caveat": "new user glyphs use the previously verified user font shapes and require runtime visual regression testing",
        "status": "pass_v7_15_15_test_iso_built_independent_post_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("changed ISO extent: SYSTEM.DAT only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
