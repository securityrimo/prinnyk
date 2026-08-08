#!/usr/bin/env python3
"""Independent postbuild review for the V7.15.9 PSP test ISO."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs/prinny_korean_v7_15_8_runtime_safe_lzs.iso"
ISO = ROOT / "workspace/build/prinny1_v7_15_9_safe_images/prinny_korean_v7_15_9_safe_images.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_9_safe_images_resources"
BUILD_REPORT = ROOT / "workspace/reports/prinny1_v7_15_9_safe_images_iso/all_report.json"
TITLE_PNG = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_9/anime/anime00/object_078/group_00_page_00.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_9_safe_images_iso_review"

EXPECTED = {
    BASE_ISO: "4ee4198acd01cbb4bda08e7b0d76b1cea3dea7de95e36b295ff6eede90876f6e",
    ISO: "f16cb548f77c094f4e01411c04b5ae5028bcdb3093d8a953727fd62bbae097f1",
    RESOURCE_DIR / "SYSTEM.DAT": "71a2df867e45579aa91de0c3a5344f93a28669c0a40982278aacb9e3d96e97bf",
    RESOURCE_DIR / "ANIME.DAT": "8a26453874bafb6f800ab3fe2c3cd9eb6ccd4aa43679016b59fea10d2f385d77",
    RESOURCE_DIR / "BG.DAT": "45f0de733dbf8ee53300090afceef5e8e52387e19c28c79b4631f59b49b0e068",
    RESOURCE_DIR / "direct_iso/ICON0.PNG": "960555d1ef29d26eeea56bbf45b6c52723d31e062ecbbea7f7c0db576f1b2e80",
    RESOURCE_DIR / "direct_iso/PIC0.PNG": "5be9973e574f552443d0a7c77d00425719c193d85359ea1930f296ec685d3aa8",
    TITLE_PNG: "f5276c8fd5ea9c8a54b46095c31ed4978c6a19f80e1faea018ee4e5bbd17e539",
}


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


def png_canvas(blob: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(blob)) as opened:
        opened.load()
        return opened.size


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.9 사후 검토 입력 해시 불일치: {path}")
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if build.get("status") != "pass_v7_15_9_test_iso_built_independent_post_review_required":
        raise ValueError("V7.15.9 빌드 보고서 상태 불일치")

    targets = (
        (["PSP_GAME", "USRDIR", "SYSTEM.DAT"], RESOURCE_DIR / "SYSTEM.DAT", False),
        (["PSP_GAME", "USRDIR", "ANIME.DAT"], RESOURCE_DIR / "ANIME.DAT", False),
        (["PSP_GAME", "USRDIR", "BG.DAT"], RESOURCE_DIR / "BG.DAT", False),
        (["PSP_GAME", "ICON0.PNG"], RESOURCE_DIR / "direct_iso/ICON0.PNG", True),
        (["PSP_GAME", "PIC0.PNG"], RESOURCE_DIR / "direct_iso/PIC0.PNG", True),
    )
    intervals = []
    for iso_path, source, padded in targets:
        base_record, final_record = find_iso_file(BASE_ISO, iso_path), find_iso_file(ISO, iso_path)
        if (base_record["extent_lba"], base_record["data_length"]) != (final_record["extent_lba"], final_record["data_length"]):
            raise ValueError(f"ISO 디렉터리 레코드 변경: {'/'.join(iso_path)}")
        expected_blob = source.read_bytes()
        extracted = read_iso_file(ISO, final_record)
        if padded:
            if extracted[:len(expected_blob)] != expected_blob or any(extracted[len(expected_blob):]):
                raise ValueError(f"직결 PNG 재추출/패딩 불일치: {'/'.join(iso_path)}")
        elif extracted != expected_blob:
            raise ValueError(f"내부 팩 재추출 불일치: {'/'.join(iso_path)}")
        offset = int(base_record["extent_lba"]) * SECTOR_SIZE
        intervals.append((offset, offset + int(base_record["data_length"])))

    cursor = 0
    for left, right in merge_intervals(intervals):
        if hash_range(BASE_ISO, cursor, left) != hash_range(ISO, cursor, left):
            raise ValueError("허용된 5개 ISO 범위 밖 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(ISO, cursor, ISO.stat().st_size):
        raise ValueError("마지막 허용 범위 뒤 ISO 변경")

    final_system = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(final_system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    final_lzs = final_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    final_start = decompress_buffer(final_lzs)[0]
    if overlap_count(final_lzs) != 0 or hashlib.sha256(final_start).hexdigest() != "25a4012feb4e468bd8fb21fec9dcece5d8f6407967894d08ef803741edc0ffac":
        raise ValueError("최종 ISO START 압축 안전성/해시 불일치")
    archive = StartRuntimeArchive.from_bytes(final_start)
    anime_record = next(r for r in archive.records if r.output_name.casefold() == "anime00.dat")
    anime00 = final_start[anime_record.data_offset:anime_record.end_offset]
    texture = texture_by_key(anime00, (78, 0, 0))
    decoded_title = decode_texture(anime00, texture).convert("RGBA")
    with Image.open(TITLE_PNG) as opened:
        opened.load()
        if decoded_title.tobytes() != opened.convert("RGBA").tobytes():
            raise ValueError("최종 ISO 타이틀 PNG 왕복 불일치")

    system_canvases = {}
    for name in ("REPLAY_ICON0.PNG", "UMD_ICON0.PNG", "UMD_PIC0.PNG", "PRINNY_ICON0.PNG"):
        row = next(r for r in rows if r["name"].casefold() == name.casefold())
        blob = final_system[row["data_offset"]:row["data_offset"] + row["size"]]
        system_canvases[name] = png_canvas(blob)
    if system_canvases != {
        "REPLAY_ICON0.PNG": (144, 80),
        "UMD_ICON0.PNG": (144, 80),
        "UMD_PIC0.PNG": (310, 180),
        "PRINNY_ICON0.PNG": (144, 80),
    }:
        raise ValueError(f"SYSTEM PNG 캔버스 불일치: {system_canvases}")

    test = subprocess.run(["7z", "t", str(ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("최종 ISO 7z 재검사 실패")

    report = {
        "format": "prinny1_v7_15_9_safe_images_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": sha256_file(ISO)},
        "verified": {"runtime_lzs_overlaps": 0, "system_png_canvases": {key: list(value) for key, value in system_canvases.items()}},
        "checks": {
            "only_five_authorized_iso_extents_changed": True,
            "all_resources_reextracted_exactly": True,
            "direct_png_zero_padding_exact": True,
            "runtime_lzs_non_overlap": True,
            "title_png_roundtrip_exact": True,
            "system_pngs_open_and_match_canvas": True,
            "seven_zip_structure_retest": True,
            "v7_15_8_parent_not_modified": True,
        },
        "status": "pass_v7_15_9_iso_ready_for_ppsspp_runtime_test",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {sha256_file(ISO)}")
    print("5 extents/reextract/LZS/title/7z: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
