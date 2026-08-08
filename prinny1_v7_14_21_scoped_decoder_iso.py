#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_15_text_test_iso import find_iso_record, hash_range, merge_intervals
from prinny1_v7_14_21_scoped_decoder_plan import BASE_ISO
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_14_21_scoped_decoder_plan"
PLAN = PLAN_DIR / "all_report.json"
WRITES = PLAN_DIR / "expected_write_confirmed.csv"
REVIEW = ROOT / "workspace/reports/prinny1_v7_14_21_scoped_decoder_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_14_21_scoped_decoder_diagnostic"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_14_21_scoped_decoder_diagnostic.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_21_scoped_decoder_iso"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for path in (BASE_ISO, PLAN, WRITES, REVIEW):
        if not path.is_file():
            raise FileNotFoundError(path)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("status") != "pass_diagnostic_iso_build_ready_automatic_approval" or review.get("final_verdict") != "PASS":
        raise ValueError("독립 검토가 진단 ISO 빌드를 허용하지 않습니다.")
    if sha256_file(WRITES) != plan["artifacts"]["expected_writes_sha256"]:
        raise ValueError("봉인 Expected Write 해시가 다릅니다.")
    with WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 6:
        raise ValueError("Expected Write가 6건이 아닙니다.")

    boot_record = find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    eboot_record = find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"])
    system_record = find_iso_record(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    base_boot = read_iso_file(BASE_ISO, boot_record)
    base_eboot = read_iso_file(BASE_ISO, eboot_record)
    patched_boot = bytearray(base_boot)
    declared = set()
    for row in rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if patched_boot[offset:offset + len(before)] != before:
            raise ValueError(f"빌드 직전 before 불일치: {row['logical_id']}")
        patched_boot[offset:offset + len(after)] = after
        declared.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    actual = {index for index, pair in enumerate(zip(base_boot, patched_boot)) if pair[0] != pair[1]}
    if actual != declared or len(actual) != 151:
        raise ValueError("빌드 직전 변경 집합이 다릅니다.")

    if OUTPUT_ISO.exists():
        raise ValueError("출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    boot_offset = int(boot_record["extent_lba"]) * SECTOR_SIZE
    eboot_offset = int(eboot_record["extent_lba"]) * SECTOR_SIZE
    system_offset = int(system_record["extent_lba"]) * SECTOR_SIZE
    record_offset = int(eboot_record["record_offset"])
    with temporary.open("r+b") as target:
        target.seek(boot_offset)
        target.write(patched_boot)
        target.seek(eboot_offset)
        target.write(patched_boot)
        target.write(bytes(len(base_eboot) - len(patched_boot)))
        target.seek(record_offset + 10)
        target.write(len(patched_boot).to_bytes(4, "little"))
        target.write(len(patched_boot).to_bytes(4, "big"))
        target.flush()
        os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기가 변경됐습니다.")
    allowed = merge_intervals([
        (boot_offset, boot_offset + len(base_boot)),
        (eboot_offset, eboot_offset + len(base_eboot)),
        (record_offset + 10, record_offset + 18),
    ])
    cursor = 0
    for left, right in allowed:
        if hash_range(BASE_ISO, cursor, left) != hash_range(temporary, cursor, left):
            raise ValueError("허용 범위 밖 ISO 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(temporary, cursor, temporary.stat().st_size):
        raise ValueError("마지막 허용 범위 뒤 ISO 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("7z ISO 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    final_boot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    final_eboot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    final_system = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    base_system = read_iso_file(BASE_ISO, system_record)
    if final_boot != bytes(patched_boot) or final_eboot != bytes(patched_boot) or final_system != base_system:
        raise ValueError("최종 ISO 자원 재추출 불일치")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sealed = REPORT_DIR / "sealed_expected_writes.csv"
    sealed.write_bytes(WRITES.read_bytes())
    report = {
        "format": "prinny1_v7_14_21_scoped_decoder_diagnostic_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_automatic_test_iso_approval_active_since_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {"expected_write_count": len(rows), "boot_actual_changed_bytes": len(actual)},
        "checks": {
            "boot_eboot_mirror": True,
            "system_start_font_translation_byte_identical_to_v14": True,
            "seven_zip_test": True,
            "changes_outside_declared_iso_ranges": 0,
            "translation_wording_changed": False,
        },
        "artifacts": {"sealed_expected_writes": str(sealed), "sealed_expected_writes_sha256": sha256_file(sealed)},
        "status": "pass_diagnostic_iso_built_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
