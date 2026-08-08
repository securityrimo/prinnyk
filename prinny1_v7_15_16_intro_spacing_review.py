#!/usr/bin/env python3
"""Independent prebuild review of the V7.15.16 anime94 spacing resource."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture
from scripts.prinny_txp_preview import decode_txp


ROOT = Path(__file__).resolve().parent
ISO = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue/prinny_korean_v7_15_15_user_dialogue.iso"
WORKSPACE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
TRANSLATED = WORKSPACE / "translated/resized"
TITLE = WORKSPACE / "translated/resized_v7_15_11/anime/anime00/object_078/group_00_page_00.png"
INTRO_SOURCE = WORKSPACE / "source_png/anime/anime94/object_000/group_00_page_00.png"
INTRO_EDITED = WORKSPACE / "translated/resized_v7_15_16/anime/anime94/object_000/group_00_page_00.png"
ANIME_OUT = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing_resources/ANIME.DAT"
ANIME94_OUT = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing_resources/anime94.dat"
ANIME96 = ROOT / "workspace/build/prinny1_v7_15_6_ui_images_resources/anime96.dat"
BG9803 = ROOT / "workspace/build/prinny1_v7_15_7_bg9803_resources/bg9803.txp"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_16_intro_spacing_plan/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_16_intro_spacing_review"

EXPECTED = {
    ISO: "ed4415d7b1eb2144a3f38c23b154e363a9536cf105e4e721cce2b8e32957793b",
    INTRO_SOURCE: "a559a714e11a37f31174d18626f6578a8ade6a2be3496cce1328a4a7c52e2eb1",
    INTRO_EDITED: "0334d4194ee48a4695e406032c21f069f08e292943b38c1a4c898e403d6c4586",
    ANIME_OUT: "3d120652ee0e69b5d3747e602509094ba1cbb37d0bf91c7970285f9d9f3051ce",
    ANIME94_OUT: "5210c65848d271f3a305e90bc927b0ea0f7c7d95be7809981ce452e0c0655714",
    PLAN: "2b1756ee2c0bfcf15bd96a44de2e0b54a8d5b51783c49c9a9e8a90801f256584",
}


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def exact_png_pixels(left: Image.Image, right_path: Path) -> bool:
    with Image.open(right_path) as opened:
        return left.convert("RGBA").tobytes() == opened.convert("RGBA").tobytes()


def audit_nine_images() -> int:
    direct = {
        "ICON0.PNG": TRANSLATED / "direct_iso/ICON0.PNG",
        "PIC0.PNG": TRANSLATED / "direct_iso/PIC0.PNG",
    }
    for name, source in direct.items():
        blob = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", name]))
        expected = source.read_bytes()
        if blob[:len(expected)] != expected or any(blob[len(expected):]):
            raise ValueError(f"direct image review mismatch: {name}")

    system = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = {r["name"].casefold(): r for r in system_records(system)}
    system_sources = {
        "REPLAY_ICON0.PNG": TRANSLATED / "system_pack/REPLAY_ICON0.PNG",
        "UMD_ICON0.PNG": TRANSLATED / "system_pack/UMD_ICON0.PNG",
        "UMD_PIC0.PNG": TRANSLATED / "system_pack/UMD_PIC0.PNG",
        "PRINNY_ICON0.PNG": TRANSLATED / "system_pack/PRINNY_ICON0.PNG",
    }
    for name, source in system_sources.items():
        row = rows[name.casefold()]
        if system[row["data_offset"]:row["data_offset"] + row["size"]] != source.read_bytes():
            raise ValueError(f"SYSTEM image review mismatch: {name}")

    start_row = rows["start.lzs"]
    start = decompress_buffer(system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]])[0]
    archive = StartRuntimeArchive.from_bytes(start)
    anime00_row = next(r for r in archive.records if r.output_name.casefold() == "anime00.dat")
    anime00 = start[anime00_row.data_offset:anime00_row.end_offset]
    if not exact_png_pixels(decode_texture(anime00, texture_by_key(anime00, (78, 0, 0))), TITLE):
        raise ValueError("title image review mismatch")

    anime = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"]))
    anime_rows = {r["name"].casefold(): r for r in system_records(anime)}
    row = anime_rows["anime96.dat"]
    anime96 = anime[row["data_offset"]:row["data_offset"] + row["size"]]
    if anime96 != ANIME96.read_bytes() or not exact_png_pixels(
        decode_texture(anime96, texture_by_key(anime96, (0, 0, 0))),
        TRANSLATED / "anime/anime96/object_000/group_00_page_00.png",
    ):
        raise ValueError("anime96 image review mismatch")

    bg = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "USRDIR", "BG.DAT"]))
    bg_rows = {r["name"].casefold(): r for r in system_records(bg)}
    row = bg_rows["bg9803.txp"]
    if bg[row["data_offset"]:row["data_offset"] + row["size"]] != BG9803.read_bytes():
        raise ValueError("bg9803 resource review mismatch")
    if not exact_png_pixels(decode_txp(BG9803), TRANSLATED / "bg/bg9803.png"):
        raise ValueError("bg9803 pixel review mismatch")
    return 9


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.16 review input hash mismatch: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "v7_15_16_intro_spacing_resource_sealed_independent_review_required":
        raise ValueError("V7.15.16 plan status mismatch")
    image_count = audit_nine_images()

    base_pack = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"]))
    final_pack = ANIME_OUT.read_bytes()
    base_rows = system_records(base_pack)
    final_rows = system_records(final_pack)
    if base_rows != final_rows:
        raise ValueError("ANIME.DAT directory changed")
    row = next(r for r in base_rows if r["name"].casefold() == "anime94.dat")
    left, right = row["data_offset"], row["data_offset"] + row["size"]
    if base_pack[:left] != final_pack[:left] or base_pack[right:] != final_pack[right:]:
        raise ValueError("ANIME.DAT changed outside anime94.dat")
    base_anime94 = base_pack[left:right]
    final_anime94 = final_pack[left:right]
    if final_anime94 != ANIME94_OUT.read_bytes():
        raise ValueError("sealed anime94.dat mismatch")
    base_texture = texture_by_key(base_anime94, (0, 0, 0))
    final_texture = texture_by_key(final_anime94, (0, 0, 0))
    if base_texture != final_texture:
        raise ValueError("anime94 texture metadata changed")
    pixel_end = base_texture.pixel_offset + base_texture.width * base_texture.height // 2
    if base_anime94[:base_texture.pixel_offset] != final_anime94[:base_texture.pixel_offset] or base_anime94[pixel_end:] != final_anime94[pixel_end:]:
        raise ValueError("anime94 changed outside texture pixels")
    before = decode_texture(base_anime94, base_texture).convert("RGBA")
    after = decode_texture(final_anime94, final_texture).convert("RGBA")
    if not exact_png_pixels(after, INTRO_EDITED):
        raise ValueError("anime94 edited PNG roundtrip mismatch")
    if before.crop((190, 25, 291, 47)).tobytes() != after.crop((166, 25, 267, 47)).tobytes():
        raise ValueError("anime94 24-pixel left shift mismatch")
    if before.crop((0, 0, 512, 25)).tobytes() != after.crop((0, 0, 512, 25)).tobytes() or before.crop((0, 47, 512, 320)).tobytes() != after.crop((0, 47, 512, 320)).tobytes():
        raise ValueError("anime94 changed outside the second intro row")
    if not set(after.getdata()).issubset(set(before.getdata())):
        raise ValueError("anime94 palette expansion detected")

    report = {
        "format": "prinny1_v7_15_16_intro_spacing_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "existing_korean_image_targets": image_count,
            "anime94_before_sha256": sha256_bytes(base_anime94),
            "anime94_after_sha256": sha256_bytes(final_anime94),
            "horizontal_shift_pixels": -24,
            "changed_anime94_bytes": sum(a != b for a, b in zip(base_anime94, final_anime94)),
        },
        "checks": {
            "fresh_nine_image_audit_pass": True,
            "anime_dat_directory_preserved": True,
            "only_anime94_span_changed": True,
            "only_anime94_texture_pixels_changed": True,
            "second_row_shifted_left_exactly_24_pixels": True,
            "other_rows_preserved": True,
            "palette_and_canvas_preserved": True,
            "ppsspp_launched": False,
        },
        "status": "pass_v7_15_16_intro_spacing_prebuild_review",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"existing Korean image targets: {image_count}")
    print("anime94-only, 24px left shift, palette/canvas: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
