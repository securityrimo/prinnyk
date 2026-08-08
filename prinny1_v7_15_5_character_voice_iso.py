#!/usr/bin/env python3
"""Build the V7.15.5 character-voice test ISO from the V7.15.4 baseline."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
SYSTEM = ROOT / "workspace/build/prinny1_v7_15_5_character_voice_resources/SYSTEM.DAT"
DEMO = ROOT / "workspace/build/prinny1_v7_15_5_character_voice_resources/Demo00.dat"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_5_character_voice"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_5_character_voice.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_iso"

EXPECTED = {
    BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    SYSTEM: "618ad8fd09794f24dd24c829b93aa274b959202c7bd4c10d357a00f33cfb232f",
    DEMO: "a7e870ad1a1561f5c57e8273689bcd5bebd8d2069eb6038f22866419dab23f26",
    REVIEW: "b9ca241d75b2c7826d10c67a94df8015e1614a0d9284ad0236a541bdf3326dc4",
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
            raise ValueError(f"V7.15.5 ISO 입력 해시 불일치: {path}")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_v7_15_5_iso_build_ready_automatic_approval":
        raise ValueError("V7.15.5 독립 사전 검토 미통과")

    system_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_system = SYSTEM.read_bytes()
    if len(final_system) != int(system_record["data_length"]):
        raise ValueError("SYSTEM.DAT 고정 자원 크기 불일치")
    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    base_eboot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    if base_boot != base_eboot:
        raise ValueError("V7.15.4 BOOT/EBOOT 미러 불일치")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.5 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    system_offset = int(system_record["extent_lba"]) * SECTOR_SIZE
    with temporary.open("r+b") as target:
        target.seek(system_offset)
        target.write(final_system)
        target.flush()
        os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("V7.15.5 ISO 크기 변경")
    intervals = [(system_offset, system_offset + len(final_system))]
    cursor = 0
    for left, right in merge_intervals(intervals):
        if hash_range(BASE_ISO, cursor, left) != hash_range(temporary, cursor, left):
            raise ValueError("SYSTEM.DAT 앞 ISO 데이터 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(temporary, cursor, temporary.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 ISO 데이터 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.5 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    extracted_system = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    if extracted_system != final_system:
        raise ValueError("최종 ISO SYSTEM.DAT 재추출 불일치")
    entry = font_builder.parse_nispack_start_entry(extracted_system)
    start, _ = decompress_buffer(extracted_system[int(entry["data_offset"]):int(entry["data_offset"]) + int(entry["size"])])
    archive = StartRuntimeArchive.from_bytes(start)
    demo_record = next(record for record in archive.records if record.output_name.casefold() == "demo00.dat")
    if start[demo_record.data_offset:demo_record.end_offset] != DEMO.read_bytes():
        raise ValueError("최종 ISO Demo00.dat 재추출 불일치")
    if read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])) != base_boot:
        raise ValueError("최종 ISO BOOT.BIN이 V7.15.4와 달라졌습니다.")
    if read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"])) != base_eboot:
        raise ValueError("최종 ISO EBOOT.BIN이 V7.15.4와 달라졌습니다.")

    report = {
        "format": "prinny1_v7_15_5_character_voice_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_automatic_test_iso_approval_active_since_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {
            "dialogue_records_audited": 1572,
            "korean_code_records": 1510,
            "changed_records": 9,
            "expected_writes": 11,
            "demo_changed_bytes": 117,
        },
        "checks": {
            "independent_prebuild_review_pass": True,
            "only_system_iso_extent_changed": True,
            "boot_eboot_preserved_from_v7_15_4": True,
            "xdelta_images_ui_stage_sound_and_other_iso_data_preserved": True,
            "seven_zip_structure_test": True,
            "system_reextracted_exactly": True,
            "demo_reextracted_exactly": True,
            "base_iso_not_overwritten": True,
        },
        "caveat": "V7.15.4 parent remains a user-directed forced-xdelta test baseline whose declared official source/output hashes do not match",
        "status": "pass_v7_15_5_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("changed: SYSTEM.DAT only; BOOT/EBOOT and other ISO data preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
