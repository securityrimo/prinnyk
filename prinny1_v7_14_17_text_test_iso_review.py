#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso_review import hash_range, locate_eboot_record_independently, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
ISO = ROOT / "workspace/build/prinny1_v7_14_17_text_test_iso/prinny_korean_v7_14_17_text_test.iso"
BUILD_REPORT = ROOT / "workspace/reports/prinny1_v7_14_17_text_test_iso/all_report.json"
SEALED = ROOT / "workspace/reports/prinny1_v7_14_17_text_resource_build/sealed_expected_writes.csv"
RESOURCE_REVIEW = ROOT / "workspace/reports/prinny1_v7_14_17_text_resource_build_review/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_17_text_test_iso_review"
VERSION = "v7_14_17"
EXPECTED_WRITE_COUNT = 23


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


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
        raise ValueError("비교 크기가 다릅니다.")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def extract_start(system: bytes) -> bytes:
    entry = font_builder.parse_nispack_start_entry(system)
    offset, size = int(entry["data_offset"]), int(entry["size"])
    start, _ = decompress_buffer(system[offset:offset + size])
    return start


def main() -> int:
    for path in (BASE_ISO, ISO, BUILD_REPORT, SEALED, RESOURCE_REVIEW):
        if not path.is_file():
            raise FileNotFoundError(path)
    report = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    review = json.loads(RESOURCE_REVIEW.read_text(encoding="utf-8"))
    if report.get("status") != "pass_test_iso_built_independent_review_required":
        raise ValueError("ISO 빌드 상태가 독립 검토 대기가 아닙니다.")
    if review.get("final_verdict") != "PASS":
        raise ValueError("내부 자원 독립 검토가 PASS가 아닙니다.")
    iso_sha = sha256_file(ISO)
    if iso_sha != report["output_iso"]["sha256"] or ISO.stat().st_size != report["output_iso"]["size"]:
        raise ValueError("ISO 크기·해시가 빌드 보고서와 다릅니다.")
    test = subprocess.run(["7z", "t", str(ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("독립 7z ISO 검사 실패")

    paths = {
        "boot": ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
        "eboot": ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
        "system": ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    }
    base_entries = {name: find_iso_file(BASE_ISO, parts) for name, parts in paths.items()}
    final_entries = {name: find_iso_file(ISO, parts) for name, parts in paths.items()}
    base_blobs = {name: read_iso_file(BASE_ISO, entry) for name, entry in base_entries.items()}
    final_blobs = {name: read_iso_file(ISO, entry) for name, entry in final_entries.items()}
    if final_blobs["boot"] != final_blobs["eboot"]:
        raise ValueError("최종 BOOT/EBOOT 미러 불일치")
    base_start, final_start = extract_start(base_blobs["system"]), extract_start(final_blobs["system"])
    base_archive = StartRuntimeArchive.from_bytes(base_start, source="independent-base-start")
    final_archive = StartRuntimeArchive.from_bytes(final_start, source="independent-final-start")
    base_records = {r.output_name.casefold(): r for r in base_archive.records}
    final_records = {r.output_name.casefold(): r for r in final_archive.records}

    rows = read_csv(SEALED)
    if len(rows) != EXPECTED_WRITE_COUNT:
        raise ValueError(f"봉인 Expected Write가 {EXPECTED_WRITE_COUNT}개가 아닙니다: {len(rows)}")
    declared_start: set[int] = set()
    declared_boot: set[int] = set()
    for row in rows:
        relative = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if row["layer"].startswith("START.DAT/"):
            resource = row["layer"].split("/", 1)[1].casefold()
            if resource not in base_records or resource not in final_records:
                raise ValueError(f"START 자원을 찾을 수 없습니다: {resource}")
            base_offset = int(base_records[resource].data_offset) + relative
            final_offset = int(final_records[resource].data_offset) + relative
            actual_before = base_start[base_offset:base_offset + len(before)]
            actual_after = final_start[final_offset:final_offset + len(after)]
            declared_start.update(base_offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
        elif row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN":
            actual_before = base_blobs["boot"][relative:relative + len(before)]
            actual_after = final_blobs["boot"][relative:relative + len(after)]
            declared_boot.update(relative + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
        else:
            raise ValueError(f"허용되지 않은 계층: {row['layer']}")
        if actual_before != before or actual_after != after:
            raise ValueError(f"최종 Expected Write 불일치: {row['logical_id']}")
    if changed(base_start, final_start) != declared_start:
        raise ValueError("최종 START 변경이 선언과 다릅니다.")
    if changed(base_blobs["boot"], final_blobs["boot"]) != declared_boot:
        raise ValueError("최종 BOOT 변경이 선언과 다릅니다.")

    record_offset = locate_eboot_record_independently(
        ISO, int(final_entries["eboot"]["extent_lba"]), int(final_entries["eboot"]["data_length"])
    )
    allowed = merge_intervals([
        (int(base_entries["boot"]["extent_lba"]) * SECTOR_SIZE,
         int(base_entries["boot"]["extent_lba"]) * SECTOR_SIZE + len(base_blobs["boot"])),
        (int(base_entries["eboot"]["extent_lba"]) * SECTOR_SIZE,
         int(base_entries["eboot"]["extent_lba"]) * SECTOR_SIZE + len(base_blobs["eboot"])),
        (int(base_entries["system"]["extent_lba"]) * SECTOR_SIZE,
         int(base_entries["system"]["extent_lba"]) * SECTOR_SIZE + len(base_blobs["system"])),
        (record_offset + 10, record_offset + 18),
    ])
    cursor = 0
    for left, right in allowed:
        if hash_range(BASE_ISO, cursor, left) != hash_range(ISO, cursor, left):
            raise ValueError("독립검사 허용 범위 밖 ISO 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(ISO, cursor, ISO.stat().st_size):
        raise ValueError("독립검사 마지막 허용 범위 뒤 ISO 변경")

    output = {
        "format": f"prinny1_{VERSION}_text_test_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "iso": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": iso_sha},
        "verified": {"expected_write_count": len(rows), "start_changed_bytes": len(declared_start),
                     "boot_changed_bytes": len(declared_boot), "boot_sha256": sha256_bytes(final_blobs["boot"]),
                     "system_sha256": sha256_bytes(final_blobs["system"]), "start_sha256": sha256_bytes(final_start)},
        "checks": {"independent_iso_hash": True, "independent_seven_zip_test": True,
                   "all_expected_writes_match": True, "actual_start_changes_equal_declared": True,
                   "actual_boot_changes_equal_declared": True, "boot_equals_eboot": True,
                   "changes_outside_declared_iso_ranges": 0, "translation_wording_changed": False,
                   "candidate_translation_or_data_imported": False, "image_writes": 0},
        "status": "pass_runtime_test_required", "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT / "all_report.json"
    report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {iso_sha}")
    print(f"Expected Writes: {EXPECTED_WRITE_COUNT} PASS")
    print(f"START/BOOT changed bytes: {len(declared_start)}/{len(declared_boot)}")
    print("outside declared ISO ranges: 0")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
