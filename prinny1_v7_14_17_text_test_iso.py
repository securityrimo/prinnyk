#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from prinny1_v7_14_15_text_test_iso import find_iso_record, hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_14_17_text_resources"
RESOURCE_REPORT = ROOT / "workspace/reports/prinny1_v7_14_17_text_resource_build/all_report.json"
RESOURCE_REVIEW = ROOT / "workspace/reports/prinny1_v7_14_17_text_resource_build_review/all_report.json"
SEALED = ROOT / "workspace/reports/prinny1_v7_14_17_text_resource_build/sealed_expected_writes.csv"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_14_17_text_test_iso"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_14_17_text_test.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_17_text_test_iso"
BASE_SHA256 = "bd5168a461adfd4a41b8daf9dfe6037d7a9838ab2fc8ee0affd1e0f5521bd5b5"
VERSION = "v7_14_17"
EXPECTED_WRITE_COUNT = 23
RESOURCE_REVIEW_READY_STATUS = "pass_test_iso_build_ready_user_approval_required"
AUTHORIZATION = "user_explicit_v7_14_17_test_iso_creation_approval"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inputs() -> tuple[dict, dict, dict[str, bytes]]:
    required = [BASE_ISO, RESOURCE_REPORT, RESOURCE_REVIEW, SEALED]
    required.extend(RESOURCE_DIR / name for name in ("BOOT.BIN", "SYSTEM.DAT", "start.dat", "start.lzs"))
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(BASE_ISO) != BASE_SHA256:
        raise ValueError("V7.14.14 기준 ISO 해시가 다릅니다.")
    report = json.loads(RESOURCE_REPORT.read_text(encoding="utf-8"))
    review = json.loads(RESOURCE_REVIEW.read_text(encoding="utf-8"))
    if report.get("status") != "pass_independent_resource_review_required":
        raise ValueError("V7.14.17 자원 빌드 상태가 다릅니다.")
    if review.get("status") != RESOURCE_REVIEW_READY_STATUS:
        raise ValueError("V7.14.17 독립 자원 검토가 ISO 승인 대기가 아닙니다.")
    blobs = {name: (RESOURCE_DIR / name).read_bytes() for name in ("BOOT.BIN", "SYSTEM.DAT", "start.dat", "start.lzs")}
    for name, blob in blobs.items():
        expected = report["outputs"][name]
        if len(blob) != expected["size"] or hashlib.sha256(blob).hexdigest() != expected["sha256"]:
            raise ValueError(f"봉인 자원 불일치: {name}")
    return report, review, blobs


def preflight() -> dict:
    report, review, blobs = inputs()
    records = {
        "boot": find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]),
        "eboot": find_iso_record(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]),
        "system": find_iso_record(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]),
    }
    base_boot = read_iso_file(BASE_ISO, records["boot"])
    base_eboot = read_iso_file(BASE_ISO, records["eboot"])
    base_system = read_iso_file(BASE_ISO, records["system"])
    if len(blobs["BOOT.BIN"]) != len(base_boot) or len(blobs["SYSTEM.DAT"]) != len(base_system):
        raise ValueError("BOOT/SYSTEM 고정 슬롯 크기 불일치")
    if len(blobs["BOOT.BIN"]) > len(base_eboot):
        raise ValueError("평문 BOOT가 EBOOT 슬롯보다 큽니다.")
    entry = font_builder.parse_nispack_start_entry(blobs["SYSTEM.DAT"])
    start, _ = decompress_buffer(blobs["SYSTEM.DAT"][int(entry["data_offset"]):int(entry["data_offset"]) + int(entry["size"])])
    if start != blobs["start.dat"]:
        raise ValueError("SYSTEM 내부 START가 봉인 start.dat와 다릅니다.")
    if OUTPUT_ISO.exists():
        raise ValueError("V7.14.17 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    return {
        "resource_report": report, "resource_review": review, "blobs": blobs,
        "records": records, "base_boot": base_boot, "base_eboot": base_eboot, "base_system": base_system,
    }


def write_preflight_report(context: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "format": f"prinny1_{VERSION}_text_test_iso_preflight_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_iso": {"path": str(BASE_ISO), "size": BASE_ISO.stat().st_size, "sha256": sha256_file(BASE_ISO)},
        "resources": context["resource_report"]["outputs"],
        "sealed": {"path": str(SEALED), "sha256": sha256_file(SEALED), "expected_write_count": EXPECTED_WRITE_COUNT},
        "checks": {"resource_build_review_pass": True, "fixed_slot_sizes_match": True,
                   "system_start_reextract_matches": True, "output_iso_absent": True,
                   "translation_wording_changed": False, "iso_created": False},
        "status": "ready_user_v7_14_17_test_iso_creation_approval_required",
        "final_verdict": "PASS",
    }
    path = REPORT_DIR / "preflight_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build(context: dict) -> None:
    blobs, records = context["blobs"], context["records"]
    boot_offset = int(records["boot"]["extent_lba"]) * SECTOR_SIZE
    eboot_offset = int(records["eboot"]["extent_lba"]) * SECTOR_SIZE
    system_offset = int(records["system"]["extent_lba"]) * SECTOR_SIZE
    record_offset = int(records["eboot"]["record_offset"])
    old_eboot_size = len(context["base_eboot"])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as target:
        target.seek(boot_offset); target.write(blobs["BOOT.BIN"])
        target.seek(system_offset); target.write(blobs["SYSTEM.DAT"])
        target.seek(eboot_offset); target.write(blobs["BOOT.BIN"])
        target.write(bytes(old_eboot_size - len(blobs["BOOT.BIN"])))
        target.seek(record_offset + 10)
        target.write(len(blobs["BOOT.BIN"]).to_bytes(4, "little"))
        target.write(len(blobs["BOOT.BIN"]).to_bytes(4, "big"))
        target.flush(); os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기가 변경됐습니다.")
    allowed = merge_intervals([
        (boot_offset, boot_offset + len(context["base_boot"])),
        (eboot_offset, eboot_offset + old_eboot_size),
        (system_offset, system_offset + len(context["base_system"])),
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
    if final_boot != blobs["BOOT.BIN"] or final_eboot != blobs["BOOT.BIN"] or final_system != blobs["SYSTEM.DAT"]:
        raise ValueError("최종 ISO 재추출 자원 불일치")
    result = {
        "format": f"prinny1_{VERSION}_text_test_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": AUTHORIZATION,
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO), "size": BASE_ISO.stat().st_size},
        "output_iso": {"path": str(OUTPUT_ISO), "sha256": sha256_file(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size},
        "sealed": {"path": str(SEALED), "sha256": sha256_file(SEALED), "expected_write_count": EXPECTED_WRITE_COUNT},
        "checks": {"boot_eboot_mirror": True, "seven_zip_test": True, "final_resources_reextracted": True,
                   "changes_outside_declared_iso_ranges": 0, "translation_wording_changed": False,
                   "image_writes": 0},
        "status": "pass_test_iso_built_independent_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {result['output_iso']['sha256']}")
    print("7z/reextract: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="사용자 명시 승인 후에만 ISO 생성")
    args = parser.parse_args()
    context = preflight()
    if not args.build:
        path = write_preflight_report(context)
        print(f"{VERSION} ISO preflight: PASS")
        print("ISO created: no")
        print(f"report: {path}")
        print("FINAL_VERDICT: PASS")
        return 0
    build(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
