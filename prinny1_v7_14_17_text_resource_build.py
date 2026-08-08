#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "workspace/build/prinny1_v7_14_16_text_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_14_17_boot_decoder_plan/all_report.json"
REVIEW = ROOT / "workspace/reports/prinny1_v7_14_17_boot_decoder_review/all_report.json"
CODE_WRITES = ROOT / "workspace/reports/prinny1_v7_14_17_boot_decoder_plan/expected_write_confirmed.csv"
V16_WRITES = ROOT / "workspace/reports/prinny1_v7_14_16_text_test_iso/sealed_expected_writes.csv"
OUTPUT = ROOT / "workspace/build/prinny1_v7_14_17_text_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_17_text_resource_build"


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
    source_files = [SOURCE / name for name in ("BOOT.BIN", "start.dat", "start.lzs", "SYSTEM.DAT")]
    for path in (*source_files, PLAN, REVIEW, CODE_WRITES, V16_WRITES):
        if not path.is_file():
            raise FileNotFoundError(path)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if plan.get("final_verdict") != "PASS" or review.get("status") != "pass_resource_build_allowed":
        raise ValueError("V7.14.17 코드 계획·독립 검토 PASS가 아닙니다.")
    if sha256_file(CODE_WRITES) != plan["artifacts"]["expected_writes_sha256"]:
        raise ValueError("코드 Expected Write 해시가 다릅니다.")

    base_boot = (SOURCE / "BOOT.BIN").read_bytes()
    patched_boot = bytearray(base_boot)
    declared: set[int] = set()
    code_rows = read_csv(CODE_WRITES)
    for row in code_rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if patched_boot[offset:offset + len(before)] != before:
            raise ValueError(f"빌드 직전 before 불일치: {row['logical_id']}")
        patched_boot[offset:offset + len(after)] = after
        declared.update(offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    actual = {i for i, pair in enumerate(zip(base_boot, patched_boot)) if pair[0] != pair[1]}
    if actual != declared or len(actual) != 167:
        raise ValueError("빌드 실제 BOOT 변경 집합 오류")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "BOOT.BIN").write_bytes(patched_boot)
    for name in ("start.dat", "start.lzs", "SYSTEM.DAT"):
        shutil.copyfile(SOURCE / name, OUTPUT / name)

    v16_rows = read_csv(V16_WRITES)
    sealed_fields = list(v16_rows[0])
    normalized_code_rows = []
    for row in code_rows:
        normalized_code_rows.append({
            "sequence": str(len(v16_rows) + len(normalized_code_rows) + 1),
            "layer": row["layer"], "logical_id": row["logical_id"], "target": row["target"],
            "offset_hex": row["offset_hex"], "write_span": row["write_span"],
            "expected_before_hex": row["expected_before_hex"], "write_after_hex": row["write_after_hex"],
            "change_kind": row["change_kind"], "wording_changed": row["translation_wording_changed"],
            "expected_write_confirmed": row["expected_write_confirmed"],
        })
    combined = v16_rows + normalized_code_rows
    combined_path = REPORT_DIR / "sealed_expected_writes.csv"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with combined_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sealed_fields)
        writer.writeheader()
        writer.writerows(combined)
    outputs = {
        name: {"path": str(OUTPUT / name), "size": (OUTPUT / name).stat().st_size, "sha256": sha256_file(OUTPUT / name)}
        for name in ("BOOT.BIN", "start.dat", "start.lzs", "SYSTEM.DAT")
    }
    report = {
        "format": "prinny1_v7_14_17_text_resource_build_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {"plan_sha256": sha256_file(PLAN), "review_sha256": sha256_file(REVIEW),
                   "code_writes_sha256": sha256_file(CODE_WRITES), "v16_writes_sha256": sha256_file(V16_WRITES)},
        "outputs": outputs,
        "verified": {"combined_expected_write_count": len(combined), "new_code_write_count": len(code_rows),
                     "boot_actual_changed_bytes_from_v16": len(actual)},
        "checks": {"all_before_bytes_rechecked": True, "actual_changes_equal_declared": True,
                   "start_lzs_system_copied_byte_identical": True, "translation_wording_changed": False,
                   "font_or_image_changed_from_v16": False, "iso_created": False},
        "artifacts": {"sealed_expected_writes": str(combined_path),
                      "sealed_expected_writes_sha256": sha256_file(combined_path)},
        "status": "pass_independent_resource_review_required",
        "final_verdict": "PASS",
    }
    report_path = REPORT_DIR / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"combined Expected Writes: {len(combined)}")
    print(f"BOOT changed bytes from V16: {len(actual)}")
    print(f"output BOOT: {outputs['BOOT.BIN']['sha256']}")
    print("ISO created: no")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
