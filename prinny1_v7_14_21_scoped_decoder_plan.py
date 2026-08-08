#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
CANDIDATE_BOOT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/BOOT.BIN"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_21_scoped_decoder_plan"
BASE_ISO_SHA256 = "bd5168a461adfd4a41b8daf9dfe6037d7a9838ab2fc8ee0affd1e0f5521bd5b5"
BASE_BOOT_SHA256 = "3220c559596cc9e91db868284157622406110faa5e8c044c3824c8a138088415"
CANDIDATE_BOOT_SHA256 = "97cbc41bd5617d1076b6eacc5907fb4edc85babcd433d65992b5b9d881ab73e6"

RANGES = (
    ("HOOK-WIDTH-CALL", 0x613F4, 4, "redirect_character_width_call"),
    ("HOOK-WIDTH-RETURN", 0x61400, 4, "consume_character_count_without_divide_by_two"),
    ("HOOK-COPY-CALL", 0x6143C, 4, "redirect_bounded_copy_call"),
    ("HOOK-COPY-LENGTH", 0x61440, 4, "pass_byte_length_without_multiply_by_two"),
    ("HOOK-COPY-TERMINATOR", 0x61450, 4, "disable_redundant_terminator_store"),
    ("INJECT-MULTIBYTE-HELPERS", 0xCCE20, 0x154, "two_position_independent_leaf_helpers"),
)

EXCLUDED_GAMEPLAY_RANGES = (
    ("PARSER-STEP-A", 0x957B4, 4),
    ("PARSER-STEP-B", 0x95814, 4),
    ("BYTE-CLASS-A", 0x9599C, 8),
    ("BYTE-CLASS-B", 0x959B0, 12),
)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> int:
    for path in (BASE_ISO, CANDIDATE_BOOT):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(BASE_ISO) != BASE_ISO_SHA256:
        raise ValueError("V7.14.14 기준 ISO 해시가 다릅니다.")
    if sha256_file(CANDIDATE_BOOT) != CANDIDATE_BOOT_SHA256:
        raise ValueError("xdelta 참고 BOOT 해시가 다릅니다.")

    base = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    candidate = CANDIDATE_BOOT.read_bytes()
    if sha256_bytes(base) != BASE_BOOT_SHA256 or len(base) != len(candidate):
        raise ValueError("BOOT 계보 또는 크기가 다릅니다.")

    patched = bytearray(base)
    rows = []
    changed = set()
    for sequence, (logical_id, offset, size, purpose) in enumerate(RANGES, 1):
        before = base[offset:offset + size]
        after = candidate[offset:offset + size]
        if len(before) != size or len(after) != size or before == after:
            raise ValueError(f"Expected Write 입력 오류: {logical_id}")
        if logical_id == "INJECT-MULTIBYTE-HELPERS" and before != bytes(size):
            raise ValueError("보조 함수 주입 영역이 0이 아닙니다.")
        patched[offset:offset + size] = after
        changed.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
        rows.append({
            "sequence": sequence,
            "layer": "PSP_GAME/SYSDIR/BOOT.BIN",
            "logical_id": logical_id,
            "target": "PSP_GAME/SYSDIR/BOOT.BIN",
            "offset_hex": f"0x{offset:X}",
            "write_span": size,
            "expected_before_hex": before.hex().upper(),
            "write_after_hex": after.hex().upper(),
            "change_kind": purpose,
            "wording_changed": "no",
            "expected_write_confirmed": "yes",
        })
    actual = {index for index, pair in enumerate(zip(base, patched)) if pair[0] != pair[1]}
    if actual != changed or len(actual) != 151:
        raise ValueError(f"축소 디코더 실제 변경 집합 오류: {len(actual)}")
    for logical_id, offset, size in EXCLUDED_GAMEPLAY_RANGES:
        if patched[offset:offset + size] != base[offset:offset + size]:
            raise ValueError(f"게임플레이 회귀 범위가 유입됐습니다: {logical_id}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    writes = OUTPUT / "expected_write_confirmed.csv"
    with writes.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "format": "prinny1_v7_14_21_scoped_decoder_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "base_iso": str(BASE_ISO),
            "base_iso_sha256": sha256_file(BASE_ISO),
            "base_boot_sha256": sha256_bytes(base),
            "candidate_boot_sha256": sha256_file(CANDIDATE_BOOT),
        },
        "verified": {
            "expected_write_count": len(rows),
            "declared_span_bytes": sum(size for _, _, size, _ in RANGES),
            "actual_changed_bytes": len(actual),
            "excluded_gameplay_range_count": len(EXCLUDED_GAMEPLAY_RANGES),
        },
        "checks": {
            "v14_start_font_translation_untouched": True,
            "candidate_font_or_text_imported": False,
            "global_parser_and_byte_class_ranges_excluded": True,
            "translation_wording_changed": False,
            "iso_created": False,
        },
        "artifacts": {"expected_writes": str(writes), "expected_writes_sha256": sha256_file(writes)},
        "status": "expected_writes_confirmed_independent_review_required",
        "final_verdict": "PASS",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Expected Writes: {len(rows)}")
    print(f"actual changed bytes: {len(actual)}")
    print("global gameplay ranges imported: 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
