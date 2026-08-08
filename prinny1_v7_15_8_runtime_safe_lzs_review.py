#!/usr/bin/env python3
"""Independent prebuild review for the V7.15.8 runtime-safe START rebuild."""
from __future__ import annotations

import csv
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


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs_resources"
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_15_8_runtime_safe_lzs_plan"
TITLE_PNG = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_8_runtime_safe_lzs_review"
EXPECTED = {
    BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    RESOURCE_DIR / "SYSTEM.DAT": "5514a39827488f1103ba02bac0b38ff6e5624abfadb069137c6d8bbe17c7206d",
    RESOURCE_DIR / "start.dat": "50196d74ade8dc7ec187d4e85885df7e25ac325e1d3e298b09d91b3eab1b0215",
    RESOURCE_DIR / "start.lzs": "02696275237d05052c377453b1a9dce178950712fb3a830a74d0cc7ed3818c21",
    RESOURCE_DIR / "Demo00.dat": "a7e870ad1a1561f5c57e8273689bcd5bebd8d2069eb6038f22866419dab23f26",
    RESOURCE_DIR / "anime00.dat": "e452f62e983038f25139e6c28d032cf1070e80a72f263eea1910598845b539cb",
    PLAN_DIR / "all_report.json": "7b1ee450b431da88c3568adc9900ac92b8e731ec99bb06fc45b2cb12d3789a94",
    PLAN_DIR / "expected_write_confirmed.csv": "d72ae0b534cebe83ef3e2b2019240a0b6df8afe5e2cbd613df20446a254d9e6c",
    TITLE_PNG: "b1e2c6ca15d2ea69a767f73e222ad88acd7a80de88626521b91898f3cb75db36",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("독립 검토 고정 크기 불일치")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


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


def png_rgba(blob: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(io.BytesIO(blob)) as opened:
        opened.load()
        return opened.size, opened.convert("RGBA").tobytes()


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.8 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads((PLAN_DIR / "all_report.json").read_text(encoding="utf-8"))
    if plan.get("status") != "runtime_safe_lzs_resources_sealed_independent_review_required":
        raise ValueError("V7.15.8 계획 봉인 상태 불일치")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    base_rows, final_rows = system_records(base_system), system_records(final_system)
    if [row["name"] for row in base_rows] != [row["name"] for row in final_rows]:
        raise ValueError("SYSTEM NISPACK 자원 목록 변경")
    base_by_name = {row["name"].casefold(): row for row in base_rows}
    final_by_name = {row["name"].casefold(): row for row in final_rows}
    changed_system_resources = []
    for name, base_row in base_by_name.items():
        final_row = final_by_name[name]
        before = base_system[base_row["data_offset"]:base_row["data_offset"] + base_row["size"]]
        after = final_system[final_row["data_offset"]:final_row["data_offset"] + final_row["size"]]
        if before != after or (base_row["data_offset"], base_row["size"]) != (final_row["data_offset"], final_row["size"]):
            changed_system_resources.append(name)
    if changed_system_resources != ["start.lzs", "umd_pic1.png", "prinny_icon0.png"]:
        raise ValueError(f"SYSTEM 변경 자원 집합 불일치: {changed_system_resources}")

    base_lzs_row, final_lzs_row = base_by_name["start.lzs"], final_by_name["start.lzs"]
    base_lzs = base_system[base_lzs_row["data_offset"]:base_lzs_row["data_offset"] + base_lzs_row["size"]]
    final_lzs = final_system[final_lzs_row["data_offset"]:final_lzs_row["data_offset"] + final_lzs_row["size"]]
    base_start = decompress_buffer(base_lzs)[0]
    final_start = decompress_buffer(final_lzs)[0]
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or overlap_count(final_lzs) != 0:
        raise ValueError("런타임 안전 LZS 왕복/겹침 검증 실패")
    base_archive = StartRuntimeArchive.from_bytes(base_start)
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    if [(r.output_name, r.data_offset, r.end_offset) for r in base_archive.records] != [(r.output_name, r.data_offset, r.end_offset) for r in final_archive.records]:
        raise ValueError("START 자원 테이블 또는 경계 변경")
    base_records = {r.output_name.casefold(): r for r in base_archive.records}
    final_records = {r.output_name.casefold(): r for r in final_archive.records}
    changed_start_resources = []
    for name, base_record in base_records.items():
        final_record = final_records[name]
        if base_start[base_record.data_offset:base_record.end_offset] != final_start[final_record.data_offset:final_record.end_offset]:
            changed_start_resources.append(name)
    if set(changed_start_resources) != {"demo00.dat", "anime00.dat"}:
        raise ValueError(f"START 변경 자원 집합 불일치: {changed_start_resources}")

    writes = read_csv(PLAN_DIR / "expected_write_confirmed.csv")
    voice_rows = [row for row in writes if row["target"] == "START.DAT/Demo00.dat"]
    title_rows = [row for row in writes if row["target"] == "START.DAT/anime00.dat"]
    if len(voice_rows) != 11 or not title_rows:
        raise ValueError("Expected Write 대상/행 수 불일치")
    for resource_name, rows in (("demo00.dat", voice_rows), ("anime00.dat", title_rows)):
        base_record, final_record = base_records[resource_name], final_records[resource_name]
        before_resource = base_start[base_record.data_offset:base_record.end_offset]
        final_resource = final_start[final_record.data_offset:final_record.end_offset]
        simulated = bytearray(before_resource)
        declared: set[int] = set()
        for row in rows:
            offset = int(row["offset_hex"], 0)
            before, after = bytes.fromhex(row["expected_before_hex"]), bytes.fromhex(row["write_after_hex"])
            if len(before) != int(row["write_span"]) or len(after) != len(before) or simulated[offset:offset + len(before)] != before:
                raise ValueError(f"Expected Write 경계/before 불일치: {row['logical_id']}")
            simulated[offset:offset + len(after)] = after
            declared.update(offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
        if bytes(simulated) != final_resource or declared != changed_offsets(before_resource, final_resource):
            raise ValueError(f"Expected Write 재구성 실패: {resource_name}")

    final_anime = (RESOURCE_DIR / "anime00.dat").read_bytes()
    texture = texture_by_key(final_anime, (78, 0, 0))
    decoded = decode_texture(final_anime, texture).convert("RGBA")
    with Image.open(TITLE_PNG) as opened:
        opened.load()
        if decoded.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("확대 타이틀 PNG/anime00.dat 왕복 불일치")

    for name in ("umd_pic1.png", "prinny_icon0.png"):
        base_row, final_row = base_by_name[name], final_by_name[name]
        before = base_system[base_row["data_offset"]:base_row["data_offset"] + base_row["size"]]
        after = final_system[final_row["data_offset"]:final_row["data_offset"] + final_row["size"]]
        if png_rgba(before) != png_rgba(after):
            raise ValueError(f"SYSTEM PNG 픽셀 변경: {name}")

    allowed = set(range(base_lzs_row["data_offset"], len(base_system)))
    for name in ("start.lzs", "umd_pic1.png", "prinny_icon0.png"):
        row = base_by_name[name]
        entry = 0x10 + row["index"] * 0x2C
        allowed.update(range(entry + 0x20, entry + 0x28))
    if not changed_offsets(base_system, final_system) <= allowed:
        raise ValueError("SYSTEM 허용 범위 밖 변경")

    report = {
        "format": "prinny1_v7_15_8_runtime_safe_lzs_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {"expected_writes": len(writes), "voice_writes": len(voice_rows), "title_write_runs": len(title_rows), "changed_start_resources": changed_start_resources, "changed_system_resources": changed_system_resources, "runtime_lzs_overlaps": 0},
        "checks": {"plan_hash_locked": True, "expected_writes_reconstruct_both_resources": True, "start_only_demo_and_anime_changed": True, "title_png_roundtrip_exact": True, "system_png_pixels_exact": True, "runtime_lzs_non_overlap": True, "system_changes_bounded": True, "base_iso_not_modified": True},
        "status": "pass_v7_15_8_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Expected Writes: {len(writes)} (voice {len(voice_rows)}, title {len(title_rows)})")
    print("LZS overlaps: 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
