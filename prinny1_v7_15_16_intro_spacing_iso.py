#!/usr/bin/env python3
"""Build the V7.15.16 combined ISO with the reviewed anime94 spacing fix."""
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
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue/prinny_korean_v7_15_15_user_dialogue.iso"
ANIME = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing_resources/ANIME.DAT"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_16_intro_spacing_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_16_intro_spacing.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_16_intro_spacing_iso"

EXPECTED = {
    BASE_ISO: "ed4415d7b1eb2144a3f38c23b154e363a9536cf105e4e721cce2b8e32957793b",
    ANIME: "3d120652ee0e69b5d3747e602509094ba1cbb37d0bf91c7970285f9d9f3051ce",
    REVIEW: "3da3540c62b22ebe4bccc064021501901a5efc41e0c27ec8996e55034ad29e22",
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
            raise ValueError(f"V7.15.16 ISO input hash mismatch: {path}")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_v7_15_16_intro_spacing_prebuild_review":
        raise ValueError("V7.15.16 independent prebuild review did not pass")

    record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"])
    payload = ANIME.read_bytes()
    if len(payload) != int(record["data_length"]):
        raise ValueError("ANIME.DAT fixed ISO extent size mismatch")
    offset = int(record["extent_lba"]) * SECTOR_SIZE
    right = offset + len(payload)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.16 output ISO already exists; refusing to overwrite it")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        raise ValueError("V7.15.16 temporary ISO already exists; refusing to overwrite it")
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as target:
        target.seek(offset)
        target.write(payload)
        target.flush()
        os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("V7.15.16 ISO size changed")
    if hash_range(BASE_ISO, 0, offset) != hash_range(temporary, 0, offset):
        raise ValueError("ISO changed before the ANIME.DAT extent")
    if hash_range(BASE_ISO, right, BASE_ISO.stat().st_size) != hash_range(temporary, right, temporary.stat().st_size):
        raise ValueError("ISO changed after the ANIME.DAT extent")
    structure = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if structure.returncode != 0 or "Everything is Ok" not in structure.stdout:
        raise ValueError("V7.15.16 ISO 7z structure check failed")
    os.replace(temporary, OUTPUT_ISO)
    if read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"])) != payload:
        raise ValueError("V7.15.16 ANIME.DAT re-extraction mismatch")

    report = {
        "format": "prinny1_v7_15_16_intro_spacing_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "changed_iso_files": ["PSP_GAME/USRDIR/ANIME.DAT"],
        "checks": {
            "independent_prebuild_review_pass": True,
            "only_anime_dat_iso_extent_changed": True,
            "anime_dat_reextracted_exactly": True,
            "seven_zip_structure_pass": True,
            "parent_iso_not_overwritten": True,
            "ppsspp_launched": False,
        },
        "status": "pass_v7_15_16_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("ANIME.DAT-only/7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
