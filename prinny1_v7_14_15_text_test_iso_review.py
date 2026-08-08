#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair"
    / "prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
)
OUTPUT_ISO = (
    ROOT / "workspace/build/prinny1_v7_14_15_text_test_iso"
    / "prinny_korean_v7_14_15_text_test.iso"
)
ISO_REPORT = ROOT / "workspace/reports/prinny1_v7_14_15_text_test_iso/all_report.json"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_14_15_text_resources"
SEALED_WRITES = (
    ROOT / "workspace/reports/prinny1_v7_14_15_text_patch_manifest"
    / "sealed_expected_writes.csv"
)
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_text_test_iso_review"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def hash_range(path: Path, start: int, end: int) -> str:
    digest = hashlib.sha256()
    remaining = end - start
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise EOFError("범위 해시 중 EOF")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def locate_eboot_record_independently(iso: Path, extent_lba: int, data_length: int) -> int:
    prefix = iso.read_bytes()[:1024 * 1024]
    matches: list[int] = []
    start = 0
    while True:
        name_offset = prefix.find(b"EBOOT.BIN", start)
        if name_offset < 0:
            break
        record_offset = name_offset - 33
        if record_offset >= 0 and prefix[record_offset] >= 42:
            extent = int.from_bytes(prefix[record_offset + 2:record_offset + 6], "little")
            size = int.from_bytes(prefix[record_offset + 10:record_offset + 14], "little")
            extent_be = int.from_bytes(prefix[record_offset + 6:record_offset + 10], "big")
            size_be = int.from_bytes(prefix[record_offset + 14:record_offset + 18], "big")
            if extent == extent_lba == extent_be and size == data_length == size_be:
                matches.append(record_offset)
        start = name_offset + 1
    if len(matches) != 1:
        raise ValueError(f"EBOOT ISO 디렉터리 레코드 독립 탐색 실패: {matches}")
    return matches[0]


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[list[int]] = []
    for start, end in sorted(intervals):
        if not result or start > result[-1][1]:
            result.append([start, end])
        else:
            result[-1][1] = max(result[-1][1], end)
    return [(start, end) for start, end in result]


def main() -> int:
    for path in (BASE_ISO, OUTPUT_ISO, ISO_REPORT, SEALED_WRITES):
        if not path.is_file():
            raise FileNotFoundError(path)
    report = json.loads(ISO_REPORT.read_text(encoding="utf-8"))
    if report.get("status") != "pass_test_iso_built_independent_post_review_required":
        raise ValueError("ISO 빌드 보고서 상태가 검토 대기가 아닙니다.")
    if OUTPUT_ISO.stat().st_size != report["output_iso"]["size"]:
        raise ValueError("ISO 크기가 빌드 보고서와 다릅니다.")
    output_sha = sha256_file(OUTPUT_ISO)
    if output_sha != report["output_iso"]["sha256"]:
        raise ValueError("ISO 해시가 빌드 보고서와 다릅니다.")

    archive_test = subprocess.run(
        ["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False
    )
    if archive_test.returncode != 0 or "Everything is Ok" not in archive_test.stdout:
        raise ValueError("독립 7z ISO 구조 검사 실패")

    paths = {
        "boot": ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
        "eboot": ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
        "system": ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    }
    base_entries = {name: find_iso_file(BASE_ISO, parts) for name, parts in paths.items()}
    output_entries = {name: find_iso_file(OUTPUT_ISO, parts) for name, parts in paths.items()}
    output_blobs = {name: read_iso_file(OUTPUT_ISO, entry) for name, entry in output_entries.items()}
    sealed_boot = (RESOURCE_DIR / "BOOT.BIN").read_bytes()
    sealed_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    sealed_start = (RESOURCE_DIR / "start.dat").read_bytes()
    if output_blobs["boot"] != sealed_boot or output_blobs["eboot"] != sealed_boot:
        raise ValueError("ISO BOOT/EBOOT가 봉인 BOOT와 다릅니다.")
    if output_blobs["system"] != sealed_system:
        raise ValueError("ISO SYSTEM이 봉인 SYSTEM과 다릅니다.")

    final_start_entry = font_builder.parse_nispack_start_entry(output_blobs["system"])
    offset = int(final_start_entry["data_offset"])
    size = int(final_start_entry["size"])
    final_start, _ = decompress_buffer(output_blobs["system"][offset:offset + size])
    if final_start != sealed_start:
        raise ValueError("ISO START가 봉인 START와 다릅니다.")
    archive = StartRuntimeArchive.from_bytes(final_start, source=f"{OUTPUT_ISO}!/start.dat")
    font_record = next(record for record in archive.records if record.output_name.casefold() == "font.txp")

    rows = read_csv(SEALED_WRITES)
    for row in rows:
        after = bytes.fromhex(row["write_after_hex"])
        relative = int(row["offset_hex"], 0)
        if row["layer"] == "START.DAT/font.txp":
            absolute = int(font_record.data_offset) + relative
            actual = final_start[absolute:absolute + len(after)]
        elif row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN":
            actual = output_blobs["boot"][relative:relative + len(after)]
        else:
            raise ValueError(f"허용되지 않은 계층: {row['layer']}")
        if actual != after:
            raise ValueError(f"ISO 최종 Expected Write 불일치: {row['logical_id']}")

    base_eboot = read_iso_file(BASE_ISO, base_entries["eboot"])
    record_offset = locate_eboot_record_independently(
        OUTPUT_ISO,
        int(output_entries["eboot"]["extent_lba"]),
        int(output_entries["eboot"]["data_length"]),
    )
    allowed = merge_intervals(
        [
            (int(base_entries["boot"]["extent_lba"]) * SECTOR_SIZE,
             int(base_entries["boot"]["extent_lba"]) * SECTOR_SIZE + int(base_entries["boot"]["data_length"])),
            (int(base_entries["eboot"]["extent_lba"]) * SECTOR_SIZE,
             int(base_entries["eboot"]["extent_lba"]) * SECTOR_SIZE + len(base_eboot)),
            (int(base_entries["system"]["extent_lba"]) * SECTOR_SIZE,
             int(base_entries["system"]["extent_lba"]) * SECTOR_SIZE + int(base_entries["system"]["data_length"])),
            (record_offset + 10, record_offset + 18),
        ]
    )
    cursor = 0
    for start, end in allowed:
        if hash_range(BASE_ISO, cursor, start) != hash_range(OUTPUT_ISO, cursor, start):
            raise ValueError(f"독립검사 허용 범위 밖 ISO 변경: 0x{cursor:X}..0x{start:X}")
        cursor = end
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(
        OUTPUT_ISO, cursor, OUTPUT_ISO.stat().st_size
    ):
        raise ValueError("독립검사 마지막 허용 범위 뒤 ISO 변경")

    review: dict[str, Any] = {
        "format": "prinny1_v7_14_15_text_test_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": output_sha},
        "verified": {
            "expected_write_count": len(rows),
            "boot_sha256": hashlib.sha256(output_blobs["boot"]).hexdigest(),
            "eboot_sha256": hashlib.sha256(output_blobs["eboot"]).hexdigest(),
            "system_sha256": hashlib.sha256(output_blobs["system"]).hexdigest(),
            "start_sha256": hashlib.sha256(final_start).hexdigest(),
            "eboot_directory_record_offset_hex": f"0x{record_offset:X}",
            "allowed_iso_intervals": [[start, end] for start, end in allowed],
        },
        "checks": {
            "independent_iso_sha256": True,
            "independent_seven_zip_test": True,
            "boot_equals_sealed_boot": True,
            "eboot_equals_sealed_boot": True,
            "system_equals_sealed_system": True,
            "start_equals_sealed_start": True,
            "all_twelve_expected_writes_match": True,
            "changes_outside_declared_iso_ranges": 0,
            "translation_wording_generated_or_changed_by_codex": False,
            "image_writes": 0,
        },
        "status": "pass_runtime_test_required",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "all_report.json"
    report_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {output_sha}")
    print(f"Expected Writes: {len(rows)} PASS")
    print("BOOT/EBOOT/SYSTEM/START: PASS")
    print("outside declared ISO ranges: 0")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
