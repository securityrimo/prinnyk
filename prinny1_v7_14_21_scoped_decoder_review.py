#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_21_scoped_decoder_plan import (
    BASE_BOOT_SHA256,
    BASE_ISO,
    CANDIDATE_BOOT,
    EXCLUDED_GAMEPLAY_RANGES,
    RANGES,
)
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_14_21_scoped_decoder_plan"
PLAN = PLAN_DIR / "all_report.json"
WRITES = PLAN_DIR / "expected_write_confirmed.csv"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_21_scoped_decoder_review"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> int:
    for path in (PLAN, WRITES, BASE_ISO, CANDIDATE_BOOT):
        if not path.is_file():
            raise FileNotFoundError(path)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("final_verdict") != "PASS" or sha256_file(WRITES) != plan["artifacts"]["expected_writes_sha256"]:
        raise ValueError("계획 또는 봉인 CSV가 다릅니다.")
    base = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    candidate = CANDIDATE_BOOT.read_bytes()
    if sha256_bytes(base) != BASE_BOOT_SHA256:
        raise ValueError("기준 BOOT 해시가 다릅니다.")
    with WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_ranges = {(logical_id, offset, size) for logical_id, offset, size, _ in RANGES}
    actual_ranges = {(row["logical_id"], int(row["offset_hex"], 0), int(row["write_span"])) for row in rows}
    if actual_ranges != expected_ranges or len(rows) != 6:
        raise ValueError("축소 범위가 독립 상수와 다릅니다.")
    patched = bytearray(base)
    declared = set()
    for row in rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if base[offset:offset + len(before)] != before or candidate[offset:offset + len(after)] != after:
            raise ValueError(f"before/candidate 불일치: {row['logical_id']}")
        patched[offset:offset + len(after)] = after
        declared.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    actual = {index for index, pair in enumerate(zip(base, patched)) if pair[0] != pair[1]}
    if actual != declared or len(actual) != 151:
        raise ValueError("독립 변경 집합 검증 실패")
    for logical_id, offset, size in EXCLUDED_GAMEPLAY_RANGES:
        if patched[offset:offset + size] != base[offset:offset + size]:
            raise ValueError(f"제외 범위 유입: {logical_id}")
    helper = bytes(patched[0xCCE20:0xCCF74])
    words = [struct.unpack_from("<I", helper, offset)[0] for offset in range(0, len(helper), 4)]
    if sum(word == 0x03E00008 for word in words) != 2 or any(word >> 26 in (2, 3) for word in words):
        raise ValueError("보조 함수 leaf 검증 실패")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "prinny1_v7_14_21_scoped_decoder_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {"plan_sha256": sha256_file(PLAN), "writes_sha256": sha256_file(WRITES)},
        "verified": {"expected_write_count": len(rows), "actual_changed_bytes": len(actual)},
        "checks": {
            "fresh_base_and_candidate_reopened": True,
            "actual_changes_equal_declared": True,
            "global_parser_and_byte_class_ranges_unchanged": True,
            "helper_two_leaf_no_absolute_calls": True,
            "v14_start_font_translation_untouched": True,
            "translation_wording_changed": False,
        },
        "status": "pass_diagnostic_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Scoped decoder independent review: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
