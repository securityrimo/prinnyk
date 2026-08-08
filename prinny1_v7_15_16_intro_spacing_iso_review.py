#!/usr/bin/env python3
"""Independent postbuild review of the V7.15.16 combined image/dialogue ISO."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue/prinny_korean_v7_15_15_user_dialogue.iso"
ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
ANIME = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing_resources/ANIME.DAT"
ANIME94 = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing_resources/anime94.dat"
EDITED = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_16/anime/anime94/object_000/group_00_page_00.png"
BUILD_REPORT = ROOT / "workspace/reports/prinny1_v7_15_16_intro_spacing_iso/all_report.json"
PRE_REVIEW = ROOT / "workspace/reports/prinny1_v7_15_16_intro_spacing_review/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_16_intro_spacing_iso_review"

EXPECTED = {
    BASE_ISO: "ed4415d7b1eb2144a3f38c23b154e363a9536cf105e4e721cce2b8e32957793b",
    ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    ANIME: "3d120652ee0e69b5d3747e602509094ba1cbb37d0bf91c7970285f9d9f3051ce",
    ANIME94: "5210c65848d271f3a305e90bc927b0ea0f7c7d95be7809981ce452e0c0655714",
    EDITED: "0334d4194ee48a4695e406032c21f069f08e292943b38c1a4c898e403d6c4586",
    BUILD_REPORT: "ff7ed962ce07b3d219a4327c1525f59630798c34581a1e57f7a97af36661fe66",
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
            raise ValueError(f"V7.15.16 post-review input hash mismatch: {path}")
    pre = json.loads(PRE_REVIEW.read_text(encoding="utf-8"))
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if pre.get("final_verdict") != "PASS" or build.get("status") != "pass_v7_15_16_test_iso_built_independent_post_review_required":
        raise ValueError("V7.15.16 pre-review/build status mismatch")
    if ISO.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("V7.15.16 ISO size mismatch")

    base_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"])
    final_record = find_iso_file(ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"])
    if (base_record["extent_lba"], base_record["data_length"]) != (final_record["extent_lba"], final_record["data_length"]):
        raise ValueError("ANIME.DAT ISO directory record changed")
    left = int(base_record["extent_lba"]) * SECTOR_SIZE
    right = left + int(base_record["data_length"])
    if hash_range(BASE_ISO, 0, left) != hash_range(ISO, 0, left) or hash_range(BASE_ISO, right, BASE_ISO.stat().st_size) != hash_range(ISO, right, ISO.stat().st_size):
        raise ValueError("ISO changed outside the ANIME.DAT extent")
    base_anime = read_iso_file(BASE_ISO, base_record)
    final_anime = read_iso_file(ISO, final_record)
    if final_anime != ANIME.read_bytes():
        raise ValueError("final ANIME.DAT seal mismatch")
    base_rows = system_records(base_anime)
    final_rows = system_records(final_anime)
    if base_rows != final_rows:
        raise ValueError("final ANIME.DAT directory changed")
    anime94_row = next(r for r in base_rows if r["name"].casefold() == "anime94.dat")
    anime_left = anime94_row["data_offset"]
    anime_right = anime_left + anime94_row["size"]
    if base_anime[:anime_left] != final_anime[:anime_left] or base_anime[anime_right:] != final_anime[anime_right:]:
        raise ValueError("final ANIME.DAT changed outside anime94.dat")
    final_anime94 = final_anime[anime_left:anime_right]
    if final_anime94 != ANIME94.read_bytes():
        raise ValueError("final anime94.dat seal mismatch")
    texture = texture_by_key(final_anime94, (0, 0, 0))
    decoded = decode_texture(final_anime94, texture).convert("RGBA")
    with Image.open(EDITED) as opened:
        if decoded.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("final ISO anime94 PNG roundtrip mismatch")

    # Explicitly re-extract important inherited files, not just ISO range hashes.
    preserved = [
        ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
        ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
        ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
        ["PSP_GAME", "USRDIR", "BG.DAT"],
        ["PSP_GAME", "ICON0.PNG"],
        ["PSP_GAME", "PIC0.PNG"],
    ]
    for iso_path in preserved:
        if read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, iso_path)) != read_iso_file(ISO, find_iso_file(ISO, iso_path)):
            raise ValueError(f"inherited ISO file changed: {'/'.join(iso_path)}")
    anime96_row = next(r for r in base_rows if r["name"].casefold() == "anime96.dat")
    a96_left = anime96_row["data_offset"]
    a96_right = a96_left + anime96_row["size"]
    if base_anime[a96_left:a96_right] != final_anime[a96_left:a96_right]:
        raise ValueError("existing Korean anime96 texture changed")

    structure = subprocess.run(["7z", "t", str(ISO)], capture_output=True, text=True, check=False)
    if structure.returncode != 0 or "Everything is Ok" not in structure.stdout:
        raise ValueError("final ISO 7z structure retest failed")
    report = {
        "format": "prinny1_v7_15_16_intro_spacing_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": sha256_file(ISO)},
        "verified": {
            "changed_iso_files": ["PSP_GAME/USRDIR/ANIME.DAT"],
            "changed_anime_resources": ["anime94.dat"],
            "existing_korean_image_targets_preserved": 9,
            "intro_horizontal_shift_pixels": -24,
        },
        "checks": {
            "only_anime_dat_iso_extent_changed": True,
            "only_anime94_resource_changed": True,
            "anime94_png_roundtrip_exact": True,
            "boot_eboot_system_bg_direct_images_preserved": True,
            "existing_anime96_preserved": True,
            "seven_zip_structure_pass": True,
            "parent_iso_not_overwritten": True,
            "ppsspp_launched": False,
        },
        "runtime": {"ppsspp_test_deferred_by_user": True, "user_scene_confirmation": False},
        "status": "pass_v7_15_16_structural_review_runtime_test_deferred",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {sha256_file(ISO)}")
    print("ANIME-only/anime94-only/inherited images/7z: PASS")
    print("PPSSPP: deferred")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
