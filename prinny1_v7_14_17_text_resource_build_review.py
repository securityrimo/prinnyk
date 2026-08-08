#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "workspace/build/prinny1_v7_14_16_text_resources"
BUILD = ROOT / "workspace/build/prinny1_v7_14_17_text_resources"
BUILD_REPORT = ROOT / "workspace/reports/prinny1_v7_14_17_text_resource_build/all_report.json"
CODE_WRITES = ROOT / "workspace/reports/prinny1_v7_14_17_boot_decoder_plan/expected_write_confirmed.csv"
V16_WRITES = ROOT / "workspace/reports/prinny1_v7_14_16_text_test_iso/sealed_expected_writes.csv"
SEALED = ROOT / "workspace/reports/prinny1_v7_14_17_text_resource_build/sealed_expected_writes.csv"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_17_text_resource_build_review"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    names = ("BOOT.BIN", "start.dat", "start.lzs", "SYSTEM.DAT")
    for path in ([SOURCE / name for name in names] + [BUILD / name for name in names]
                 + [BUILD_REPORT, CODE_WRITES, V16_WRITES, SEALED]):
        if not path.is_file():
            raise FileNotFoundError(path)
    build_report = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if build_report.get("status") != "pass_independent_resource_review_required":
        raise ValueError("자원 빌드 상태가 독립 검토 대기가 아닙니다.")
    for name in names:
        if sha256_file(BUILD / name) != build_report["outputs"][name]["sha256"]:
            raise ValueError(f"출력 해시 불일치: {name}")
    for name in ("start.dat", "start.lzs", "SYSTEM.DAT"):
        if (SOURCE / name).read_bytes() != (BUILD / name).read_bytes():
            raise ValueError(f"V16에서 바뀌면 안 되는 자원 변경: {name}")

    source_boot = (SOURCE / "BOOT.BIN").read_bytes()
    output_boot = (BUILD / "BOOT.BIN").read_bytes()
    simulated = bytearray(source_boot)
    declared: set[int] = set()
    code_rows = read_csv(CODE_WRITES)
    for row in code_rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if simulated[offset:offset + len(before)] != before:
            raise ValueError(f"독립 before 불일치: {row['logical_id']}")
        simulated[offset:offset + len(after)] = after
        declared.update(offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if bytes(simulated) != output_boot:
        raise ValueError("독립 모의 BOOT와 출력 BOOT 불일치")
    actual = {i for i, pair in enumerate(zip(source_boot, output_boot)) if pair[0] != pair[1]}
    if actual != declared or len(actual) != 167:
        raise ValueError("독립 BOOT 변경 범위 불일치")
    v16_rows, sealed_rows = read_csv(V16_WRITES), read_csv(SEALED)
    if len(v16_rows) != 13 or len(code_rows) != 10 or len(sealed_rows) != 23:
        raise ValueError("결합 봉인 행 수 오류")
    if sealed_rows[:13] != v16_rows:
        raise ValueError("결합 봉인의 앞 13건이 V16 봉인과 다릅니다.")
    comparison_fields = (
        "layer", "logical_id", "target", "offset_hex", "write_span",
        "expected_before_hex", "write_after_hex", "change_kind", "expected_write_confirmed",
    )
    for sealed_row, code_row in zip(sealed_rows[13:], code_rows):
        if any(sealed_row[field] != code_row[field] for field in comparison_fields):
            raise ValueError(f"결합 코드 봉인 불일치: {code_row['logical_id']}")
        if sealed_row["wording_changed"] != code_row["translation_wording_changed"]:
            raise ValueError(f"결합 문구 변경 플래그 불일치: {code_row['logical_id']}")
    for row in v16_rows:
        if row["layer"] != "PSP_GAME/SYSDIR/BOOT.BIN":
            continue
        offset = int(row["offset_hex"], 0)
        after = bytes.fromhex(row["write_after_hex"])
        if output_boot[offset:offset + len(after)] != after:
            raise ValueError(f"사용자 문구 보존 실패: {row['logical_id']}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "prinny1_v7_14_17_text_resource_build_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verified": {"combined_expected_write_count": len(sealed_rows), "new_code_write_count": len(code_rows),
                     "boot_changed_bytes_from_v16": len(actual), "boot_sha256": sha256_file(BUILD / "BOOT.BIN")},
        "checks": {"fresh_inputs_reopened": True, "independent_simulation_equals_output": True,
                   "actual_boot_changes_equal_declared": True, "other_three_resources_byte_identical": True,
                   "all_v16_user_boot_writes_preserved": True, "combined_manifest_exact": True,
                   "translation_wording_changed": False, "iso_created": False},
        "status": "pass_test_iso_build_ready_user_approval_required",
        "final_verdict": "PASS",
    }
    report_path = OUTPUT / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.14.17 resource independent review: PASS")
    print("combined Expected Writes: 23")
    print("ISO created: no")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
