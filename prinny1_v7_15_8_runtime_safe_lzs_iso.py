#!/usr/bin/env python3
"""Build the V7.15.8 runtime-safe title/dialogue test ISO."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs_resources"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_8_runtime_safe_lzs_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_8_runtime_safe_lzs.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_8_runtime_safe_lzs_iso"
EXPECTED = {
    BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    RESOURCE_DIR / "SYSTEM.DAT": "5514a39827488f1103ba02bac0b38ff6e5624abfadb069137c6d8bbe17c7206d",
    RESOURCE_DIR / "start.dat": "50196d74ade8dc7ec187d4e85885df7e25ac325e1d3e298b09d91b3eab1b0215",
    RESOURCE_DIR / "Demo00.dat": "a7e870ad1a1561f5c57e8273689bcd5bebd8d2069eb6038f22866419dab23f26",
    RESOURCE_DIR / "anime00.dat": "e452f62e983038f25139e6c28d032cf1070e80a72f263eea1910598845b539cb",
    REVIEW: "748bcaa7a6fc18c48e35f8b366f3227d29dfd77fd1fdd5bd74e68f65c56d06c3",
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
            raise ValueError(f"V7.15.8 ISO 입력 해시 불일치: {path}")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_v7_15_8_iso_build_ready_automatic_approval":
        raise ValueError("V7.15.8 독립 사전 검토 미통과")

    system_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    if len(final_system) != int(system_record["data_length"]):
        raise ValueError("SYSTEM.DAT 고정 자원 크기 불일치")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.8 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    system_left = int(system_record["extent_lba"]) * SECTOR_SIZE
    with temporary.open("r+b") as target:
        target.seek(system_left)
        target.write(final_system)
        target.flush()
        os.fsync(target.fileno())
    system_right = system_left + len(final_system)
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("V7.15.8 ISO 크기 변경")
    if hash_range(BASE_ISO, 0, system_left) != hash_range(temporary, 0, system_left) or hash_range(BASE_ISO, system_right, BASE_ISO.stat().st_size) != hash_range(temporary, system_right, temporary.stat().st_size):
        raise ValueError("SYSTEM.DAT 허용 ISO 범위 밖 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.8 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    extracted = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    if extracted != final_system:
        raise ValueError("최종 ISO SYSTEM.DAT 재추출 불일치")
    row = next(item for item in system_records(extracted) if item["name"].casefold() == "start.lzs")
    start = decompress_buffer(extracted[row["data_offset"]:row["data_offset"] + row["size"]])[0]
    if start != (RESOURCE_DIR / "start.dat").read_bytes():
        raise ValueError("최종 ISO START.DAT 재추출 불일치")
    archive = StartRuntimeArchive.from_bytes(start)
    for name, path in (("demo00.dat", RESOURCE_DIR / "Demo00.dat"), ("anime00.dat", RESOURCE_DIR / "anime00.dat")):
        record = next(item for item in archive.records if item.output_name.casefold() == name)
        if start[record.data_offset:record.end_offset] != path.read_bytes():
            raise ValueError(f"최종 ISO {name} 재추출 불일치")

    report = {
        "format": "prinny1_v7_15_8_runtime_safe_lzs_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_automatic_test_iso_approval_active_since_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "changed_iso_files": ["PSP_GAME/USRDIR/SYSTEM.DAT"],
        "checks": {"independent_prebuild_review_pass": True, "only_system_iso_extent_changed": True, "seven_zip_structure_test": True, "system_start_demo_anime_reextracted_exactly": True, "base_iso_not_overwritten": True},
        "status": "pass_v7_15_8_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
