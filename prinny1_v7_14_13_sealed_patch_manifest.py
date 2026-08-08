#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.start_runtime import StartRuntimeArchive


ROOT = Path(__file__).resolve().parent
SOURCE_START = (
    ROOT
    / "workspace/build/prinny1_v7_14_9_prologue_full_punctuation/start.dat"
)
PLAN_PATHS = [
    ROOT
    / "workspace/reports/prinny1_v7_14_11_speaker_ligature_plan"
    / "expected_write_confirmed.csv",
    ROOT
    / "workspace/reports/prinny1_v7_14_12_screenshot_alignment_plan"
    / "expected_write_confirmed.csv",
]
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_13_sealed_patch_manifest"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes())


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    for required in [SOURCE_START, *PLAN_PATHS]:
        if not required.is_file():
            raise FileNotFoundError(required)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    source = SOURCE_START.read_bytes()
    archive = StartRuntimeArchive.from_bytes(source, source=str(SOURCE_START))
    records = {str(record.output_name).casefold(): record for record in archive.records}

    merged: list[dict[str, Any]] = []
    input_plans: list[dict[str, Any]] = []
    for plan_path in PLAN_PATHS:
        with plan_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise ValueError(f"빈 계획입니다: {plan_path}")
        input_plans.append({
            "path": str(plan_path),
            "sha256": sha256_file(plan_path),
            "write_count": len(rows),
        })
        for row in rows:
            merged.append({
                "sequence": 0,
                "source_plan": plan_path.parent.name,
                "group_id": row.get("group_id", ""),
                "logical_id": row.get("logical_id", ""),
                "target": row["target"],
                "offset_hex": row["offset_hex"],
                "expected_before_hex": row["expected_before_hex"],
                "write_after_hex": row["write_after_hex"],
                "write_length": len(bytes.fromhex(row["write_after_hex"])),
                "change_kind": row.get("change_kind", ""),
                "wording_changed": row.get("wording_changed", "no"),
                "user_wording_approval": row.get(
                    "user_wording_approval", "not_required_mechanical_only"
                ),
                "expected_write_confirmed": row.get(
                    "expected_write_confirmed", ""
                ),
            })

    merged.sort(key=lambda row: (str(row["target"]).casefold(), int(row["offset_hex"], 0)))
    for sequence, row in enumerate(merged, start=1):
        row["sequence"] = sequence

    seen: set[tuple[str, int]] = set()
    absolute_ranges: list[tuple[int, int, str]] = []
    for row in merged:
        target = str(row["target"])
        record = records.get(target.casefold())
        if record is None:
            raise ValueError(f"START 레코드가 없습니다: {target}")
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(str(row["expected_before_hex"]))
        after = bytes.fromhex(str(row["write_after_hex"]))
        if len(before) != len(after) or not before:
            raise ValueError(f"Expected Write 길이가 잘못됐습니다: {row['logical_id']}")
        key = (target.casefold(), offset)
        if key in seen:
            raise ValueError(f"중복 Expected Write입니다: {key}")
        seen.add(key)
        absolute_start = int(record.data_offset) + offset
        absolute_end = absolute_start + len(before)
        if absolute_end > int(record.end_offset):
            raise ValueError(f"레코드 경계를 벗어납니다: {row['logical_id']}")
        actual = source[absolute_start:absolute_end]
        if actual != before:
            raise ValueError(
                f"봉인 직전 before 불일치: {row['logical_id']} "
                f"expected={before.hex().upper()} actual={actual.hex().upper()}"
            )
        absolute_ranges.append((absolute_start, absolute_end, str(row["logical_id"])))

    absolute_ranges.sort()
    for left, right in zip(absolute_ranges, absolute_ranges[1:]):
        if left[1] > right[0]:
            raise ValueError(f"Expected Write 겹침: {left[2]} / {right[2]}")

    simulated = bytearray(source)
    declared_changed_offsets: set[int] = set()
    for row in merged:
        record = records[str(row["target"]).casefold()]
        start = int(record.data_offset) + int(row["offset_hex"], 0)
        after = bytes.fromhex(str(row["write_after_hex"]))
        before = bytes.fromhex(str(row["expected_before_hex"]))
        simulated[start:start + len(after)] = after
        declared_changed_offsets.update(
            start + index
            for index, (old, new) in enumerate(zip(before, after))
            if old != new
        )

    actual_changed_offsets = {
        index
        for index, (old, new) in enumerate(zip(source, simulated))
        if old != new
    }
    if actual_changed_offsets != declared_changed_offsets:
        raise ValueError("메모리 적용 변경 범위가 선언과 다릅니다.")
    if not actual_changed_offsets:
        raise ValueError("실제 변경 바이트가 0개입니다.")
    if len(simulated) != len(source):
        raise ValueError("START 크기가 변경됐습니다.")
    if any(str(row["wording_changed"]).casefold() not in {"", "no"} for row in merged):
        raise ValueError("승인되지 않은 번역 문구 변경이 포함됐습니다.")
    if any(str(row["expected_write_confirmed"]).casefold() != "yes" for row in merged):
        raise ValueError("미확정 Expected Write가 포함됐습니다.")

    write_csv(REPORT_DIR / "sealed_expected_writes.csv", merged)
    write_csv(REPORT_DIR / "confirmed_patch_plan.csv", merged)
    write_csv(REPORT_DIR / "expected_write_confirmed.csv", merged)
    manifest = {
        "format": "prinny1_v7_14_13_sealed_patch_manifest_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "policy": "docs/PRINNY1_PRIORITY_RULES_V2.md",
        "source": {
            "path": str(SOURCE_START),
            "size": len(source),
            "sha256": sha256(source),
        },
        "inputs": input_plans,
        "sealed_writes_csv": {
            "path": str(REPORT_DIR / "sealed_expected_writes.csv"),
            "sha256": sha256_file(REPORT_DIR / "sealed_expected_writes.csv"),
        },
        "write_count": len(merged),
        "changed_byte_count": len(actual_changed_offsets),
        "changed_resources": sorted({str(row["target"]) for row in merged}),
        "simulated_output": {
            "size": len(simulated),
            "sha256": sha256(bytes(simulated)),
            "file_written": False,
        },
        "checks": {
            "fresh_before_revalidation": True,
            "nonempty_expected_writes": True,
            "equal_before_after_lengths": True,
            "record_boundaries_valid": True,
            "non_overlapping_ranges": True,
            "actual_changes_equal_declared_changes": True,
            "source_size_preserved": True,
            "translation_wording_changed": False,
            "source_file_unchanged": sha256_file(SOURCE_START) == sha256(source),
            "iso_created": False,
        },
        "review": {
            "external_reviewers": "disabled_by_user",
            "codex_dual_validation": "required",
            "user_iso_build_approval": "required",
        },
        "status": "sealed_manifest_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"봉인 Expected Writes: {len(merged)}")
    print(f"실제 변경 예상 바이트: {len(actual_changed_offsets)}")
    print(f"변경 자원: {', '.join(manifest['changed_resources'])}")
    print(f"예상 START SHA-256: {manifest['simulated_output']['sha256']}")
    print("START/ISO 생성: 없음")
    print(f"보고서: {REPORT_DIR / 'all_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
