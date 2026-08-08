#!/usr/bin/env python3
"""Rebuild the V7.15.5 dialogue edit with PSP-safe non-overlap LZS."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import struct
from datetime import datetime
from pathlib import Path

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from PIL import Image

from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import enlarge_title_glyphs, texture_by_key
from scripts.prinny_anime_preview import decode_texture, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
PATCHED_DEMO = ROOT / "workspace/build/prinny1_v7_15_5_character_voice_resources/Demo00.dat"
VOICE_WRITES = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_plan/expected_write_confirmed.csv"
VOICE_PLAN = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_plan/all_report.json"
TITLE_PNG = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/source_png/anime/anime00/object_078/group_00_page_00.png"
TITLE_OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_8_runtime_safe_lzs_plan"
EXPECTED = {
    BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    PATCHED_DEMO: "a7e870ad1a1561f5c57e8273689bcd5bebd8d2069eb6038f22866419dab23f26",
    VOICE_WRITES: "4c304013d28d2e5753ee7b125d8197d76fa4ff33c829898834dc5d6397346995",
    VOICE_PLAN: "42fed876faa5058c440311a444c6af81b62b98c953f5071314ef0695cf537c0c",
    TITLE_PNG: "ea5407d38d4ef2fbd4069f7b4c225a44cc0175c285e7f74fae6b163fd69f9fa1",
}


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def backreference_stats(stream: bytes) -> dict[str, int]:
    _raw, header = decompress_buffer(stream)
    flag = int(header["flag"])
    position, end = 0x10, int(header["compressed_end"])
    references = overlaps = maximum_length = 0
    while position < end:
        token = stream[position]
        position += 1
        if token != flag:
            continue
        second = stream[position]
        position += 1
        if second == flag:
            continue
        length = stream[position]
        position += 1
        distance = second if second < flag else second - 1
        references += 1
        maximum_length = max(maximum_length, length)
        overlaps += int(length > distance)
    return {"references": references, "overlapping_references": overlaps, "maximum_length": maximum_length}


def optimize_png_losslessly(blob: bytes) -> tuple[bytes, tuple[int, int]]:
    with Image.open(io.BytesIO(blob)) as opened:
        opened.load()
        size = opened.size
        expected = opened.convert("RGBA").tobytes()
        output = io.BytesIO()
        opened.save(output, format="PNG", optimize=True, compress_level=9)
    optimized = output.getvalue()
    with Image.open(io.BytesIO(optimized)) as checked:
        checked.load()
        if checked.convert("RGBA").tobytes() != expected:
            raise ValueError("시스템 PNG 무손실 최적화 픽셀이 달라졌습니다.")
    return optimized, size


def align_down(value: int, alignment: int = 0x10) -> int:
    return value - value % alignment


def rgba_pixels(blob: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(io.BytesIO(blob)) as opened:
        opened.load()
        return opened.size, opened.convert("RGBA").tobytes()


def changed_runs(before: bytes, after: bytes) -> list[tuple[int, bytes, bytes]]:
    if len(before) != len(after):
        raise ValueError("고정 크기 자원의 changed-run 길이가 다릅니다.")
    runs: list[tuple[int, bytes, bytes]] = []
    begin: int | None = None
    for index, (left, right) in enumerate(zip(before, after)):
        if left != right and begin is None:
            begin = index
        elif left == right and begin is not None:
            runs.append((begin, before[begin:index], after[begin:index]))
            begin = None
    if begin is not None:
        runs.append((begin, before[begin:], after[begin:]))
    return runs


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.8 입력 해시 불일치: {path}")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    records = system_records(base_system)
    start_record = next(row for row in records if row["name"].casefold() == "start.lzs")
    lzs_offset, old_lzs_size = start_record["data_offset"], start_record["size"]
    old_next_offset = records[start_record["index"] + 1]["data_offset"]
    old_capacity = old_next_offset - lzs_offset
    old_lzs = base_system[lzs_offset:lzs_offset + old_lzs_size]
    base_start, old_header = decompress_buffer(old_lzs)
    if backreference_stats(old_lzs)["overlapping_references"] != 0:
        raise ValueError("정상 xdelta START.LZS에 겹침 역참조가 있습니다.")
    archive = StartRuntimeArchive.from_bytes(base_start)
    demo_record = next(record for record in archive.records if record.output_name.casefold() == "demo00.dat")
    anime_record = next(record for record in archive.records if record.output_name.casefold() == "anime00.dat")
    base_demo = base_start[demo_record.data_offset:demo_record.end_offset]
    final_demo = PATCHED_DEMO.read_bytes()
    if len(base_demo) != len(final_demo):
        raise ValueError("Demo00.dat 고정 크기 불일치")

    with VOICE_WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    simulated = bytearray(base_demo)
    for row in rows:
        offset = int(row["offset_hex"], 16)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if simulated[offset:offset + len(before)] != before or len(before) != len(after):
            raise ValueError(f"V7.15.5 Expected Write 근거 불일치: {row['logical_id']}")
        simulated[offset:offset + len(after)] = after
    if bytes(simulated) != final_demo:
        raise ValueError("V7.15.5 Expected Write로 Demo00.dat 재구성 실패")

    base_anime = base_start[anime_record.data_offset:anime_record.end_offset]
    title_texture = texture_by_key(base_anime, (78, 0, 0))
    title_before = decode_texture(base_anime, title_texture)
    with Image.open(TITLE_PNG) as opened:
        title_source = opened.convert("RGBA")
    if title_source.tobytes() != title_before.tobytes():
        raise ValueError("object_078 기준 PNG와 V7.15.4 anime00.dat가 다릅니다.")
    title_after, title_changed_pixels = enlarge_title_glyphs(title_before)
    final_anime = repack_texture(base_anime, title_texture, title_after)
    if decode_texture(final_anime, title_texture).tobytes() != title_after.tobytes():
        raise ValueError("object_078 재패킹 왕복 실패")

    patched_start = bytearray(base_start)
    patched_start[demo_record.data_offset:demo_record.end_offset] = final_demo
    patched_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    for record in archive.records:
        before = base_start[record.data_offset:record.end_offset]
        after = bytes(patched_start[record.data_offset:record.end_offset])
        if record.output_name.casefold() not in {"demo00.dat", "anime00.dat"} and before != after:
            raise ValueError(f"비대상 START 자원 변경: {record.output_name}")
    new_lzs = compress_buffer_runtime_safe(bytes(patched_start), old_lzs[:4], int(old_header["flag"]))
    decoded, new_header = decompress_buffer(new_lzs)
    if decoded != bytes(patched_start):
        raise ValueError("런타임 안전 LZS 왕복 실패")
    stats = backreference_stats(new_lzs)
    if stats["overlapping_references"] != 0:
        raise ValueError("런타임 안전 LZS에 겹침 역참조가 생성됐습니다.")
    pic1_record = next(row for row in records if row["name"].casefold() == "umd_pic1.png")
    prinny_record = next(row for row in records if row["name"].casefold() == "prinny_icon0.png")
    pic1_before = base_system[pic1_record["data_offset"]:pic1_record["data_offset"] + pic1_record["size"]]
    prinny_before = base_system[prinny_record["data_offset"]:prinny_record["data_offset"] + prinny_record["size"]]
    pic1_after, pic1_size = optimize_png_losslessly(pic1_before)
    prinny_after, prinny_size = optimize_png_losslessly(prinny_before)
    file_end = len(base_system)
    new_prinny_offset = align_down(file_end - len(prinny_after))
    new_pic1_offset = align_down(new_prinny_offset - len(pic1_after))
    capacity = new_pic1_offset - lzs_offset
    if len(new_lzs) > capacity:
        raise ValueError(f"START.LZS 재배치 슬롯 초과: {len(new_lzs)}>{capacity}")
    if new_pic1_offset <= old_next_offset:
        raise ValueError("PNG 무손실 최적화로 START 슬롯이 늘어나지 않았습니다.")

    final_system = bytearray(base_system)
    final_system[lzs_offset:file_end] = bytes(file_end - lzs_offset)
    final_system[lzs_offset:lzs_offset + len(new_lzs)] = new_lzs
    final_system[new_pic1_offset:new_pic1_offset + len(pic1_after)] = pic1_after
    final_system[new_prinny_offset:new_prinny_offset + len(prinny_after)] = prinny_after
    size_at = 0x10 + start_record["index"] * 0x2C + 0x24
    struct.pack_into("<I", final_system, size_at, len(new_lzs))
    for record, offset, blob in (
        (pic1_record, new_pic1_offset, pic1_after),
        (prinny_record, new_prinny_offset, prinny_after),
    ):
        entry_at = 0x10 + record["index"] * 0x2C
        struct.pack_into("<II", final_system, entry_at + 0x20, offset, len(blob))
    final_records = system_records(bytes(final_system))
    final_start_record = next(row for row in final_records if row["name"].casefold() == "start.lzs")
    verified_start = decompress_buffer(bytes(final_system[final_start_record["data_offset"]:final_start_record["data_offset"] + final_start_record["size"]]))[0]
    if verified_start != bytes(patched_start):
        raise ValueError("최종 SYSTEM.DAT START 재추출 불일치")
    for name, expected_size, expected_pixels in (
        ("UMD_PIC1.PNG", *rgba_pixels(pic1_before)),
        ("PRINNY_ICON0.PNG", *rgba_pixels(prinny_before)),
    ):
        record = next(row for row in final_records if row["name"].casefold() == name.casefold())
        blob = bytes(final_system[record["data_offset"]:record["data_offset"] + record["size"]])
        with Image.open(io.BytesIO(blob)) as checked:
            checked.load()
            if checked.size != expected_size or checked.convert("RGBA").tobytes() != expected_pixels:
                raise ValueError(f"재배치 시스템 PNG 픽셀 불일치: {name}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "SYSTEM.DAT").write_bytes(bytes(final_system))
    (OUTPUT / "start.dat").write_bytes(bytes(patched_start))
    (OUTPUT / "start.lzs").write_bytes(new_lzs)
    (OUTPUT / "Demo00.dat").write_bytes(final_demo)
    (OUTPUT / "anime00.dat").write_bytes(final_anime)
    TITLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    title_after.save(TITLE_OUTPUT, format="PNG", optimize=True, compress_level=9)

    expected_rows = list(rows)
    for index, (offset, before, after) in enumerate(changed_runs(base_anime, final_anime), 1):
        expected_rows.append({
            "logical_id": f"P1-V7.15.8-TITLE-{index:04d}",
            "target": "START.DAT/anime00.dat",
            "offset_hex": f"0x{offset:X}",
            "write_span": str(len(after)),
            "expected_before_hex": before.hex().upper(),
            "write_after_hex": after.hex().upper(),
            "text": "시작 화면 프리니 로고 확대",
            "change_kind": "palette_preserving_title_glyph_scale",
            "expected_write_confirmed": "yes",
        })
    expected_path = REPORT_DIR / "expected_write_confirmed.csv"
    with expected_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(expected_rows[0]))
        writer.writeheader()
        writer.writerows(expected_rows)
    anime_changed = sum(left != right for left, right in zip(base_anime, final_anime))
    report = {
        "format": "prinny1_v7_15_8_runtime_safe_lzs_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cause": "v7_15_5_encoder_emitted_51778_overlapping_backreferences_not_supported_by_psp_runtime",
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "dialogue_expected_writes": len(rows),
            "demo_changed_bytes": sum(left != right for left, right in zip(base_demo, final_demo)),
            "anime00_changed_bytes": anime_changed,
            "title_changed_pixels": title_changed_pixels,
            "title_expected_write_runs": len(expected_rows) - len(rows),
            "old_lzs_size": old_lzs_size,
            "new_lzs_size": len(new_lzs),
            "lzs_capacity": capacity,
            "old_lzs_capacity": old_capacity,
            "system_tail_pngs": {
                "UMD_PIC1.PNG": {"old_size": len(pic1_before), "new_size": len(pic1_after), "old_offset": pic1_record["data_offset"], "new_offset": new_pic1_offset, "pixels_identical": True},
                "PRINNY_ICON0.PNG": {"old_size": len(prinny_before), "new_size": len(prinny_after), "old_offset": prinny_record["data_offset"], "new_offset": new_prinny_offset, "pixels_identical": True},
            },
            "old_stream_stats": backreference_stats(old_lzs),
            "new_stream_stats": stats,
            "flag": int(new_header["flag"]),
        },
        "sealed": {
            "SYSTEM.DAT": sha256_bytes(bytes(final_system)),
            "start.dat": sha256_bytes(bytes(patched_start)),
            "start.lzs": sha256_bytes(new_lzs),
            "Demo00.dat": sha256_bytes(final_demo),
            "anime00.dat": sha256_bytes(final_anime),
            "title_png": sha256_file(TITLE_OUTPUT),
            "expected_write_confirmed.csv": sha256_file(expected_path),
        },
        "checks": {"only_demo00_and_anime00_logically_changed": True, "title_source_matches_v7_15_4": True, "title_palette_preserved": True, "system_png_pixels_preserved": True, "non_overlapping_backreferences_only": True, "lzs_roundtrip": True, "slot_capacity_pass": True, "v7_15_4_base_not_modified": True, "iso_created": False},
        "status": "runtime_safe_lzs_resources_sealed_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"START.LZS: {old_lzs_size} -> {len(new_lzs)} / {capacity}")
    print(f"references: {stats['references']}, overlaps: {stats['overlapping_references']}")
    print(f"title: {title_changed_pixels} pixels, anime00: {anime_changed} bytes")
    print(f"SYSTEM.DAT: {sha256_bytes(bytes(final_system))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
