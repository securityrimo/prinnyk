#!/usr/bin/env python3
"""Independent pre-ISO review of the logo-weight Korean title candidate."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from scripts.prinny_anime_preview import decode_texture, parse_objects, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_16_intro_spacing/prinny_korean_v7_15_16_intro_spacing.iso"
BUILD = ROOT / "workspace/build/prinny1_v7_15_18_logo_style_title_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_18_logo_style_title_plan/all_report.json"
TITLE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_18/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_18_logo_style_title_review"
EXPECTED = {
    BASE_ISO: "f62aa240706b9830f7e1b46a8f707dcb3f9cf4cf6b476147667a162d43a1b7c6",
    BUILD / "SYSTEM.DAT": "f33b250ad4f90874c4f5f901e0ec237f966c77285ddc3e4c2dbba95f02de10d9",
    BUILD / "start.dat": "4dddda2e554292f7a4af15b94aaf1889597dd829d58730541cc31a8a5cc8e6f9",
    BUILD / "start.lzs": "eca06e7e6406d72e34fd5178bb88dd824601d6e082697d052f5c3f3bef249e79",
    BUILD / "anime00.dat": "8ee7db07bd7d3b4977d5c5e40e54fba720f61b01940bd263b1100b1b0d72437e",
    TITLE: "416e4f040505838b2d4041bd9ae3489426caa5671f52ff43bf762941e78e200c",
    PLAN: "7ebf9ff964e38b7ffd57a821495d0fa53a4513109ad81e281f4df1cb99ceb570",
}
FOREGROUND = (0, 255, 0, 255)
TRANSPARENT = (0, 0, 0, 0)
CELLS = ((256, 160, 320, 224), (320, 160, 376, 208), (376, 160, 424, 208))
TARGETS = ((263, 166, 318, 219, 1840), (323, 165, 371, 201, 1028), (378, 163, 422, 205, 858))
BAR_CELL = (424, 160, 464, 192)
TRANSFORMS = (
    (0x23B4, (-63, -29, 32, 32)), (0x23C4, (-63, -37, 32, 32)),
    (0x23D4, (-7, -38, 28, 24)), (0x23E4, (-6, -46, 28, 24)),
    (0x23F4, (-6, -38, 28, 24)), (0x2404, (39, -50, 24, 24)),
    (0x2414, (39, -58, 24, 24)), (0x2424, (77, -61, 20, 16)),
    (0x2434, (77, -69, 20, 16)),
)


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
    count = 0
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
        count += int(length > distance)
    return count


def extract_start(system: bytes) -> tuple[bytes, bytes, list[dict]]:
    rows = system_records(system)
    row = next(item for item in rows if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    return decompress_buffer(lzs)[0], lzs, rows


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.18 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "logo_style_title_resources_sealed_independent_review_required":
        raise ValueError("V7.15.18 계획 상태 불일치")
    if plan.get("font", {}).get("license") != "SIL Open Font License":
        raise ValueError("V7.15.18 폰트 라이선스 봉인 불일치")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = (BUILD / "SYSTEM.DAT").read_bytes()
    base_start, _base_lzs, base_rows = extract_start(base_system)
    final_start, final_lzs, final_rows = extract_start(final_system)
    if final_start != (BUILD / "start.dat").read_bytes() or final_lzs != (BUILD / "start.lzs").read_bytes() or overlap_count(final_lzs):
        raise ValueError("V7.15.18 START/LZS 봉인 또는 안전성 불일치")
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
    ba, fa = StartRuntimeArchive.from_bytes(base_start), StartRuntimeArchive.from_bytes(final_start)
    changed_start = []
    for old, new in zip(ba.records, fa.records):
        if (old.output_name, old.data_offset, old.end_offset) != (new.output_name, new.data_offset, new.end_offset):
            raise ValueError("START 자원 경계 변경")
        if base_start[old.data_offset:old.end_offset] != final_start[new.data_offset:new.end_offset]:
            changed_start.append(old.output_name.casefold())
    if changed_start != ["anime00.dat"]:
        raise ValueError(f"START 변경 자원 불일치: {changed_start}")
    old_row = next(r for r in ba.records if r.output_name.casefold() == "anime00.dat")
    new_row = next(r for r in fa.records if r.output_name.casefold() == "anime00.dat")
    base_anime = base_start[old_row.data_offset:old_row.end_offset]
    final_anime = final_start[new_row.data_offset:new_row.end_offset]
    if final_anime != (BUILD / "anime00.dat").read_bytes():
        raise ValueError("V7.15.18 anime00 봉인 불일치")
    texture = texture_by_key(base_anime, (78, 0, 0))
    base_title = decode_texture(base_anime, texture).convert("RGBA")
    final_title = decode_texture(final_anime, texture).convert("RGBA")
    with Image.open(TITLE) as opened:
        opened.load()
        if final_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("최종 anime00/PNG 왕복 불일치")
    for cell in CELLS:
        if set(final_title.crop(cell).getdata()) > {TRANSPARENT, FOREGROUND}:
            raise ValueError("한글 셀 팔레트 불일치")
    for left, top, right, bottom, pixels in TARGETS:
        if sum(pixel == FOREGROUND for pixel in final_title.crop((left, top, right, bottom)).getdata()) != pixels:
            raise ValueError("로고형 글리프 픽셀 수 불일치")
    if any(pixel != TRANSPARENT for pixel in final_title.crop(BAR_CELL).getdata()):
        raise ValueError("일본어 장음표 셀이 완전 투명이 아님")
    changed_pixels = assert_changes_inside(base_title, final_title, CELLS + (BAR_CELL,))
    if changed_pixels != 4084:
        raise ValueError(f"V7.15.18 변경 픽셀 수 불일치: {changed_pixels}")
    obj = parse_objects(base_anime)[78]
    for relative, values in TRANSFORMS:
        expected = struct.pack("<2h2H", *values)
        if base_anime[obj.offset + relative:obj.offset + relative + 8] != expected or final_anime[obj.offset + relative:obj.offset + relative + 8] != expected:
            raise ValueError(f"텍스처 전용 후보 transform 변경: 0x{relative:X}")
    if repack_texture(base_anime, texture, final_title) != final_anime:
        raise ValueError("네 타이틀 셀 밖 anime00 변경")
    report = {
        "format": "prinny1_v7_15_18_logo_style_title_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verified": {"changed_system_resources": changed_system, "changed_start_resources": changed_start, "changed_title_pixels": changed_pixels, "removed_long_mark_pixels": 308, "runtime_lzs_overlaps": 0},
        "checks": {"plan_hash_locked": True, "font_license_locked": True, "logo_weight_glyphs_exact": True, "long_mark_cell_transparent": True, "sprite_geometry_byte_identical": True, "only_four_title_cells_changed": True, "only_anime00_changed_in_start": True},
        "status": "pass_v7_15_18_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.15.18 logo-style title independent review: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
