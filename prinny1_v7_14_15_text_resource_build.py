#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as font_builder
from core.lzs import compress_buffer, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_14_14_title_difficulty_repair"
    / "prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
)
SEALED_REPORT = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_text_patch_manifest"
    / "all_report.json"
)
SEALED_WRITES = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_text_patch_manifest"
    / "sealed_expected_writes.csv"
)
INDEPENDENT_REVIEW = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_text_patch_review"
    / "all_report.json"
)
OUTPUT = ROOT / "workspace/build/prinny1_v7_14_15_text_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_text_resource_build"
OUTPUT_NAMES = ("BOOT.BIN", "start.dat", "start.lzs", "SYSTEM.DAT")


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


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("변경 범위 비교 대상의 크기가 다릅니다.")
    return {index for index, (old, new) in enumerate(zip(before, after)) if old != new}


def start_from_system(system: bytes) -> tuple[bytes, bytes, dict[str, Any]]:
    entry = font_builder.parse_nispack_start_entry(system)
    offset = int(entry["data_offset"])
    size = int(entry["size"])
    old_lzs = system[offset:offset + size]
    start, header = decompress_buffer(old_lzs)
    return start, old_lzs, {"entry": entry, "header": header}


def main() -> int:
    for path in (BASE_ISO, SEALED_REPORT, SEALED_WRITES, INDEPENDENT_REVIEW):
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = json.loads(SEALED_REPORT.read_text(encoding="utf-8"))
    review = json.loads(INDEPENDENT_REVIEW.read_text(encoding="utf-8"))
    if manifest.get("status") != "sealed_text_patch_iso_build_approval_required":
        raise ValueError("텍스트 패치 manifest가 봉인 상태가 아닙니다.")
    if (
        review.get("status") != "pass_iso_build_approval_required"
        or review.get("final_verdict") != "PASS"
    ):
        raise ValueError("독립 검토 상태가 PASS가 아닙니다.")
    if sha256_file(BASE_ISO) != manifest["base_iso"]["sha256"]:
        raise ValueError("기준 V7.14.14 ISO 해시가 봉인값과 다릅니다.")
    if sha256_file(SEALED_WRITES) != manifest["sealed"]["sha256"]:
        raise ValueError("Expected Write CSV 해시가 봉인값과 다릅니다.")

    system_entry = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    boot_entry = find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    base_system = read_iso_file(BASE_ISO, system_entry)
    base_boot = read_iso_file(BASE_ISO, boot_entry)
    base_start, old_lzs, start_meta = start_from_system(base_system)
    nis_entry = start_meta["entry"]
    lzs_offset = int(nis_entry["data_offset"])
    old_lzs_size = int(nis_entry["size"])

    archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    font_record = next(
        (record for record in archive.records if record.output_name.casefold() == "font.txp"),
        None,
    )
    if font_record is None:
        raise ValueError("START.DAT에 font.txp가 없습니다.")

    rows = read_csv(SEALED_WRITES)
    if len(rows) != 12:
        raise ValueError(f"봉인 Expected Write 수가 12개가 아닙니다: {len(rows)}")
    patched_start = bytearray(base_start)
    patched_boot = bytearray(base_boot)
    declared_start: set[int] = set()
    declared_boot: set[int] = set()

    for row in rows:
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if len(before) != len(after) or len(before) != int(row["write_length"]):
            raise ValueError(f"Expected Write 길이 오류: {row['logical_id']}")
        relative = int(row["offset_hex"], 0)
        if row["layer"] == "START.DAT/font.txp":
            offset = int(font_record.data_offset) + relative
            if offset + len(before) > int(font_record.end_offset):
                raise ValueError(f"font.txp 범위 초과: {row['logical_id']}")
            if patched_start[offset:offset + len(before)] != before:
                raise ValueError(f"font.txp before 불일치: {row['logical_id']}")
            patched_start[offset:offset + len(after)] = after
            declared_start.update(
                offset + index
                for index, (old, new) in enumerate(zip(before, after))
                if old != new
            )
        elif row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN":
            offset = relative
            if offset + len(before) > len(patched_boot):
                raise ValueError(f"BOOT.BIN 범위 초과: {row['logical_id']}")
            if patched_boot[offset:offset + len(before)] != before:
                raise ValueError(f"BOOT.BIN before 불일치: {row['logical_id']}")
            patched_boot[offset:offset + len(after)] = after
            declared_boot.update(
                offset + index
                for index, (old, new) in enumerate(zip(before, after))
                if old != new
            )
        else:
            raise ValueError(f"허용되지 않은 패치 계층: {row['layer']}")

    actual_start = changed_offsets(base_start, bytes(patched_start))
    actual_boot = changed_offsets(base_boot, bytes(patched_boot))
    if actual_start != declared_start or actual_boot != declared_boot:
        raise ValueError("실제 변경 범위가 봉인 Expected Write 합집합과 다릅니다.")
    if sha256_bytes(bytes(patched_start)) != manifest["sealed"]["patched_start_sha256"]:
        raise ValueError("패치 START.DAT 해시가 사전검사 봉인값과 다릅니다.")
    if sha256_bytes(bytes(patched_boot)) != manifest["sealed"]["patched_boot_sha256"]:
        raise ValueError("패치 BOOT.BIN 해시가 사전검사 봉인값과 다릅니다.")

    new_lzs = compress_buffer(bytes(patched_start), old_lzs[:4])
    decoded_start, decoded_header = decompress_buffer(new_lzs)
    if decoded_start != bytes(patched_start):
        raise ValueError("START.LZS 압축 왕복 검증 실패")
    if len(new_lzs) > old_lzs_size:
        raise ValueError(f"SYSTEM.DAT 고정 슬롯 초과: {len(new_lzs)}>{old_lzs_size}")
    patched_system = bytearray(base_system)
    patched_system[lzs_offset:lzs_offset + old_lzs_size] = (
        new_lzs + bytes(old_lzs_size - len(new_lzs))
    )
    struct.pack_into(
        "<I", patched_system, int(nis_entry["entry_offset"]) + 0x24, len(new_lzs)
    )
    if sha256_bytes(bytes(patched_system)) != manifest["sealed"]["preflight_system_sha256"]:
        raise ValueError("패치 SYSTEM.DAT 해시가 사전검사 봉인값과 다릅니다.")

    # 기존 출력이 있어도 봉인된 결과로만 원자적으로 교체한다.
    staging = OUTPUT.with_name(OUTPUT.name + ".staging")
    if staging.exists():
        for child in staging.iterdir():
            if not child.is_file() or child.name not in OUTPUT_NAMES:
                raise ValueError(f"staging에 예상하지 않은 항목이 있습니다: {child}")
            child.unlink()
        staging.rmdir()
    staging.mkdir(parents=True)
    (staging / "BOOT.BIN").write_bytes(bytes(patched_boot))
    (staging / "start.dat").write_bytes(bytes(patched_start))
    (staging / "start.lzs").write_bytes(new_lzs)
    (staging / "SYSTEM.DAT").write_bytes(bytes(patched_system))

    # 디스크에 기록된 새 산출물에서 독립적으로 다시 파싱한다.
    disk_boot = (staging / "BOOT.BIN").read_bytes()
    disk_start = (staging / "start.dat").read_bytes()
    disk_lzs = (staging / "start.lzs").read_bytes()
    disk_system = (staging / "SYSTEM.DAT").read_bytes()
    roundtrip_start, _ = decompress_buffer(disk_lzs)
    system_start, _old, _system_meta = start_from_system(disk_system)
    if disk_boot != bytes(patched_boot):
        raise ValueError("기록 후 BOOT.BIN 재검증 실패")
    if disk_start != bytes(patched_start) or roundtrip_start != disk_start:
        raise ValueError("기록 후 START.DAT/LZS 재검증 실패")
    if system_start != disk_start:
        raise ValueError("기록 후 SYSTEM.DAT 내부 START 재검증 실패")
    if len(disk_system) != len(base_system) or len(disk_boot) != len(base_boot):
        raise ValueError("출력 BOOT.BIN 또는 SYSTEM.DAT 크기가 바뀌었습니다.")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    unexpected = [child for child in OUTPUT.iterdir() if child.name not in OUTPUT_NAMES]
    if unexpected:
        raise ValueError(f"출력 디렉터리에 예상하지 않은 항목이 있습니다: {unexpected[0]}")
    for name in OUTPUT_NAMES:
        (staging / name).replace(OUTPUT / name)
    staging.rmdir()

    outputs = {
        name: {
            "path": str(OUTPUT / name),
            "size": (OUTPUT / name).stat().st_size,
            "sha256": sha256_file(OUTPUT / name),
        }
        for name in OUTPUT_NAMES
    }
    report = {
        "format": "prinny1_v7_14_15_text_resource_build_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_iso": {
            "path": str(BASE_ISO),
            "size": BASE_ISO.stat().st_size,
            "sha256": sha256_file(BASE_ISO),
        },
        "sealed_inputs": {
            "manifest": str(SEALED_REPORT),
            "manifest_sha256": sha256_file(SEALED_REPORT),
            "expected_writes": str(SEALED_WRITES),
            "expected_writes_sha256": sha256_file(SEALED_WRITES),
            "independent_review": str(INDEPENDENT_REVIEW),
            "independent_review_sha256": sha256_file(INDEPENDENT_REVIEW),
        },
        "writes": {
            "count": len(rows),
            "font_count": sum(row["layer"] == "START.DAT/font.txp" for row in rows),
            "boot_count": sum(row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN" for row in rows),
            "start_changed_bytes": len(actual_start),
            "boot_changed_bytes": len(actual_boot),
        },
        "compression": {
            "new_lzs_size": len(new_lzs),
            "available_slot": old_lzs_size,
            "remaining_capacity": old_lzs_size - len(new_lzs),
            "roundtrip": True,
            "decoded_header": decoded_header,
        },
        "outputs": outputs,
        "checks": {
            "fresh_base_iso_reextracted": True,
            "base_iso_hash_matches_seal": True,
            "expected_write_hash_matches_seal": True,
            "before_bytes_match": True,
            "actual_changes_equal_declared_changes": True,
            "preflight_hashes_match_manifest": True,
            "disk_outputs_reopened": True,
            "disk_lzs_roundtrip": True,
            "disk_system_start_matches_output_start": True,
            "translation_wording_generated_or_changed_by_codex": False,
            "image_writes": 0,
            "iso_created": False,
        },
        "status": "pass_text_resources_built_iso_approval_required",
        "next_action": "사용자 명시 승인 후 V7.14.15 텍스트 테스트 ISO를 별도 경로에 생성한다.",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Expected Writes: {len(rows)} (font 3, BOOT 9)")
    print(f"START changed bytes: {len(actual_start)}")
    print(f"BOOT changed bytes: {len(actual_boot)}")
    print(f"LZS: {len(new_lzs)} / {old_lzs_size}")
    print(f"resources: {OUTPUT}")
    print(f"report: {report_path}")
    print("ISO created: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
