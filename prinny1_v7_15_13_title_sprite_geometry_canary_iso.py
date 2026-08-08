#!/usr/bin/env python3
"""Build the transform-only 프 enlargement canary ISO."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
SYSTEM = ROOT / "workspace/build/prinny1_v7_15_13_title_sprite_geometry_canary_resources/SYSTEM.DAT"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_13_title_sprite_geometry_canary_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_13_title_sprite_geometry_canary"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_13_title_sprite_geometry_canary.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_13_title_sprite_geometry_canary_iso"
EXPECTED = {
    BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    SYSTEM: "9cc4549585730c090d93902dbbbef905e611fa67ef0aa9ccc4524c8a13b3c4fc",
    REVIEW: "d3710101216257621d939e2b006c31953195784d619811c9aee7c920b6cad84d",
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
            raise ValueError(f"카나리 ISO 입력 해시 불일치: {path}")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("status") != "pass_canary_iso_build_ready_automatic_approval" or review.get("final_verdict") != "PASS":
        raise ValueError("카나리 독립 사전 검토 미통과")
    record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_system = SYSTEM.read_bytes()
    if len(final_system) != int(record["data_length"]):
        raise ValueError("SYSTEM.DAT 고정 영역 크기 불일치")
    offset = int(record["extent_lba"]) * SECTOR_SIZE
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("카나리 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as target:
        target.seek(offset)
        target.write(final_system)
        target.flush()
        os.fsync(target.fileno())
    end = offset + len(final_system)
    if temporary.stat().st_size != BASE_ISO.stat().st_size or hash_range(BASE_ISO, 0, offset) != hash_range(temporary, 0, offset) or hash_range(BASE_ISO, end, BASE_ISO.stat().st_size) != hash_range(temporary, end, temporary.stat().st_size):
        raise ValueError("카나리 ISO 허용 영역 밖 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("카나리 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    if read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])) != final_system:
        raise ValueError("카나리 ISO SYSTEM 재추출 불일치")
    report = {
        "format": "prinny1_v7_15_13_title_sprite_geometry_canary_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "test_iso_automatic_approval",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "checks": {"independent_prebuild_review_pass": True, "only_system_dat_extent_changed": True, "seven_zip_structure_test": True, "system_reextracted_exactly": True, "parent_not_overwritten": True},
        "status": "pass_canary_iso_ready_for_runtime_test",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
