#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as builder
from core.lzs import compress_buffer, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_14_14_title_difficulty_repair"
    / "prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
)
FONT_PLAN = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_font_extension_plan"
    / "expected_write_confirmed.csv"
)
BOOT_PLAN = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_boot_translation_plan"
    / "expected_write_confirmed.csv"
)
TRANSLATION_CSV = (
    ROOT / "workspace/translations/ui_v7_14_15/title_difficulty_translation.csv"
)
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
IMAGE_EXPORT = ROOT / "workspace/exports/prinny1_v7_14_15_images/all_report.json"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_text_patch_manifest"

BASE_ISO_SHA256 = "bd5168a461adfd4a41b8daf9dfe6037d7a9838ab2fc8ee0affd1e0f5521bd5b5"
TRANSLATION_SHA256 = "2099d8923f4854dc4bd46b8fd2c7e7a6188ed192eef4403746a61ecdf8198689"
DEFERRED_IMAGE_IDS = (
    "P1-UI-TITLE-001",
    "P1-UI-TITLE-002",
    "P1-UI-TITLE-003",
    "P1-UI-TITLE-004",
    "P1-UI-DIFFICULTY-001",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"빈 CSV입니다: {path}")
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("비교 대상 크기가 다릅니다.")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def main() -> int:
    for path in (
        BASE_ISO,
        FONT_PLAN,
        BOOT_PLAN,
        TRANSLATION_CSV,
        ALLOCATION,
        IMAGE_EXPORT,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(BASE_ISO) != BASE_ISO_SHA256:
        raise ValueError("V7.14.14 기준 ISO 해시가 다릅니다.")
    if sha256_file(TRANSLATION_CSV) != TRANSLATION_SHA256:
        raise ValueError("사용자 번역 CSV 봉인 해시가 다릅니다.")

    system_entry = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    boot_entry = find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    system = read_iso_file(BASE_ISO, system_entry)
    boot = read_iso_file(BASE_ISO, boot_entry)
    start_entry = builder.parse_nispack_start_entry(system)
    lzs_offset = int(start_entry["data_offset"])
    old_lzs_size = int(start_entry["size"])
    old_lzs = system[lzs_offset:lzs_offset + old_lzs_size]
    start, old_lzs_header = decompress_buffer(old_lzs)
    archive = StartRuntimeArchive.from_bytes(start, source=f"{BASE_ISO}!/start.dat")
    records = {record.output_name.casefold(): record for record in archive.records}
    font_record = records.get("font.txp")
    if font_record is None:
        raise ValueError("START에 font.txp가 없습니다.")

    font_rows = read_csv(FONT_PLAN)
    boot_rows = read_csv(BOOT_PLAN)
    if len(font_rows) != 3 or len(boot_rows) != 9:
        raise ValueError("폰트 3개/BOOT 9개 Expected Write 수가 다릅니다.")

    patched_start = bytearray(start)
    patched_boot = bytearray(boot)
    sealed: list[dict[str, Any]] = []
    declared_start: set[int] = set()
    declared_boot: set[int] = set()

    for row in font_rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        absolute = int(font_record.data_offset) + offset
        if absolute + len(before) > int(font_record.end_offset):
            raise ValueError(f"font.txp 경계 초과: {row['logical_id']}")
        if patched_start[absolute:absolute + len(before)] != before:
            raise ValueError(f"font.txp before 불일치: {row['logical_id']}")
        patched_start[absolute:absolute + len(after)] = after
        declared_start.update(
            absolute + i for i, (old, new) in enumerate(zip(before, after)) if old != new
        )
        sealed.append(
            {
                "sequence": 0,
                "layer": "START.DAT/font.txp",
                "source_plan": FONT_PLAN.parent.name,
                "group_id": row["group_id"],
                "logical_id": row["logical_id"],
                "target": "font.txp",
                "offset_hex": row["offset_hex"],
                "write_length": len(after),
                "expected_before_hex": row["expected_before_hex"],
                "write_after_hex": row["write_after_hex"],
                "change_kind": row["change_kind"],
                "wording_changed": "no",
                "user_wording_approval": "yes_translation_csv",
                "expected_write_confirmed": "yes",
            }
        )

    for row in boot_rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if len(before) != len(after) or offset + len(before) > len(patched_boot):
            raise ValueError(f"BOOT 쓰기 길이/경계 오류: {row['logical_id']}")
        if patched_boot[offset:offset + len(before)] != before:
            raise ValueError(f"BOOT before 불일치: {row['logical_id']}")
        patched_boot[offset:offset + len(after)] = after
        declared_boot.update(
            offset + i for i, (old, new) in enumerate(zip(before, after)) if old != new
        )
        sealed.append(
            {
                "sequence": 0,
                "layer": "PSP_GAME/SYSDIR/BOOT.BIN",
                "source_plan": BOOT_PLAN.parent.name,
                "group_id": row["group_id"],
                "logical_id": row["logical_id"],
                "target": "PSP_GAME/SYSDIR/BOOT.BIN",
                "offset_hex": row["offset_hex"],
                "write_length": len(after),
                "expected_before_hex": row["expected_before_hex"],
                "write_after_hex": row["write_after_hex"],
                "change_kind": row["change_kind"],
                "wording_changed": "no",
                "user_wording_approval": "yes_translation_csv",
                "expected_write_confirmed": "yes",
            }
        )

    actual_start = changed_offsets(start, bytes(patched_start))
    actual_boot = changed_offsets(boot, bytes(patched_boot))
    if actual_start != declared_start or actual_boot != declared_boot:
        raise ValueError("시뮬레이션 변경 범위가 Expected Write와 다릅니다.")
    if not actual_start or not actual_boot:
        raise ValueError("START 또는 BOOT 실제 변경이 없습니다.")

    # Preflight the fixed-size SYSTEM.DAT slot without writing build artifacts.
    new_lzs = compress_buffer(bytes(patched_start), old_lzs[:4])
    decoded, _ = decompress_buffer(new_lzs)
    if decoded != bytes(patched_start):
        raise ValueError("패치 START LZS 왕복 검증 실패")
    if len(new_lzs) > old_lzs_size:
        raise ValueError(f"START LZS 고정 영역 초과: {len(new_lzs)}>{old_lzs_size}")
    patched_system = bytearray(system)
    patched_system[lzs_offset:lzs_offset + old_lzs_size] = (
        new_lzs + bytes(old_lzs_size - len(new_lzs))
    )
    struct.pack_into(
        "<I", patched_system, int(start_entry["entry_offset"]) + 0x24, len(new_lzs)
    )
    verified_entry = builder.parse_nispack_start_entry(bytes(patched_system))
    verified_start, _ = decompress_buffer(
        bytes(patched_system)[
            int(verified_entry["data_offset"]):
            int(verified_entry["data_offset"]) + int(verified_entry["size"])
        ]
    )
    if verified_start != bytes(patched_start) or len(patched_system) != len(system):
        raise ValueError("SYSTEM.DAT 사전 재패킹 검증 실패")

    sealed.sort(key=lambda row: (row["layer"], int(row["offset_hex"], 0)))
    for sequence, row in enumerate(sealed, start=1):
        row["sequence"] = sequence
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sealed_path = REPORT_DIR / "sealed_expected_writes.csv"
    write_csv(sealed_path, sealed)

    image_report = json.loads(IMAGE_EXPORT.read_text(encoding="utf-8"))
    report = {
        "format": "prinny1_v7_14_15_text_patch_manifest_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "priority": "in_game_text_first_images_deferred",
        "base_iso": {
            "path": str(BASE_ISO),
            "size": BASE_ISO.stat().st_size,
            "sha256": sha256_file(BASE_ISO),
        },
        "inputs": {
            "translation_csv": str(TRANSLATION_CSV),
            "translation_csv_sha256": sha256_file(TRANSLATION_CSV),
            "allocation_980": str(ALLOCATION),
            "allocation_980_sha256": sha256_file(ALLOCATION),
            "font_plan": str(FONT_PLAN),
            "font_plan_sha256": sha256_file(FONT_PLAN),
            "boot_plan": str(BOOT_PLAN),
            "boot_plan_sha256": sha256_file(BOOT_PLAN),
        },
        "sealed": {
            "path": str(sealed_path),
            "sha256": sha256_file(sealed_path),
            "write_count": len(sealed),
            "font_write_count": len(font_rows),
            "boot_write_count": len(boot_rows),
            "start_changed_bytes": len(actual_start),
            "boot_changed_bytes": len(actual_boot),
            "patched_start_sha256": sha256_bytes(bytes(patched_start)),
            "patched_boot_sha256": sha256_bytes(bytes(patched_boot)),
            "preflight_lzs_size": len(new_lzs),
            "available_lzs_slot": old_lzs_size,
            "preflight_system_sha256": sha256_bytes(bytes(patched_system)),
        },
        "deferred_images": {
            "ids": list(DEFERRED_IMAGE_IDS),
            "write_count": 0,
            "export": str(IMAGE_EXPORT.parent),
            "export_counts": image_report["counts"],
            "external_texture_replacement_used": False,
        },
        "checks": {
            "fresh_iso_inputs_reextracted": True,
            "font_before_bytes_match": True,
            "boot_before_bytes_match": True,
            "actual_changes_equal_declared_changes": True,
            "start_size_preserved": True,
            "boot_size_preserved": True,
            "system_size_preserved": True,
            "lzs_roundtrip": True,
            "lzs_fits_fixed_slot": True,
            "translation_wording_changed_by_codex": False,
            "image_writes_included": 0,
            "iso_created": False,
        },
        "status": "sealed_text_patch_iso_build_approval_required",
        "next_action": "사용자 승인 후 V7.14.15 텍스트 테스트 ISO를 생성한다.",
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"봉인 Expected Writes: {len(sealed)} (폰트 3, BOOT 9)")
    print(f"START 변경 바이트: {len(actual_start)}")
    print(f"BOOT 변경 바이트: {len(actual_boot)}")
    print(f"LZS 사전검사: {len(new_lzs)} / {old_lzs_size}")
    print("이미지 적용: 0 (후순위)")
    print("ISO 생성: 없음")
    print(f"보고서: {REPORT_DIR / 'all_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
