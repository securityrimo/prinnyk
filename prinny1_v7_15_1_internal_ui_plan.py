#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from PIL import Image

import core.font_builder as font_builder
from core.lzs import compress_buffer, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from scripts.prinny_anime_preview import (
    decode_texture,
    find_texture_groups,
    parse_objects,
    repack_texture,
)


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_0_full_korean_baseline/prinny_korean_v7_15_0_full_text_baseline.iso"
CANDIDATE_ANIME = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start_resources/anime00.dat"
TRANSLATIONS = ROOT / "workspace/translations/ui_v7_14_15/title_difficulty_translation.csv"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_1_internal_ui_plan"

EXPECTED_BASE_ISO_SHA256 = "491f147225bbb665f98c41dcbb3c66843a0875427d793c97aec743dc075b891e"
EXPECTED_CANDIDATE_ANIME_SHA256 = "4db8d10bc5c6ccc0e0d6f392d91f82cddcffae573e5a477c47646a4cfa71f55e"

# Half-open rectangles. Only pixels spelling the five user-approved strings are copied.
TARGETS = (
    {"id": "P1-UI-TITLE-001", "text": "처음부터", "object": 78, "group": 0, "page": 0, "rect": (280, 238, 366, 263)},
    {"id": "P1-UI-TITLE-002", "text": "이어하기", "object": 78, "group": 0, "page": 0, "rect": (280, 265, 366, 288)},
    {"id": "P1-UI-TITLE-003", "text": "설정", "object": 78, "group": 0, "page": 0, "rect": (300, 288, 346, 311)},
    {"id": "P1-UI-TITLE-004", "text": "데이터 교환", "object": 78, "group": 0, "page": 0, "rect": (426, 136, 501, 159)},
    {"id": "P1-UI-DIFFICULTY-001", "text": "난이도 설정", "object": 82, "group": 0, "page": 0, "rect": (18, 156, 131, 184)},
)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_approved_translations() -> dict[str, str]:
    with TRANSLATIONS.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["id"]: row["translation_korean"] for row in csv.DictReader(handle)}


def textures_by_key(blob: bytes) -> dict[tuple[int, int, int], object]:
    result = {}
    for obj in parse_objects(blob):
        for group in find_texture_groups(blob, obj):
            for texture in group:
                result[(texture.object_index, texture.group_index, texture.page_index)] = texture
    return result


def changed_runs(before: bytes, after: bytes) -> list[tuple[int, int]]:
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not changed:
        return []
    runs = []
    start = previous = changed[0]
    for index in changed[1:]:
        if index != previous + 1:
            runs.append((start, previous + 1))
            start = index
        previous = index
    runs.append((start, previous + 1))
    return runs


def main() -> int:
    for path in (BASE_ISO, CANDIDATE_ANIME, TRANSLATIONS):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(BASE_ISO) != EXPECTED_BASE_ISO_SHA256:
        raise ValueError("V7.15.0 기준 ISO 해시가 다릅니다.")
    if sha256_file(CANDIDATE_ANIME) != EXPECTED_CANDIDATE_ANIME_SHA256:
        raise ValueError("xdelta 참고 anime00.dat 해시가 다릅니다.")

    approved = read_approved_translations()
    for target in TARGETS:
        if approved.get(str(target["id"])) != target["text"]:
            raise ValueError(f"사용자 승인 번역 불일치: {target['id']}")

    system_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    base_system = read_iso_file(BASE_ISO, system_record)
    start_entry = font_builder.parse_nispack_start_entry(base_system)
    lzs_offset = int(start_entry["data_offset"])
    old_lzs_size = int(start_entry["size"])
    old_lzs = base_system[lzs_offset:lzs_offset + old_lzs_size]
    base_start, _ = decompress_buffer(old_lzs)
    archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    record = next(
        row for row in archive.records if row.output_name.casefold() == "anime00.dat"
    )
    base_anime = base_start[int(record.data_offset):int(record.end_offset)]
    candidate_anime = CANDIDATE_ANIME.read_bytes()
    if len(base_anime) != len(candidate_anime):
        raise ValueError("anime00.dat 기준/후보 크기가 다릅니다.")

    base_textures = textures_by_key(base_anime)
    candidate_textures = textures_by_key(candidate_anime)
    if set(base_textures) != set(candidate_textures):
        raise ValueError("anime00.dat 텍스처 페이지 목록이 다릅니다.")

    grouped: dict[tuple[int, int, int], list[dict[str, object]]] = {}
    for target in TARGETS:
        key = (int(target["object"]), int(target["group"]), int(target["page"]))
        grouped.setdefault(key, []).append(target)

    patched_anime = base_anime
    target_reports = []
    authorized_pixel_changes = 0
    for key, targets in grouped.items():
        base_texture = base_textures[key]
        candidate_texture = candidate_textures[key]
        if base_texture != candidate_texture:
            raise ValueError(f"텍스처 메타데이터 불일치: {key}")
        palette_start = int(base_texture.palette_offset)
        if base_anime[palette_start:palette_start + 64] != candidate_anime[palette_start:palette_start + 64]:
            raise ValueError(f"텍스처 팔레트 불일치: {key}")
        base_image = decode_texture(base_anime, base_texture)
        candidate_image = decode_texture(candidate_anime, candidate_texture)
        edited = base_image.copy()
        for target in targets:
            rect = tuple(int(value) for value in target["rect"])
            edited.paste(candidate_image.crop(rect), (rect[0], rect[1]))
            diff_count = sum(
                base_image.getpixel((x, y)) != candidate_image.getpixel((x, y))
                for y in range(rect[1], rect[3])
                for x in range(rect[0], rect[2])
            )
            if diff_count <= 0:
                raise ValueError(f"승인 영역에 실제 픽셀 변경이 없습니다: {target['id']}")
            authorized_pixel_changes += diff_count
            target_reports.append({**target, "rect": list(rect), "changed_rgba_pixels": diff_count})
        for y in range(base_image.height):
            for x in range(base_image.width):
                if base_image.getpixel((x, y)) == edited.getpixel((x, y)):
                    continue
                if not any(
                    int(t["rect"][0]) <= x < int(t["rect"][2])
                    and int(t["rect"][1]) <= y < int(t["rect"][3])
                    for t in targets
                ):
                    raise ValueError(f"승인 사각형 밖 픽셀 변경: {key} ({x},{y})")
        patched_anime = repack_texture(patched_anime, base_texture, edited)

    if len(patched_anime) != len(base_anime):
        raise ValueError("패치 anime00.dat 크기가 변경됐습니다.")
    parse_objects(patched_anime)
    runs = changed_runs(base_anime, patched_anime)
    changed_bytes = sum(end - start for start, end in runs)
    if changed_bytes <= 0:
        raise ValueError("anime00.dat 실제 변경이 없습니다.")

    patched_start = bytearray(base_start)
    patched_start[int(record.data_offset):int(record.end_offset)] = patched_anime
    new_lzs = compress_buffer(bytes(patched_start), old_lzs[:4])
    decoded, _ = decompress_buffer(new_lzs)
    if decoded != bytes(patched_start):
        raise ValueError("START.LZS 압축 왕복 실패")
    if len(new_lzs) > old_lzs_size:
        raise ValueError(f"SYSTEM.DAT START 슬롯 초과: {len(new_lzs)}>{old_lzs_size}")
    patched_system = bytearray(base_system)
    patched_system[lzs_offset:lzs_offset + old_lzs_size] = new_lzs + bytes(old_lzs_size - len(new_lzs))
    struct.pack_into("<I", patched_system, int(start_entry["entry_offset"]) + 0x24, len(new_lzs))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "anime00.dat").write_bytes(patched_anime)
    (OUTPUT / "start.dat").write_bytes(bytes(patched_start))
    (OUTPUT / "start.lzs").write_bytes(new_lzs)
    (OUTPUT / "SYSTEM.DAT").write_bytes(bytes(patched_system))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    writes_path = REPORT_DIR / "expected_write_confirmed.csv"
    with writes_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["logical_id", "target", "offset_hex", "length", "expected_before_hex", "write_after_hex"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, (start, end) in enumerate(runs, 1):
            writer.writerow({
                "logical_id": f"P1-V7.15.1-ANIME00-{index:04d}",
                "target": "START.DAT/anime00.dat",
                "offset_hex": f"0x{start:X}",
                "length": end - start,
                "expected_before_hex": base_anime[start:end].hex(),
                "write_after_hex": patched_anime[start:end].hex(),
            })
    report = {
        "format": "prinny1_v7_15_1_internal_ui_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "reference": {"path": str(CANDIDATE_ANIME), "sha256": sha256_file(CANDIDATE_ANIME), "role": "pixel_location_reference_only"},
        "translation_source": {"path": str(TRANSLATIONS), "sha256": sha256_file(TRANSLATIONS), "authoritative": "user"},
        "targets": target_reports,
        "verified": {
            "approved_texture_targets": len(TARGETS),
            "authorized_rgba_pixel_changes": authorized_pixel_changes,
            "expected_write_runs": len(runs),
            "anime_changed_bytes": changed_bytes,
            "anime_size_preserved": len(patched_anime),
            "anime_object_count": len(parse_objects(patched_anime)),
            "start_lzs_size": len(new_lzs),
            "start_lzs_capacity": old_lzs_size,
        },
        "preflight": {
            "base_anime_sha256": sha256_bytes(base_anime),
            "patched_anime_sha256": sha256_bytes(patched_anime),
            "base_start_sha256": sha256_bytes(base_start),
            "patched_start_sha256": sha256_bytes(bytes(patched_start)),
            "new_lzs_sha256": sha256_bytes(new_lzs),
            "patched_system_sha256": sha256_bytes(bytes(patched_system)),
        },
        "artifacts": {
            "expected_writes": str(writes_path),
            "expected_writes_sha256": sha256_file(writes_path),
            "resources": str(OUTPUT),
        },
        "checks": {
            "candidate_nonapproved_regions_imported": False,
            "only_user_approved_pixel_rectangles_changed": True,
            "palettes_byte_identical": True,
            "metadata_byte_identical": True,
            "translation_wording_changed_by_codex": False,
            "lzs_roundtrip": True,
            "iso_created": False,
        },
        "status": "pass_internal_ui_resources_built_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"targets: {len(TARGETS)}")
    print(f"anime00 changed bytes: {changed_bytes} in {len(runs)} runs")
    print(f"START LZS: {len(new_lzs)} / {old_lzs_size}")
    print(f"report: {REPORT_DIR / 'all_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
