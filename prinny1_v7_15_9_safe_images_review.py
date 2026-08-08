#!/usr/bin/env python3
"""Independent prebuild review for the V7.15.9 safe Korean image set."""
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
from scripts.prinny_anime_preview import decode_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs/prinny_korean_v7_15_8_runtime_safe_lzs.iso"
XDELTA_BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_9_safe_images_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_9_safe_images_plan/all_report.json"
TITLE_PNG = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_9/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_9_safe_images_review"
TRANSLATED = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized"

EXPECTED = {
    BASE_ISO: "4ee4198acd01cbb4bda08e7b0d76b1cea3dea7de95e36b295ff6eede90876f6e",
    XDELTA_BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    RESOURCE_DIR / "SYSTEM.DAT": "71a2df867e45579aa91de0c3a5344f93a28669c0a40982278aacb9e3d96e97bf",
    RESOURCE_DIR / "start.dat": "25a4012feb4e468bd8fb21fec9dcece5d8f6407967894d08ef803741edc0ffac",
    RESOURCE_DIR / "start.lzs": "4ddc9394a721f7e2b8c2cda5e3673ce0e43433bcaa26584eea42dca5481a1ea1",
    RESOURCE_DIR / "anime00.dat": "791bff25ce7b499278b3e0e092dd587dcaef718782ad82c9517a5196dd835f57",
    RESOURCE_DIR / "ANIME.DAT": "8a26453874bafb6f800ab3fe2c3cd9eb6ccd4aa43679016b59fea10d2f385d77",
    RESOURCE_DIR / "BG.DAT": "45f0de733dbf8ee53300090afceef5e8e52387e19c28c79b4631f59b49b0e068",
    RESOURCE_DIR / "direct_iso/ICON0.PNG": "960555d1ef29d26eeea56bbf45b6c52723d31e062ecbbea7f7c0db576f1b2e80",
    RESOURCE_DIR / "direct_iso/PIC0.PNG": "5be9973e574f552443d0a7c77d00425719c193d85359ea1930f296ec685d3aa8",
    TITLE_PNG: "f5276c8fd5ea9c8a54b46095c31ed4978c6a19f80e1faea018ee4e5bbd17e539",
    PLAN: "53a5a310ecbe244289b45c7f6f4e25f8b2fd51ad7c9e300a65e5b3606c742461",
}

SYSTEM_IMAGES = {
    "replay_icon0.png": TRANSLATED / "system_pack/REPLAY_ICON0.PNG",
    "umd_icon0.png": TRANSLATED / "system_pack/UMD_ICON0.PNG",
    "umd_pic0.png": TRANSLATED / "system_pack/UMD_PIC0.PNG",
    "prinny_icon0.png": TRANSLATED / "system_pack/PRINNY_ICON0.PNG",
}
TITLE_GLYPHS = (
    ((273, 181, 303, 212), (269, 177, 307, 216)),
    ((331, 161, 359, 187), (327, 158, 362, 191)),
    ((381, 159, 409, 186), (377, 156, 412, 190)),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("고정 크기 비교 길이 불일치")
    return {index for index, (old, new) in enumerate(zip(before, after)) if old != new}


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


def changed_pack_resources(before: bytes, after: bytes) -> list[str]:
    before_rows, after_rows = system_records(before), system_records(after)
    if [(r["name"], r["data_offset"]) for r in before_rows] != [(r["name"], r["data_offset"]) for r in after_rows]:
        raise ValueError("NISPACK 자원 목록/오프셋 변경")
    changed = []
    for old, new in zip(before_rows, after_rows):
        old_blob = before[old["data_offset"]:old["data_offset"] + old["size"]]
        new_blob = after[new["data_offset"]:new["data_offset"] + new["size"]]
        if old_blob != new_blob or old["size"] != new["size"]:
            changed.append(old["name"].casefold())
    return changed


def png_rgba(blob: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(io.BytesIO(blob)) as opened:
        opened.load()
        return opened.size, opened.convert("RGBA").tobytes()


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.9 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "safe_image_resources_sealed_independent_review_required":
        raise ValueError("V7.15.9 계획 봉인 상태 불일치")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    base_rows, final_rows = system_records(base_system), system_records(final_system)
    base_by_name = {row["name"].casefold(): row for row in base_rows}
    final_by_name = {row["name"].casefold(): row for row in final_rows}
    if [row["name"] for row in base_rows] != [row["name"] for row in final_rows]:
        raise ValueError("SYSTEM 자원 목록 변경")
    system_changes = changed_pack_resources(base_system, final_system)
    expected_system = ["replay_icon0.png", "umd_icon0.png", "umd_pic0.png", "start.lzs", "prinny_icon0.png"]
    if system_changes != expected_system:
        raise ValueError(f"SYSTEM 변경 자원 집합 불일치: {system_changes}")

    base_lzs_row, final_lzs_row = base_by_name["start.lzs"], final_by_name["start.lzs"]
    base_lzs = base_system[base_lzs_row["data_offset"]:base_lzs_row["data_offset"] + base_lzs_row["size"]]
    final_lzs = final_system[final_lzs_row["data_offset"]:final_lzs_row["data_offset"] + final_lzs_row["size"]]
    base_start, final_start = decompress_buffer(base_lzs)[0], decompress_buffer(final_lzs)[0]
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or overlap_count(final_lzs) != 0:
        raise ValueError("START.LZS 왕복 또는 런타임 안전성 실패")
    base_archive, final_archive = StartRuntimeArchive.from_bytes(base_start), StartRuntimeArchive.from_bytes(final_start)
    base_records = {r.output_name.casefold(): r for r in base_archive.records}
    final_records = {r.output_name.casefold(): r for r in final_archive.records}
    if [(r.output_name, r.data_offset, r.end_offset) for r in base_archive.records] != [(r.output_name, r.data_offset, r.end_offset) for r in final_archive.records]:
        raise ValueError("START 자원 테이블/경계 변경")
    start_changes = []
    for name, old in base_records.items():
        new = final_records[name]
        if base_start[old.data_offset:old.end_offset] != final_start[new.data_offset:new.end_offset]:
            start_changes.append(name)
    if start_changes != ["anime00.dat"]:
        raise ValueError(f"START 변경 자원 집합 불일치: {start_changes}")
    final_anime = final_start[final_records["anime00.dat"].data_offset:final_records["anime00.dat"].end_offset]
    if final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("최종 anime00.dat 봉인본 불일치")

    xdelta_system = read_iso_file(XDELTA_BASE_ISO, find_iso_file(XDELTA_BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    xdelta_lzs_row = next(r for r in system_records(xdelta_system) if r["name"].casefold() == "start.lzs")
    xdelta_start = decompress_buffer(xdelta_system[xdelta_lzs_row["data_offset"]:xdelta_lzs_row["data_offset"] + xdelta_lzs_row["size"]])[0]
    xdelta_archive = StartRuntimeArchive.from_bytes(xdelta_start)
    xdelta_record = next(r for r in xdelta_archive.records if r.output_name.casefold() == "anime00.dat")
    original_anime = xdelta_start[xdelta_record.data_offset:xdelta_record.end_offset]
    original_texture = texture_by_key(original_anime, (78, 0, 0))
    final_texture = texture_by_key(final_anime, (78, 0, 0))
    original_title = decode_texture(original_anime, original_texture).convert("RGBA")
    decoded_title = decode_texture(final_anime, final_texture).convert("RGBA")
    independently_rebuilt = original_title.copy()
    transparent = original_title.getpixel((511, 511))
    allowed = []
    for source_rect, target_rect in TITLE_GLYPHS:
        independently_rebuilt.paste(transparent, target_rect)
        crop = original_title.crop(source_rect).resize(
            (target_rect[2] - target_rect[0], target_rect[3] - target_rect[1]),
            Image.Resampling.NEAREST,
        )
        independently_rebuilt.paste(crop, target_rect[:2])
        allowed.append(target_rect)
    if decoded_title.tobytes() != independently_rebuilt.tobytes():
        raise ValueError("타이틀 독립 재구성 불일치")
    with Image.open(TITLE_PNG) as opened:
        opened.load()
        if decoded_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("타이틀 PNG/anime00 왕복 불일치")
    title_changed = assert_changes_inside(original_title, decoded_title, tuple(allowed))
    if title_changed != 892 or not set(decoded_title.getdata()).issubset(set(original_title.getdata())):
        raise ValueError("타이틀 변경 픽셀 수 또는 팔레트 불일치")

    for name, source in SYSTEM_IMAGES.items():
        row = final_by_name[name]
        blob = final_system[row["data_offset"]:row["data_offset"] + row["size"]]
        if blob != source.read_bytes() or png_rgba(blob)[0] not in {(144, 80), (310, 180)}:
            raise ValueError(f"SYSTEM 한글 PNG 불일치: {name}")

    allowed_system: set[int] = set()
    for name in expected_system:
        row = base_by_name[name]
        following = base_rows[row["index"] + 1]["data_offset"] if row["index"] + 1 < len(base_rows) else len(base_system)
        allowed_system.update(range(row["data_offset"], following))
        entry = 0x10 + row["index"] * 0x2C
        allowed_system.update(range(entry + 0x24, entry + 0x28))
    if not changed_offsets(base_system, final_system) <= allowed_system:
        raise ValueError("SYSTEM 허용 범위 밖 변경")

    base_anime_pack = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "ANIME.DAT"]))
    base_bg_pack = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "BG.DAT"]))
    anime_changes = changed_pack_resources(base_anime_pack, (RESOURCE_DIR / "ANIME.DAT").read_bytes())
    bg_changes = changed_pack_resources(base_bg_pack, (RESOURCE_DIR / "BG.DAT").read_bytes())
    if anime_changes != ["anime96.dat"] or bg_changes != ["bg9803.txp"]:
        raise ValueError(f"외부 이미지 팩 변경 집합 불일치: {anime_changes}/{bg_changes}")

    for name in ("ICON0.PNG", "PIC0.PNG"):
        direct = (RESOURCE_DIR / "direct_iso" / name).read_bytes()
        record = find_iso_file(BASE_ISO, ["PSP_GAME", name])
        if len(direct) > int(record["data_length"]):
            raise ValueError(f"직결 PNG ISO 영역 초과: {name}")
        if png_rgba(direct)[0] != ((144, 80) if name == "ICON0.PNG" else (310, 180)):
            raise ValueError(f"직결 PNG 캔버스 불일치: {name}")

    report = {
        "format": "prinny1_v7_15_9_safe_images_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "changed_system_resources": system_changes,
            "changed_start_resources": start_changes,
            "changed_anime_resources": anime_changes,
            "changed_bg_resources": bg_changes,
            "title_changed_pixels": title_changed,
            "runtime_lzs_overlaps": 0,
        },
        "checks": {
            "plan_hash_locked": True,
            "title_independently_reconstructed": True,
            "title_original_palette_only": True,
            "start_only_anime00_changed_from_v7_15_8": True,
            "dialogue_and_other_start_resources_preserved": True,
            "runtime_lzs_non_overlap": True,
            "system_image_slots_exact": True,
            "anime96_and_bg9803_only_external_pack_changes": True,
            "direct_png_extents_fit": True,
            "base_iso_not_modified": True,
        },
        "status": "pass_v7_15_9_test_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SYSTEM resources: {', '.join(system_changes)}")
    print(f"START resources: {', '.join(start_changes)}; LZS overlaps: 0")
    print(f"ANIME/BG resources: {anime_changes}/{bg_changes}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
