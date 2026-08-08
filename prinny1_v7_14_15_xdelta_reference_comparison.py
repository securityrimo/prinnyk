#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from prinny1_v7_14_15_xdelta_import_audit import (
    CANDIDATE_ISO,
    CURRENT_ISO,
    ORIGINAL_ISO,
    XDELTA,
    iso_blobs,
    record_blob,
    record_map,
    sha256_file,
    start_from_system,
)


ROOT = Path(__file__).resolve().parent
QA_ROWS = ROOT / "workspace/reports/prinny_qa/qa_rows.csv"
BOOT_PLAN = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_boot_translation_plan"
    / "expected_write_confirmed.csv"
)
IMPORT_AUDIT = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_xdelta_import_audit"
    / "all_report.json"
)
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_15_xdelta_reference_comparison"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def count_candidate_udc_pairs(blob: bytes) -> int:
    count = 0
    index = 0
    while index + 1 < len(blob):
        if 0xF0 <= blob[index] <= 0xF5 and 0x40 <= blob[index + 1] <= 0xFF:
            count += 1
            index += 2
        else:
            index += 1
    return count


def classify_slot(original: bytes, current: bytes, candidate: bytes) -> str:
    current_changed = current != original
    candidate_changed = candidate != original
    if current == candidate:
        return "exact_same_bytes"
    if not current_changed and candidate_changed:
        return "candidate_only_change_review_for_missing_current_text"
    if current_changed and not candidate_changed:
        return "current_only_change_preserve"
    if current_changed and candidate_changed:
        return "both_changed_different_encoding_or_wording_reference_only"
    return "all_unchanged"


def main() -> int:
    for path in (XDELTA, ORIGINAL_ISO, CURRENT_ISO, CANDIDATE_ISO, QA_ROWS, BOOT_PLAN, IMPORT_AUDIT):
        if not path.is_file():
            raise FileNotFoundError(path)

    import_audit = json.loads(IMPORT_AUDIT.read_text(encoding="utf-8"))
    if import_audit["decision"]["safe_result"] != "candidate_resources_extracted_for_reference_only":
        raise ValueError("xdelta 후보가 참고 전용 상태로 봉인되지 않았습니다.")

    iso_data = {
        "original": iso_blobs(ORIGINAL_ISO),
        "current": iso_blobs(CURRENT_ISO),
        "candidate": iso_blobs(CANDIDATE_ISO),
    }
    archives = {}
    records = {}
    for label in ("original", "current", "candidate"):
        _start, archive, _meta = start_from_system(
            iso_data[label]["system"], f"{label}!/start.dat"
        )
        archives[label] = archive
        records[label] = record_map(archive)

    qa_output: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for row in read_csv(QA_ROWS):
        key = row["resource"].casefold()
        if any(key not in records[label] for label in records):
            skipped_rows.append({"id": row["id"], "resource": row["resource"], "reason": "resource_missing"})
            continue
        offset = int(row["offset"], 0)
        capacity = int(row["capacity_bytes"])
        blobs = {
            label: record_blob(archives[label], records[label][key])
            for label in records
        }
        if any(offset < 0 or offset + capacity > len(blob) for blob in blobs.values()):
            skipped_rows.append({"id": row["id"], "resource": row["resource"], "reason": "slot_out_of_range"})
            continue
        slots = {label: blob[offset:offset + capacity] for label, blob in blobs.items()}
        classification = classify_slot(slots["original"], slots["current"], slots["candidate"])
        qa_output.append(
            {
                "id": row["id"],
                "resource": row["resource"],
                "offset": row["offset"],
                "capacity_bytes": capacity,
                "current_status": row["status"],
                "classification": classification,
                "current_changed_from_original": "yes" if slots["current"] != slots["original"] else "no",
                "candidate_changed_from_original": "yes" if slots["candidate"] != slots["original"] else "no",
                "candidate_equals_current": "yes" if slots["candidate"] == slots["current"] else "no",
                "candidate_udc_pair_count": count_candidate_udc_pairs(slots["candidate"]),
                "original_slot_sha256": sha256_bytes(slots["original"]),
                "current_slot_sha256": sha256_bytes(slots["current"]),
                "candidate_slot_sha256": sha256_bytes(slots["candidate"]),
                "action": (
                    "user_translation_review_queue"
                    if classification == "candidate_only_change_review_for_missing_current_text"
                    else "preserve_current"
                    if classification == "current_only_change_preserve"
                    else "reference_only_no_byte_import"
                ),
            }
        )

    boot_output: list[dict[str, Any]] = []
    for row in read_csv(BOOT_PLAN):
        offset = int(row["offset_hex"], 0)
        length = int(row["write_span"])
        slots = {
            label: iso_data[label]["boot"][offset:offset + length]
            for label in iso_data
        }
        classification = classify_slot(slots["original"], slots["current"], slots["candidate"])
        boot_output.append(
            {
                "logical_id": row["logical_id"],
                "group_id": row["group_id"],
                "offset_hex": row["offset_hex"],
                "write_length": length,
                "classification": classification,
                "candidate_changed_from_original": "yes" if slots["candidate"] != slots["original"] else "no",
                "candidate_equals_planned_after": "yes" if slots["candidate"] == bytes.fromhex(row["write_after_hex"]) else "no",
                "candidate_udc_pair_count": count_candidate_udc_pairs(slots["candidate"]),
                "action": "keep_sealed_v7_14_15_boot_write_xdelta_reference_only",
            }
        )

    qa_counts = Counter(row["classification"] for row in qa_output)
    boot_counts = Counter(row["classification"] for row in boot_output)
    queue_rows = [
        row for row in qa_output
        if row["classification"] == "candidate_only_change_review_for_missing_current_text"
    ]

    OUTPUT.mkdir(parents=True, exist_ok=True)
    qa_path = OUTPUT / "text_slot_comparison.csv"
    queue_path = OUTPUT / "user_translation_review_queue.csv"
    boot_path = OUTPUT / "boot_expected_write_comparison.csv"
    qa_fields = list(qa_output[0]) if qa_output else ["id"]
    write_csv(qa_path, qa_output, qa_fields)
    write_csv(queue_path, queue_rows, qa_fields)
    write_csv(boot_path, boot_output, list(boot_output[0]) if boot_output else ["logical_id"])

    report = {
        "format": "prinny1_v7_14_15_xdelta_reference_comparison_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "policy": {
            "xdelta_role": "reference_only_not_build_base",
            "exact_source_iso_required": False,
            "candidate_bytes_directly_imported": False,
            "candidate_translation_wording_adopted": False,
            "translation_wording_generated_or_changed_by_codex": False,
            "current_prinnyname_change_preserved": True,
            "images_applied": False,
            "final_iso_created": False,
        },
        "inputs": {
            "xdelta_sha256": sha256_file(XDELTA),
            "original_iso_sha256": sha256_file(ORIGINAL_ISO),
            "current_iso_sha256": sha256_file(CURRENT_ISO),
            "candidate_iso_sha256": sha256_file(CANDIDATE_ISO),
            "qa_rows_sha256": sha256_file(QA_ROWS),
            "boot_plan_sha256": sha256_file(BOOT_PLAN),
            "import_audit_sha256": sha256_file(IMPORT_AUDIT),
        },
        "text_slot_comparison": {
            "path": str(qa_path),
            "sha256": sha256_file(qa_path),
            "row_count": len(qa_output),
            "skipped_count": len(skipped_rows),
            "classification_counts": dict(sorted(qa_counts.items())),
        },
        "user_translation_review_queue": {
            "path": str(queue_path),
            "sha256": sha256_file(queue_path),
            "row_count": len(queue_rows),
            "meaning": "xdelta 후보에서는 바뀌었지만 현재판 슬롯은 원본과 같은 텍스트 위치",
        },
        "boot_comparison": {
            "path": str(boot_path),
            "sha256": sha256_file(boot_path),
            "row_count": len(boot_output),
            "classification_counts": dict(sorted(boot_counts.items())),
        },
        "reference_findings": {
            "candidate_text_font_coupling": import_audit["font_coupling"],
            "candidate_changed_start_resources": import_audit["summary"]["candidate_changed_start_resources"],
            "current_only_resource_to_preserve": import_audit["summary"]["current_only_changed_resources_at_risk"],
            "deferred_internal_image_resources": import_audit["summary"]["deferred_internal_image_resources"],
            "deferred_internal_image_containers": import_audit["summary"]["deferred_internal_image_containers"],
        },
        "priority_application": [
            "현재 V7.14.15 사용자 번역·980자 폰트·12개 Expected Write를 1순위로 유지한다.",
            "후보만 변경된 QA 슬롯은 사용자 번역 검토 목록으로 보내고 후보 바이트를 직접 가져오지 않는다.",
            "현재판 고유 PrinnyName.dat와 화면 정렬 수정을 보존한다.",
            "후보 ANIME.DAT, BG.DAT, anime00.dat, number.txp는 텍스트 완료 후 내부 이미지 비교 자료로 사용한다.",
            "정확한 xdelta 원본 ISO나 공식 결과 ISO를 요구하지 않고 참고 분석을 계속한다.",
        ],
        "skipped_rows": skipped_rows,
        "status": "pass_reference_comparison_integrated_no_binary_writes",
    }
    report_path = OUTPUT / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"QA 텍스트 슬롯 비교: {len(qa_output)}")
    print(f"사용자 번역 검토 후보: {len(queue_rows)}")
    print(f"BOOT Expected Write 비교: {len(boot_output)}")
    print(f"후보 바이트 직접 적용: 0")
    print(f"이미지 적용: 0")
    print(f"보고서: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
