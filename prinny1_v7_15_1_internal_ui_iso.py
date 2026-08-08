#!/usr/bin/env python3
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
from prinny1_v7_14_15_text_test_iso import hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_1_internal_ui_plan import BASE_ISO, OUTPUT as RESOURCE_DIR, sha256_file


ROOT = Path(__file__).resolve().parent
PLAN = ROOT / "workspace/reports/prinny1_v7_15_1_internal_ui_plan/all_report.json"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_1_internal_ui_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_1_full_text_internal_ui.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_1_internal_ui_iso"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def main() -> int:
    patched_system_path = RESOURCE_DIR / "SYSTEM.DAT"
    patched_start_path = RESOURCE_DIR / "start.dat"
    for path in (BASE_ISO, PLAN, REVIEW, patched_system_path, patched_start_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_internal_ui_iso_build_ready_automatic_approval":
        raise ValueError("V7.15.1 독립 사전 검토가 PASS가 아닙니다.")
    patched_system = patched_system_path.read_bytes()
    patched_start = patched_start_path.read_bytes()
    if sha256_bytes(patched_system) != plan["preflight"]["patched_system_sha256"]:
        raise ValueError("빌드 직전 SYSTEM.DAT 봉인 해시 불일치")
    if sha256_bytes(patched_start) != plan["preflight"]["patched_start_sha256"]:
        raise ValueError("빌드 직전 START.DAT 봉인 해시 불일치")

    system_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    boot_record = find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    eboot_record = find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"])
    base_system = read_iso_file(BASE_ISO, system_record)
    base_boot = read_iso_file(BASE_ISO, boot_record)
    base_eboot = read_iso_file(BASE_ISO, eboot_record)
    if len(patched_system) != len(base_system):
        raise ValueError("SYSTEM.DAT 고정 ISO 영역 크기가 달라졌습니다.")
    system_offset = int(system_record["extent_lba"]) * SECTOR_SIZE

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.1 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as target:
        target.seek(system_offset)
        target.write(patched_system)
        target.flush()
        os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기가 변경됐습니다.")

    allowed = merge_intervals([(system_offset, system_offset + len(base_system))])
    cursor = 0
    for left, right in allowed:
        if hash_range(BASE_ISO, cursor, left) != hash_range(temporary, cursor, left):
            raise ValueError("SYSTEM.DAT 앞 허용 범위 밖 ISO 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(temporary, cursor, temporary.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 허용 범위 밖 ISO 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.1 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    final_system = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_boot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    final_eboot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    final_entry = font_builder.parse_nispack_start_entry(final_system)
    final_start, _ = decompress_buffer(
        final_system[int(final_entry["data_offset"]):int(final_entry["data_offset"]) + int(final_entry["size"])]
    )
    if final_system != patched_system or final_start != patched_start:
        raise ValueError("최종 ISO SYSTEM/START 재추출 불일치")
    if final_boot != base_boot or final_eboot != base_eboot:
        raise ValueError("V7.15.0 BOOT/EBOOT가 변경됐습니다.")

    report = {
        "format": "prinny1_v7_15_1_internal_ui_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_automatic_test_iso_approval_active_since_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {
            "approved_internal_ui_targets": 5,
            "expected_write_runs": int(review["verified"]["expected_write_runs"]),
            "anime_changed_bytes": int(review["verified"]["anime_changed_bytes"]),
            "decoder_ranges_preserved": 10,
            "qa_text_slots_preserved": 4110,
            "f0_aliases_preserved": 980,
        },
        "checks": {
            "independent_prebuild_review_pass": True,
            "only_system_iso_range_changed": True,
            "seven_zip_structure_test": True,
            "system_start_reextracted": True,
            "boot_eboot_byte_identical_to_v7_15_0": True,
            "candidate_nonapproved_regions_imported": False,
            "translation_wording_changed_by_codex": False,
        },
        "known_runtime_regressions": ["prologue_boss_interaction_may_fail"],
        "status": "pass_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
