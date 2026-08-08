#!/usr/bin/env python3
"""Move the anime94 '마계…….' fragment 24 more pixels left on V7.15.31."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import (
    SECTOR_SIZE,
    find_iso_file,
    read_iso_file,
)
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import assert_changes_inside, texture_by_key
from scripts.prinny_anime_preview import decode_texture, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_31_company_logo_original_restore"
    / "prinny_korean_v7_15_31_company_logo_original_restore.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_32_intro_gap_tighten"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_32_intro_gap_tighten.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_32_intro_gap_tighten_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_32_intro_gap_tighten"
PREVIEW_DIR = ROOT / "workspace/exports/prinny1_v7_15_32_intro_gap_tighten"
USER_SCREENSHOT = Path("/home/hyuk/사진/인트로데모.png")

EXPECTED_BASE_ISO_SHA256 = "46331164f28aa899e368a512b8c4208ca14f53c16b2955039b4494e7e6570a2b"
EXPECTED_SCREENSHOT_SHA256 = "b8fab6251b7aa23930d36c42200eb5174ed0777fac56b378b8a25b44c1101366"
EXPECTED_ANIME_PACK_SHA256 = "3d120652ee0e69b5d3747e602509094ba1cbb37d0bf91c7970285f9d9f3051ce"
EXPECTED_ANIME94_SHA256 = "5210c65848d271f3a305e90bc927b0ea0f7c7d95be7809981ce452e0c0655714"
EXPECTED_RGBA_SHA256 = "ebac9ad31e1bee08414e538a532815b4c9147e031ed0aa9ad504842655943ed3"
EXPECTED_ANIME94_OFFSET = 27_414_528
EXPECTED_ANIME94_SIZE = 84_688
TEXTURE_KEY = (0, 0, 0)
CURRENT_FRAGMENT_RECT = (166, 25, 267, 47)
TARGET_FRAGMENT_ORIGIN = (142, 25)
CLEAR_AND_WRITE_RECT = (142, 25, 267, 47)
ADDITIONAL_SHIFT_X = -24
TOTAL_SHIFT_FROM_ORIGINAL_X = -48
EXPECTED_FRAGMENT_OPAQUE_PIXELS = 1_000


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(name: str, report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def extract_anime_pack(iso: Path) -> tuple[bytes, dict]:
    record = find_iso_file(iso, ["PSP_GAME", "USRDIR", "ANIME.DAT"])
    return read_iso_file(iso, record), record


def anime94_span(pack: bytes) -> tuple[bytes, dict, list[dict]]:
    rows = system_records(pack)
    row = next(item for item in rows if item["name"].casefold() == "anime94.dat")
    left = int(row["data_offset"])
    right = left + int(row["size"])
    return pack[left:right], row, rows


def patch_intro_gap(anime94: bytes) -> tuple[bytes, Image.Image, Image.Image, dict]:
    if len(anime94) != EXPECTED_ANIME94_SIZE or sha256_bytes(anime94) != EXPECTED_ANIME94_SHA256:
        raise ValueError("V7.15.31 anime94.dat 봉인값 불일치")
    texture = texture_by_key(anime94, TEXTURE_KEY)
    if (texture.width, texture.height) != (512, 320):
        raise ValueError("anime94 인트로 텍스처 크기 불일치")
    before = decode_texture(anime94, texture).convert("RGBA")
    if sha256_bytes(before.tobytes()) != EXPECTED_RGBA_SHA256:
        raise ValueError("V7.15.31 인트로 RGBA 봉인값 불일치")
    transparent = before.getpixel((511, 319))
    if transparent[3] != 0:
        raise ValueError("투명 기준 픽셀이 불투명합니다")
    fragment = before.crop(CURRENT_FRAGMENT_RECT)
    opaque_pixels = sum(pixel[3] != 0 for pixel in fragment.getdata())
    if fragment.size != (101, 22) or opaque_pixels != EXPECTED_FRAGMENT_OPAQUE_PIXELS:
        raise ValueError("현재 마계 문구 조각이 봉인값과 다릅니다")
    if any(
        before.getpixel((x, y))[3] != 0
        for y in range(TARGET_FRAGMENT_ORIGIN[1], CURRENT_FRAGMENT_RECT[3])
        for x in range(TARGET_FRAGMENT_ORIGIN[0], CURRENT_FRAGMENT_RECT[0])
    ):
        raise ValueError("마계 문구의 새 왼쪽 공간이 비어 있지 않습니다")
    after = before.copy()
    after.paste(transparent, CLEAR_AND_WRITE_RECT)
    after.paste(fragment, TARGET_FRAGMENT_ORIGIN)
    changed_pixels = assert_changes_inside(before, after, (CLEAR_AND_WRITE_RECT,))
    expected = before.crop(CURRENT_FRAGMENT_RECT)
    actual = after.crop(
        (
            TARGET_FRAGMENT_ORIGIN[0],
            TARGET_FRAGMENT_ORIGIN[1],
            TARGET_FRAGMENT_ORIGIN[0] + expected.width,
            TARGET_FRAGMENT_ORIGIN[1] + expected.height,
        )
    )
    if actual.tobytes() != expected.tobytes():
        raise ValueError("마계 문구 24픽셀 이동 결과 불일치")
    if not set(after.getdata()).issubset(set(before.getdata())):
        raise ValueError("원본 팔레트 밖 색상이 생겼습니다")
    patched = repack_texture(anime94, texture, after)
    if decode_texture(patched, texture).convert("RGBA").tobytes() != after.tobytes():
        raise ValueError("anime94 텍스처 재패킹 왕복 불일치")
    pixel_end = texture.pixel_offset + texture.width * texture.height // 2
    if anime94[:texture.pixel_offset] != patched[:texture.pixel_offset] or anime94[pixel_end:] != patched[pixel_end:]:
        raise ValueError("anime94 텍스처 픽셀 저장소 밖 변경")
    return patched, before, after, {
        "resource": "ANIME.DAT/anime94.dat/object_000/group_00_page_00",
        "current_fragment_rect": list(CURRENT_FRAGMENT_RECT),
        "target_fragment_origin": list(TARGET_FRAGMENT_ORIGIN),
        "additional_horizontal_shift_pixels": ADDITIONAL_SHIFT_X,
        "total_horizontal_shift_from_original_pixels": TOTAL_SHIFT_FROM_ORIGINAL_X,
        "fragment_opaque_pixels": opaque_pixels,
        "changed_rgba_pixels": changed_pixels,
        "canvas": [texture.width, texture.height],
        "palette_table_changed": False,
    }


def rebuild_pack(pack: bytes) -> tuple[bytes, bytes, Image.Image, Image.Image, dict]:
    if len(pack) != 27_827_616 or sha256_bytes(pack) != EXPECTED_ANIME_PACK_SHA256:
        raise ValueError("V7.15.31 ANIME.DAT 봉인값 불일치")
    anime94, row, rows = anime94_span(pack)
    if (row["data_offset"], row["size"]) != (EXPECTED_ANIME94_OFFSET, EXPECTED_ANIME94_SIZE):
        raise ValueError("anime94.dat 디렉터리 위치/크기 불일치")
    patched_anime94, before, after, meta = patch_intro_gap(anime94)
    final_pack = bytearray(pack)
    left = int(row["data_offset"])
    right = left + int(row["size"])
    final_pack[left:right] = patched_anime94
    final_pack_bytes = bytes(final_pack)
    final_anime94, final_row, final_rows = anime94_span(final_pack_bytes)
    if rows != final_rows or row != final_row:
        raise ValueError("ANIME.DAT 디렉터리가 변경됐습니다")
    if final_anime94 != patched_anime94:
        raise ValueError("ANIME.DAT anime94.dat 재추출 불일치")
    if pack[:left] != final_pack_bytes[:left] or pack[right:] != final_pack_bytes[right:]:
        raise ValueError("ANIME.DAT anime94.dat 범위 밖 변경")
    meta["anime94_before_sha256"] = sha256_bytes(anime94)
    meta["anime94_after_sha256"] = sha256_bytes(patched_anime94)
    meta["changed_anime94_bytes"] = sum(
        old != new for old, new in zip(anime94, patched_anime94)
    )
    return final_pack_bytes, patched_anime94, before, after, meta


def preflight_and_seal() -> dict:
    if sha256_file(BASE_ISO) != EXPECTED_BASE_ISO_SHA256:
        raise ValueError("V7.15.31 부모 ISO 해시 불일치")
    if sha256_file(USER_SCREENSHOT) != EXPECTED_SCREENSHOT_SHA256:
        raise ValueError("사용자 인트로 화면 해시 불일치")
    base_pack, record = extract_anime_pack(BASE_ISO)
    final_pack, final_anime94, before, after, edit_meta = rebuild_pack(base_pack)
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (RESOURCE_DIR / "ANIME.DAT").write_bytes(final_pack)
    (RESOURCE_DIR / "anime94.dat").write_bytes(final_anime94)
    before_path = PREVIEW_DIR / "intro_before.png"
    after_path = PREVIEW_DIR / "intro_after_gap_tightened.png"
    comparison_path = PREVIEW_DIR / "intro_gap_comparison_4x.png"
    before.save(before_path, format="PNG", optimize=True, compress_level=9)
    after.save(after_path, format="PNG", optimize=True, compress_level=9)
    comparison = Image.new("RGBA", (1024, 176), (0, 0, 0, 255))
    comparison.paste(before.crop((80, 0, 336, 44)).resize((512, 176)), (0, 0))
    comparison.paste(after.crop((80, 0, 336, 44)).resize((512, 176)), (512, 0))
    comparison.save(comparison_path, format="PNG", optimize=True, compress_level=9)
    expected_write = {
        "id": "P1-V7.15.32-INTRO-GAP-0001",
        "target": "ANIME.DAT/anime94.dat/object_000/group_00_page_00",
        "operation": "move_current_makai_fragment_left_24_pixels",
        "anime_dat_offset": EXPECTED_ANIME94_OFFSET,
        "span_size": EXPECTED_ANIME94_SIZE,
        "before_sha256": EXPECTED_ANIME94_SHA256,
        "after_sha256": sha256_bytes(final_anime94),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / "expected_writes.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(expected_write))
        writer.writeheader()
        writer.writerow(expected_write)
    report = {
        "format": "prinny1_v7_15_32_intro_gap_tighten_preflight_v1",
        "created_at": now(),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "user_evidence": {"path": str(USER_SCREENSHOT), "sha256": sha256_file(USER_SCREENSHOT)},
        "iso_target": {
            "path": "PSP_GAME/USRDIR/ANIME.DAT",
            "extent_lba": int(record["extent_lba"]),
            "size": int(record["data_length"]),
        },
        "intro_edit": edit_meta,
        "expected_write": expected_write,
        "sealed": {
            "ANIME.DAT": sha256_bytes(final_pack),
            "anime94.dat": sha256_bytes(final_anime94),
            "before_png": sha256_file(before_path),
            "after_png": sha256_file(after_path),
            "comparison_png": sha256_file(comparison_path),
        },
        "checks": {
            "current_fragment_freshly_verified": True,
            "target_space_was_transparent": True,
            "exact_24_pixel_left_move": True,
            "only_anime94_texture_pixels_changed": True,
            "only_anime94_span_changed_in_anime_dat": True,
            "palette_canvas_and_metadata_preserved": True,
            "external_textures_used": False,
        },
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json("preflight_report.json", report)
    return report


def independent_prebuild_review() -> dict:
    base_pack, _record = extract_anime_pack(BASE_ISO)
    sealed_pack = (RESOURCE_DIR / "ANIME.DAT").read_bytes()
    sealed_anime94 = (RESOURCE_DIR / "anime94.dat").read_bytes()
    expected_pack, expected_anime94, _before, _after, meta = rebuild_pack(base_pack)
    if sealed_pack != expected_pack or sealed_anime94 != expected_anime94:
        raise ValueError("독립 사전 재계산/봉인 불일치")
    _base_anime94, base_row, base_rows = anime94_span(base_pack)
    _final_anime94, final_row, final_rows = anime94_span(sealed_pack)
    if base_rows != final_rows or base_row != final_row:
        raise ValueError("독립 사전 ANIME.DAT 디렉터리 변경")
    report = {
        "format": "prinny1_v7_15_32_intro_gap_tighten_prebuild_review_v1",
        "created_at": now(),
        "verified": meta,
        "checks": {
            "fresh_patch_recalculation": True,
            "sealed_resources_exact": True,
            "only_anime94_span_changed": True,
            "exact_24_pixel_left_move": True,
            "other_anime_resources_preserved": True,
        },
        "status": "pass_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    write_json("independent_prebuild_review.json", report)
    return report


def build_iso() -> dict:
    review = json.loads(
        (REPORT_DIR / "independent_prebuild_review.json").read_text(encoding="utf-8")
    )
    if review.get("final_verdict") != "PASS":
        raise ValueError("V7.15.32 독립 사전 검토 미통과")
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.32 출력 ISO가 이미 존재합니다")
    final_pack = (RESOURCE_DIR / "ANIME.DAT").read_bytes()
    _base_pack, record = extract_anime_pack(BASE_ISO)
    if len(final_pack) != int(record["data_length"]):
        raise ValueError("ANIME.DAT ISO 크기 변경")
    offset = int(record["extent_lba"]) * SECTOR_SIZE
    end = offset + len(final_pack)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as handle:
        handle.seek(offset)
        handle.write(final_pack)
        handle.flush()
        os.fsync(handle.fileno())
    if (
        temporary.stat().st_size != BASE_ISO.stat().st_size
        or hash_range(BASE_ISO, 0, offset) != hash_range(temporary, 0, offset)
        or hash_range(BASE_ISO, end, BASE_ISO.stat().st_size)
        != hash_range(temporary, end, temporary.stat().st_size)
    ):
        raise ValueError("ANIME.DAT 허용 범위 밖 ISO 변경")
    test = subprocess.run(
        ["7z", "t", str(temporary)], capture_output=True, text=True, check=False
    )
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.32 ISO 7z 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_32_intro_gap_tighten_iso_v1",
        "created_at": now(),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "output_iso": {
            "path": str(OUTPUT_ISO),
            "size": OUTPUT_ISO.stat().st_size,
            "sha256": sha256_file(OUTPUT_ISO),
        },
        "checks": {
            "only_anime_dat_iso_extent_changed": True,
            "seven_zip_structure_test": True,
            "parent_not_overwritten": True,
        },
        "status": "built_independent_postbuild_review_required",
    }
    write_json("iso_build_report.json", report)
    return report


def independent_postbuild_review() -> dict:
    base_pack, base_record = extract_anime_pack(BASE_ISO)
    final_pack, final_record = extract_anime_pack(OUTPUT_ISO)
    if (base_record["extent_lba"], base_record["data_length"]) != (
        final_record["extent_lba"], final_record["data_length"]
    ):
        raise ValueError("사후 ANIME.DAT ISO 범위 변경")
    offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    end = offset + int(base_record["data_length"])
    if (
        BASE_ISO.stat().st_size != OUTPUT_ISO.stat().st_size
        or hash_range(BASE_ISO, 0, offset) != hash_range(OUTPUT_ISO, 0, offset)
        or hash_range(BASE_ISO, end, BASE_ISO.stat().st_size)
        != hash_range(OUTPUT_ISO, end, OUTPUT_ISO.stat().st_size)
    ):
        raise ValueError("사후 ANIME.DAT 범위 밖 ISO 변경")
    if final_pack != (RESOURCE_DIR / "ANIME.DAT").read_bytes():
        raise ValueError("사후 ANIME.DAT 봉인 불일치")
    expected_pack, expected_anime94, _before, _after, meta = rebuild_pack(base_pack)
    if final_pack != expected_pack:
        raise ValueError("사후 인트로 간격 재계산 불일치")
    final_anime94, final_row, final_rows = anime94_span(final_pack)
    _base_anime94, base_row, base_rows = anime94_span(base_pack)
    if final_anime94 != expected_anime94 or final_anime94 != (RESOURCE_DIR / "anime94.dat").read_bytes():
        raise ValueError("사후 anime94.dat 봉인 불일치")
    if base_rows != final_rows or base_row != final_row:
        raise ValueError("사후 ANIME.DAT 디렉터리 변경")
    test = subprocess.run(
        ["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False
    )
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_32_intro_gap_tighten_postbuild_review_v1",
        "created_at": now(),
        "output_iso": {
            "path": str(OUTPUT_ISO),
            "size": OUTPUT_ISO.stat().st_size,
            "sha256": sha256_file(OUTPUT_ISO),
        },
        "verified": meta | {"ppsspp_launched": False},
        "checks": {
            "only_anime_dat_iso_extent_changed": True,
            "sealed_anime_dat_reextracted_exactly": True,
            "fresh_patch_recalculation": True,
            "only_anime94_texture_pixels_changed": True,
            "all_other_iso_data_preserved": True,
            "seven_zip_structure_retest": True,
            "external_textures_used": False,
        },
        "status": "pass_ready_for_ppsspp_intro_runtime_test",
        "final_verdict": "PASS",
    }
    write_json("independent_postbuild_review.json", report)
    return report


def main() -> int:
    preflight_and_seal()
    independent_prebuild_review()
    build = build_iso()
    review = independent_postbuild_review()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print(f"intro 마계 fragment: {ADDITIONAL_SHIFT_X}px (total {TOTAL_SHIFT_FROM_ORIGINAL_X}px)")
    print("preflight/prebuild/7z/reextract/postbuild: PASS")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
