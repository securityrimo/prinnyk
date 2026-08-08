#!/usr/bin/env python3
"""Build and independently verify the Korean title embedded in the red plaque.

The old title used four small, separately transformed glyph cells.  Runtime
colour modulation made enlarged pixels unreliable.  This candidate instead
draws the exact Korean title into the already proven plaque sprite and clears
the obsolete overlaid glyph cells.  No UV, transform, palette, or object table
bytes are changed.
"""
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

from PIL import Image, ImageChops, ImageDraw, ImageFont

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture, repack_texture


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_final_updated_master"
    / "prinny_korean_final_updated_master.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_28_title_plaque_korean"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_28_title_plaque_korean.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_28_title_plaque_korean_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_28_title_plaque_korean"
PREVIEW_DIR = (
    ROOT
    / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
    / "translated/resized_v7_15_28/anime/anime00/object_078"
)
TITLE_PNG = PREVIEW_DIR / "group_00_page_00.png"
PLAQUE_PREVIEW = PREVIEW_DIR / "korean_plaque_preview_4x.png"
FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
FONT_LICENSE = Path("/usr/share/doc/fonts-noto-cjk/copyright")
IMAGEGEN_REFERENCE = (
    ROOT
    / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
    / "style_references/prinny_title_plaque_reference_imagegen.png"
)

EXPECTED_BASE_SHA256 = "c3eaea06cff95eedc59bce9712c4e405e58c520790a23a3e77a0cb50db6e7568"
TITLE_TEXT = "프리니"
PLAQUE_FILL = (249, 198, 197, 255)
FOREGROUND = (0, 255, 0, 255)
TRANSPARENT = (0, 0, 0, 0)
TITLE_CELLS = (
    (256, 160, 320, 224),
    (320, 160, 376, 208),
    (376, 160, 424, 208),
    (424, 160, 464, 192),
)
FONT_SIZE = 51
HORIZONTAL_SCALE = 1.05
ROTATION_DEGREES = 14.5
TITLE_CENTER = (130, 230)
MASK_THRESHOLD = 100
EXPECTED_MASK_SIZE = (166, 95)
EXPECTED_FOREGROUND_PIXELS = 2529


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


def extract_system(iso: Path) -> tuple[bytes, dict]:
    record = find_iso_file(iso, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    return read_iso_file(iso, record), record


def extract_start(system: bytes) -> tuple[bytes, bytes, dict, list[dict]]:
    rows = system_records(system)
    row = next(item for item in rows if item["name"].casefold() == "start.lzs")
    lzs = system[row["data_offset"]:row["data_offset"] + row["size"]]
    start, _header = decompress_buffer(lzs)
    return start, lzs, row, rows


def extract_anime(start: bytes) -> tuple[bytes, object, StartRuntimeArchive]:
    archive = StartRuntimeArchive.from_bytes(start)
    record = next(
        item for item in archive.records if item.output_name.casefold() == "anime00.dat"
    )
    return start[record.data_offset:record.end_offset], record, archive


def render_title_mask() -> Image.Image:
    font = ImageFont.truetype(str(FONT), FONT_SIZE, index=1)
    bounds = font.getbbox(TITLE_TEXT)
    raw = Image.new(
        "L",
        (bounds[2] - bounds[0] + 8, bounds[3] - bounds[1] + 8),
        0,
    )
    ImageDraw.Draw(raw).text(
        (4 - bounds[0], 4 - bounds[1]),
        TITLE_TEXT,
        font=font,
        fill=255,
    )
    stretched = raw.resize(
        (round(raw.width * HORIZONTAL_SCALE), raw.height),
        Image.Resampling.LANCZOS,
    )
    rotated = stretched.rotate(
        ROTATION_DEGREES,
        expand=True,
        resample=Image.Resampling.BICUBIC,
    )
    return rotated.point(lambda value: 255 if value >= MASK_THRESHOLD else 0)


def plaque_allowed_mask(title: Image.Image) -> Image.Image:
    mask = Image.new("L", title.size, 0)
    mask.putdata([255 if pixel == PLAQUE_FILL else 0 for pixel in title.getdata()])
    # The user reference intentionally fills most of the plaque.  The exact
    # fill-colour mask is the write boundary: title pixels may approach the
    # existing outline, but may never overwrite it or transparent pixels.
    return mask


def build_title(base_title: Image.Image) -> tuple[Image.Image, dict]:
    source = base_title.convert("RGBA")
    if source.size != (512, 512):
        raise ValueError(f"타이틀 아틀라스 크기 불일치: {source.size}")
    if PLAQUE_FILL not in set(source.getdata()) or FOREGROUND not in set(source.getdata()):
        raise ValueError("타이틀 명패 기준 팔레트가 없습니다")

    mask = render_title_mask()
    foreground_pixels = sum(value != 0 for value in mask.getdata())
    if mask.size != EXPECTED_MASK_SIZE or foreground_pixels != EXPECTED_FOREGROUND_PIXELS:
        raise ValueError(
            f"결정적 한글 마스크 불일치: {mask.size}/{foreground_pixels}"
        )
    left = TITLE_CENTER[0] - mask.width // 2
    top = TITLE_CENTER[1] - mask.height // 2
    placed = Image.new("L", source.size, 0)
    placed.paste(mask, (left, top))
    if ImageChops.subtract(placed, plaque_allowed_mask(source)).getbbox() is not None:
        raise ValueError("한글 마스크가 명패 안전 내부를 벗어납니다")

    edited = source.copy()
    for cell in TITLE_CELLS:
        edited.paste(TRANSPARENT, cell)
    glyph = Image.new("RGBA", mask.size, TRANSPARENT)
    glyph.paste(Image.new("RGBA", mask.size, FOREGROUND), (0, 0), mask)
    edited.alpha_composite(glyph, (left, top))
    if not set(edited.getdata()).issubset(set(source.getdata())):
        raise ValueError("기존 16색 팔레트 밖 색이 생성됐습니다")

    changed = sum(a != b for a, b in zip(source.getdata(), edited.getdata()))
    cleared = sum(
        pixel[3] != 0
        for cell in TITLE_CELLS
        for pixel in source.crop(cell).getdata()
    )
    return edited, {
        "text": TITLE_TEXT,
        "font_size": FONT_SIZE,
        "horizontal_scale": HORIZONTAL_SCALE,
        "rotation_degrees": ROTATION_DEGREES,
        "mask_size": list(mask.size),
        "mask_origin": [left, top],
        "foreground_pixels": foreground_pixels,
        "cleared_old_title_pixels": cleared,
        "changed_atlas_pixels": changed,
    }


def changed_start_resources(before: bytes, after: bytes) -> list[str]:
    old_archive = StartRuntimeArchive.from_bytes(before)
    new_archive = StartRuntimeArchive.from_bytes(after)
    if len(old_archive.records) != len(new_archive.records):
        raise ValueError("START 자원 수 변경")
    changed: list[str] = []
    for old, new in zip(old_archive.records, new_archive.records):
        old_boundary = (old.output_name, old.data_offset, old.end_offset)
        new_boundary = (new.output_name, new.data_offset, new.end_offset)
        if old_boundary != new_boundary:
            raise ValueError("START 자원 경계 변경")
        if before[old.data_offset:old.end_offset] != after[new.data_offset:new.end_offset]:
            changed.append(old.output_name.casefold())
    return changed


def write_json(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def preflight_and_seal() -> dict:
    if sha256_file(BASE_ISO) != EXPECTED_BASE_SHA256:
        raise ValueError("V7.15.28 부모 ISO 해시 불일치")
    if "Open Font License" not in FONT_LICENSE.read_text(
        encoding="utf-8", errors="replace"
    ):
        raise ValueError("Noto CJK OFL 라이선스 근거 누락")
    if not IMAGEGEN_REFERENCE.is_file():
        raise ValueError("사용자 시안에서 분리한 형태 참고 PNG 누락")

    base_system, _record = extract_system(BASE_ISO)
    base_start, old_lzs, start_row, rows = extract_start(base_system)
    if overlap_count(old_lzs):
        raise ValueError("부모 START.LZS에 PSP 비호환 겹침 역참조가 있습니다")
    base_anime, anime_record, _archive = extract_anime(base_start)
    texture = texture_by_key(base_anime, (78, 0, 0))
    base_title = decode_texture(base_anime, texture).convert("RGBA")
    final_title, title_meta = build_title(base_title)
    final_anime = repack_texture(base_anime, texture, final_title)
    if decode_texture(final_anime, texture).convert("RGBA").tobytes() != final_title.tobytes():
        raise ValueError("타이틀 텍스처 왕복 실패")

    pixel_end = texture.pixel_offset + texture.width * texture.height // 2
    if (
        base_anime[:texture.pixel_offset] != final_anime[:texture.pixel_offset]
        or base_anime[pixel_end:] != final_anime[pixel_end:]
    ):
        raise ValueError("타이틀 픽셀 데이터 밖 anime00 변경")

    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    final_start_bytes = bytes(final_start)
    if changed_start_resources(base_start, final_start_bytes) != ["anime00.dat"]:
        raise ValueError("anime00.dat 외 START 자원 변경")

    header = decompress_buffer(old_lzs)[1]
    new_lzs = compress_buffer_runtime_safe(
        final_start_bytes, old_lzs[:4], int(header["flag"])
    )
    if decompress_buffer(new_lzs)[0] != final_start_bytes or overlap_count(new_lzs):
        raise ValueError("PSP 런타임 안전 LZS 왕복 실패")
    capacity = rows[start_row["index"] + 1]["data_offset"] - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError(f"START.LZS 슬롯 초과: {len(new_lzs)}>{capacity}")

    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:start_row["data_offset"] + capacity] = bytes(
        capacity
    )
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into(
        "<I",
        final_system,
        0x10 + start_row["index"] * 0x2C + 0x24,
        len(new_lzs),
    )
    final_system_bytes = bytes(final_system)
    check_start, check_lzs, _check_row, _check_rows = extract_start(final_system_bytes)
    if check_start != final_start_bytes or check_lzs != new_lzs:
        raise ValueError("봉인 SYSTEM.DAT의 START 재추출 실패")

    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "SYSTEM.DAT": final_system_bytes,
        "start.dat": final_start_bytes,
        "start.lzs": new_lzs,
        "anime00.dat": final_anime,
    }
    for name, blob in artifacts.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    final_title.save(TITLE_PNG, format="PNG", optimize=True, compress_level=9)
    final_title.crop((0, 160, 260, 305)).resize(
        (1040, 580), Image.Resampling.NEAREST
    ).save(PLAQUE_PREVIEW, format="PNG", optimize=True, compress_level=9)

    expected_write = {
        "id": "P1-V7.15.28-TITLE-0001",
        "target": "START.DAT/anime00.dat/object_078/group_00_page_00",
        "anime00_offset_hex": hex(texture.pixel_offset),
        "capacity_bytes": texture.width * texture.height // 2,
        "before_sha256": sha256_bytes(
            base_anime[texture.pixel_offset:pixel_end]
        ),
        "after_sha256": sha256_bytes(
            final_anime[texture.pixel_offset:pixel_end]
        ),
        "allowed_atlas_regions": "plaque_fill_interior;old_title_cells_4",
        "geometry_change": "none",
        "palette_change": "none",
    }
    with (REPORT_DIR / "expected_writes.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(expected_write))
        writer.writeheader()
        writer.writerow(expected_write)

    report = {
        "format": "prinny1_v7_15_28_title_plaque_preflight_v1",
        "created_at": now(),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "visual_reference": {
            "user_image": "/home/hyuk/사진/타이틀화면.png",
            "imagegen_reference": str(IMAGEGEN_REFERENCE),
            "imagegen_reference_sha256": sha256_file(IMAGEGEN_REFERENCE),
            "use": "shape_and_proportion_reference_only",
        },
        "font": {
            "path": str(FONT),
            "sha256": sha256_file(FONT),
            "family": "Noto Sans CJK KR",
            "style": "Bold",
            "collection_index": 1,
            "license": "SIL Open Font License",
        },
        "title": title_meta,
        "expected_write": expected_write,
        "lzs": {
            "old_size": len(old_lzs),
            "new_size": len(new_lzs),
            "capacity": capacity,
            "overlap_backreferences": 0,
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()}
        | {
            "title_png": sha256_file(TITLE_PNG),
            "plaque_preview": sha256_file(PLAQUE_PREVIEW),
        },
        "checks": {
            "title_text_exact": TITLE_TEXT,
            "text_inside_plaque_safe_interior": True,
            "old_overlay_title_cells_cleared": True,
            "palette_preserved": True,
            "uv_and_sprite_geometry_preserved": True,
            "only_anime00_changed_in_start": True,
            "runtime_safe_lzs_non_overlap": True,
            "iso_created": False,
        },
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json(REPORT_DIR / "preflight_report.json", report)
    return report


def independent_prebuild_review() -> dict:
    base_system, _record = extract_system(BASE_ISO)
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    base_start, _base_lzs, _base_row, base_rows = extract_start(base_system)
    final_start, final_lzs, _final_row, final_rows = extract_start(final_system)
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes():
        raise ValueError("독립 검토 START 봉인 불일치")
    if final_lzs != (RESOURCE_DIR / "start.lzs").read_bytes() or overlap_count(final_lzs):
        raise ValueError("독립 검토 LZS 봉인/안전성 불일치")
    if [(r["name"], r["data_offset"]) for r in base_rows] != [
        (r["name"], r["data_offset"]) for r in final_rows
    ]:
        raise ValueError("SYSTEM 자원 목록 또는 오프셋 변경")
    if changed_start_resources(base_start, final_start) != ["anime00.dat"]:
        raise ValueError("독립 검토 비대상 START 자원 변경")

    base_anime, _old_record, _old_archive = extract_anime(base_start)
    final_anime, _new_record, _new_archive = extract_anime(final_start)
    if final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("독립 검토 anime00 봉인 불일치")
    texture = texture_by_key(base_anime, (78, 0, 0))
    base_title = decode_texture(base_anime, texture).convert("RGBA")
    expected_title, expected_meta = build_title(base_title)
    final_title = decode_texture(final_anime, texture).convert("RGBA")
    if final_title.tobytes() != expected_title.tobytes():
        raise ValueError("독립 재렌더 결과와 봉인 타이틀 불일치")
    with Image.open(TITLE_PNG) as opened:
        opened.load()
        if opened.convert("RGBA").tobytes() != final_title.tobytes():
            raise ValueError("독립 검토 PNG 왕복 불일치")
    if any(pixel != TRANSPARENT for cell in TITLE_CELLS for pixel in final_title.crop(cell).getdata()):
        raise ValueError("옛 분리 타이틀 셀이 완전 투명이 아님")
    if repack_texture(base_anime, texture, expected_title) != final_anime:
        raise ValueError("허용 타이틀 페이지 밖 anime00 변경")

    report = {
        "format": "prinny1_v7_15_28_title_plaque_prebuild_review_v1",
        "created_at": now(),
        "verified": {
            "changed_start_resources": ["anime00.dat"],
            "title_text": TITLE_TEXT,
            "foreground_pixels": expected_meta["foreground_pixels"],
            "changed_atlas_pixels": expected_meta["changed_atlas_pixels"],
            "runtime_lzs_overlaps": 0,
        },
        "checks": {
            "fresh_base_extraction": True,
            "fresh_title_rerender_exact": True,
            "sealed_resources_exact": True,
            "old_title_cells_transparent": True,
            "no_uv_transform_or_palette_write": True,
            "only_anime00_changed_in_start": True,
        },
        "status": "pass_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    write_json(REPORT_DIR / "independent_prebuild_review.json", report)
    return report


def build_iso() -> dict:
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.28 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    review = json.loads(
        (REPORT_DIR / "independent_prebuild_review.json").read_text(encoding="utf-8")
    )
    if review.get("final_verdict") != "PASS":
        raise ValueError("독립 사전 검토 미통과")
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    _base_system, record = extract_system(BASE_ISO)
    if len(final_system) != int(record["data_length"]):
        raise ValueError("SYSTEM.DAT 고정 ISO 영역 크기 변경")
    offset = int(record["extent_lba"]) * SECTOR_SIZE

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as target:
        target.seek(offset)
        target.write(final_system)
        target.flush()
        os.fsync(target.fileno())
    end = offset + len(final_system)
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기 변경")
    if hash_range(BASE_ISO, 0, offset) != hash_range(temporary, 0, offset):
        raise ValueError("SYSTEM.DAT 앞 ISO 데이터 변경")
    if hash_range(BASE_ISO, end, BASE_ISO.stat().st_size) != hash_range(
        temporary, end, temporary.stat().st_size
    ):
        raise ValueError("SYSTEM.DAT 뒤 ISO 데이터 변경")
    test = subprocess.run(
        ["7z", "t", str(temporary)], capture_output=True, text=True, check=False
    )
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.28 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    report = {
        "format": "prinny1_v7_15_28_title_plaque_iso_v1",
        "created_at": now(),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {
            "path": str(OUTPUT_ISO),
            "size": OUTPUT_ISO.stat().st_size,
            "sha256": sha256_file(OUTPUT_ISO),
        },
        "changed_iso_files": ["PSP_GAME/USRDIR/SYSTEM.DAT"],
        "checks": {
            "independent_prebuild_review_pass": True,
            "only_system_dat_iso_extent_changed": True,
            "seven_zip_structure_test": True,
            "parent_iso_not_overwritten": True,
        },
        "status": "built_independent_postbuild_review_required",
    }
    write_json(REPORT_DIR / "iso_build_report.json", report)
    return report


def independent_postbuild_review() -> dict:
    base_system, base_record = extract_system(BASE_ISO)
    final_system, final_record = extract_system(OUTPUT_ISO)
    if (base_record["extent_lba"], base_record["data_length"]) != (
        final_record["extent_lba"],
        final_record["data_length"],
    ):
        raise ValueError("사후 검토 SYSTEM.DAT ISO 범위 변경")
    offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    end = offset + int(base_record["data_length"])
    if (
        BASE_ISO.stat().st_size != OUTPUT_ISO.stat().st_size
        or hash_range(BASE_ISO, 0, offset) != hash_range(OUTPUT_ISO, 0, offset)
        or hash_range(BASE_ISO, end, BASE_ISO.stat().st_size)
        != hash_range(OUTPUT_ISO, end, OUTPUT_ISO.stat().st_size)
    ):
        raise ValueError("사후 검토 SYSTEM.DAT 범위 밖 ISO 변경")
    if final_system != (RESOURCE_DIR / "SYSTEM.DAT").read_bytes():
        raise ValueError("사후 재추출 SYSTEM.DAT 봉인 불일치")

    base_start, _base_lzs, _base_row, _base_rows = extract_start(base_system)
    final_start, final_lzs, _final_row, _final_rows = extract_start(final_system)
    if overlap_count(final_lzs):
        raise ValueError("사후 재추출 LZS 겹침 역참조")
    if changed_start_resources(base_start, final_start) != ["anime00.dat"]:
        raise ValueError("사후 재추출 비대상 START 자원 변경")
    base_anime, _base_anime_record, _base_archive = extract_anime(base_start)
    final_anime, _final_anime_record, _final_archive = extract_anime(final_start)
    if final_anime != (RESOURCE_DIR / "anime00.dat").read_bytes():
        raise ValueError("사후 재추출 anime00 봉인 불일치")
    texture = texture_by_key(base_anime, (78, 0, 0))
    expected_title, expected_meta = build_title(decode_texture(base_anime, texture))
    final_title = decode_texture(final_anime, texture).convert("RGBA")
    if final_title.tobytes() != expected_title.tobytes():
        raise ValueError("사후 독립 재렌더와 ISO 타이틀 불일치")
    if repack_texture(base_anime, texture, expected_title) != final_anime:
        raise ValueError("사후 검토 허용 타이틀 페이지 밖 anime00 변경")
    test = subprocess.run(
        ["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False
    )
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 ISO 7z 구조 재검사 실패")

    report = {
        "format": "prinny1_v7_15_28_title_plaque_postbuild_review_v1",
        "created_at": now(),
        "output_iso": {
            "path": str(OUTPUT_ISO),
            "size": OUTPUT_ISO.stat().st_size,
            "sha256": sha256_file(OUTPUT_ISO),
        },
        "verified": {
            "changed_start_resources": ["anime00.dat"],
            "title_text": TITLE_TEXT,
            "foreground_pixels": expected_meta["foreground_pixels"],
            "changed_atlas_pixels": expected_meta["changed_atlas_pixels"],
            "runtime_lzs_overlaps": 0,
            "ppsspp_launched": False,
        },
        "checks": {
            "only_system_dat_iso_extent_changed": True,
            "sealed_system_reextracted_exactly": True,
            "sealed_anime00_reextracted_exactly": True,
            "fresh_title_rerender_exact": True,
            "only_anime00_changed_in_start": True,
            "seven_zip_structure_retest": True,
        },
        "status": "pass_ready_for_user_title_screen_runtime_test",
        "final_verdict": "PASS",
    }
    write_json(REPORT_DIR / "independent_postbuild_review.json", report)
    return report


def main() -> int:
    if not BASE_ISO.is_file():
        raise ValueError(f"부모 ISO 누락: {BASE_ISO}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    preflight_and_seal()
    independent_prebuild_review()
    build = build_iso()
    review = independent_postbuild_review()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print(f"title: {TITLE_TEXT} / plaque-embedded / {EXPECTED_FOREGROUND_PIXELS} pixels")
    print("preflight/prebuild/7z/reextract/postbuild: PASS")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
