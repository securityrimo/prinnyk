#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_14_22_coherent_f0/prinny_korean_v7_14_22_coherent_f0.iso"
CANDIDATE_BOOT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/BOOT.BIN"
RUNTIME = ROOT / "workspace/reports/prinny1_v7_14_22_runtime_test/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_23_byte_class_plan"
BASE_ISO_SHA256 = "fd460bbc0057a738712b2fcf7adaee985c13a156529fff5179e7e6a54cc77510"
CANDIDATE_BOOT_SHA256 = "97cbc41bd5617d1076b6eacc5907fb4edc85babcd433d65992b5b9d881ab73e6"
RANGES = (
    ("BYTE-CLASS-A", 0x9599C, 8, "unsigned_multibyte_lead_classification"),
    ("BYTE-CLASS-B", 0x959B0, 12, "f0_f5_multibyte_range_classification"),
)
EXCLUDED_PARSER_STEPS = (("PARSER-STEP-A", 0x957B4, 4), ("PARSER-STEP-B", 0x95814, 4))


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> int:
    for path in (BASE_ISO, CANDIDATE_BOOT, RUNTIME):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(BASE_ISO) != BASE_ISO_SHA256 or sha256_file(CANDIDATE_BOOT) != CANDIDATE_BOOT_SHA256:
        raise ValueError("V22 ISO 또는 후보 BOOT 해시가 다릅니다.")
    runtime = json.loads(RUNTIME.read_text(encoding="utf-8"))
    if runtime.get("status") != "runtime_blocker_byte_class_diagnostic_required" or runtime.get("final_verdict") != "BLOCKER":
        raise ValueError("V22 런타임 근거가 BYTE-CLASS 진단을 요구하지 않습니다.")
    base = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    candidate = CANDIDATE_BOOT.read_bytes()
    if len(base) != len(candidate):
        raise ValueError("BOOT 크기가 다릅니다.")
    patched = bytearray(base)
    rows = []
    declared: set[int] = set()
    for sequence, (logical_id, offset, size, purpose) in enumerate(RANGES, 1):
        before, after = base[offset:offset + size], candidate[offset:offset + size]
        if len(before) != size or before == after:
            raise ValueError(f"BYTE-CLASS Expected Write 입력 오류: {logical_id}")
        patched[offset:offset + size] = after
        declared.update(offset + i for i, (a, b) in enumerate(zip(before, after)) if a != b)
        rows.append({
            "sequence": sequence, "layer": "PSP_GAME/SYSDIR/BOOT.BIN", "logical_id": logical_id,
            "target": "PSP_GAME/SYSDIR/BOOT.BIN", "offset_hex": f"0x{offset:X}", "write_span": size,
            "expected_before_hex": before.hex().upper(), "write_after_hex": after.hex().upper(),
            "change_kind": purpose, "wording_changed": "no", "expected_write_confirmed": "yes",
        })
    actual = {i for i, pair in enumerate(zip(base, patched)) if pair[0] != pair[1]}
    if actual != declared:
        raise ValueError("BYTE-CLASS 실제 변경 집합 오류")
    for logical_id, offset, size in EXCLUDED_PARSER_STEPS:
        if patched[offset:offset + size] != base[offset:offset + size]:
            raise ValueError(f"PARSER-STEP 유입: {logical_id}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    writes = OUTPUT / "expected_write_confirmed.csv"
    with writes.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    report = {
        "format": "prinny1_v7_14_23_byte_class_plan_v1", "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {"base_iso": str(BASE_ISO), "base_iso_sha256": sha256_file(BASE_ISO), "candidate_boot_sha256": sha256_file(CANDIDATE_BOOT), "runtime_report_sha256": sha256_file(RUNTIME)},
        "verified": {"expected_write_count": len(rows), "actual_changed_bytes": len(actual), "parser_step_excluded_count": len(EXCLUDED_PARSER_STEPS)},
        "checks": {"v22_system_start_font_text_untouched": True, "byte_class_ranges_only": True, "parser_step_ranges_excluded": True, "translation_wording_changed": False, "iso_created": False},
        "preflight": {"patched_boot_sha256": sha256_bytes(bytes(patched))},
        "artifacts": {"expected_writes": str(writes), "expected_writes_sha256": sha256_file(writes)},
        "status": "expected_writes_confirmed_independent_review_required", "final_verdict": "PASS",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"BYTE-CLASS Expected Writes: {len(rows)}")
    print(f"actual changed bytes: {len(actual)}")
    print("PARSER-STEP imported: 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
