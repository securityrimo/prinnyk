#!/usr/bin/env python3
"""Seal the anime94 intro-spacing fix on top of the V7.15.15 combined ISO."""
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
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from scripts.prinny_anime_preview import decode_texture, repack_texture
from scripts.prinny_txp_preview import decode_txp


ROOT = Path(__file__).resolve().parent
ISO = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue/prinny_korean_v7_15_15_user_dialogue.iso"
WORKSPACE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
TRANSLATED = WORKSPACE / "translated/resized"
TITLE = WORKSPACE / "translated/resized_v7_15_11/anime/anime00/object_078/group_00_page_00.png"
INTRO_SOURCE = WORKSPACE / "source_png/anime/anime94/object_000/group_00_page_00.png"
INTRO_OUTPUT = WORKSPACE / "translated/resized_v7_15_16/anime/anime94/object_000/group_00_page_00.png"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_16_intro_spacing_plan"

ANIME96 = ROOT / "workspace/build/prinny1_v7_15_6_ui_images_resources/anime96.dat"
BG9803 = ROOT / "workspace/build/prinny1_v7_15_7_bg9803_resources/bg9803.txp"

EXPECTED = {
    ISO: "ed4415d7b1eb2144a3f38c23b154e363a9536cf105e4e721cce2b8e32957793b",
    INTRO_SOURCE: "a559a714e11a37f31174d18626f6578a8ade6a2be3496cce1328a4a7c52e2eb1",
    TITLE: "d3baf482be50ee6ec2c2f10ab94cff3daae847b54807a82e2f62ba31d7f33f35",
    ANIME96: "24a80e8d05a41387336e149c3c1c1e8084fcee3c1eb2d135858fdf7de26b8c9f",
    BG9803: "c9c0763fdb7d04cefb89c845dea3caa8e91362c65356be225a701d4c35574a8f",
}

SYSTEM_IMAGES = {
    "REPLAY_ICON0.PNG": TRANSLATED / "system_pack/REPLAY_ICON0.PNG",
    "UMD_ICON0.PNG": TRANSLATED / "system_pack/UMD_ICON0.PNG",
    "UMD_PIC0.PNG": TRANSLATED / "system_pack/UMD_PIC0.PNG",
    "PRINNY_ICON0.PNG": TRANSLATED / "system_pack/PRINNY_ICON0.PNG",
}
DIRECT_IMAGES = {
    "ICON0.PNG": TRANSLATED / "direct_iso/ICON0.PNG",
    "PIC0.PNG": TRANSLATED / "direct_iso/PIC0.PNG",
}
INTRO_TEXTURE_KEY = (0, 0, 0)
INTRO_SOURCE_RECT = (190, 25, 291, 47)
INTRO_TARGET_ORIGIN = (166, 25)
INTRO_SHIFT_X = -24


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def changed_runs(before: bytes, after: bytes) -> list[tuple[int, int]]:
    changed = [offset for offset, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not changed:
        return []
    runs: list[tuple[int, int]] = []
    left = previous = changed[0]
    for offset in changed[1:]:
        if offset != previous + 1:
            runs.append((left, previous + 1))
            left = offset
        previous = offset
    runs.append((left, previous + 1))
    return runs


def tighten_intro_horizontal_spacing(original: Image.Image) -> tuple[Image.Image, int]:
    source = original.convert("RGBA")
    if source.size != (512, 320):
        raise ValueError(f"anime94 object_000 canvas mismatch: {source.size}")
    transparent = source.getpixel((511, 319))
    if transparent[3] != 0:
        raise ValueError("anime94 transparent reference pixel is opaque")
    crop = source.crop(INTRO_SOURCE_RECT)
    if crop.getbbox() is None:
        raise ValueError("anime94 demon-world line crop is empty")
    edited = source.copy()
    allowed = (
        INTRO_TARGET_ORIGIN[0],
        INTRO_SOURCE_RECT[1],
        INTRO_SOURCE_RECT[2],
        INTRO_SOURCE_RECT[3],
    )
    edited.paste(transparent, allowed)
    edited.paste(crop, INTRO_TARGET_ORIGIN)
    if not set(edited.getdata()).issubset(set(source.getdata())):
        raise ValueError("anime94 edit introduced a color outside the original palette")
    changed = assert_changes_inside(source, edited, (allowed,))
    expected = source.crop(INTRO_SOURCE_RECT)
    actual = edited.crop(
        (
            INTRO_TARGET_ORIGIN[0],
            INTRO_TARGET_ORIGIN[1],
            INTRO_TARGET_ORIGIN[0] + expected.width,
            INTRO_TARGET_ORIGIN[1] + expected.height,
        )
    )
    if actual.tobytes() != expected.tobytes():
        raise ValueError("anime94 horizontal move did not preserve the source pixels exactly")
    return edited, changed


def extract_start(system: bytes) -> tuple[bytes, bytes]:
    row = next(r for r in system_records(system) if r["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs


def verify_existing_korean_images(iso: Path) -> dict[str, object]:
    verified: dict[str, object] = {}
    for name, translated in DIRECT_IMAGES.items():
        blob = read_iso_file(iso, find_iso_file(iso, ["PSP_GAME", name]))
        expected = translated.read_bytes()
        if blob[:len(expected)] != expected or any(blob[len(expected):]):
            raise ValueError(f"direct Korean image mismatch: {name}")
        verified[f"direct/{name}"] = sha256_file(translated)

    system = read_iso_file(iso, find_iso_file(iso, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = {r["name"].casefold(): r for r in system_records(system)}
    for name, translated in SYSTEM_IMAGES.items():
        row = rows[name.casefold()]
        blob = system[row["data_offset"]:row["data_offset"] + row["size"]]
        if blob != translated.read_bytes():
            raise ValueError(f"SYSTEM Korean image mismatch: {name}")
        with Image.open(io.BytesIO(blob)) as opened:
            opened.load()
        verified[f"SYSTEM/{name}"] = sha256_bytes(blob)

    start, _lzs = extract_start(system)
    archive = StartRuntimeArchive.from_bytes(start)
    anime00_row = next(r for r in archive.records if r.output_name.casefold() == "anime00.dat")
    anime00 = start[anime00_row.data_offset:anime00_row.end_offset]
    title = decode_texture(anime00, texture_by_key(anime00, (78, 0, 0))).convert("RGBA")
    with Image.open(TITLE) as opened:
        if title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("V7.15.11 Korean title image is not preserved")
    verified["START/anime00/object_078"] = sha256_file(TITLE)

    anime_pack = read_iso_file(iso, find_iso_file(iso, ["PSP_GAME", "USRDIR", "ANIME.DAT"]))
    anime_rows = {r["name"].casefold(): r for r in system_records(anime_pack)}
    anime96_row = anime_rows["anime96.dat"]
    anime96 = anime_pack[anime96_row["data_offset"]:anime96_row["data_offset"] + anime96_row["size"]]
    if anime96 != ANIME96.read_bytes():
        raise ValueError("existing Korean anime96 intro texture is not preserved")
    with Image.open(TRANSLATED / "anime/anime96/object_000/group_00_page_00.png") as opened:
        expected_intro = opened.convert("RGBA")
    if decode_texture(anime96, texture_by_key(anime96, (0, 0, 0))).convert("RGBA").tobytes() != expected_intro.tobytes():
        raise ValueError("anime96 translated PNG roundtrip mismatch")
    verified["ANIME/anime96/object_000"] = sha256_file(TRANSLATED / "anime/anime96/object_000/group_00_page_00.png")

    bg_pack = read_iso_file(iso, find_iso_file(iso, ["PSP_GAME", "USRDIR", "BG.DAT"]))
    bg_rows = {r["name"].casefold(): r for r in system_records(bg_pack)}
    bg_row = bg_rows["bg9803.txp"]
    bg9803 = bg_pack[bg_row["data_offset"]:bg_row["data_offset"] + bg_row["size"]]
    if bg9803 != BG9803.read_bytes():
        raise ValueError("existing Korean bg9803 texture is not preserved")
    with Image.open(TRANSLATED / "bg/bg9803.png") as opened:
        expected_bg = opened.convert("RGBA")
    if decode_txp(BG9803).convert("RGBA").tobytes() != expected_bg.tobytes():
        raise ValueError("bg9803 translated PNG roundtrip mismatch")
    verified["BG/bg9803"] = sha256_file(TRANSLATED / "bg/bg9803.png")
    if len(verified) != 9:
        raise ValueError(f"expected nine existing Korean image targets, got {len(verified)}")
    return verified


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.16 input hash mismatch: {path}")
    existing = verify_existing_korean_images(ISO)

    anime_pack = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"]))
    rows = system_records(anime_pack)
    anime94_row = next(r for r in rows if r["name"].casefold() == "anime94.dat")
    anime94 = anime_pack[anime94_row["data_offset"]:anime94_row["data_offset"] + anime94_row["size"]]
    texture = texture_by_key(anime94, INTRO_TEXTURE_KEY)
    decoded = decode_texture(anime94, texture).convert("RGBA")
    with Image.open(INTRO_SOURCE) as opened:
        source_png = opened.convert("RGBA")
    if decoded.tobytes() != source_png.tobytes():
        raise ValueError("current ISO anime94 does not match the sealed source PNG")
    edited, changed_pixels = tighten_intro_horizontal_spacing(decoded)
    patched_anime94 = repack_texture(anime94, texture, edited)
    if decode_texture(patched_anime94, texture).convert("RGBA").tobytes() != edited.tobytes():
        raise ValueError("anime94 repack roundtrip mismatch")
    pixel_end = texture.pixel_offset + texture.width * texture.height // 2
    if anime94[:texture.pixel_offset] != patched_anime94[:texture.pixel_offset] or anime94[pixel_end:] != patched_anime94[pixel_end:]:
        raise ValueError("anime94 changed outside object_000 pixel storage")

    patched_pack = bytearray(anime_pack)
    left = int(anime94_row["data_offset"])
    right = left + int(anime94_row["size"])
    patched_pack[left:right] = patched_anime94
    if bytes(patched_pack[:left]) != anime_pack[:left] or bytes(patched_pack[right:]) != anime_pack[right:]:
        raise ValueError("ANIME.DAT changed outside anime94.dat")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    INTRO_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    edited.save(INTRO_OUTPUT, format="PNG", optimize=True, compress_level=9)
    (OUTPUT / "anime94.dat").write_bytes(patched_anime94)
    (OUTPUT / "ANIME.DAT").write_bytes(bytes(patched_pack))

    byte_runs = changed_runs(anime94, patched_anime94)
    expected_writes = [
        {
            "target": "ANIME.DAT/anime94.dat",
            "anime_dat_offset_hex": f"0x{left:X}",
            "span_bytes": len(anime94),
            "before_sha256": sha256_bytes(anime94),
            "after_sha256": sha256_bytes(patched_anime94),
            "actual_changed_byte_runs": [
                {
                    "relative_offset_hex": f"0x{run_left:X}",
                    "length": run_right - run_left,
                    "before_hex": anime94[run_left:run_right].hex().upper(),
                    "after_hex": patched_anime94[run_left:run_right].hex().upper(),
                }
                for run_left, run_right in byte_runs
            ],
        }
    ]
    report = {
        "format": "prinny1_v7_15_16_intro_spacing_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "parent_iso": {"path": str(ISO), "sha256": sha256_file(ISO)},
        "existing_korean_images": existing,
        "intro_edit": {
            "resource": "ANIME.DAT/anime94.dat/object_000/group_00_page_00",
            "source_rect": list(INTRO_SOURCE_RECT),
            "target_origin": list(INTRO_TARGET_ORIGIN),
            "horizontal_shift_pixels": INTRO_SHIFT_X,
            "changed_rgba_pixels": changed_pixels,
            "canvas": [512, 320],
            "palette_colors": len(set(decoded.getdata())),
        },
        "expected_writes": expected_writes,
        "sealed": {
            "ANIME.DAT": sha256_bytes(bytes(patched_pack)),
            "anime94.dat": sha256_bytes(patched_anime94),
            "edited_png": sha256_file(INTRO_OUTPUT),
        },
        "checks": {
            "all_nine_existing_korean_images_present": True,
            "anime94_current_iso_matches_source_png": True,
            "only_anime94_pixel_storage_changed": True,
            "only_anime94_span_changed_in_anime_dat": True,
            "canvas_and_palette_preserved": True,
            "iso_created": False,
            "ppsspp_launched": False,
        },
        "status": "v7_15_16_intro_spacing_resource_sealed_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"existing Korean image targets: {len(existing)}")
    print(f"anime94 shift: {INTRO_SHIFT_X}px; changed RGBA pixels: {changed_pixels}")
    print(f"ANIME.DAT sha256: {sha256_bytes(bytes(patched_pack))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
