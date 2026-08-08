#!/usr/bin/env python3
"""Independent prebuild review for the V7.15.11 PIC0-style title glyphs."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from scripts.prinny_anime_preview import decode_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_10_title_color_restore/prinny_korean_v7_15_10_title_color_restore.iso"
PIC0 = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/source_png/direct_iso/PIC0.png"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_11_pic0_title_style_plan/all_report.json"
TITLE_PNG = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_11/anime/anime00/object_078/group_00_page_00.png"
PREVIEW = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_11/pic0_title_glyph_preview.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_11_pic0_title_style_review"

EXPECTED = {
    BASE_ISO: "e26f628360cac2043338051070acfb1f4586a9e321469f7dc3d578375265badf",
    PIC0: "7fb529379799b875e482553b483ca11fae581a669b37580ac2ac2da4f6f992f7",
    RESOURCE_DIR / "SYSTEM.DAT": "4cab10eec60afcf43ea872bd7c93934f46b7d1af538384218fa822f24bd437e8",
    RESOURCE_DIR / "start.dat": "0b3616c3b72d12fcac25d2a8ea052795ce45c4926dd6f2fe2fc76fed7cec1623",
    RESOURCE_DIR / "start.lzs": "31a4baecc5ba9305b826fbf1c799381006848db4e3fad4ffc70aa42387e283df",
    RESOURCE_DIR / "anime00.dat": "df9df6273e3cf8714121fa0e405dd37844251fc036b2b596e01b267b63cefb6a",
    TITLE_PNG: "d3baf482be50ee6ec2c2f10ab94cff3daae847b54807a82e2f62ba31d7f33f35",
    PREVIEW: "a93302f3041b17d6b0985b9ff0a2d1bc50b30677d45cccad197f341cca44fbcf",
    PLAN: "93c80f5c85e8a520eaa9549a8db1446df659ca536c73a41a573b8ddaab93cdbd",
}
GLYPHS = (
    {"text": "프", "crop": (990, 570, 1420, 980), "component_sizes": [39901, 16875], "target": (273, 181, 303, 212), "pixels": 330},
    {"text": "리", "crop": (1330, 440, 1760, 860), "component_sizes": [61905], "target": (331, 161, 359, 187), "pixels": 314},
    {"text": "니", "crop": (1680, 320, 2120, 750), "component_sizes": [51623], "target": (381, 159, 409, 186), "pixels": 252},
)
FOREGROUND = (0, 255, 0, 255)
TRANSPARENT = (0, 0, 0, 0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def overlap_count(stream: bytes) -> int:
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


def white_component_sizes(image: Image.Image, box: tuple[int, int, int, int]) -> list[int]:
    crop = image.crop(box).convert("RGB")
    width, height = crop.size
    remaining = {(x, y) for y in range(height) for x in range(width) if min(crop.getpixel((x, y))) >= 215}
    interior = []
    while remaining:
        seed = remaining.pop()
        stack = [seed]
        component = {seed}
        while stack:
            x, y = stack.pop()
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if point in remaining:
                    remaining.remove(point)
                    component.add(point)
                    stack.append(point)
        if not any(x in (0, width - 1) or y in (0, height - 1) for x, y in component):
            interior.append(len(component))
    return sorted(interior, reverse=True)


def extract_start(system: bytes) -> tuple[bytes, bytes, dict, list[dict]]:
    rows = system_records(system)
    row = next(item for item in rows if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs, row, rows


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.11 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "pic0_title_style_resources_sealed_independent_review_required":
        raise ValueError("V7.15.11 계획 상태 불일치")

    with Image.open(PIC0) as opened:
        opened.load()
        pic0 = opened.convert("RGBA")
    for spec in GLYPHS:
        sizes = white_component_sizes(pic0, spec["crop"])
        expected_sizes = spec["component_sizes"]
        if sizes[:len(expected_sizes)] != expected_sizes:
            raise ValueError(f"PIC0 흰색 글리프 연결 요소 불일치: {spec['text']}/{sizes[:3]}")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    base_start, _base_lzs, base_row, base_rows = extract_start(base_system)
    final_start, final_lzs, final_row, final_rows = extract_start(final_system)
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or final_lzs != (RESOURCE_DIR / "start.lzs").read_bytes() or overlap_count(final_lzs) != 0:
        raise ValueError("최종 START/LZS 봉인 또는 안전성 불일치")
    if [(r["name"], r["data_offset"]) for r in base_rows] != [(r["name"], r["data_offset"]) for r in final_rows]:
        raise ValueError("SYSTEM 자원 목록/오프셋 변경")
    changed_system = []
    for old, new in zip(base_rows, final_rows):
        before = base_system[old["data_offset"]:old["data_offset"] + old["size"]]
        after = final_system[new["data_offset"]:new["data_offset"] + new["size"]]
        if before != after or old["size"] != new["size"]:
            changed_system.append(old["name"].casefold())
    if changed_system != ["start.lzs"]:
        raise ValueError(f"SYSTEM 변경 자원 불일치: {changed_system}")

    base_archive, final_archive = StartRuntimeArchive.from_bytes(base_start), StartRuntimeArchive.from_bytes(final_start)
    changed_start = []
    for old, new in zip(base_archive.records, final_archive.records):
        if (old.output_name, old.data_offset, old.end_offset) != (new.output_name, new.data_offset, new.end_offset):
            raise ValueError("START 자원 경계 변경")
        if base_start[old.data_offset:old.end_offset] != final_start[new.data_offset:new.end_offset]:
            changed_start.append(old.output_name.casefold())
    if changed_start != ["anime00.dat"]:
        raise ValueError(f"START 변경 자원 불일치: {changed_start}")
    base_anime_record = next(r for r in base_archive.records if r.output_name.casefold() == "anime00.dat")
    final_anime_record = next(r for r in final_archive.records if r.output_name.casefold() == "anime00.dat")
    base_anime = base_start[base_anime_record.data_offset:base_anime_record.end_offset]
    final_anime = final_start[final_anime_record.data_offset:final_anime_record.end_offset]
    if final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("최종 anime00 봉인본 불일치")
    base_title = decode_texture(base_anime, texture_by_key(base_anime, (78, 0, 0))).convert("RGBA")
    final_title = decode_texture(final_anime, texture_by_key(final_anime, (78, 0, 0))).convert("RGBA")
    with Image.open(TITLE_PNG) as opened:
        opened.load()
        if final_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("타이틀 PNG/anime00 왕복 불일치")
    changed_pixels = assert_changes_inside(base_title, final_title, tuple(spec["target"] for spec in GLYPHS))
    if changed_pixels != 384:
        raise ValueError(f"타이틀 변경 픽셀 수 불일치: {changed_pixels}")
    for spec in GLYPHS:
        cell = final_title.crop(spec["target"])
        colors = set(cell.getdata())
        foreground_pixels = sum(1 for pixel in cell.getdata() if pixel == FOREGROUND)
        border = list(cell.crop((0, 0, cell.width, 1)).getdata()) + list(cell.crop((0, cell.height - 1, cell.width, cell.height)).getdata()) + list(cell.crop((0, 0, 1, cell.height)).getdata()) + list(cell.crop((cell.width - 1, 0, cell.width, cell.height)).getdata())
        if not colors <= {TRANSPARENT, FOREGROUND} or foreground_pixels != spec["pixels"] or any(pixel != TRANSPARENT for pixel in border):
            raise ValueError(f"최종 글리프 팔레트/픽셀/안전 여백 불일치: {spec['text']}")

    next_offset = base_rows[base_row["index"] + 1]["data_offset"]
    allowed = set(range(base_row["data_offset"], next_offset))
    entry = 0x10 + base_row["index"] * 0x2C
    allowed.update(range(entry + 0x24, entry + 0x28))
    changed_offsets = {i for i, pair in enumerate(zip(base_system, final_system)) if pair[0] != pair[1]}
    if not changed_offsets <= allowed:
        raise ValueError("SYSTEM START 슬롯 밖 변경")

    report = {
        "format": "prinny1_v7_15_11_pic0_title_style_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "changed_system_resources": changed_system,
            "changed_start_resources": changed_start,
            "changed_title_pixels": changed_pixels,
            "runtime_lzs_overlaps": 0,
            "pic0_component_sizes": {spec["text"]: spec["component_sizes"] for spec in GLYPHS},
        },
        "checks": {
            "plan_hash_locked": True,
            "pic0_glyph_components_independently_identified": True,
            "three_original_uv_cells_only": True,
            "one_pixel_transparent_cell_border": True,
            "original_two_color_palette_only": True,
            "only_anime00_changed_in_start": True,
            "dialogue_and_other_images_preserved": True,
            "runtime_lzs_non_overlap": True,
            "system_changes_bounded": True,
        },
        "status": "pass_v7_15_11_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PIC0 components/UV cells/palette: PASS")
    print("SYSTEM start.lzs only; START anime00.dat only; overlaps 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
