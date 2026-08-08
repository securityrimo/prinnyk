#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_1_internal_ui_plan import (
    BASE_ISO,
    CANDIDATE_ANIME,
    EXPECTED_BASE_ISO_SHA256,
    OUTPUT,
    REPORT_DIR as PLAN_DIR,
    TARGETS,
    TRANSLATIONS,
    sha256_bytes,
    sha256_file,
    textures_by_key,
)
from scripts.prinny_anime_preview import decode_texture, parse_objects


ROOT = Path(__file__).resolve().parent
PLAN = PLAN_DIR / "all_report.json"
WRITES = PLAN_DIR / "expected_write_confirmed.csv"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_1_internal_ui_review"


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("독립 검토 대상 크기가 다릅니다.")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def main() -> int:
    required = (BASE_ISO, CANDIDATE_ANIME, TRANSLATIONS, PLAN, WRITES, OUTPUT / "anime00.dat", OUTPUT / "start.dat", OUTPUT / "start.lzs", OUTPUT / "SYSTEM.DAT")
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if sha256_file(BASE_ISO) != EXPECTED_BASE_ISO_SHA256:
        raise ValueError("독립 검토 기준 ISO 해시 불일치")
    if sha256_file(WRITES) != plan["artifacts"]["expected_writes_sha256"]:
        raise ValueError("독립 검토 Expected Write 봉인 해시 불일치")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    entry = font_builder.parse_nispack_start_entry(base_system)
    old_lzs = base_system[int(entry["data_offset"]):int(entry["data_offset"]) + int(entry["size"])]
    base_start, _ = decompress_buffer(old_lzs)
    archive = StartRuntimeArchive.from_bytes(base_start, source="independent-v7.15.1-base")
    record = next(row for row in archive.records if row.output_name.casefold() == "anime00.dat")
    base_anime = base_start[int(record.data_offset):int(record.end_offset)]
    patched_anime = (OUTPUT / "anime00.dat").read_bytes()
    candidate_anime = CANDIDATE_ANIME.read_bytes()

    reconstructed = bytearray(base_anime)
    declared: set[int] = set()
    with WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if len(before) != len(after) or len(before) != int(row["length"]):
            raise ValueError(f"Expected Write 길이 오류: {row['logical_id']}")
        if reconstructed[offset:offset + len(before)] != before:
            raise ValueError(f"Expected Write before 불일치: {row['logical_id']}")
        reconstructed[offset:offset + len(after)] = after
        declared.update(offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    actual = changed_offsets(base_anime, patched_anime)
    if bytes(reconstructed) != patched_anime or actual != declared:
        raise ValueError("Expected Write 재적용 결과 또는 실제 변경 집합 불일치")
    if sha256_bytes(patched_anime) != plan["preflight"]["patched_anime_sha256"]:
        raise ValueError("패치 anime00.dat 봉인 해시 불일치")
    if len(parse_objects(base_anime)) != len(parse_objects(patched_anime)):
        raise ValueError("anime 오브젝트 구조가 바뀌었습니다.")

    base_textures = textures_by_key(base_anime)
    patched_textures = textures_by_key(patched_anime)
    candidate_textures = textures_by_key(candidate_anime)
    authorized_by_page: dict[tuple[int, int, int], list[tuple[int, int, int, int]]] = {}
    for target in TARGETS:
        key = (int(target["object"]), int(target["group"]), int(target["page"]))
        authorized_by_page.setdefault(key, []).append(tuple(int(v) for v in target["rect"]))

    excluded_candidate_pixels = 0
    changed_rgba_pixels = 0
    for key in base_textures:
        base_image = decode_texture(base_anime, base_textures[key])
        patched_image = decode_texture(patched_anime, patched_textures[key])
        candidate_image = decode_texture(candidate_anime, candidate_textures[key])
        rects = authorized_by_page.get(key, [])
        for y in range(base_image.height):
            for x in range(base_image.width):
                inside = any(left <= x < right and top <= y < bottom for left, top, right, bottom in rects)
                base_pixel = base_image.getpixel((x, y))
                patched_pixel = patched_image.getpixel((x, y))
                candidate_pixel = candidate_image.getpixel((x, y))
                if inside:
                    if patched_pixel != candidate_pixel:
                        raise ValueError(f"승인 영역 후보 픽셀 미적용: {key} ({x},{y})")
                elif patched_pixel != base_pixel:
                    raise ValueError(f"승인 영역 밖 픽셀 변경: {key} ({x},{y})")
                if patched_pixel != base_pixel:
                    changed_rgba_pixels += 1
                if not inside and candidate_pixel != base_pixel and patched_pixel == base_pixel:
                    excluded_candidate_pixels += 1
    if excluded_candidate_pixels <= 0:
        raise ValueError("승인되지 않은 후보 픽셀 제외 증거가 없습니다.")

    patched_start = (OUTPUT / "start.dat").read_bytes()
    expected_start = bytearray(base_start)
    expected_start[int(record.data_offset):int(record.end_offset)] = patched_anime
    if patched_start != bytes(expected_start):
        raise ValueError("START.DAT에 anime00.dat 외 변경이 있습니다.")
    new_lzs = (OUTPUT / "start.lzs").read_bytes()
    if decompress_buffer(new_lzs)[0] != patched_start or len(new_lzs) > len(old_lzs):
        raise ValueError("START.LZS 왕복 또는 용량 검증 실패")
    patched_system = (OUTPUT / "SYSTEM.DAT").read_bytes()
    patched_entry = font_builder.parse_nispack_start_entry(patched_system)
    embedded, _ = decompress_buffer(
        patched_system[int(patched_entry["data_offset"]):int(patched_entry["data_offset"]) + int(patched_entry["size"])]
    )
    if embedded != patched_start or len(patched_system) != len(base_system):
        raise ValueError("SYSTEM.DAT 재추출 검증 실패")

    report = {
        "format": "prinny1_v7_15_1_internal_ui_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verified": {
            "approved_targets": len(TARGETS),
            "expected_write_runs": len(rows),
            "anime_changed_bytes": len(actual),
            "changed_rgba_pixels": changed_rgba_pixels,
            "excluded_nonapproved_candidate_pixels": excluded_candidate_pixels,
            "anime_objects": len(parse_objects(patched_anime)),
            "texture_pages": len(base_textures),
        },
        "checks": {
            "fresh_base_iso_reextracted": True,
            "expected_writes_reapplied": True,
            "actual_changes_equal_declared": True,
            "approved_rectangles_equal_reference": True,
            "all_pixels_outside_approved_rectangles_equal_base": True,
            "nonapproved_candidate_pixels_excluded": True,
            "start_only_anime00_changed": True,
            "lzs_roundtrip_and_capacity": True,
            "system_reextract": True,
            "translation_wording_changed_by_codex": False,
        },
        "status": "pass_internal_ui_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Expected Writes: {len(rows)}")
    print(f"anime00 changed bytes: {len(actual)}")
    print(f"excluded nonapproved candidate pixels: {excluded_candidate_pixels}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
