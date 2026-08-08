#!/usr/bin/env python3
"""Standardize the tutorial and save NPC names on the sealed V7.15.42 ISO."""
from __future__ import annotations

import csv
import json
import struct
from pathlib import Path

import prinny1_v7_15_41_title_subtitle_town_runtime_iso as parent
from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from prinny1_v7_15_28_title_plaque_korean_iso import changed_start_resources, overlap_count
from prinny1_v7_15_29_title_plaque_white_index_iso import extract_anime, extract_start
from prinny1_v7_15_34_text_suffix_repair_iso import records
from prinny1_v7_15_35_candidate_text_runtime_repair_iso import resource_blob, sha256_bytes
from prinny1_v7_15_38_dessert_terminology_dialogue_iso import runtime_from_start, validate_runtime_text


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_42_original_subtitle_style"
    / "prinny_korean_v7_15_42_original_subtitle_style.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_43_npc_name_standardization"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_43_npc_name_standardization.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_43_npc_name_standardization_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_43_npc_name_standardization"

EXPECTED_BASE_SHA256 = "77a52a9c093d1006d3804759472e91c593881eaa6eaf10f5c3d165f784d08246"
EXPECTED_BASE_START_SHA256 = "5b89f0c685af9efe5838627d9cf4133945e4d868730bdd3e059395573a59f0a9"
EXPECTED_BASE_ANIME_SHA256 = "3c02bb05a3c85ab7cd640014e99d9bb9b22d75ac58292392584c6becfeceda7d"
EXPECTED_BASE_FILES = {
    "BOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
    "EBOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
    "SYSTEM.DAT": (4_070_251, "766c3262e86f04a62d574854871478eeee3dd42fbf0b8a5c3bfefffa7bce2ee0"),
    "STAGE.DAT": (155_647_296, "b8d1e8169147b79d89bb1a75ba9548bec4bc8032be1dbfa5edd43149cc54c965"),
}

# Codes are sealed against the current embedded Korean font and current slots.
OLD_TUTORIAL = bytes.fromhex("F45EF457F1C2F2E1F284")          # 튜토리얼상
NEW_TUTORIAL = bytes.fromhex("F45EF457F1C2F2E1F2C6")          # 튜토리얼씨
OLD_SAVE = bytes.fromhex("F290F362F26A20F0F9F0FB")         # 세이브 담당
NEW_SAVE = bytes.fromhex("F290F362F26AF2C6")                 # 세이브씨

TUTORIAL_TOKEN_SLOTS = (
    ("Demo00.dat", 0x231B),
    ("Demo00.dat", 0x341F),
    ("Demo00.dat", 0x34A3),
    ("Demo00.dat", 0x3538),
    ("Demo00.dat", 0x85AA),
    ("PictureBook.dat", 0x8FFA),
)

SAVE_FULL_SLOTS = (
    {
        "resource": "Demo00.dat",
        "offset": 0x37BA,
        "before": bytes.fromhex("C8F290F362F26A20F0F9F0FB00"),
        "after": bytes.fromhex("C8F290F362F26AF2C600"),
        "old_text": "세이브 담당",
        "target_text": "세이브씨",
    },
    {
        "resource": "Demo00.dat",
        "offset": 0x3850,
        "before": bytes.fromhex(
            "F290F362F26A20F0F9F0FBF2E8F05620F1CEF35E20F052F1E200"
        ),
        "after": bytes.fromhex(
            "F290F362F26AF2C6F2E8F05620F1CEF35E20F052F1E200"
        ),
        "old_text": "세이브 담당에게 말을 걸면",
        "target_text": "세이브씨에게 말을 걸면",
    },
    {
        "resource": "Demo00.dat",
        "offset": 0x7EF4,
        "before": bytes.fromhex("8179F290F362F26A20F0F9F0FB8100"),
        "after": bytes.fromhex("8179F290F362F26AF2C6817AF36100"),
        "old_text": "【세이브 담당】의 (끝 글자 손상)",
        "target_text": "【세이브씨】의",
    },
)


def rewrite_report(value):
    key_replacements = {
        "subtitle": "npc_names",
        "only_anime00_changed_in_start": "only_demo00_and_picturebook_changed_in_start",
        "title_plaque_and_logo_outside_subtitle_exact": "v7_15_42_title_and_other_resources_exact",
        "v7_15_40_stage_dat_exact": "v7_15_42_stage_dat_exact",
        "v7_15_40_stage_dat_preserved": "v7_15_42_stage_dat_preserved",
    }
    if isinstance(value, str):
        value = value.replace("v7_15_41", "v7_15_43").replace("V7.15.41", "V7.15.43")
        if value == "user_requested_exact_title_subtitle_replacement_2026_08_08":
            return "user_requested_npc_name_standardization_2026_08_08"
        return value
    if isinstance(value, list):
        return [rewrite_report(item) for item in value]
    if isinstance(value, dict):
        return {
            key_replacements.get(key, key): rewrite_report(item)
            for key, item in value.items()
        }
    return value


def write_json(name: str, payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(rewrite_report(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(name: str, rows: list[dict]) -> None:
    rows = rewrite_report(rows)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def count_occurrences(start: bytes, table: dict[str, object], needle: bytes) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for row in table.values():
        blob = start[row.data_offset:row.end_offset]
        at = 0
        while True:
            offset = blob.find(needle, at)
            if offset < 0:
                break
            found.append((row.output_name, offset))
            at = offset + 1
    return found


def patch_system(base_system: bytes) -> tuple[bytes, dict[str, bytes], list[dict], dict]:
    base_start, base_lzs, start_row, system_rows = extract_start(base_system)
    if sha256_bytes(base_start) != EXPECTED_BASE_START_SHA256:
        raise ValueError("V7.15.42 START.DAT 봉인값 불일치")
    if overlap_count(base_lzs):
        raise ValueError("V7.15.42 START.LZS 겹침 역참조")
    base_anime, _anime_record = extract_anime(base_start)
    if sha256_bytes(base_anime) != EXPECTED_BASE_ANIME_SHA256:
        raise ValueError("V7.15.42 원본 스타일 타이틀 봉인값 불일치")

    table = records(base_start)
    old_tutorial_hits = count_occurrences(base_start, table, OLD_TUTORIAL)
    old_save_hits = count_occurrences(base_start, table, OLD_SAVE)
    expected_tutorial_hits = [(name, offset) for name, offset in TUTORIAL_TOKEN_SLOTS]
    expected_save_hits = [(slot["resource"], slot["offset"] + (1 if slot["offset"] == 0x37BA else 2 if slot["offset"] == 0x7EF4 else 0)) for slot in SAVE_FULL_SLOTS]
    if old_tutorial_hits != expected_tutorial_hits:
        raise ValueError(f"튜토리얼상 위치 봉인 불일치: {old_tutorial_hits}")
    if old_save_hits != expected_save_hits:
        raise ValueError(f"세이브 담당 위치 봉인 불일치: {old_save_hits}")

    final_start = bytearray(base_start)
    writes: list[dict] = []
    for number, (resource, offset) in enumerate(TUTORIAL_TOKEN_SLOTS, 1):
        row = table[resource.casefold()]
        absolute = row.data_offset + offset
        if bytes(final_start[absolute:absolute + len(OLD_TUTORIAL)]) != OLD_TUTORIAL:
            raise ValueError(f"튜토리얼상 슬롯 불일치: {resource}+0x{offset:X}")
        final_start[absolute:absolute + len(NEW_TUTORIAL)] = NEW_TUTORIAL
        writes.append({
            "id": f"P1-V7.15.43-NPC-TUTORIAL-{number:02d}",
            "resource": resource,
            "offset_hex": f"0x{offset:X}",
            "operation": "same_length_npc_name_token_replacement",
            "old_text": "튜토리얼상",
            "target_text": "튜토리얼씨",
            "write_span": len(NEW_TUTORIAL),
        })

    for number, slot in enumerate(SAVE_FULL_SLOTS, 1):
        row = table[slot["resource"].casefold()]
        absolute = row.data_offset + slot["offset"]
        before = slot["before"]
        after = slot["after"]
        if bytes(final_start[absolute:absolute + len(before)]) != before:
            raise ValueError(f"세이브 담당 슬롯 불일치: {slot['resource']}+0x{slot['offset']:X}")
        if len(after) > len(before):
            raise ValueError("세이브씨 슬롯 용량 초과")
        payload = after + bytes(len(before) - len(after))
        final_start[absolute:absolute + len(before)] = payload
        writes.append({
            "id": f"P1-V7.15.43-NPC-SAVE-{number:02d}",
            "resource": slot["resource"],
            "offset_hex": f"0x{slot['offset']:X}",
            "operation": "shorter_npc_name_slot_replacement_and_zero_fill",
            "old_text": slot["old_text"],
            "target_text": slot["target_text"],
            "write_span": len(before),
        })

    final_start_bytes = bytes(final_start)
    final_table = records(final_start_bytes)
    if changed_start_resources(base_start, final_start_bytes) != ["demo00.dat", "picturebook.dat"]:
        raise ValueError("Demo00.dat/PictureBook.dat 외 START 자원 변경")
    if count_occurrences(final_start_bytes, final_table, OLD_TUTORIAL):
        raise ValueError("튜토리얼상 잔존")
    if count_occurrences(final_start_bytes, final_table, OLD_SAVE):
        raise ValueError("세이브 담당 잔존")
    if len(count_occurrences(final_start_bytes, final_table, NEW_TUTORIAL)) != 6:
        raise ValueError("튜토리얼씨 적용 수 불일치")
    if len(count_occurrences(final_start_bytes, final_table, NEW_SAVE)) != 3:
        raise ValueError("세이브씨 적용 수 불일치")

    runtime, _runtime_records = runtime_from_start(final_start_bytes)
    for slot in SAVE_FULL_SLOTS:
        row = final_table[slot["resource"].casefold()]
        absolute = row.data_offset + slot["offset"]
        end = final_start_bytes.find(b"\0", absolute, absolute + len(slot["before"]))
        visible = final_start_bytes[absolute:end + 1]
        if visible[0] in (0xC8, 0xC9, 0xCA):
            visible = visible[1:]
        validate_runtime_text(runtime, visible)

    header = decompress_buffer(base_lzs)[1]
    final_lzs = compress_buffer_runtime_safe(final_start_bytes, base_lzs[:4], int(header["flag"]))
    if decompress_buffer(final_lzs)[0] != final_start_bytes or overlap_count(final_lzs):
        raise ValueError("START.LZS PSP 런타임 안전 왕복 실패")
    capacity = system_rows[start_row["index"] + 1]["data_offset"] - start_row["data_offset"]
    if len(final_lzs) > capacity:
        raise ValueError("START.LZS 슬롯 초과")

    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:start_row["data_offset"] + capacity] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(final_lzs)] = final_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(final_lzs))
    check_start, check_lzs, _row, _rows = extract_start(bytes(final_system))
    if check_start != final_start_bytes or check_lzs != final_lzs:
        raise ValueError("SYSTEM.DAT 재추출 불일치")

    artifacts = {
        "start.dat": final_start_bytes,
        "start.lzs": final_lzs,
        "Demo00.dat": resource_blob(final_start_bytes, final_table, "Demo00.dat"),
        "PictureBook.dat": resource_blob(final_start_bytes, final_table, "PictureBook.dat"),
    }
    metadata = {
        "requested_names": {"튜토리얼상": "튜토리얼씨", "세이브 담당": "세이브씨"},
        "tutorial_name_writes": 6,
        "save_name_writes": 3,
        "expected_write_rows": 9,
        "repaired_truncated_save_reference": "【세이브씨】의",
        "changed_start_resources": ["Demo00.dat", "PictureBook.dat"],
        "v7_15_42_title_anime_preserved_sha256": EXPECTED_BASE_ANIME_SHA256,
        "lzs_old_size": len(base_lzs),
        "lzs_new_size": len(final_lzs),
        "lzs_capacity": capacity,
        "lzs_overlap_backreferences": 0,
    }
    return bytes(final_system), artifacts, writes, metadata


def build_resources() -> tuple[dict[str, bytes], list[dict], dict, dict[str, bytes]]:
    iso_records = parent.exact_iso_records(BASE_ISO)
    base = {name: parent.iso_blob(BASE_ISO, name, iso_records) for name in parent.v40.ISO_FILES}
    for name, (size, digest) in EXPECTED_BASE_FILES.items():
        if len(base[name]) != size or sha256_bytes(base[name]) != digest:
            raise ValueError(f"V7.15.42 부모 {name} 봉인값 불일치")
    final_system, artifacts, writes, metadata = patch_system(base["SYSTEM.DAT"])
    final = dict(base)
    final["SYSTEM.DAT"] = final_system
    final.update(artifacts)
    for name in ("BOOT.BIN", "EBOOT.BIN", "STAGE.DAT"):
        if final[name] != base[name]:
            raise ValueError(f"비대상 ISO 자원 변경: {name}")
    return final, writes, metadata, {}


def configure_parent() -> None:
    parent.BASE_ISO = BASE_ISO
    parent.OUTPUT_DIR = OUTPUT_DIR
    parent.OUTPUT_ISO = OUTPUT_ISO
    parent.RESOURCE_DIR = RESOURCE_DIR
    parent.REPORT_DIR = REPORT_DIR
    parent.EXPECTED_BASE_SHA256 = EXPECTED_BASE_SHA256
    parent.EXPECTED_BASE_FILES = EXPECTED_BASE_FILES
    parent.TARGET_SUBTITLE = "NPC: 튜토리얼씨 / 세이브씨"
    parent.build_resources = build_resources
    parent.write_json = write_json
    parent.write_csv = write_csv


def main() -> int:
    configure_parent()
    parent.seal()
    parent.independent_prebuild()
    build = parent.build_iso()
    review = parent.independent_postbuild()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print("NPC: 튜토리얼씨 / 세이브씨")
    print("PPSSPP: not launched")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
