#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_14_14_title_difficulty_repair"
    / "prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
)
SEALED_WRITES = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_text_patch_manifest"
    / "sealed_expected_writes.csv"
)
BUILD_REPORT = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_text_resource_build"
    / "all_report.json"
)
BUILD_DIR = ROOT / "workspace/build/prinny1_v7_14_15_text_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_text_resource_build_review"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("비교 대상 크기가 다릅니다.")
    return {index for index, (old, new) in enumerate(zip(before, after)) if old != new}


def main() -> int:
    paths = [BASE_ISO, SEALED_WRITES, BUILD_REPORT]
    paths.extend(BUILD_DIR / name for name in ("BOOT.BIN", "start.dat", "start.lzs", "SYSTEM.DAT"))
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)

    build_report = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if build_report.get("status") != "pass_text_resources_built_iso_approval_required":
        raise ValueError("자원 빌드 보고서 상태가 PASS가 아닙니다.")

    base_boot = read_iso_file(
        BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    )
    base_system = read_iso_file(
        BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    )
    base_entry = font_builder.parse_nispack_start_entry(base_system)
    base_lzs_offset = int(base_entry["data_offset"])
    base_lzs_size = int(base_entry["size"])
    base_start, _ = decompress_buffer(
        base_system[base_lzs_offset:base_lzs_offset + base_lzs_size]
    )
    base_archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    font_record = next(
        record for record in base_archive.records if record.output_name.casefold() == "font.txp"
    )

    built_boot = (BUILD_DIR / "BOOT.BIN").read_bytes()
    built_start = (BUILD_DIR / "start.dat").read_bytes()
    built_lzs = (BUILD_DIR / "start.lzs").read_bytes()
    built_system = (BUILD_DIR / "SYSTEM.DAT").read_bytes()
    if len(built_boot) != len(base_boot) or len(built_start) != len(base_start):
        raise ValueError("BOOT 또는 START 크기가 기준과 다릅니다.")
    if len(built_system) != len(base_system):
        raise ValueError("SYSTEM 크기가 기준과 다릅니다.")

    declared_start: set[int] = set()
    declared_boot: set[int] = set()
    rows = read_csv(SEALED_WRITES)
    for row in rows:
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        relative = int(row["offset_hex"], 0)
        if row["layer"] == "START.DAT/font.txp":
            offset = int(font_record.data_offset) + relative
            if base_start[offset:offset + len(before)] != before:
                raise ValueError(f"독립검사 START before 불일치: {row['logical_id']}")
            if built_start[offset:offset + len(after)] != after:
                raise ValueError(f"독립검사 START after 불일치: {row['logical_id']}")
            declared_start.update(
                offset + index
                for index, (old, new) in enumerate(zip(before, after))
                if old != new
            )
        elif row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN":
            offset = relative
            if base_boot[offset:offset + len(before)] != before:
                raise ValueError(f"독립검사 BOOT before 불일치: {row['logical_id']}")
            if built_boot[offset:offset + len(after)] != after:
                raise ValueError(f"독립검사 BOOT after 불일치: {row['logical_id']}")
            declared_boot.update(
                offset + index
                for index, (old, new) in enumerate(zip(before, after))
                if old != new
            )
        else:
            raise ValueError(f"알 수 없는 패치 계층: {row['layer']}")

    actual_start = changed_offsets(base_start, built_start)
    actual_boot = changed_offsets(base_boot, built_boot)
    if actual_start != declared_start or actual_boot != declared_boot:
        raise ValueError("독립검사 실제 변경 범위가 Expected Write와 다릅니다.")

    lzs_start, _ = decompress_buffer(built_lzs)
    built_entry = font_builder.parse_nispack_start_entry(built_system)
    built_offset = int(built_entry["data_offset"])
    built_size = int(built_entry["size"])
    system_start, _ = decompress_buffer(built_system[built_offset:built_offset + built_size])
    if lzs_start != built_start or system_start != built_start:
        raise ValueError("독립검사 START/LZS/SYSTEM 왕복 불일치")
    if built_offset != base_lzs_offset or built_size != len(built_lzs):
        raise ValueError("SYSTEM 내부 START 위치 또는 크기 필드가 잘못됐습니다.")

    system_changes = changed_offsets(base_system, built_system)
    allowed_system = set(range(base_lzs_offset, base_lzs_offset + base_lzs_size))
    size_field = int(base_entry["entry_offset"]) + 0x24
    allowed_system.update(range(size_field, size_field + 4))
    outside_system = sorted(system_changes - allowed_system)
    if outside_system:
        raise ValueError(f"SYSTEM 보호 영역 변경: 0x{outside_system[0]:X}")

    for name, expected in build_report["outputs"].items():
        path = BUILD_DIR / name
        if path.stat().st_size != expected["size"] or sha256_file(path) != expected["sha256"]:
            raise ValueError(f"빌드 보고서 출력 해시 불일치: {name}")

    report: dict[str, Any] = {
        "format": "prinny1_v7_14_15_text_resource_build_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "base_iso": str(BASE_ISO),
            "base_iso_sha256": sha256_file(BASE_ISO),
            "sealed_writes": str(SEALED_WRITES),
            "sealed_writes_sha256": sha256_file(SEALED_WRITES),
            "build_report": str(BUILD_REPORT),
            "build_report_sha256": sha256_file(BUILD_REPORT),
        },
        "verified": {
            "expected_write_count": len(rows),
            "start_changed_bytes": len(actual_start),
            "boot_changed_bytes": len(actual_boot),
            "system_changed_bytes": len(system_changes),
            "system_changes_outside_allowed_ranges": 0,
            "built_lzs_size": len(built_lzs),
            "available_lzs_slot": base_lzs_size,
        },
        "checks": {
            "fresh_base_iso_reextracted": True,
            "all_before_bytes_match": True,
            "all_after_bytes_match": True,
            "actual_changes_equal_declared_changes": True,
            "output_hashes_match_build_report": True,
            "lzs_roundtrip": True,
            "system_embedded_start_matches": True,
            "system_protected_ranges_unchanged": True,
            "translation_wording_generated_or_changed_by_codex": False,
            "image_writes": 0,
            "iso_created": False,
        },
        "status": "pass_iso_build_approval_required",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"독립 검증 Expected Writes: {len(rows)}")
    print(f"START/BOOT changed bytes: {len(actual_start)}/{len(actual_boot)}")
    print(f"SYSTEM protected range violations: 0")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
