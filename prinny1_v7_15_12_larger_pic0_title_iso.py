#!/usr/bin/env python3
"""Build the V7.15.12 larger PIC0-style title PSP test ISO."""
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
SYSTEM = ROOT / "workspace/build/prinny1_v7_15_12_larger_pic0_title_resources/SYSTEM.DAT"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_12_larger_pic0_title_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_12_larger_pic0_title"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_12_larger_pic0_title.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_12_larger_pic0_title_iso"

EXPECTED = {
    BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    SYSTEM: "d4fe0cbd6f53447dfd87765c1e934d180a96ecbc289b2674373500ed682449ab",
    REVIEW: "e6fd9bbaca945f6731e8e07387e721b23e336767516a8b88204d4a01a70d251e",
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
            raise ValueError(f"V7.15.12 ISO 입력 해시 불일치: {path}")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_v7_15_12_iso_build_ready_automatic_approval":
        raise ValueError("V7.15.12 독립 사전 검토 미통과")
    record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_system = SYSTEM.read_bytes()
    if len(final_system) != int(record["data_length"]):
        raise ValueError("SYSTEM.DAT 고정 ISO 영역 크기 불일치")
    offset = int(record["extent_lba"]) * SECTOR_SIZE

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.12 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
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
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("V7.15.12 ISO 크기 변경")
    if hash_range(BASE_ISO, 0, offset) != hash_range(temporary, 0, offset):
        raise ValueError("SYSTEM.DAT 앞 ISO 데이터 변경")
    end = offset + len(final_system)
    if hash_range(BASE_ISO, end, BASE_ISO.stat().st_size) != hash_range(temporary, end, temporary.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 ISO 데이터 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.12 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    if read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])) != final_system:
        raise ValueError("최종 ISO SYSTEM.DAT 재추출 불일치")

    report = {
        "format": "prinny1_v7_15_12_larger_pic0_title_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "test_iso_automatic_approval_and_user_runtime_request_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "changed_iso_files": ["PSP_GAME/USRDIR/SYSTEM.DAT"],
        "checks": {
            "independent_prebuild_review_pass": True,
            "only_system_dat_iso_extent_changed": True,
            "seven_zip_structure_test": True,
            "system_dat_reextracted_exactly": True,
            "v7_15_11_parent_not_overwritten": True,
        },
        "status": "pass_v7_15_12_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
