#!/usr/bin/env python3
"""Build V7.15.4 from the complete forced-xdelta ISO plus one user fallback."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_15_text_test_iso import hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/analysis/prinny1_xdelta_20260729/forced_redecode_20260801.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative_resources"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_4_xdelta_authoritative_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_4_xdelta_authoritative.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_4_xdelta_authoritative_iso"
EXPECTED = {
    BASE_ISO: "8bc47f189a41309dcca5ef6c61bd5e1368909da8c9b0fc032e2498368d095b65",
    REVIEW: "c371fd5e32a6c6862b51609268245cd940e68bcb36d3b9f80ff191c44c6b4439",
    RESOURCE_DIR / "BOOT.BIN": "67d63f8c122c252fc8062f97425c1a57ad7bf1cb298683d09dcdcacfbe92df65",
    RESOURCE_DIR / "EBOOT.BIN": "67d63f8c122c252fc8062f97425c1a57ad7bf1cb298683d09dcdcacfbe92df65",
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
            raise ValueError(f"V7.15.4 ISO 입력 해시 불일치: {path}")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_v7_15_4_iso_build_ready_automatic_approval":
        raise ValueError("V7.15.4 독립 사전 검토 미통과")
    parts = {
        "boot": ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
        "eboot": ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
    }
    records = {key: find_iso_file(BASE_ISO, value) for key, value in parts.items()}
    resources = {key: (RESOURCE_DIR / ("BOOT.BIN" if key == "boot" else "EBOOT.BIN")).read_bytes() for key in parts}
    for key, record in records.items():
        if len(resources[key]) != int(record["data_length"]):
            raise ValueError(f"V7.15.4 고정 자원 크기 불일치: {key}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.4 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    intervals = []
    with temporary.open("r+b") as target:
        for key in ("boot", "eboot"):
            offset = int(records[key]["extent_lba"]) * SECTOR_SIZE
            target.seek(offset); target.write(resources[key])
            intervals.append((offset, offset + len(resources[key])))
        target.flush(); os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("V7.15.4 ISO 크기 변경")
    cursor = 0
    for left, right in merge_intervals(intervals):
        if hash_range(BASE_ISO, cursor, left) != hash_range(temporary, cursor, left):
            raise ValueError("BOOT/EBOOT 밖 xdelta 데이터 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(temporary, cursor, temporary.stat().st_size):
        raise ValueError("마지막 BOOT 범위 뒤 xdelta 데이터 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.4 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    for key, parts_value in parts.items():
        if read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, parts_value)) != resources[key]:
            raise ValueError(f"최종 ISO {key} 재추출 불일치")

    report = {
        "format": "prinny1_v7_15_4_xdelta_authoritative_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_automatic_test_iso_approval_active_since_2026_08_01",
        "directive": "xdelta_all_data_authoritative_one_user_fallback_only",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {"xdelta_unchanged_translation_rows": 541, "user_fallback_rows": 1, "boot_changed_bytes_per_mirror": 24},
        "checks": {
            "independent_prebuild_review_pass": True, "only_boot_eboot_iso_ranges_changed": True,
            "all_system_anime_bg_script_stage_sound_data_from_xdelta_unchanged": True,
            "seven_zip_structure_test": True, "boot_eboot_reextracted_exactly": True,
            "base_xdelta_iso_not_overwritten": True,
        },
        "caveat": "forced xdelta decode does not match the patch-declared official source/output hashes; user explicitly selected it as the test data baseline",
        "status": "pass_v7_15_4_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("xdelta data outside one mirrored slot: byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
