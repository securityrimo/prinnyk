#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "workspace/reports/prinny_qa/boot_executable_candidates/strings.csv"
BASE_ISO = ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
CURRENT_ISO = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui/prinny_korean_v7_15_1_full_text_internal_ui.iso"
OUTPUT = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_corrected.csv"
USER_ONLY = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_user_only.csv"
REJECTED = ROOT / "workspace/translations/pending_user/boot_executable_translation_rejected_v7_15_2.csv"
REPORT = ROOT / "workspace/reports/prinny1_v7_15_2_boot_translation_queue_corrected/all_report.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for path in (SOURCE, BASE_ISO, CURRENT_ISO):
        if not path.is_file():
            raise FileNotFoundError(path)
    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    current_boot = read_iso_file(CURRENT_ISO, find_iso_file(CURRENT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    source_rows = list(csv.DictReader(SOURCE.open(encoding="utf-8-sig", newline="")))
    accepted = []
    rejected = []
    for index, source in enumerate(source_rows, 1):
        offset = int(source["offset"])
        length = int(source["byte_length"])
        raw = base_boot[offset:offset + length]
        reasons = []
        if offset < 0xED000:
            reasons.append("legacy_scanner_low_address_outside_boot_text_block")
        try:
            decoded = raw.decode("shift_jis")
        except UnicodeDecodeError:
            decoded = ""
            reasons.append("not_valid_shift_jis")
        if decoded and decoded.encode("shift_jis") != raw:
            reasons.append("shift_jis_roundtrip_mismatch")
        if decoded.startswith("繝") or raw.startswith(b"\xE3\x83"):
            reasons.append("utf8_bytes_misread_as_shift_jis")
        if reasons:
            rejected.append({
                "original_id": f"P1-V7.15.2-BOOT-{index:04d}",
                "offset_hex": source["offset_hex"],
                "byte_length": source["byte_length"],
                "scanner_text": source["text"],
                "raw_bytes_hex": raw.hex(),
                "rejection_reason": ";".join(dict.fromkeys(reasons)),
            })
            continue
        current = current_boot[offset:offset + length]
        accepted.append({
            "id": f"P1-V7.15.2-BOOT-{len(accepted) + 1:04d}",
            "resource": "PSP_GAME/SYSDIR/BOOT.BIN",
            "offset_hex": source["offset_hex"],
            "byte_length": source["byte_length"],
            "character_length": str(len(decoded)),
            "source_japanese": decoded,
            "base_bytes_hex": raw.hex(),
            "current_bytes_hex": current.hex(),
            "user_translation_korean": "",
            "status": "already_modified_by_approved_ui_patch" if current != raw else "needs_user_translation",
            "notes": "실제 기준 BOOT 바이트에서 재디코드; Codex 번역 금지",
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(accepted[0]))
        writer.writeheader()
        writer.writerows(accepted)
    user_only = [row for row in accepted if row["status"] == "needs_user_translation"]
    with USER_ONLY.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(user_only[0]))
        writer.writeheader()
        writer.writerows(user_only)
    with REJECTED.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rejected[0]))
        writer.writeheader()
        writer.writerows(rejected)
    report = {
        "format": "prinny1_v7_15_2_boot_translation_queue_corrected_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {"path": str(SOURCE), "sha256": sha256_file(SOURCE), "rows": len(source_rows)},
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "current_iso": {"path": str(CURRENT_ISO), "sha256": sha256_file(CURRENT_ISO)},
        "verified": {
            "source_rows": len(source_rows),
            "accepted_normal_shiftjis_strings": len(accepted),
            "rejected_scanner_false_or_wrong_encoding": len(rejected),
            "accepted_needs_user_translation": sum(row["status"] == "needs_user_translation" for row in accepted),
            "accepted_already_modified": sum(row["status"] != "needs_user_translation" for row in accepted),
            "codex_translation_count": 0,
        },
        "artifacts": {
            "corrected_queue": str(OUTPUT),
            "corrected_queue_sha256": sha256_file(OUTPUT),
            "user_only_queue": str(USER_ONLY),
            "user_only_queue_sha256": sha256_file(USER_ONLY),
            "rejected_rows": str(REJECTED),
            "rejected_rows_sha256": sha256_file(REJECTED),
        },
        "checks": {
            "raw_shiftjis_roundtrip": True,
            "actual_source_spaces_preserved": True,
            "low_address_false_positives_separated": True,
            "utf8_misread_separated": True,
            "original_queue_overwritten": False,
            "codex_wording_generated": False,
        },
        "status": "corrected_user_translation_queue_ready",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"source rows: {len(source_rows)}")
    print(f"accepted normal strings: {len(accepted)}")
    print(f"rejected false/misread rows: {len(rejected)}")
    print(f"corrected queue: {OUTPUT}")
    print(f"user-only queue: {USER_ONLY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
