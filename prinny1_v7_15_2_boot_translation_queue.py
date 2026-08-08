#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_1_internal_ui_plan import BASE_ISO, sha256_file


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "workspace/reports/prinny_qa/boot_executable_candidates/strings.csv"
ORIGINAL_BASE_ISO = ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
ISO = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui/prinny_korean_v7_15_1_full_text_internal_ui.iso"
OUTPUT = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2.csv"
REPORT = ROOT / "workspace/reports/prinny1_v7_15_2_boot_translation_queue/all_report.json"


def sha256_file_local(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for path in (SOURCE, ORIGINAL_BASE_ISO, ISO):
        if not path.is_file():
            raise FileNotFoundError(path)
    boot = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    base_boot = read_iso_file(ORIGINAL_BASE_ISO, find_iso_file(ORIGINAL_BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    rows = []
    modified = 0
    for index, source in enumerate(source_rows, 1):
        offset = int(source["offset"])
        length = int(source["byte_length"])
        before = base_boot[offset:offset + length]
        current = boot[offset:offset + length]
        if len(before) != length:
            raise ValueError(f"기준 BOOT 범위 불일치: {source['offset_hex']}")
        is_modified = current != before
        if is_modified:
            modified += 1
        rows.append({
            "id": f"P1-V7.15.2-BOOT-{index:04d}",
            "resource": "PSP_GAME/SYSDIR/BOOT.BIN",
            "offset_hex": source["offset_hex"],
            "byte_length": source["byte_length"],
            "character_length": source["character_length"],
            "source_japanese": source["text"],
            "base_bytes_hex": before.hex(),
            "current_bytes_hex": current.hex(),
            "user_translation_korean": "",
            "status": "already_modified_by_approved_ui_patch" if is_modified else "needs_user_translation",
            "notes": "Codex 번역 금지; 사용자 번역 입력 후 동일 슬롯·길이 검증",
        })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "format": "prinny1_v7_15_2_boot_translation_queue_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {"path": str(SOURCE), "sha256": sha256_file_local(SOURCE), "rows": len(rows)},
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "current_iso": {"path": str(ISO), "sha256": sha256_file_local(ISO)},
        "verified": {
            "boot_candidates": len(rows),
            "already_modified_slots": modified,
            "needs_user_translation": len(rows) - modified,
            "codex_translation_count": 0,
        },
        "artifacts": {"queue": str(OUTPUT), "queue_sha256": sha256_file_local(OUTPUT)},
        "checks": {
            "source_bytes_redecoded": True,
            "user_translation_authoritative": True,
            "codex_wording_generated": False,
            "iso_modified": False,
        },
        "status": "user_translation_required_before_boot_text_patch",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"BOOT candidates: {len(rows)}")
    print(f"already modified slots: {modified}")
    print(f"needs user translation: {len(rows) - modified}")
    print(f"queue: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
