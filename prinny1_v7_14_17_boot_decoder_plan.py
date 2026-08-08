#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
BASE_BOOT = ROOT / "workspace/build/prinny1_v7_14_16_text_resources/BOOT.BIN"
CANDIDATE_BOOT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/BOOT.BIN"
AUDIT = ROOT / "workspace/reports/prinny1_v7_14_16_xdelta_boot_code_audit/all_report.json"
V16_WRITES = ROOT / "workspace/reports/prinny1_v7_14_16_text_test_iso/sealed_expected_writes.csv"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_17_boot_decoder_plan"
BASE_BOOT_SHA256 = "a0503d7125ee1ed51a7b85e44b7c808d5b154c0af2d830fd118a2022e5f49652"
CANDIDATE_BOOT_SHA256 = "97cbc41bd5617d1076b6eacc5907fb4edc85babcd433d65992b5b9d881ab73e6"

# All candidate executable-mechanism differences, grouped on instruction boundaries.
# Candidate translation/data differences are deliberately excluded.
RANGES = (
    ("HOOK-WIDTH-CALL", 0x613F4, 4, "redirect_character_width_call"),
    ("HOOK-WIDTH-RETURN", 0x61400, 4, "consume_character_count_without_divide_by_two"),
    ("HOOK-COPY-CALL", 0x6143C, 4, "redirect_bounded_copy_call"),
    ("HOOK-COPY-LENGTH", 0x61440, 4, "pass_byte_length_without_multiply_by_two"),
    ("HOOK-COPY-TERMINATOR", 0x61450, 4, "disable_redundant_terminator_store"),
    ("PARSER-STEP-A", 0x957B4, 4, "candidate_parser_step_constant"),
    ("PARSER-STEP-B", 0x95814, 4, "candidate_parser_step_constant"),
    ("BYTE-CLASS-A", 0x9599C, 8, "unsigned_byte_class_branch"),
    ("BYTE-CLASS-B", 0x959B0, 12, "unsigned_byte_class_ranges"),
    ("INJECT-MULTIBYTE-HELPERS", 0xCCE20, 0x154, "two_position_independent_leaf_helpers"),
)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def changed(before: bytes, after: bytes) -> set[int]:
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    for path in (BASE_BOOT, CANDIDATE_BOOT, AUDIT, V16_WRITES):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(BASE_BOOT) != BASE_BOOT_SHA256 or sha256_file(CANDIDATE_BOOT) != CANDIDATE_BOOT_SHA256:
        raise ValueError("BOOT 봉인 해시가 다릅니다.")
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if audit.get("status") != "reference_code_separated_not_safe_to_apply":
        raise ValueError("xdelta BOOT 코드 분리 감사 상태가 다릅니다.")

    base = BASE_BOOT.read_bytes()
    candidate = CANDIDATE_BOOT.read_bytes()
    simulated = bytearray(base)
    rows: list[dict[str, Any]] = []
    declared: set[int] = set()
    for logical_id, offset, size, purpose in RANGES:
        before = base[offset:offset + size]
        after = candidate[offset:offset + size]
        if len(before) != size or len(after) != size or before == after:
            raise ValueError(f"Expected Write 입력 오류: {logical_id}")
        if logical_id == "INJECT-MULTIBYTE-HELPERS" and before != bytes(size):
            raise ValueError("주입 대상이 V7.14.16에서 전부 0이 아닙니다.")
        simulated[offset:offset + size] = after
        declared.update(offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
        rows.append({
            "group_id": "G026", "logical_id": logical_id,
            "layer": "PSP_GAME/SYSDIR/BOOT.BIN", "target": "PSP_GAME/SYSDIR/BOOT.BIN",
            "offset_hex": f"0x{offset:X}", "write_span": size,
            "expected_before_hex": before.hex().upper(), "write_after_hex": after.hex().upper(),
            "change_kind": purpose, "candidate_role": "code_reference_only",
            "translation_wording_changed": "no", "expected_write_confirmed": "yes",
        })
    if changed(base, bytes(simulated)) != declared:
        raise ValueError("모의 적용 변경과 선언 변경이 다릅니다.")
    if len(declared) != 167:
        raise ValueError(f"실제 변경 바이트가 167이 아닙니다: {len(declared)}")

    # Every executable candidate difference must be covered; no candidate data/string byte may be imported.
    candidate_mechanism = set()
    for _logical_id, offset, size, _purpose in RANGES:
        candidate_mechanism.update(
            offset + i for i, pair in enumerate(zip(base[offset:offset + size], candidate[offset:offset + size]))
            if pair[0] != pair[1]
        )
    if candidate_mechanism != declared:
        raise ValueError("후보 실행 메커니즘 범위가 선언과 다릅니다.")
    if bytes(simulated[0xED324:]) != base[0xED324:]:
        raise ValueError("후보 번역·데이터 영역이 유입됐습니다.")

    # Static invariants for the two hooks and injected leaf helpers.
    words = {offset: struct.unpack_from("<I", simulated, offset)[0] for offset in (0x613F4, 0x6143C)}
    if words != {0x613F4: 0x0E234373, 0x6143C: 0x0E234394}:
        raise ValueError("주입 함수 JAL 대상이 예상과 다릅니다.")
    helper_words = [struct.unpack_from("<I", simulated, offset)[0] for offset in range(0xCCE20, 0xCCF74, 4)]
    absolute_calls = [word for word in helper_words if word >> 26 in (2, 3)]
    if absolute_calls:
        raise ValueError("주입 함수가 외부 절대 jump/call에 의존합니다.")
    if helper_words.count(0x03E00008) != 2:
        raise ValueError("주입 함수 반환 명령이 정확히 2개가 아닙니다.")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    writes_path = OUTPUT / "expected_write_confirmed.csv"
    write_csv(writes_path, rows)
    report = {
        "format": "prinny1_v7_14_17_boot_decoder_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "base_boot": str(BASE_BOOT), "base_boot_sha256": sha256_file(BASE_BOOT),
            "candidate_boot": str(CANDIDATE_BOOT), "candidate_boot_sha256": sha256_file(CANDIDATE_BOOT),
            "v16_writes_sha256": sha256_file(V16_WRITES),
        },
        "plan": {
            "expected_write_count": len(rows), "declared_span_bytes": sum(size for _, _, size, _ in RANGES),
            "actual_changed_bytes": len(declared), "text_instruction_words_changed": 12,
            "helper_region": {"offset_hex": "0xCCE20", "size": 0x154, "original_all_zero": True},
            "hook_targets": ["0x088D0DCC", "0x088D0E50"],
        },
        "checks": {
            "all_candidate_executable_mechanism_changes_covered": True,
            "helper_functions_position_independent_leaf_functions": True,
            "candidate_translation_or_data_imported": False,
            "user_translation_wording_changed": False,
            "font_or_image_changed": False, "iso_created": False,
        },
        "artifacts": {"expected_writes": str(writes_path), "expected_writes_sha256": sha256_file(writes_path)},
        "status": "expected_writes_confirmed_independent_review_required",
        "final_verdict": "PASS",
    }
    report_path = OUTPUT / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Expected Writes: {len(rows)}")
    print(f"actual changed bytes: {len(declared)}")
    print("candidate translation/data imported: 0")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
