#!/usr/bin/env python3
"""Extract the original Japanese title atlas and title-cell crop from game.iso."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture


ROOT = Path(__file__).resolve().parent
ISO = ROOT / "game.iso"
OUTPUT = ROOT / "workspace/exports/prinny1_v7_15_18_original_title"
EXPECTED = {
    "iso": "af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03",
    "system": "facf0905f80479952d1a4926ca3530ff2740b8492bf39cb4ba1e2b2ee3339c4e",
    "start_lzs": "2242dee86aefd0a1ee91a9092ee9525986431027943a544622c5c5e50ab5a58c",
    "start": "e2e9870cc4b62db0ee08ba1cbb1958bfdfa172a4df589288c01fde89c6befd41",
    "anime00": "deffb004f010c29b3575f8ed5ff801420366c0d952a54989186c8faface0fd73",
    "pixels": "82c9b06fb670806c1a05a8afd7e21051de55368035ab4987143d1974f7eb56f2",
}
TITLE_CROP = (256, 160, 464, 224)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not ISO.is_file() or sha256_file(ISO) != EXPECTED["iso"]:
        raise ValueError("원본 game.iso 해시 불일치")
    system = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    if sha256_bytes(system) != EXPECTED["system"]:
        raise ValueError("원본 SYSTEM.DAT 해시 불일치")
    row = next(item for item in system_records(system) if item["name"].casefold() == "start.lzs")
    start_lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    if sha256_bytes(start_lzs) != EXPECTED["start_lzs"]:
        raise ValueError("원본 START.LZS 해시 불일치")
    start = decompress_buffer(start_lzs)[0]
    if sha256_bytes(start) != EXPECTED["start"]:
        raise ValueError("원본 START.DAT 해시 불일치")
    archive = StartRuntimeArchive.from_bytes(start)
    anime_row = next(item for item in archive.records if item.output_name.casefold() == "anime00.dat")
    anime00 = start[anime_row.data_offset:anime_row.end_offset]
    if sha256_bytes(anime00) != EXPECTED["anime00"]:
        raise ValueError("원본 anime00.dat 해시 불일치")
    texture = texture_by_key(anime00, (78, 0, 0))
    atlas = decode_texture(anime00, texture).convert("RGBA")
    if sha256_bytes(atlas.tobytes()) != EXPECTED["pixels"]:
        raise ValueError("원본 object_078 텍스처 픽셀 해시 불일치")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    atlas_path = OUTPUT / "original_anime00_object_078_group_00_page_00.png"
    crop_path = OUTPUT / "original_japanese_title_cells.png"
    atlas.save(atlas_path, format="PNG", optimize=True, compress_level=9)
    atlas.crop(TITLE_CROP).save(crop_path, format="PNG", optimize=True, compress_level=9)
    report = {
        "format": "prinny1_v7_15_18_original_title_export_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_chain": ["game.iso", "PSP_GAME/USRDIR/SYSTEM.DAT", "START.LZS", "anime00.dat", "object_078/group_00_page_00"],
        "source_hashes": EXPECTED,
        "texture": {
            "object": 78,
            "group": 0,
            "page": 0,
            "width": texture.width,
            "height": texture.height,
            "descriptor_offset": texture.descriptor_offset,
            "pixel_offset": texture.pixel_offset,
            "palette_offset": texture.palette_offset,
        },
        "outputs": {
            "atlas": {"path": str(atlas_path), "sha256": sha256_file(atlas_path), "size": list(atlas.size)},
            "title_cells": {"path": str(crop_path), "sha256": sha256_file(crop_path), "crop": list(TITLE_CROP)},
        },
        "checks": {"original_iso_read_only": True, "full_source_chain_hash_locked": True, "decoded_pixel_hash_exact": True},
        "status": "pass_original_title_images_exported",
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(atlas_path)
    print(crop_path)
    print("original source chain/pixel hash: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
