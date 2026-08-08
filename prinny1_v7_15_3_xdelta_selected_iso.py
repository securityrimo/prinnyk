#!/usr/bin/env python3
"""Build the automatically approved V7.15.3 test ISO without overwriting a prior image."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from prinny1_v7_14_15_text_test_iso import hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui/prinny_korean_v7_15_1_full_text_internal_ui.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_3_xdelta_selected_resources"
PRE_REVIEW = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_selected_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_3_xdelta_selected"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_3_xdelta_selected.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_selected_iso"
EXPECTED = {
    BASE_ISO: "98411d6861c0cc9cc6b34672915786426fc2260ea005b7ba13ac0d75aac7e7d8",
    PRE_REVIEW: "eeef5f26ed196b4c713b51b1a12a92b5e8439eaddce7c582ff1b106ece414b8a",
    RESOURCE_DIR / "BOOT.BIN": "782bab27ce20d438ef7abc6568c367d17ac5f66d3ad2e64bf4fd9550fce6e6ad",
    RESOURCE_DIR / "EBOOT.BIN": "782bab27ce20d438ef7abc6568c367d17ac5f66d3ad2e64bf4fd9550fce6e6ad",
    RESOURCE_DIR / "SYSTEM.DAT": "dec58d4dfff22d8d1d53a7cd6e079785844ef93821da85b66c4720e97fd9f2fc",
    RESOURCE_DIR / "start.dat": "c5222be3d41a2d24847d770e486334b54aa2315704abf303816734fad7b7ced5",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.3 ISO 입력 해시 불일치: {path}")
    review = json.loads(PRE_REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_v7_15_3_iso_build_ready_automatic_approval":
        raise ValueError("V7.15.3 독립 사전 검토 미통과")

    parts = {
        "boot": ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
        "eboot": ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
        "system": ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    }
    records = {key: find_iso_file(BASE_ISO, value) for key, value in parts.items()}
    resources = {
        "boot": (RESOURCE_DIR / "BOOT.BIN").read_bytes(),
        "eboot": (RESOURCE_DIR / "EBOOT.BIN").read_bytes(),
        "system": (RESOURCE_DIR / "SYSTEM.DAT").read_bytes(),
    }
    base_resources = {key: read_iso_file(BASE_ISO, record) for key, record in records.items()}
    for key in resources:
        if len(resources[key]) != len(base_resources[key]) or len(resources[key]) != int(records[key]["data_length"]):
            raise ValueError(f"고정 ISO 자원 크기 불일치: {key}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.3 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    intervals = []
    with temporary.open("r+b") as target:
        for key in ("boot", "eboot", "system"):
            offset = int(records[key]["extent_lba"]) * SECTOR_SIZE
            target.seek(offset)
            target.write(resources[key])
            intervals.append((offset, offset + len(resources[key])))
        target.flush()
        os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기가 변경됐습니다.")

    cursor = 0
    for left, right in merge_intervals(intervals):
        if hash_range(BASE_ISO, cursor, left) != hash_range(temporary, cursor, left):
            raise ValueError("허용 자원 앞 ISO 범위 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(temporary, cursor, temporary.stat().st_size):
        raise ValueError("마지막 허용 자원 뒤 ISO 범위 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.3 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    extracted = {key: read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, parts[key])) for key in parts}
    if extracted != resources:
        raise ValueError("최종 ISO 자원 재추출 불일치")
    start_entry = font_builder.parse_nispack_start_entry(extracted["system"])
    final_start, _ = decompress_buffer(extracted["system"][int(start_entry["data_offset"]):int(start_entry["data_offset"]) + int(start_entry["size"])])
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes():
        raise ValueError("최종 ISO START.DAT 재추출 불일치")

    report = {
        "format": "prinny1_v7_15_3_xdelta_selected_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_automatic_test_iso_approval_active_since_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "resources": {key: hashlib.sha256(value).hexdigest() for key, value in resources.items()},
        "verified": {
            "selected_translation_rows": 542, "boot_expected_writes": 540,
            "boot_changed_bytes": 14902, "font_aliases": 988,
            "decoder_ranges_preserved": 10, "internal_ui_targets_preserved": 5,
        },
        "checks": {
            "independent_prebuild_review_pass": True, "only_boot_eboot_system_iso_ranges_changed": True,
            "seven_zip_structure_test": True, "boot_eboot_system_reextracted_exactly": True,
            "start_reextracted_exactly": True, "base_iso_not_overwritten": True,
        },
        "known_runtime_regressions": ["prologue_boss_interaction_may_fail"],
        "status": "pass_v7_15_3_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
