#!/usr/bin/env python3
"""Validate the user-owned V7.15.2 BOOT translation queue without editing it."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_user_only.csv"
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
REPORT = ROOT / "workspace/reports/prinny1_v7_15_2_boot_translation_validation/all_report.json"
PLACEHOLDER = re.compile(r"%(?:\d+\$)?(?:0\d+)?[sd]")


def encode(text: str, mapping: dict[str, bytes]) -> bytes:
    out = bytearray()
    for char in text:
        out.extend(mapping[char] if char in mapping else char.encode("cp932"))
    return bytes(out)


def find_missing_characters(text: str, mapping: dict[str, bytes]) -> list[str]:
    missing = []
    for char in text:
        if char in mapping:
            continue
        try:
            char.encode("cp932")
        except UnicodeEncodeError:
            missing.append(char)
    return missing


def main() -> int:
    rows = list(csv.DictReader(QUEUE.open(encoding="utf-8-sig", newline="")))
    document = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    mapping = {str(item["hangul"]): bytes.fromhex(str(item["sjis"])) for item in document["allocations"]}
    errors: list[dict[str, object]] = []
    missing = Counter()
    overflow = 0
    placeholder = 0
    encoded = 0
    for row in rows:
        error: dict[str, object] = {
            "id": row["id"], "offset_hex": row["offset_hex"],
            "source_japanese": row["source_japanese"],
            "user_translation_korean": row["user_translation_korean"],
            "slot_bytes": int(row["byte_length"]),
        }
        source_placeholders = PLACEHOLDER.findall(row["source_japanese"])
        translation_placeholders = PLACEHOLDER.findall(row["user_translation_korean"])
        if source_placeholders != translation_placeholders:
            placeholder += 1
            errors.append({
                "id": row["id"], "offset_hex": row["offset_hex"], "kind": "placeholder_mismatch",
                "source_japanese": row["source_japanese"], "user_translation_korean": row["user_translation_korean"],
                "source": source_placeholders,
                "translation": translation_placeholders,
            })
        missing_in_row = find_missing_characters(row["user_translation_korean"], mapping)
        if missing_in_row:
            missing.update(missing_in_row)
            error["kind"] = "missing_font_mapping"
            error["characters"] = sorted(set(missing_in_row))
            errors.append(error)
            continue
        payload = encode(row["user_translation_korean"], mapping)
        encoded += 1
        if len(payload) + 2 > int(row["byte_length"]):
            overflow += 1
            error["kind"] = "slot_overflow"
            error["encoded_bytes_with_nul"] = len(payload) + 2
            error["slot_bytes"] = int(row["byte_length"])
            errors.append(error)
    status = "ready_for_patch_planning" if not errors else "blocked_until_user_translation_corrections"
    report = {
        "format": "prinny1_v7_15_2_boot_translation_validation_v1",
        "queue": str(QUEUE), "row_count": len(rows), "encoded_row_count": encoded,
        "slot_overflow_rows": overflow, "missing_font_mapping_rows": sum(1 for e in errors if e["kind"] == "missing_font_mapping"),
        "placeholder_mismatch_rows": placeholder, "missing_characters": dict(sorted(missing.items())),
        "errors": errors,
        "status": status,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("row_count", "encoded_row_count", "slot_overflow_rows", "missing_font_mapping_rows", "placeholder_mismatch_rows", "status")}, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
