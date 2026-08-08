#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from prinny1_v7_14_minimum_test_iso import (
    SECTOR_SIZE,
    find_iso_file,
    normalized_iso_name,
    parse_directory_record,
    read_iso_file,
    read_primary_volume_descriptor,
)


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_14_14_title_difficulty_repair"
    / "prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
)
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_14_15_text_resources"
RESOURCE_REPORT = (
    ROOT / "workspace/reports/prinny1_v7_14_15_text_resource_build/all_report.json"
)
RESOURCE_REVIEW = (
    ROOT / "workspace/reports/prinny1_v7_14_15_text_resource_build_review/all_report.json"
)
XDELTA_AUDIT = (
    ROOT / "workspace/reports/prinny1_v7_14_15_xdelta_import_audit/all_report.json"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_14_15_text_test_iso"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_14_15_text_test.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_text_test_iso"
EXPECTED_BASE_SHA256 = "bd5168a461adfd4a41b8daf9dfe6037d7a9838ab2fc8ee0affd1e0f5521bd5b5"


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
                raise EOFError("ISO 범위 해시 중 EOF")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def directory_entries_with_offsets(
    handle: BinaryIO, extent_lba: int, data_length: int
) -> list[dict[str, Any]]:
    base = extent_lba * SECTOR_SIZE
    handle.seek(base)
    data = handle.read(data_length)
    if len(data) != data_length:
        raise EOFError("ISO 디렉터리를 전부 읽지 못했습니다.")
    entries: list[dict[str, Any]] = []
    offset = 0
    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset = ((offset // SECTOR_SIZE) + 1) * SECTOR_SIZE
            continue
        end = offset + length
        if end > len(data):
            raise ValueError("ISO 디렉터리 레코드 범위 오류")
        entry = parse_directory_record(data[offset:end])
        entry["record_offset"] = base + offset
        entry["record_length"] = length
        entries.append(entry)
        offset = end
    return entries


def find_iso_record(iso_path: Path, path_parts: list[str]) -> dict[str, Any]:
    with iso_path.open("rb") as handle:
        descriptor = read_primary_volume_descriptor(handle)
        root_length = descriptor[156]
        current = parse_directory_record(descriptor[156:156 + root_length])
        for index, wanted in enumerate(path_parts):
            entries = directory_entries_with_offsets(
                handle, int(current["extent_lba"]), int(current["data_length"])
            )
            matches = [
                entry for entry in entries
                if normalized_iso_name(str(entry["name"])) == normalized_iso_name(wanted)
            ]
            if len(matches) != 1:
                raise ValueError(f"ISO 레코드를 확정하지 못했습니다: {'/'.join(path_parts[:index + 1])}")
            current = matches[0]
        return current


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def main() -> int:
    required = [BASE_ISO, RESOURCE_REPORT, RESOURCE_REVIEW, XDELTA_AUDIT]
    required.extend(RESOURCE_DIR / name for name in ("BOOT.BIN", "SYSTEM.DAT", "start.dat"))
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(BASE_ISO) != EXPECTED_BASE_SHA256:
        raise ValueError("V7.14.14 기준 ISO 해시 불일치")

    resource_report = json.loads(RESOURCE_REPORT.read_text(encoding="utf-8"))
    resource_review = json.loads(RESOURCE_REVIEW.read_text(encoding="utf-8"))
    xdelta_audit = json.loads(XDELTA_AUDIT.read_text(encoding="utf-8"))
    if resource_report.get("status") != "pass_text_resources_built_iso_approval_required":
        raise ValueError("텍스트 자원 빌드 상태가 PASS가 아닙니다.")
    if resource_review.get("final_verdict") != "PASS":
        raise ValueError("텍스트 자원 독립 검토가 PASS가 아닙니다.")

    patched_boot = (RESOURCE_DIR / "BOOT.BIN").read_bytes()
    patched_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    patched_start = (RESOURCE_DIR / "start.dat").read_bytes()
    for name, blob in (("BOOT.BIN", patched_boot), ("SYSTEM.DAT", patched_system), ("start.dat", patched_start)):
        expected = resource_report["outputs"][name]
        if len(blob) != int(expected["size"]) or hashlib.sha256(blob).hexdigest() != expected["sha256"]:
            raise ValueError(f"봉인 내부 자원 해시 불일치: {name}")

    boot_record = find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    eboot_record = find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"])
    system_record = find_iso_record(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    base_boot = read_iso_file(BASE_ISO, boot_record)
    base_eboot = read_iso_file(BASE_ISO, eboot_record)
    base_system = read_iso_file(BASE_ISO, system_record)
    if len(patched_boot) != len(base_boot) or len(patched_system) != len(base_system):
        raise ValueError("BOOT 또는 SYSTEM 교체 크기 불일치")
    if len(patched_boot) > len(base_eboot):
        raise ValueError("패치 BOOT가 EBOOT 기존 영역보다 큽니다.")
    if not base_boot.startswith(b"\x7fELF") or not base_eboot.startswith(b"~PSP"):
        raise ValueError("기준 BOOT/EBOOT 실행 파일 형식이 예상과 다릅니다.")

    candidate_iso_files = {row["name"]: row for row in xdelta_audit["iso_file_comparison"]}
    if not (
        candidate_iso_files["boot"]["candidate"]["sha256"]
        == candidate_iso_files["eboot"]["candidate"]["sha256"]
        and candidate_iso_files["boot"]["candidate"]["size"]
        == candidate_iso_files["eboot"]["candidate"]["size"]
    ):
        raise ValueError("xdelta 참고본에서 BOOT/EBOOT 미러링 근거를 확인하지 못했습니다.")

    boot_offset = int(boot_record["extent_lba"]) * SECTOR_SIZE
    eboot_offset = int(eboot_record["extent_lba"]) * SECTOR_SIZE
    system_offset = int(system_record["extent_lba"]) * SECTOR_SIZE
    eboot_record_offset = int(eboot_record["record_offset"])
    old_eboot_size = int(eboot_record["data_length"])
    new_eboot_size = len(patched_boot)
    iso_size = BASE_ISO.stat().st_size

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as target:
        target.seek(boot_offset)
        target.write(patched_boot)
        target.seek(system_offset)
        target.write(patched_system)
        target.seek(eboot_offset)
        target.write(patched_boot)
        target.write(bytes(old_eboot_size - new_eboot_size))
        target.seek(eboot_record_offset + 10)
        target.write(new_eboot_size.to_bytes(4, "little"))
        target.write(new_eboot_size.to_bytes(4, "big"))
        target.flush()
        os.fsync(target.fileno())
    if temporary.stat().st_size != iso_size:
        raise ValueError("출력 ISO 크기가 변경됐습니다.")

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
            raise ValueError(f"허용 범위 이전 ISO 변경 감지: 0x{cursor:X}..0x{start:X}")
        cursor = end
    if hash_range(BASE_ISO, cursor, iso_size) != hash_range(temporary, cursor, iso_size):
        raise ValueError(f"허용 범위 이후 ISO 변경 감지: 0x{cursor:X}..EOF")

    archive_test = subprocess.run(
        ["7z", "t", str(temporary)],
        capture_output=True,
        text=True,
        check=False,
    )
    if archive_test.returncode != 0 or "Everything is Ok" not in archive_test.stdout:
        raise RuntimeError("7z ISO 구조 검사 실패:\n" + (archive_test.stdout + archive_test.stderr)[-3000:])
    os.replace(temporary, OUTPUT_ISO)

    final_boot_entry = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    final_eboot_entry = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"])
    final_system_entry = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_boot = read_iso_file(OUTPUT_ISO, final_boot_entry)
    final_eboot = read_iso_file(OUTPUT_ISO, final_eboot_entry)
    final_system = read_iso_file(OUTPUT_ISO, final_system_entry)
    if final_boot != patched_boot or final_eboot != patched_boot or final_system != patched_system:
        raise ValueError("완성 ISO 내부 BOOT/EBOOT/SYSTEM 재추출 불일치")
    final_start_entry = font_builder.parse_nispack_start_entry(final_system)
    start_offset = int(final_start_entry["data_offset"])
    start_size = int(final_start_entry["size"])
    final_start, _ = decompress_buffer(final_system[start_offset:start_offset + start_size])
    if final_start != patched_start:
        raise ValueError("완성 ISO 내부 START.DAT 재추출 불일치")

    report = {
        "format": "prinny1_v7_14_15_text_test_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_explicit_v7_14_15_test_iso_creation_approval",
        "base_iso": {"path": str(BASE_ISO), "size": iso_size, "sha256": sha256_file(BASE_ISO)},
        "sealed_resources": resource_report["outputs"],
        "eboot_runtime_packaging": {
            "method": "mirror_patched_boot_as_plain_elf_eboot",
            "reference": str(XDELTA_AUDIT),
            "reference_candidate_boot_equals_eboot": True,
            "expected_before_size": len(base_eboot),
            "expected_before_sha256": hashlib.sha256(base_eboot).hexdigest(),
            "write_after_size": len(patched_boot),
            "write_after_sha256": hashlib.sha256(patched_boot).hexdigest(),
            "directory_record_offset_hex": f"0x{eboot_record_offset:X}",
            "directory_length_write_offset_hex": f"0x{eboot_record_offset + 10:X}",
            "directory_length_write_bytes": 8,
        },
        "output_iso": {
            "path": str(OUTPUT_ISO),
            "size": OUTPUT_ISO.stat().st_size,
            "sha256": sha256_file(OUTPUT_ISO),
        },
        "checks": {
            "base_hash_rechecked_before_write": True,
            "sealed_resource_hashes_rechecked": True,
            "resource_independent_review_pass": True,
            "xdelta_reference_confirms_boot_eboot_mirror": True,
            "only_declared_iso_ranges_changed": True,
            "iso_size_preserved": True,
            "seven_zip_structure_test": True,
            "final_boot_reextracted": True,
            "final_eboot_reextracted": True,
            "final_system_reextracted": True,
            "final_start_decompressed_and_matched": True,
            "translation_wording_generated_or_changed_by_codex": False,
            "image_writes": 0,
        },
        "status": "pass_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"size: {OUTPUT_ISO.stat().st_size}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z structure: PASS")
    print("BOOT/EBOOT/SYSTEM/START reextract: PASS")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
