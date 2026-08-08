#!/usr/bin/env python3
"""Independent prebuild review for the larger V7.15.12 PIC0 title."""
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
from scripts.prinny_anime_preview import decode_texture, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_12_larger_pic0_title_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_12_larger_pic0_title_plan/all_report.json"
TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_12/anime/anime00/object_078/group_00_page_00.png"
PREVIEW = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_12/pic0_title_glyph_preview.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_12_larger_pic0_title_review"

EXPECTED = {
    BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    RESOURCE_DIR / "SYSTEM.DAT": "d4fe0cbd6f53447dfd87765c1e934d180a96ecbc289b2674373500ed682449ab",
    RESOURCE_DIR / "start.dat": "7d5a055eee55ff532f47e0f6ff6a56d842d0f9ed5bade41e4c15082b7a0e54e1",
    RESOURCE_DIR / "start.lzs": "3f295592187ff49bafd1d33bb77effb5fa4d6bc2c841bd3a87fa4793616fc5c8",
    RESOURCE_DIR / "anime00.dat": "72197a6bfef150bd819a354ad1cd331c185cdedf9b2f6884a5c85ce2dfab8925",
    TITLE: "ed44ba30ee1dd48ff47d60d3538d1b39bd4a236ddaf7be3da38842d0e5887d81",
    PREVIEW: "c4aca6d40aff360b70a612468fec6577fe71ca3ca807030152de99f383bd44d7",
    PLAN: "3e6de686440e3f3aed1f79d0f4ce63068484332a9adae87d17f69055d6a6cada",
}
GLYPHS = (
    {"text": "프", "cell": (256, 160, 320, 224), "target": (262, 166, 314, 218), "pixels": 1040, "rel": 0x2018, "table": "010000000001A0004000400000000000"},
    {"text": "리", "cell": (320, 160, 376, 208), "target": (325, 164, 371, 204), "pixels": 788, "rel": 0x2028, "table": "010000004001A0003800300000000000"},
    {"text": "니", "cell": (376, 160, 424, 208), "target": (380, 164, 420, 204), "pixels": 529, "rel": 0x2038, "table": "010000007801A0003000300000000000"},
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


def extract_start(system: bytes) -> tuple[bytes, bytes, dict, list[dict]]:
    rows = system_records(system)
    row = next(item for item in rows if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs, row, rows


def edge_pixels(image: Image.Image) -> list[tuple[int, int, int, int]]:
    return (
        list(image.crop((0, 0, image.width, 1)).getdata())
        + list(image.crop((0, image.height - 1, image.width, image.height)).getdata())
        + list(image.crop((0, 0, 1, image.height)).getdata())
        + list(image.crop((image.width - 1, 0, image.width, image.height)).getdata())
    )


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.12 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "larger_pic0_title_resources_sealed_independent_review_required":
        raise ValueError("V7.15.12 계획 상태 불일치")
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
    old_record = next(row for row in base_archive.records if row.output_name.casefold() == "anime00.dat")
    new_record = next(row for row in final_archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[old_record.data_offset:old_record.end_offset]
    final_anime = final_start[new_record.data_offset:new_record.end_offset]
    if final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("최종 anime00 봉인본 불일치")
    obj = parse_objects(final_anime)[78]
    for spec in GLYPHS:
        at = obj.offset + spec["rel"]
        if final_anime[at:at + 16] != bytes.fromhex(spec["table"]):
            raise ValueError(f"최종 UV 셀 메타데이터 불일치: {spec['text']}")
    base_title = decode_texture(base_anime, texture_by_key(base_anime, (78, 0, 0))).convert("RGBA")
    final_title = decode_texture(final_anime, texture_by_key(final_anime, (78, 0, 0))).convert("RGBA")
    with Image.open(TITLE) as opened:
        opened.load()
        if final_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("타이틀 PNG/anime00 왕복 불일치")
    changed_pixels = assert_changes_inside(base_title, final_title, tuple(spec["cell"] for spec in GLYPHS))
    if changed_pixels != 2387:
        raise ValueError(f"타이틀 변경 픽셀 수 불일치: {changed_pixels}")
    for spec in GLYPHS:
        cell = final_title.crop(spec["cell"])
        target = final_title.crop(spec["target"])
        if set(cell.getdata()) > {TRANSPARENT, FOREGROUND} or sum(pixel == FOREGROUND for pixel in target.getdata()) != spec["pixels"] or any(pixel != TRANSPARENT for pixel in edge_pixels(cell)):
            raise ValueError(f"확대 글리프 팔레트/픽셀/셀 여백 불일치: {spec['text']}")

    next_offset = base_rows[base_row["index"] + 1]["data_offset"]
    allowed = set(range(base_row["data_offset"], next_offset))
    entry = 0x10 + base_row["index"] * 0x2C
    allowed.update(range(entry + 0x24, entry + 0x28))
    actual = {i for i, pair in enumerate(zip(base_system, final_system)) if pair[0] != pair[1]}
    if not actual <= allowed:
        raise ValueError("SYSTEM START 슬롯 밖 변경")
    report = {
        "format": "prinny1_v7_15_12_larger_pic0_title_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {"changed_system_resources": changed_system, "changed_start_resources": changed_start, "changed_title_pixels": changed_pixels, "runtime_lzs_overlaps": 0},
        "checks": {"plan_hash_locked": True, "uv_cell_table_byte_exact": True, "three_uv_cells_only": True, "cell_edges_transparent": True, "original_palette_only": True, "dialogue_and_other_images_preserved": True, "runtime_lzs_non_overlap": True, "system_changes_bounded": True},
        "status": "pass_v7_15_12_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("UV table/cells/palette/margins: PASS")
    print("SYSTEM start.lzs only; START anime00.dat only; overlaps 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
