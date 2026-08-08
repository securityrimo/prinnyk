#!/usr/bin/env python3
"""Reapply the existing Korean image set on the runtime-safe V7.15.8 base."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from scripts.prinny_anime_preview import decode_texture, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs/prinny_korean_v7_15_8_runtime_safe_lzs.iso"
XDELTA_BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
ANIME_SOURCE = ROOT / "workspace/build/prinny1_v7_15_6_ui_images_resources/ANIME.DAT"
BG_SOURCE = ROOT / "workspace/build/prinny1_v7_15_7_bg9803_resources/BG.DAT"
TRANSLATED = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_9_safe_images_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_9_safe_images_plan"
TITLE_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_9/anime/anime00/object_078/group_00_page_00.png"

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
EXPECTED = {
    BASE_ISO: "4ee4198acd01cbb4bda08e7b0d76b1cea3dea7de95e36b295ff6eede90876f6e",
    XDELTA_BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    ANIME_SOURCE: "8a26453874bafb6f800ab3fe2c3cd9eb6ccd4aa43679016b59fea10d2f385d77",
    BG_SOURCE: "45f0de733dbf8ee53300090afceef5e8e52387e19c28c79b4631f59b49b0e068",
    SYSTEM_IMAGES["REPLAY_ICON0.PNG"]: "050ff8d68d6768a3863d00840731322cf64cf7cb4218dabe9338e274b4ed5eac",
    SYSTEM_IMAGES["UMD_ICON0.PNG"]: "960555d1ef29d26eeea56bbf45b6c52723d31e062ecbbea7f7c0db576f1b2e80",
    SYSTEM_IMAGES["UMD_PIC0.PNG"]: "5be9973e574f552443d0a7c77d00425719c193d85359ea1930f296ec685d3aa8",
    SYSTEM_IMAGES["PRINNY_ICON0.PNG"]: "c528c363ca46a2c10d13dbe8e0d25f1d568cd0ea1df9900f9c55978ffea9e70d",
    DIRECT_IMAGES["ICON0.PNG"]: "960555d1ef29d26eeea56bbf45b6c52723d31e062ecbbea7f7c0db576f1b2e80",
    DIRECT_IMAGES["PIC0.PNG"]: "5be9973e574f552443d0a7c77d00425719c193d85359ea1930f296ec685d3aa8",
}

# V7.15.8보다 약 15% 작게 조정해 반복 색상 패스가 겹치는 현상을 줄인다.
TITLE_GLYPHS_BALANCED = (
    {"text": "프", "source": (273, 181, 303, 212), "target": (269, 177, 307, 216)},
    {"text": "리", "source": (331, 161, 359, 187), "target": (327, 158, 362, 191)},
    {"text": "니", "source": (381, 159, 409, 186), "target": (377, 156, 412, 190)},
)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def balanced_title(original: Image.Image) -> tuple[Image.Image, int]:
    source = original.convert("RGBA")
    if source.size != (512, 512):
        raise ValueError("타이틀 아틀라스 캔버스 불일치")
    transparent = source.getpixel((511, 511))
    if transparent[3] != 0:
        raise ValueError("타이틀 투명 배경 기준 불일치")
    edited = source.copy()
    allowed = []
    for glyph in TITLE_GLYPHS_BALANCED:
        source_rect, target_rect = tuple(glyph["source"]), tuple(glyph["target"])
        crop = source.crop(source_rect)
        edited.paste(transparent, target_rect)
        scaled = crop.resize((target_rect[2] - target_rect[0], target_rect[3] - target_rect[1]), Image.Resampling.NEAREST)
        edited.paste(scaled, (target_rect[0], target_rect[1]))
        allowed.append(target_rect)
    if not set(edited.getdata()).issubset(set(source.getdata())):
        raise ValueError("타이틀 원본 팔레트 밖 색 생성")
    return edited, assert_changes_inside(source, edited, tuple(allowed))


def lzs_overlap_count(stream: bytes) -> int:
    _raw, header = decompress_buffer(stream)
    flag = int(header["flag"])
    cursor, end = 0x10, int(header["compressed_end"])
    overlaps = 0
    while cursor < end:
        token = stream[cursor]
        cursor += 1
        if token != flag:
            continue
        second = stream[cursor]
        cursor += 1
        if second == flag:
            continue
        length = stream[cursor]
        cursor += 1
        distance = second if second < flag else second - 1
        overlaps += int(length > distance)
    return overlaps


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.9 입력 해시 불일치: {path}")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    xdelta_system = read_iso_file(XDELTA_BASE_ISO, find_iso_file(XDELTA_BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(base_system)
    by_name = {row["name"].casefold(): row for row in rows}
    start_row = by_name["start.lzs"]
    old_lzs = base_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    base_start, header = decompress_buffer(old_lzs)
    if lzs_overlap_count(old_lzs) != 0:
        raise ValueError("V7.15.8 부모 LZS에 겹침 역참조 존재")
    archive = StartRuntimeArchive.from_bytes(base_start)
    anime_record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")

    xdelta_start_row = next(row for row in system_records(xdelta_system) if row["name"].casefold() == "start.lzs")
    xdelta_start = decompress_buffer(xdelta_system[xdelta_start_row["data_offset"]:xdelta_start_row["data_offset"] + xdelta_start_row["size"]])[0]
    xdelta_archive = StartRuntimeArchive.from_bytes(xdelta_start)
    xdelta_anime_record = next(row for row in xdelta_archive.records if row.output_name.casefold() == "anime00.dat")
    original_anime = xdelta_start[xdelta_anime_record.data_offset:xdelta_anime_record.end_offset]
    texture = texture_by_key(original_anime, (78, 0, 0))
    original_title = decode_texture(original_anime, texture)
    final_title, title_changed_pixels = balanced_title(original_title)
    final_anime = repack_texture(original_anime, texture, final_title)
    if decode_texture(final_anime, texture).convert("RGBA").tobytes() != final_title.tobytes():
        raise ValueError("균형 타이틀 아틀라스 재패킹 왕복 실패")

    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    for row in archive.records:
        before = base_start[row.data_offset:row.end_offset]
        after = bytes(final_start[row.data_offset:row.end_offset])
        if row.output_name.casefold() != "anime00.dat" and before != after:
            raise ValueError(f"비대상 START 자원 변경: {row.output_name}")
    new_lzs = compress_buffer_runtime_safe(bytes(final_start), old_lzs[:4], int(header["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start) or lzs_overlap_count(new_lzs) != 0:
        raise ValueError("V7.15.9 런타임 안전 LZS 검증 실패")
    next_offset = rows[start_row["index"] + 1]["data_offset"]
    capacity = next_offset - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError(f"V7.15.9 START.LZS 슬롯 초과: {len(new_lzs)}>{capacity}")

    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:next_offset] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))
    system_manifest = []
    for name, source in SYSTEM_IMAGES.items():
        row = by_name[name.casefold()]
        following = rows[row["index"] + 1]["data_offset"] if row["index"] + 1 < len(rows) else len(final_system)
        slot_capacity = following - row["data_offset"]
        blob = source.read_bytes()
        if len(blob) > slot_capacity:
            raise ValueError(f"SYSTEM PNG 슬롯 초과: {name}/{len(blob)}/{slot_capacity}")
        final_system[row["data_offset"]:following] = bytes(slot_capacity)
        final_system[row["data_offset"]:row["data_offset"] + len(blob)] = blob
        struct.pack_into("<I", final_system, 0x10 + row["index"] * 0x2C + 0x24, len(blob))
        system_manifest.append({"name": name, "offset": row["data_offset"], "old_size": row["size"], "new_size": len(blob), "capacity": slot_capacity, "sha256": sha256_bytes(blob)})

    verified_rows = {row["name"].casefold(): row for row in system_records(bytes(final_system))}
    verified_lzs_row = verified_rows["start.lzs"]
    verified_start = decompress_buffer(bytes(final_system[verified_lzs_row["data_offset"]:verified_lzs_row["data_offset"] + verified_lzs_row["size"]]))[0]
    if verified_start != bytes(final_start):
        raise ValueError("최종 SYSTEM.DAT START 재추출 실패")
    for name, source in SYSTEM_IMAGES.items():
        row = verified_rows[name.casefold()]
        if bytes(final_system[row["data_offset"]:row["data_offset"] + row["size"]]) != source.read_bytes():
            raise ValueError(f"최종 SYSTEM PNG 재추출 실패: {name}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    TITLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final_title.save(TITLE_OUTPUT, format="PNG", optimize=True, compress_level=9)
    artifacts = {
        "SYSTEM.DAT": bytes(final_system),
        "start.dat": bytes(final_start),
        "start.lzs": new_lzs,
        "anime00.dat": final_anime,
        "ANIME.DAT": ANIME_SOURCE.read_bytes(),
        "BG.DAT": BG_SOURCE.read_bytes(),
        "direct_iso/ICON0.PNG": DIRECT_IMAGES["ICON0.PNG"].read_bytes(),
        "direct_iso/PIC0.PNG": DIRECT_IMAGES["PIC0.PNG"].read_bytes(),
    }
    for relative, blob in artifacts.items():
        target = OUTPUT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    report = {
        "format": "prinny1_v7_15_9_safe_images_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {"title_changed_pixels_from_xdelta": title_changed_pixels, "title_scale": "balanced_smaller_than_v7_15_8", "old_lzs_size": len(old_lzs), "new_lzs_size": len(new_lzs), "lzs_capacity": capacity, "lzs_overlaps": 0, "system_images": system_manifest, "external_image_packs": ["ANIME.DAT/anime96", "BG.DAT/bg9803", "ISO/ICON0.PNG", "ISO/PIC0.PNG"]},
        "sealed": {relative: sha256_bytes(blob) for relative, blob in artifacts.items()} | {"title_png": sha256_file(TITLE_OUTPUT)},
        "checks": {"v7_15_8_parent_preserved": True, "only_anime00_changed_inside_start": True, "runtime_safe_lzs_non_overlap": True, "all_existing_korean_images_reinserted": True, "system_png_slots_fit": True, "iso_created": False},
        "status": "safe_image_resources_sealed_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"START.LZS: {len(old_lzs)} -> {len(new_lzs)} / {capacity}; overlaps 0")
    print(f"title changed pixels: {title_changed_pixels}")
    print(f"SYSTEM.DAT: {sha256_bytes(bytes(final_system))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
