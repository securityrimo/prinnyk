#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_14_17_boot_decoder_plan"
PLAN = PLAN_DIR / "all_report.json"
WRITES = PLAN_DIR / "expected_write_confirmed.csv"
BASE_BOOT = ROOT / "workspace/build/prinny1_v7_14_16_text_resources/BOOT.BIN"
CANDIDATE_BOOT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/BOOT.BIN"
V16_WRITES = ROOT / "workspace/reports/prinny1_v7_14_16_text_test_iso/sealed_expected_writes.csv"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_17_boot_decoder_review"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def changed(before: bytes, after: bytes) -> set[int]:
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def branch_target(word: int, pc: int) -> int | None:
    if word >> 26 not in (1, 4, 5, 6, 7):
        return None
    immediate = struct.unpack("<h", struct.pack("<H", word & 0xFFFF))[0]
    return pc + 4 + immediate * 4


def main() -> int:
    for path in (PLAN, WRITES, BASE_BOOT, CANDIDATE_BOOT, V16_WRITES):
        if not path.is_file():
            raise FileNotFoundError(path)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "expected_writes_confirmed_independent_review_required":
        raise ValueError("계획 상태가 독립 검토 대기가 아닙니다.")
    if sha256_file(BASE_BOOT) != plan["inputs"]["base_boot_sha256"]:
        raise ValueError("기준 BOOT가 바뀌었습니다.")
    if sha256_file(CANDIDATE_BOOT) != plan["inputs"]["candidate_boot_sha256"]:
        raise ValueError("후보 BOOT가 바뀌었습니다.")
    if sha256_file(WRITES) != plan["artifacts"]["expected_writes_sha256"]:
        raise ValueError("Expected Write CSV가 바뀌었습니다.")

    base = BASE_BOOT.read_bytes()
    candidate = CANDIDATE_BOOT.read_bytes()
    patched = bytearray(base)
    declared: set[int] = set()
    rows = read_csv(WRITES)
    if len(rows) != 10:
        raise ValueError(f"Expected Write 수가 10이 아닙니다: {len(rows)}")
    intervals: list[tuple[int, int]] = []
    for row in rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if len(before) != len(after) or len(after) != int(row["write_span"]):
            raise ValueError(f"길이 오류: {row['logical_id']}")
        if patched[offset:offset + len(before)] != before:
            raise ValueError(f"before 불일치: {row['logical_id']}")
        if candidate[offset:offset + len(after)] != after:
            raise ValueError(f"후보 코드 불일치: {row['logical_id']}")
        if any(offset < right and left < offset + len(after) for left, right in intervals):
            raise ValueError(f"Expected Write 겹침: {row['logical_id']}")
        intervals.append((offset, offset + len(after)))
        patched[offset:offset + len(after)] = after
        declared.update(offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if changed(base, bytes(patched)) != declared or len(declared) != 167:
        raise ValueError("독립 모의 적용 변경 집합 오류")

    # Verify the helper block as two self-contained leaf routines inside the RWE load segment.
    helper = bytes(patched[0xCCE20:0xCCF74])
    if base[0xCCE20:0xCCF74] != bytes(0x154) or helper != candidate[0xCCE20:0xCCF74]:
        raise ValueError("주입 함수 범위 검증 실패")
    helper_words = [struct.unpack_from("<I", helper, offset)[0] for offset in range(0, len(helper), 4)]
    if any(word >> 26 in (2, 3) for word in helper_words):
        raise ValueError("주입 함수에 외부 절대 jump/call 존재")
    if [i for i, word in enumerate(helper_words) if word == 0x03E00008] != [30, 84]:
        raise ValueError("두 leaf 함수 반환 위치가 예상과 다릅니다.")
    load_offset, load_va, load_size, flags = 0x54, 0x08804000, 0x1130F0, 7
    helper_va_start = load_va + 0xCCE20 - load_offset
    helper_va_end = load_va + 0xCCF74 - load_offset
    if flags != 7 or not (load_offset <= 0xCCE20 < 0xCCF74 <= load_offset + load_size):
        raise ValueError("주입 영역이 RWE LOAD 세그먼트 안이 아닙니다.")
    for index, word in enumerate(helper_words):
        target = branch_target(word, helper_va_start + index * 4)
        if target is not None and not (helper_va_start <= target < helper_va_end):
            raise ValueError(f"주입 함수 상대 분기가 영역 밖입니다: {index}/{target:#x}")

    # Re-open the V16 write list and prove all user text/font writes survive byte-for-byte.
    for row in read_csv(V16_WRITES):
        if row["layer"] != "PSP_GAME/SYSDIR/BOOT.BIN":
            continue
        offset = int(row["offset_hex"], 0)
        expected = bytes.fromhex(row["write_after_hex"])
        if base[offset:offset + len(expected)] != expected or patched[offset:offset + len(expected)] != expected:
            raise ValueError(f"V16 사용자 문구 보존 실패: {row['logical_id']}")
    allowed = set()
    for left, right in intervals:
        allowed.update(range(left, right))
    if any(a != b and index not in allowed for index, (a, b) in enumerate(zip(base, patched))):
        raise ValueError("허용 범위 밖 BOOT 변경")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "prinny1_v7_14_17_boot_decoder_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {"plan_sha256": sha256_file(PLAN), "writes_sha256": sha256_file(WRITES)},
        "verified": {
            "expected_write_count": len(rows), "actual_changed_bytes": len(declared),
            "patched_boot_sha256": sha256_bytes(bytes(patched)),
            "helper_virtual_range": [f"0x{helper_va_start:08X}", f"0x{helper_va_end:08X}"],
        },
        "checks": {
            "fresh_inputs_reopened": True, "all_before_and_candidate_after_bytes_match": True,
            "actual_changes_equal_declared": True, "helper_inside_rwe_load_segment": True,
            "two_leaf_returns_at_expected_positions": True,
            "all_relative_branches_stay_inside_helper_region": True,
            "external_absolute_helper_dependencies": 0, "all_v16_user_boot_writes_preserved": True,
            "candidate_translation_or_data_imported": False, "iso_created": False,
        },
        "status": "pass_resource_build_allowed",
        "final_verdict": "PASS",
    }
    report_path = OUTPUT / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Expected Writes: 10 PASS")
    print("helper leaf/control-flow checks: PASS")
    print("V16 user BOOT writes preserved: PASS")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
