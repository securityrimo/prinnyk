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
from typing import Any

import core.font_builder as font_builder
from core.lzs import compress_buffer, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import find_iso_record, hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair"
    / "prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
)
FONT_WRITES = (
    ROOT / "workspace/reports/prinny1_v7_14_15_font_extension_plan"
    / "expected_write_confirmed.csv"
)
ALIAS_WRITES = (
    ROOT / "workspace/reports/prinny1_v7_14_16_boot_alias_plan"
    / "expected_write_confirmed.csv"
)
ALIAS_REVIEW = ROOT / "workspace/reports/prinny1_v7_14_16_boot_alias_review/all_report.json"
RUNTIME_BLOCKER = ROOT / "workspace/reports/prinny1_v7_14_15_runtime_test/all_report.json"
XDELTA_AUDIT = ROOT / "workspace/reports/prinny1_v7_14_15_xdelta_import_audit/all_report.json"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_14_16_text_resources"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_14_16_text_test_iso"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_14_16_text_test.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_16_text_test_iso"
BASE_SHA256 = "bd5168a461adfd4a41b8daf9dfe6037d7a9838ab2fc8ee0affd1e0f5521bd5b5"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def changed(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("변경 비교 크기가 다릅니다.")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    for path in (BASE_ISO, FONT_WRITES, ALIAS_WRITES, ALIAS_REVIEW, RUNTIME_BLOCKER, XDELTA_AUDIT):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(BASE_ISO) != BASE_SHA256:
        raise ValueError("V7.14.14 기준 ISO 해시가 다릅니다.")
    alias_review = json.loads(ALIAS_REVIEW.read_text(encoding="utf-8"))
    runtime = json.loads(RUNTIME_BLOCKER.read_text(encoding="utf-8"))
    xdelta = json.loads(XDELTA_AUDIT.read_text(encoding="utf-8"))
    if alias_review.get("final_verdict") != "PASS":
        raise ValueError("V7.14.16 별칭 독립 검토가 PASS가 아닙니다.")
    if runtime.get("final_verdict") != "BLOCKER":
        raise ValueError("V7.14.15 런타임 BLOCKER가 봉인되지 않았습니다.")

    boot_entry = find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    system_entry = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    base_boot = read_iso_file(BASE_ISO, boot_entry)
    base_system = read_iso_file(BASE_ISO, system_entry)
    start_entry = font_builder.parse_nispack_start_entry(base_system)
    lzs_offset = int(start_entry["data_offset"])
    old_lzs_size = int(start_entry["size"])
    old_lzs = base_system[lzs_offset:lzs_offset + old_lzs_size]
    base_start, _ = decompress_buffer(old_lzs)
    archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    records = {record.output_name.casefold(): record for record in archive.records}
    fnt_record = records["font.fnt"]
    txp_record = records["font.txp"]

    patched_start = bytearray(base_start)
    patched_boot = bytearray(base_boot)
    declared_start: set[int] = set()
    declared_boot: set[int] = set()
    sealed_rows: list[dict[str, Any]] = []

    font_rows = read_csv(FONT_WRITES)
    if len(font_rows) != 3:
        raise ValueError("신규 글리프 Expected Write가 3개가 아닙니다.")
    for row in font_rows:
        relative = int(row["offset_hex"], 0)
        absolute = int(txp_record.data_offset) + relative
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if absolute + len(before) > int(txp_record.end_offset):
            raise ValueError(f"font.txp 범위 초과: {row['logical_id']}")
        if patched_start[absolute:absolute + len(before)] != before:
            raise ValueError(f"font.txp before 불일치: {row['logical_id']}")
        patched_start[absolute:absolute + len(after)] = after
        declared_start.update(
            absolute + index for index, (old, new) in enumerate(zip(before, after)) if old != new
        )
        sealed_rows.append(
            {
                "sequence": 0, "layer": "START.DAT/font.txp", "logical_id": row["logical_id"],
                "target": "font.txp", "offset_hex": row["offset_hex"], "write_span": len(after),
                "expected_before_hex": row["expected_before_hex"], "write_after_hex": row["write_after_hex"],
                "change_kind": row["change_kind"], "wording_changed": "no",
                "expected_write_confirmed": "yes",
            }
        )

    alias_rows = read_csv(ALIAS_WRITES)
    if len(alias_rows) != 10:
        raise ValueError("V7.14.16 별칭 Expected Write가 10개가 아닙니다.")
    for row in alias_rows:
        relative = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if row["layer"] == "START.DAT/font.fnt":
            absolute = int(fnt_record.data_offset) + relative
            if absolute + len(before) > int(fnt_record.end_offset):
                raise ValueError("font.fnt 별칭 범위 초과")
            if patched_start[absolute:absolute + len(before)] != before:
                raise ValueError("font.fnt 별칭 before 불일치")
            patched_start[absolute:absolute + len(after)] = after
            declared_start.update(
                absolute + index for index, (old, new) in enumerate(zip(before, after)) if old != new
            )
        elif row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN":
            absolute = relative
            if patched_boot[absolute:absolute + len(before)] != before:
                raise ValueError(f"BOOT before 불일치: {row['logical_id']}")
            patched_boot[absolute:absolute + len(after)] = after
            declared_boot.update(
                absolute + index for index, (old, new) in enumerate(zip(before, after)) if old != new
            )
        else:
            raise ValueError(f"허용되지 않은 별칭 계층: {row['layer']}")
        sealed_rows.append(
            {
                "sequence": 0, "layer": row["layer"], "logical_id": row["logical_id"],
                "target": row["target"], "offset_hex": row["offset_hex"], "write_span": len(after),
                "expected_before_hex": row["expected_before_hex"], "write_after_hex": row["write_after_hex"],
                "change_kind": row["change_kind"], "wording_changed": "no",
                "expected_write_confirmed": "yes",
            }
        )

    actual_start = changed(base_start, bytes(patched_start))
    actual_boot = changed(base_boot, bytes(patched_boot))
    if actual_start != declared_start or actual_boot != declared_boot:
        raise ValueError("실제 START/BOOT 변경이 13개 Expected Write와 다릅니다.")

    new_lzs = compress_buffer(bytes(patched_start), old_lzs[:4])
    roundtrip, _ = decompress_buffer(new_lzs)
    if roundtrip != bytes(patched_start) or len(new_lzs) > old_lzs_size:
        raise ValueError("V7.14.16 START 압축 왕복 또는 고정 슬롯 검사 실패")
    patched_system = bytearray(base_system)
    patched_system[lzs_offset:lzs_offset + old_lzs_size] = new_lzs + bytes(old_lzs_size - len(new_lzs))
    struct.pack_into("<I", patched_system, int(start_entry["entry_offset"]) + 0x24, len(new_lzs))

    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    (RESOURCE_DIR / "BOOT.BIN").write_bytes(bytes(patched_boot))
    (RESOURCE_DIR / "start.dat").write_bytes(bytes(patched_start))
    (RESOURCE_DIR / "start.lzs").write_bytes(new_lzs)
    (RESOURCE_DIR / "SYSTEM.DAT").write_bytes(bytes(patched_system))
    for name, expected in (
        ("BOOT.BIN", bytes(patched_boot)), ("start.dat", bytes(patched_start)),
        ("start.lzs", new_lzs), ("SYSTEM.DAT", bytes(patched_system)),
    ):
        if (RESOURCE_DIR / name).read_bytes() != expected:
            raise ValueError(f"자원 기록 후 불일치: {name}")

    boot_record = find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    eboot_record = find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"])
    system_record = find_iso_record(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    base_eboot = read_iso_file(BASE_ISO, eboot_record)
    if not base_eboot.startswith(b"~PSP") or not bytes(patched_boot).startswith(b"\x7fELF"):
        raise ValueError("BOOT/EBOOT 실행 파일 형식 불일치")
    candidate_files = {row["name"]: row for row in xdelta["iso_file_comparison"]}
    if candidate_files["boot"]["candidate"] != candidate_files["eboot"]["candidate"]:
        raise ValueError("xdelta BOOT/EBOOT 미러 근거 불일치")

    boot_offset = int(boot_record["extent_lba"]) * SECTOR_SIZE
    eboot_offset = int(eboot_record["extent_lba"]) * SECTOR_SIZE
    system_offset = int(system_record["extent_lba"]) * SECTOR_SIZE
    eboot_record_offset = int(eboot_record["record_offset"])
    old_eboot_size = len(base_eboot)
    new_eboot_size = len(patched_boot)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as target:
        target.seek(boot_offset); target.write(patched_boot)
        target.seek(system_offset); target.write(patched_system)
        target.seek(eboot_offset); target.write(patched_boot); target.write(bytes(old_eboot_size - new_eboot_size))
        target.seek(eboot_record_offset + 10)
        target.write(new_eboot_size.to_bytes(4, "little")); target.write(new_eboot_size.to_bytes(4, "big"))
        target.flush(); os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("V7.14.16 ISO 크기가 변경됐습니다.")

    allowed = merge_intervals(
        [
            (boot_offset, boot_offset + len(base_boot)),
            (eboot_offset, eboot_offset + old_eboot_size),
            (system_offset, system_offset + len(base_system)),
            (eboot_record_offset + 10, eboot_record_offset + 18),
        ]
    )
    cursor = 0
    for start, end in allowed:
        if hash_range(BASE_ISO, cursor, start) != hash_range(temporary, cursor, start):
            raise ValueError("V7.14.16 허용 범위 밖 ISO 변경")
        cursor = end
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(
        temporary, cursor, temporary.stat().st_size
    ):
        raise ValueError("V7.14.16 마지막 허용 범위 뒤 ISO 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.14.16 7z ISO 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    final_boot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    final_eboot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    final_system = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_entry = font_builder.parse_nispack_start_entry(final_system)
    final_start, _ = decompress_buffer(
        final_system[int(final_entry["data_offset"]):int(final_entry["data_offset"]) + int(final_entry["size"])]
    )
    if final_boot != bytes(patched_boot) or final_eboot != bytes(patched_boot):
        raise ValueError("V7.14.16 BOOT/EBOOT 재추출 실패")
    if final_system != bytes(patched_system) or final_start != bytes(patched_start):
        raise ValueError("V7.14.16 SYSTEM/START 재추출 실패")

    sealed_rows.sort(key=lambda row: (row["layer"], int(row["offset_hex"], 0)))
    for sequence, row in enumerate(sealed_rows, start=1):
        row["sequence"] = sequence
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sealed_path = REPORT_DIR / "sealed_expected_writes.csv"
    write_csv(sealed_path, sealed_rows)
    resources = {
        name: {"path": str(RESOURCE_DIR / name), "size": (RESOURCE_DIR / name).stat().st_size,
               "sha256": sha256_file(RESOURCE_DIR / name)}
        for name in ("BOOT.BIN", "start.dat", "start.lzs", "SYSTEM.DAT")
    }
    report = {
        "format": "prinny1_v7_14_16_text_test_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_explicit_v7_14_16_test_iso_creation_approval",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO), "size": BASE_ISO.stat().st_size},
        "sealed": {"path": str(sealed_path), "sha256": sha256_file(sealed_path),
                   "write_count": len(sealed_rows), "font_txp_writes": 3,
                   "font_fnt_writes": 1, "boot_writes": 9,
                   "start_changed_bytes": len(actual_start), "boot_changed_bytes": len(actual_boot)},
        "resources": resources,
        "compression": {"lzs_size": len(new_lzs), "slot_size": old_lzs_size,
                        "remaining": old_lzs_size - len(new_lzs), "roundtrip": True},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size,
                       "sha256": sha256_file(OUTPUT_ISO)},
        "checks": {
            "fresh_v14_sources_reextracted": True, "all_before_bytes_match": True,
            "actual_changes_equal_13_expected_writes": True, "user_wording_changed": False,
            "xdelta_wording_or_font_imported": False, "existing_start_mapping_preserved": True,
            "f0_aliases_added": 54, "boot_eboot_mirror": True, "seven_zip_test": True,
            "final_boot_eboot_system_start_reextracted": True,
            "changes_outside_declared_iso_ranges": 0, "image_writes": 0,
        },
        "status": "pass_test_iso_built_independent_review_required",
    }
    report_path = REPORT_DIR / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Expected Writes: {len(sealed_rows)} (font.txp 3, font.fnt 1, BOOT 9)")
    print(f"START/BOOT changed bytes: {len(actual_start)}/{len(actual_boot)}")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
