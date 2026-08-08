#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import compress_buffer, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import find_iso_record, hash_range, merge_intervals
from prinny1_v7_14_21_scoped_decoder_plan import BASE_ISO
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_plan"
PLAN = PLAN_DIR / "all_report.json"
WRITES = PLAN_DIR / "expected_write_confirmed.csv"
REVIEW = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_14_22_coherent_f0"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_14_22_coherent_f0.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_iso"


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
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_resource_build_ready_automatic_test_iso_approval":
        raise ValueError("독립 검토가 테스트 ISO 빌드를 허용하지 않습니다.")
    if sha256_file(WRITES) != plan["artifacts"]["expected_writes_sha256"]:
        raise ValueError("Expected Write 봉인 해시가 다릅니다.")

    boot_record = find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    eboot_record = find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"])
    system_record = find_iso_record(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    base_boot = read_iso_file(BASE_ISO, boot_record)
    base_eboot = read_iso_file(BASE_ISO, eboot_record)
    base_system = read_iso_file(BASE_ISO, system_record)
    start_entry = font_builder.parse_nispack_start_entry(base_system)
    lzs_offset, old_lzs_size = int(start_entry["data_offset"]), int(start_entry["size"])
    old_lzs = base_system[lzs_offset:lzs_offset + old_lzs_size]
    base_start, _ = decompress_buffer(old_lzs)
    archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    records = {record.output_name.casefold(): record for record in archive.records}
    patched_start, patched_boot = bytearray(base_start), bytearray(base_boot)
    with WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != int(plan["verified"]["expected_write_count"]):
        raise ValueError("빌드 직전 Expected Write 수가 다릅니다.")
    declared_start: set[int] = set()
    declared_boot: set[int] = set()
    for row in rows:
        before, after = bytes.fromhex(row["expected_before_hex"]), bytes.fromhex(row["write_after_hex"])
        relative = int(row["offset_hex"], 0)
        if row["layer"].startswith("START.DAT/"):
            record = records[row["target"].casefold()]
            absolute = int(record.data_offset) + relative
            if patched_start[absolute:absolute + len(before)] != before:
                raise ValueError(f"빌드 직전 START before 불일치: {row['logical_id']}")
            patched_start[absolute:absolute + len(after)] = after
            declared_start.update(absolute + i for i, (a, b) in enumerate(zip(before, after)) if a != b)
        else:
            absolute = relative
            if patched_boot[absolute:absolute + len(before)] != before:
                raise ValueError(f"빌드 직전 BOOT before 불일치: {row['logical_id']}")
            patched_boot[absolute:absolute + len(after)] = after
            declared_boot.update(absolute + i for i, (a, b) in enumerate(zip(before, after)) if a != b)
    actual_start = {i for i, pair in enumerate(zip(base_start, patched_start)) if pair[0] != pair[1]}
    actual_boot = {i for i, pair in enumerate(zip(base_boot, patched_boot)) if pair[0] != pair[1]}
    if actual_start != declared_start or actual_boot != declared_boot:
        raise ValueError("빌드 직전 실제 변경 집합이 선언과 다릅니다.")
    if sha256_bytes(bytes(patched_start)) != plan["preflight"]["patched_start_sha256"] or sha256_bytes(bytes(patched_boot)) != plan["preflight"]["patched_boot_sha256"]:
        raise ValueError("빌드 직전 자원 해시가 봉인값과 다릅니다.")

    new_lzs = compress_buffer(bytes(patched_start), old_lzs[:4])
    decoded, _ = decompress_buffer(new_lzs)
    if decoded != bytes(patched_start) or len(new_lzs) > old_lzs_size or sha256_bytes(new_lzs) != plan["preflight"]["new_lzs_sha256"]:
        raise ValueError("빌드 직전 START LZS 검증 실패")
    patched_system = bytearray(base_system)
    patched_system[lzs_offset:lzs_offset + old_lzs_size] = new_lzs + bytes(old_lzs_size - len(new_lzs))
    struct.pack_into("<I", patched_system, int(start_entry["entry_offset"]) + 0x24, len(new_lzs))

    if len(patched_boot) > len(base_eboot) or len(patched_system) != len(base_system):
        raise ValueError("ISO 고정 영역 크기 조건 실패")
    boot_offset = int(boot_record["extent_lba"]) * SECTOR_SIZE
    eboot_offset = int(eboot_record["extent_lba"]) * SECTOR_SIZE
    system_offset = int(system_record["extent_lba"]) * SECTOR_SIZE
    eboot_record_offset = int(eboot_record["record_offset"])
    old_eboot_size = int(eboot_record["data_length"])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as target:
        target.seek(boot_offset); target.write(patched_boot)
        target.seek(eboot_offset); target.write(patched_boot); target.write(bytes(old_eboot_size - len(patched_boot)))
        target.seek(eboot_record_offset + 10); target.write(len(patched_boot).to_bytes(4, "little")); target.write(len(patched_boot).to_bytes(4, "big"))
        target.seek(system_offset); target.write(patched_system)
        target.flush(); os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기가 변경됐습니다.")
    allowed = merge_intervals([
        (boot_offset, boot_offset + len(base_boot)),
        (eboot_offset, eboot_offset + old_eboot_size),
        (eboot_record_offset + 10, eboot_record_offset + 18),
        (system_offset, system_offset + len(base_system)),
    ])
    cursor = 0
    for left, right in allowed:
        if hash_range(BASE_ISO, cursor, left) != hash_range(temporary, cursor, left):
            raise ValueError("허용 ISO 범위 밖 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(temporary, cursor, temporary.stat().st_size):
        raise ValueError("마지막 허용 ISO 범위 뒤 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("7z ISO 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    final_boot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    final_eboot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    final_system = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_entry = font_builder.parse_nispack_start_entry(final_system)
    final_start, _ = decompress_buffer(final_system[int(final_entry["data_offset"]):int(final_entry["data_offset"]) + int(final_entry["size"])])
    if final_boot != bytes(patched_boot) or final_eboot != bytes(patched_boot) or final_system != bytes(patched_system) or final_start != bytes(patched_start):
        raise ValueError("최종 ISO 재추출 검증 실패")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "prinny1_v7_14_22_coherent_f0_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_automatic_test_iso_approval_active_since_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "size": BASE_ISO.stat().st_size, "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "resources": {
            "boot_sha256": sha256_bytes(bytes(patched_boot)), "system_sha256": sha256_bytes(bytes(patched_system)),
            "start_sha256": sha256_bytes(bytes(patched_start)), "start_lzs_sha256": sha256_bytes(new_lzs),
        },
        "verified": {"expected_write_count": len(rows), "start_changed_bytes": len(actual_start), "boot_changed_bytes": len(actual_boot)},
        "checks": {
            "independent_prebuild_review_pass": True, "fresh_inputs_reopened": True, "all_before_bytes_match": True,
            "actual_changes_equal_declared": True, "preflight_hashes_match": True, "only_declared_iso_ranges_changed": True,
            "seven_zip_structure_test": True, "boot_eboot_system_start_reextracted": True,
            "translation_wording_changed": False, "candidate_wording_imported": False, "font_txp_changed": False,
        },
        "status": "pass_test_iso_built_independent_post_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
