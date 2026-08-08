#!/usr/bin/env python3
"""Tighten the tutorial-boss intro gap through anime96 sprite transforms."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_31_company_logo_original_restore"
    / "prinny_korean_v7_15_31_company_logo_original_restore.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_33_intro_transform_gap"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_33_intro_transform_gap.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_33_intro_transform_gap_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_33_intro_transform_gap"
USER_SCREENSHOT = Path("/home/hyuk/사진/인트로데모.png")

EXPECTED_BASE_ISO_SHA256 = "46331164f28aa899e368a512b8c4208ca14f53c16b2955039b4494e7e6570a2b"
EXPECTED_SCREENSHOT_SHA256 = "b8fab6251b7aa23930d36c42200eb5174ed0777fac56b378b8a25b44c1101366"
EXPECTED_ANIME_PACK_SHA256 = "3d120652ee0e69b5d3747e602509094ba1cbb37d0bf91c7970285f9d9f3051ce"
EXPECTED_ANIME96_OFFSET = 15_769_600
EXPECTED_ANIME96_SIZE = 286_448
EXPECTED_ANIME96_SHA256 = "24a80e8d05a41387336e149c3c1c1e8084fcee3c1eb2d135858fdf7de26b8c9f"
EXPECTED_OBJECT0_OFFSET = 16
EXPECTED_OBJECT0_SIZE = 84_672
EXPECTED_OBJECT0_SHA256 = "a89f0950a0a72e26474d7c2dd22f090b435d82681bd5f0ca77aee4a1cf166fee"
EXPECTED_TEXTURE_RGBA_SHA256 = "851f4f165a83ca3b2ae1718f670b345eea396cc3d052778315adb9d212473b14"
SHIFT_X = -24
BEFORE_X = 199
AFTER_X = 175

# The x/y pair is the final four bytes in each 16-byte transform row.
TRANSFORM_PATCHES = (
    {
        "state": "first_intro_pair",
        "row_relative": 0x960,
        "xy_relative": 0x96C,
        "before_row": "00010C006400640000000000C700C8FF",
        "before_xy": (199, -56),
        "after_xy": (175, -56),
    },
    {
        "state": "second_intro_pair",
        "row_relative": 0xA20,
        "xy_relative": 0xA2C,
        "before_row": "00010C006400640000000000C7000000",
        "before_xy": (199, 0),
        "after_xy": (175, 0),
    },
)

FIRST_FRAGMENT_ROWS = (
    (0x950, "000000006400640000000000D1FFC8FF", (-47, -56)),
    (0xA10, "00010C006400640000000000D1FF0000", (-47, 0)),
)


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


def anime96_span(pack: bytes) -> tuple[bytes, dict, list[dict]]:
    rows = system_records(pack)
    row = next(item for item in rows if item["name"].casefold() == "anime96.dat")
    left = int(row["data_offset"])
    right = left + int(row["size"])
    return pack[left:right], row, rows


def patch_anime96_transform(anime96: bytes) -> tuple[bytes, dict]:
    if len(anime96) != EXPECTED_ANIME96_SIZE or sha256_bytes(anime96) != EXPECTED_ANIME96_SHA256:
        raise ValueError("V7.15.31 anime96.dat 봉인값 불일치")
    objects = parse_objects(anime96)
    obj = objects[0]
    if (obj.offset, obj.size) != (EXPECTED_OBJECT0_OFFSET, EXPECTED_OBJECT0_SIZE):
        raise ValueError("anime96 object_000 위치/크기 불일치")
    before_object = anime96[obj.offset:obj.end]
    if sha256_bytes(before_object) != EXPECTED_OBJECT0_SHA256:
        raise ValueError("anime96 object_000 봉인 해시 불일치")
    texture = texture_by_key(anime96, (0, 0, 0))
    rgba_before = decode_texture(anime96, texture).convert("RGBA").tobytes()
    if sha256_bytes(rgba_before) != EXPECTED_TEXTURE_RGBA_SHA256:
        raise ValueError("anime96 인트로 텍스처 봉인값 불일치")
    for relative, expected_hex, expected_xy in FIRST_FRAGMENT_ROWS:
        row = anime96[obj.offset + relative:obj.offset + relative + 16]
        if row != bytes.fromhex(expected_hex) or struct.unpack_from("<2h", row, 12) != expected_xy:
            raise ValueError(f"첫 구절 transform 기준 불일치: 0x{relative:X}")
    patched = bytearray(anime96)
    writes: list[dict] = []
    expected_changed_offsets: set[int] = set()
    for spec in TRANSFORM_PATCHES:
        row_at = obj.offset + int(spec["row_relative"])
        xy_at = obj.offset + int(spec["xy_relative"])
        before_row = bytes(patched[row_at:row_at + 16])
        if before_row != bytes.fromhex(str(spec["before_row"])):
            raise ValueError(f"마계 transform 행 기준 불일치: 0x{row_at:X}")
        before_xy = struct.pack("<2h", *spec["before_xy"])
        after_xy = struct.pack("<2h", *spec["after_xy"])
        if bytes(patched[xy_at:xy_at + 4]) != before_xy:
            raise ValueError(f"마계 transform 좌표 기준 불일치: 0x{xy_at:X}")
        patched[xy_at:xy_at + 4] = after_xy
        expected_changed_offsets.update(
            xy_at + index
            for index, (old, new) in enumerate(zip(before_xy, after_xy))
            if old != new
        )
        writes.append(
            {
                "state": spec["state"],
                "object_relative_xy_offset_hex": f"0x{int(spec['xy_relative']):X}",
                "anime96_absolute_xy_offset_hex": f"0x{xy_at:X}",
                "before_xy": list(spec["before_xy"]),
                "after_xy": list(spec["after_xy"]),
                "before_hex": before_xy.hex().upper(),
                "after_hex": after_xy.hex().upper(),
            }
        )
    final = bytes(patched)
    actual_changed_offsets = {
        index for index, (old, new) in enumerate(zip(anime96, final)) if old != new
    }
    if actual_changed_offsets != expected_changed_offsets or len(actual_changed_offsets) != 2:
        raise ValueError("anime96 transform 실제 변경 바이트 범위 불일치")
    if decode_texture(final, texture).convert("RGBA").tobytes() != rgba_before:
        raise ValueError("transform 변경 중 인트로 텍스처가 바뀌었습니다")
    final_objects = parse_objects(final)
    for before, after in zip(objects, final_objects):
        if (before.offset, before.size, before.end) != (after.offset, after.size, after.end):
            raise ValueError("anime96 오브젝트 레이아웃 변경")
        if before.index != 0 and anime96[before.offset:before.end] != final[after.offset:after.end]:
            raise ValueError(f"anime96 비대상 object_{before.index:03d} 변경")
    return final, {
        "resource": "ANIME.DAT/anime96.dat/object_000",
        "diagnosis": "anime94_pixel_patch_had_no_runtime_effect_scene_uses_anime96_transform",
        "first_fragment_x_preserved": -47,
        "makai_fragment_x_before": BEFORE_X,
        "makai_fragment_x_after": AFTER_X,
        "screen_shift_pixels": SHIFT_X,
        "transform_rows_changed": len(TRANSFORM_PATCHES),
        "actual_changed_bytes": len(actual_changed_offsets),
        "texture_pixels_changed": 0,
        "object_layout_changed": False,
        "writes": writes,
        "anime96_before_sha256": sha256_bytes(anime96),
        "anime96_after_sha256": sha256_bytes(final),
    }


def rebuild_pack(pack: bytes) -> tuple[bytes, bytes, dict]:
    if len(pack) != 27_827_616 or sha256_bytes(pack) != EXPECTED_ANIME_PACK_SHA256:
        raise ValueError("V7.15.31 ANIME.DAT 봉인값 불일치")
    anime96, row, rows = anime96_span(pack)
    if (row["data_offset"], row["size"]) != (EXPECTED_ANIME96_OFFSET, EXPECTED_ANIME96_SIZE):
        raise ValueError("anime96.dat 디렉터리 위치/크기 불일치")
    final_anime96, meta = patch_anime96_transform(anime96)
    final_pack = bytearray(pack)
    left = int(row["data_offset"])
    right = left + int(row["size"])
    final_pack[left:right] = final_anime96
    final_pack_bytes = bytes(final_pack)
    reextracted, final_row, final_rows = anime96_span(final_pack_bytes)
    if rows != final_rows or row != final_row or reextracted != final_anime96:
        raise ValueError("ANIME.DAT anime96.dat 재추출/디렉터리 불일치")
    if pack[:left] != final_pack_bytes[:left] or pack[right:] != final_pack_bytes[right:]:
        raise ValueError("ANIME.DAT anime96.dat 범위 밖 변경")
    return final_pack_bytes, final_anime96, meta


def preflight_and_seal() -> dict:
    if sha256_file(BASE_ISO) != EXPECTED_BASE_ISO_SHA256:
        raise ValueError("V7.15.31 부모 ISO 해시 불일치")
    if sha256_file(USER_SCREENSHOT) != EXPECTED_SCREENSHOT_SHA256:
        raise ValueError("사용자 인트로 화면 해시 불일치")
    base_pack, record = extract_anime_pack(BASE_ISO)
    final_pack, final_anime96, meta = rebuild_pack(base_pack)
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    (RESOURCE_DIR / "ANIME.DAT").write_bytes(final_pack)
    (RESOURCE_DIR / "anime96.dat").write_bytes(final_anime96)
    expected_writes = [
        {
            "id": f"P1-V7.15.33-INTRO-X-{index:04d}",
            "target": "ANIME.DAT/anime96.dat/object_000",
            "state": write["state"],
            "relative_offset": write["object_relative_xy_offset_hex"],
            "before_xy": str(tuple(write["before_xy"])),
            "after_xy": str(tuple(write["after_xy"])),
        }
        for index, write in enumerate(meta["writes"], 1)
    ]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / "expected_writes.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(expected_writes[0]))
        writer.writeheader()
        writer.writerows(expected_writes)
    report = {
        "format": "prinny1_v7_15_33_intro_transform_gap_preflight_v1",
        "created_at": now(),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "failed_predecessor": {
            "version": "V7.15.32",
            "reason": "anime94 pixel move had no visible runtime effect",
            "excluded_as_parent": True,
        },
        "user_evidence": {"path": str(USER_SCREENSHOT), "sha256": sha256_file(USER_SCREENSHOT)},
        "iso_target": {
            "path": "PSP_GAME/USRDIR/ANIME.DAT",
            "extent_lba": int(record["extent_lba"]),
            "size": int(record["data_length"]),
        },
        "transform_edit": meta,
        "expected_writes": expected_writes,
        "sealed": {
            "ANIME.DAT": sha256_bytes(final_pack),
            "anime96.dat": sha256_bytes(final_anime96),
        },
        "checks": {
            "parent_is_last_runtime_approved_v7_15_31": True,
            "only_two_transform_x_bytes_changed": True,
            "first_fragment_transform_preserved": True,
            "makai_y_scale_rotation_preserved": True,
            "anime96_texture_pixels_preserved": True,
            "only_anime96_changed_in_anime_dat": True,
            "external_textures_used": False,
        },
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json("preflight_report.json", report)
    return report


def independent_prebuild_review() -> dict:
    base_pack, _record = extract_anime_pack(BASE_ISO)
    expected_pack, expected_anime96, meta = rebuild_pack(base_pack)
    if expected_pack != (RESOURCE_DIR / "ANIME.DAT").read_bytes():
        raise ValueError("독립 사전 ANIME.DAT 봉인 불일치")
    if expected_anime96 != (RESOURCE_DIR / "anime96.dat").read_bytes():
        raise ValueError("독립 사전 anime96.dat 봉인 불일치")
    report = {
        "format": "prinny1_v7_15_33_intro_transform_gap_prebuild_review_v1",
        "created_at": now(),
        "verified": meta,
        "checks": {
            "fresh_transform_recalculation": True,
            "sealed_resources_exact": True,
            "only_two_transform_x_bytes_changed": True,
            "texture_pixels_byte_preserved": True,
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
        raise ValueError("V7.15.33 독립 사전 검토 미통과")
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.33 출력 ISO가 이미 존재합니다")
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
        raise ValueError("V7.15.33 ISO 7z 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_33_intro_transform_gap_iso_v1",
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
    expected_pack, expected_anime96, meta = rebuild_pack(base_pack)
    if final_pack != expected_pack:
        raise ValueError("사후 transform 재계산 불일치")
    final_anime96, final_row, final_rows = anime96_span(final_pack)
    _base_anime96, base_row, base_rows = anime96_span(base_pack)
    if final_anime96 != expected_anime96 or final_anime96 != (RESOURCE_DIR / "anime96.dat").read_bytes():
        raise ValueError("사후 anime96.dat 봉인 불일치")
    if base_rows != final_rows or base_row != final_row:
        raise ValueError("사후 ANIME.DAT 디렉터리 변경")
    test = subprocess.run(
        ["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False
    )
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_33_intro_transform_gap_postbuild_review_v1",
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
            "fresh_transform_recalculation": True,
            "only_two_anime96_transform_x_bytes_changed": True,
            "all_texture_pixels_and_other_iso_data_preserved": True,
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
    print(f"anime96 마계 transform X: {BEFORE_X} -> {AFTER_X}")
    print("preflight/prebuild/7z/reextract/postbuild: PASS")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
