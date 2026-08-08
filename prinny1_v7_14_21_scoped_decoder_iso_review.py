#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_21_scoped_decoder_iso import BASE_ISO, OUTPUT_ISO, REPORT_DIR, WRITES
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BUILD_REPORT = REPORT_DIR / "all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_21_scoped_decoder_iso_review"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> int:
    for path in (BASE_ISO, OUTPUT_ISO, BUILD_REPORT, WRITES):
        if not path.is_file():
            raise FileNotFoundError(path)
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if build.get("status") != "pass_diagnostic_iso_built_independent_review_required":
        raise ValueError("빌드 보고서 상태가 다릅니다.")
    if sha256_file(OUTPUT_ISO) != build["output_iso"]["sha256"]:
        raise ValueError("진단 ISO 해시가 다릅니다.")
    with WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    final_boot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    final_eboot = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    simulated = bytearray(base_boot)
    declared = set()
    for row in rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if simulated[offset:offset + len(before)] != before:
            raise ValueError(f"독립 before 불일치: {row['logical_id']}")
        simulated[offset:offset + len(after)] = after
        declared.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if final_boot != bytes(simulated) or final_eboot != bytes(simulated) or len(declared) != 151:
        raise ValueError("최종 BOOT/EBOOT 독립 재현 실패")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    if final_system != base_system:
        raise ValueError("V14 SYSTEM/START가 변경됐습니다.")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "prinny1_v7_14_21_scoped_decoder_diagnostic_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {"build_report_sha256": sha256_file(BUILD_REPORT), "iso_sha256": sha256_file(OUTPUT_ISO)},
        "verified": {"expected_write_count": len(rows), "actual_changed_bytes": len(declared)},
        "checks": {
            "boot_eboot_independently_reproduced": True,
            "v14_system_start_font_translation_byte_identical": True,
            "translation_wording_changed": False,
            "runtime_not_yet_tested": True,
        },
        "status": "pass_runtime_gameplay_regression_test_required",
        "final_verdict": "PASS",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.14.21 diagnostic ISO independent review: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
