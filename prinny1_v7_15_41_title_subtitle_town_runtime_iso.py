#!/usr/bin/env python3
"""Replace the title subtitle while preserving the V7.15.40 town repairs."""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import prinny1_v7_15_40_town_runtime_orientation_iso as v40
from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE
from prinny1_v7_15_28_title_plaque_korean_iso import changed_start_resources, overlap_count
from prinny1_v7_15_29_title_plaque_white_index_iso import (
    extract_anime,
    extract_start,
    linear_indices,
    repack_indices,
)
from prinny1_v7_15_35_candidate_text_runtime_repair_iso import sha256_bytes, sha256_file
from prinny1_v7_15_6_ui_image_plan import texture_by_key
from scripts.prinny_anime_preview import decode_texture, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_40_town_runtime_orientation"
    / "prinny_korean_v7_15_40_town_runtime_orientation.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_41_title_subtitle_town_runtime"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_41_title_subtitle_town_runtime.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_41_title_subtitle_town_runtime_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_41_title_subtitle_town_runtime"
FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")

EXPECTED_BASE_SIZE = 500_465_664
EXPECTED_BASE_SHA256 = "4e11afcced36c5df86ac4d4f59d62d383b04fb74f7f1b1784278b241eeb8308d"
EXPECTED_BASE_FILES = {
    "BOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
    "EBOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
    "SYSTEM.DAT": (4_070_251, "c5d03f9bae13099feaf5e20b7802f74cdc2f799e404cd3f5f2fc087bc020c342"),
    "STAGE.DAT": (155_647_296, "b8d1e8169147b79d89bb1a75ba9548bec4bc8032be1dbfa5edd43149cc54c965"),
}
EXPECTED_ANIME00_SHA256 = "f3d61297a552af655ad6d0cee990558ef18cdb1d710af94b9fd2b71c62630452"
EXPECTED_OBJECT78_SHA256 = "39c980fcf666e898cec7185b2be22d598a9ff94ff0a40488c937da96f05ab46e"
EXPECTED_TEXTURE_SHA256 = "bb415b4051aae5ddfb98457209cb12949382f5b89f7e0bb67fb766c90edae189"

OLD_SUBTITLE = "~제가 주인공해도 되겠슴까?~"
TARGET_SUBTITLE = "~제가 주인공이여도 되겠슴까?~"
TEXT_CLEAR_BOX = (29, 131, 264, 160)
TEXT_TARGET_BOX = (33, 134, 259, 157)
FONT_SIZE = 19
OUTLINE_INDEX = 8
FILL_INDEX = 15


def write_json(name: str, payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_csv(name: str, rows: list[dict]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def exact_iso_records(iso: Path) -> dict[str, dict]:
    return v40.exact_iso_records(iso)


def iso_blob(iso: Path, name: str, records: dict[str, dict] | None = None) -> bytes:
    return v40.iso_blob(iso, name, records)


def subtitle_mask() -> Image.Image:
    font = ImageFont.truetype(str(FONT), FONT_SIZE)
    bbox = font.getbbox(TARGET_SUBTITLE, stroke_width=1)
    natural = Image.new("L", (bbox[2] - bbox[0], bbox[3] - bbox[1]), 0)
    draw = ImageDraw.Draw(natural)
    # Value 1 becomes the dark runtime outline CLUT entry; the fill keeps
    # anti-alias intensity and is quantized through entries 9..15 below.
    draw.text(
        (-bbox[0], -bbox[1]), TARGET_SUBTITLE, font=font,
        fill=255, stroke_width=1, stroke_fill=1,
    )
    width = TEXT_TARGET_BOX[2] - TEXT_TARGET_BOX[0]
    height = TEXT_TARGET_BOX[3] - TEXT_TARGET_BOX[1]
    fitted = natural.resize((width, min(height, natural.height)), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (512, 512), 0)
    y = TEXT_TARGET_BOX[1] + (height - fitted.height) // 2
    canvas.paste(fitted, (TEXT_TARGET_BOX[0], y))
    if canvas.getbbox() is None:
        raise ValueError("타이틀 부제 마스크가 비었습니다")
    if not (
        TEXT_CLEAR_BOX[0] <= canvas.getbbox()[0] < canvas.getbbox()[2] <= TEXT_CLEAR_BOX[2]
        and TEXT_CLEAR_BOX[1] <= canvas.getbbox()[1] < canvas.getbbox()[3] <= TEXT_CLEAR_BOX[3]
    ):
        raise ValueError(f"타이틀 부제 마스크 경계 초과: {canvas.getbbox()}")
    return canvas


def mask_value_to_index(value: int) -> int:
    if value <= 0:
        return 0
    if value <= 16:
        return OUTLINE_INDEX
    return min(FILL_INDEX, OUTLINE_INDEX + (value * 8 // 256))


def index_preview(indices: list[int], box: tuple[int, int, int, int]) -> Image.Image:
    colors = [
        (0, 0, 0, 0), (64, 64, 64, 255), (96, 96, 96, 255), (128, 128, 128, 255),
        (160, 160, 160, 255), (192, 192, 192, 255), (224, 224, 224, 255), (240, 240, 240, 255),
        (24, 24, 24, 255), (52, 52, 52, 255), (80, 80, 80, 255), (108, 108, 108, 255),
        (136, 136, 136, 255), (164, 164, 164, 255), (208, 208, 208, 255), (255, 255, 255, 255),
    ]
    image = Image.new("RGBA", (512, 512))
    image.putdata([colors[index] for index in indices])
    return image.crop(box).resize(
        ((box[2] - box[0]) * 4, (box[3] - box[1]) * 4), Image.Resampling.NEAREST
    )


def patch_subtitle(base_anime: bytes) -> tuple[bytes, dict, dict[str, bytes]]:
    if sha256_bytes(base_anime) != EXPECTED_ANIME00_SHA256:
        raise ValueError("anime00.dat 부모 해시 불일치")
    obj = next(item for item in parse_objects(base_anime) if item.index == 78)
    if sha256_bytes(base_anime[obj.offset:obj.offset + obj.size]) != EXPECTED_OBJECT78_SHA256:
        raise ValueError("object_078 부모 해시 불일치")
    texture = texture_by_key(base_anime, (78, 0, 0))
    decoded_before = decode_texture(base_anime, texture).convert("RGBA")
    out = io.BytesIO()
    decoded_before.save(out, format="PNG")
    if sha256_bytes(out.getvalue()) != EXPECTED_TEXTURE_SHA256:
        raise ValueError("object_078 텍스처 부모 픽셀 불일치")

    before = linear_indices(base_anime, texture)
    after = before.copy()
    left, top, right, bottom = TEXT_CLEAR_BOX
    cleared_nonzero = 0
    for y in range(top, bottom):
        for x in range(left, right):
            position = y * 512 + x
            if after[position] != 0:
                cleared_nonzero += 1
            after[position] = 0
    mask = subtitle_mask()
    drawn = 0
    for y in range(top, bottom):
        for x in range(left, right):
            value = mask.getpixel((x, y))
            if value:
                after[y * 512 + x] = mask_value_to_index(value)
                drawn += 1
    if cleared_nonzero < 1000 or drawn < 1000:
        raise ValueError(f"타이틀 부제 픽셀 수 불일치: {cleared_nonzero}/{drawn}")

    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    allowed = {
        y * 512 + x
        for y in range(top, bottom)
        for x in range(left, right)
    }
    if not changed or set(changed) - allowed:
        raise ValueError("타이틀 부제 허용 사각형 밖 인덱스 변경")
    final_anime = repack_indices(base_anime, texture, after)
    pixel_end = texture.pixel_offset + texture.width * texture.height // 2
    if base_anime[:texture.pixel_offset] != final_anime[:texture.pixel_offset] or base_anime[pixel_end:] != final_anime[pixel_end:]:
        raise ValueError("object_078 픽셀 스트림 밖 anime00 변경")
    decoded_after = decode_texture(final_anime, texture).convert("RGBA")
    previews = {
        "title_subtitle_atlas_preview.png": png_bytes(decoded_after.crop((0, 125, 320, 165)), 4),
        "title_subtitle_runtime_index_preview.png": png_bytes(index_preview(after, (0, 125, 320, 165)), 1),
    }
    metadata = {
        "old_visible_text": OLD_SUBTITLE,
        "target_visible_text": TARGET_SUBTITLE,
        "clear_box": list(TEXT_CLEAR_BOX),
        "target_box": list(TEXT_TARGET_BOX),
        "mask_bbox": list(mask.getbbox()),
        "cleared_nonzero_pixels": cleared_nonzero,
        "drawn_pixels": drawn,
        "changed_indices": len(changed),
        "outline_index": OUTLINE_INDEX,
        "fill_index": FILL_INDEX,
        "palette_changes": 0,
        "uv_transform_changes": 0,
    }
    return final_anime, metadata, previews


def png_bytes(image: Image.Image, scale: int) -> bytes:
    output = io.BytesIO()
    if scale != 1:
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    image.save(output, format="PNG")
    return output.getvalue()


def patch_system(base_system: bytes) -> tuple[bytes, dict[str, bytes], dict, dict[str, bytes]]:
    base_start, base_lzs, row, rows = extract_start(base_system)
    if overlap_count(base_lzs):
        raise ValueError("부모 START.LZS 겹침 역참조")
    base_anime, anime_record = extract_anime(base_start)
    final_anime, subtitle_meta, previews = patch_subtitle(base_anime)
    final_start = bytearray(base_start)
    final_start[anime_record.data_offset:anime_record.end_offset] = final_anime
    final_start_bytes = bytes(final_start)
    if changed_start_resources(base_start, final_start_bytes) != ["anime00.dat"]:
        raise ValueError("anime00.dat 외 START 자원 변경")
    header = decompress_buffer(base_lzs)[1]
    final_lzs = compress_buffer_runtime_safe(final_start_bytes, base_lzs[:4], int(header["flag"]))
    if decompress_buffer(final_lzs)[0] != final_start_bytes or overlap_count(final_lzs):
        raise ValueError("START.LZS PSP 런타임 안전 왕복 실패")
    capacity = rows[row["index"] + 1]["data_offset"] - row["data_offset"]
    if len(final_lzs) > capacity:
        raise ValueError("START.LZS 슬롯 초과")
    final_system = bytearray(base_system)
    final_system[row["data_offset"]:row["data_offset"] + capacity] = bytes(capacity)
    final_system[row["data_offset"]:row["data_offset"] + len(final_lzs)] = final_lzs
    struct.pack_into("<I", final_system, 0x10 + row["index"] * 0x2C + 0x24, len(final_lzs))
    check_start, check_lzs, _row, _rows = extract_start(bytes(final_system))
    if check_start != final_start_bytes or check_lzs != final_lzs:
        raise ValueError("SYSTEM START 재추출 불일치")
    artifacts = {"start.dat": final_start_bytes, "start.lzs": final_lzs, "anime00.dat": final_anime}
    metadata = subtitle_meta | {
        "changed_start_resources": ["anime00.dat"],
        "lzs_old_size": len(base_lzs),
        "lzs_new_size": len(final_lzs),
        "lzs_capacity": capacity,
        "lzs_overlap_backreferences": 0,
    }
    return bytes(final_system), artifacts, metadata, previews


def build_resources() -> tuple[dict[str, bytes], list[dict], dict, dict[str, bytes]]:
    records = exact_iso_records(BASE_ISO)
    base = {name: iso_blob(BASE_ISO, name, records) for name in v40.ISO_FILES}
    for name, (size, digest) in EXPECTED_BASE_FILES.items():
        if len(base[name]) != size or sha256_bytes(base[name]) != digest:
            raise ValueError(f"부모 {name} 봉인값 불일치")
    v40.verify_embedded_korean(base)
    final_system, artifacts, metadata, previews = patch_system(base["SYSTEM.DAT"])
    final = dict(base)
    final["SYSTEM.DAT"] = final_system
    final.update(artifacts)
    for name in ("BOOT.BIN", "EBOOT.BIN", "STAGE.DAT"):
        if final[name] != base[name]:
            raise ValueError(f"비대상 자원 변경: {name}")
    writes = [{
        "id": "P1-V7.15.41-TITLE-SUBTITLE-01",
        "target": "START.DAT/anime00.dat/object_078/group_00_page_00",
        "operation": "replace_title_subtitle_index_pixels",
        "old_text": OLD_SUBTITLE,
        "target_text": TARGET_SUBTITLE,
        "boundary": str(TEXT_CLEAR_BOX),
        "before_anime_sha256": EXPECTED_ANIME00_SHA256,
        "after_anime_sha256": sha256_bytes(artifacts["anime00.dat"]),
    }]
    return final, writes, metadata, previews


def input_seal() -> None:
    if not BASE_ISO.is_file() or BASE_ISO.stat().st_size != EXPECTED_BASE_SIZE or sha256_file(BASE_ISO) != EXPECTED_BASE_SHA256:
        raise ValueError("V7.15.40 부모 ISO 봉인값 불일치")
    if not FONT.is_file():
        raise FileNotFoundError(FONT)


def seal() -> None:
    input_seal()
    final, writes, metadata, previews = build_resources()
    if OUTPUT_ISO.exists() or RESOURCE_DIR.exists() or REPORT_DIR.exists():
        raise ValueError("V7.15.41 출력 또는 보고서 경로가 이미 존재합니다")
    RESOURCE_DIR.mkdir(parents=True)
    REPORT_DIR.mkdir(parents=True)
    for name, blob in final.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    for name, blob in previews.items():
        (REPORT_DIR / name).write_bytes(blob)
    write_csv("expected_writes.csv", writes)
    write_json("preflight.json", {
        "format": "prinny1_v7_15_41_title_subtitle_town_runtime_preflight_v1",
        "created_at": v40.v39.now(),
        "authorization": "user_requested_exact_title_subtitle_replacement_2026_08_08",
        "base_iso": {"path": str(BASE_ISO), "size": BASE_ISO.stat().st_size, "sha256": sha256_file(BASE_ISO)},
        "sealed_resources": {name: {"size": len(blob), "sha256": sha256_bytes(blob)} for name, blob in final.items()},
        "sealed_previews": {name: sha256_bytes(blob) for name, blob in previews.items()},
        "expected_writes": writes,
        "subtitle": metadata,
        "preserved": {
            "v7_15_40_stage_dat_exact": True,
            "boot_eboot_exact": True,
            "title_plaque_and_logo_outside_subtitle_exact": True,
            "external_textures_used": False,
        },
        "status": "sealed_independent_prebuild_review_required",
    })


def independent_prebuild() -> None:
    input_seal()
    final, writes, metadata, previews = build_resources()
    for name, blob in final.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"독립 사전 봉인 자원 불일치: {name}")
    for name, blob in previews.items():
        if (REPORT_DIR / name).read_bytes() != blob:
            raise ValueError(f"독립 사전 미리보기 불일치: {name}")
    with (REPORT_DIR / "expected_writes.csv").open(encoding="utf-8-sig") as handle:
        if len(list(csv.DictReader(handle))) != len(writes):
            raise ValueError("독립 사전 Expected Write 수 불일치")
    write_json("independent_prebuild.json", {
        "format": "prinny1_v7_15_41_title_subtitle_town_runtime_prebuild_v1",
        "created_at": v40.v39.now(),
        "verified": metadata,
        "checks": {"fresh_parent_recalculation": True, "sealed_resources_exact": True, "runtime_safe_lzs": True, "only_anime00_changed_in_start": True},
        "status": "pass_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    })


def verify_iso_outside_system(candidate: Path, record: dict) -> None:
    left = int(record["extent_lba"]) * SECTOR_SIZE
    right = left + int(record["data_length"])
    if candidate.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기 변경")
    if hash_range(BASE_ISO, 0, left) != hash_range(candidate, 0, left):
        raise ValueError("SYSTEM.DAT 앞 ISO 범위 변경")
    if hash_range(BASE_ISO, right, BASE_ISO.stat().st_size) != hash_range(candidate, right, candidate.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 ISO 범위 변경")


def build_iso() -> dict:
    review = json.loads((REPORT_DIR / "independent_prebuild.json").read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or OUTPUT_ISO.exists():
        raise ValueError("독립 사전 검토 미통과 또는 출력 ISO 존재")
    records = exact_iso_records(BASE_ISO)
    OUTPUT_DIR.mkdir(parents=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        raise ValueError("임시 ISO가 이미 존재합니다")
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    record = records["SYSTEM.DAT"]
    if len(system) != int(record["data_length"]):
        raise ValueError("SYSTEM.DAT 크기 변경")
    with temporary.open("r+b") as handle:
        handle.seek(int(record["extent_lba"]) * SECTOR_SIZE)
        handle.write(system)
        handle.flush()
        os.fsync(handle.fileno())
    verify_iso_outside_system(temporary, record)
    check = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if check.returncode != 0 or "Everything is Ok" not in check.stdout:
        raise ValueError("ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_41_title_subtitle_town_runtime_iso_v1",
        "created_at": v40.v39.now(),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "checks": {"only_system_dat_extent_changed": True, "seven_zip_structure_test": True, "parent_not_overwritten": True},
        "status": "built_independent_postbuild_review_required",
    }
    write_json("build_report.json", report)
    return report


def independent_postbuild() -> dict:
    base_records = exact_iso_records(BASE_ISO)
    final_records = exact_iso_records(OUTPUT_ISO)
    for name in v40.ISO_FILES:
        if (base_records[name]["extent_lba"], base_records[name]["data_length"]) != (final_records[name]["extent_lba"], final_records[name]["data_length"]):
            raise ValueError(f"사후 ISO 자원 경계 변경: {name}")
    verify_iso_outside_system(OUTPUT_ISO, base_records["SYSTEM.DAT"])
    for name in v40.ISO_FILES:
        if iso_blob(OUTPUT_ISO, name, final_records) != (RESOURCE_DIR / name).read_bytes():
            raise ValueError(f"사후 ISO 재추출 불일치: {name}")
    final_start, final_lzs, _row, _rows = extract_start(iso_blob(OUTPUT_ISO, "SYSTEM.DAT", final_records))
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or overlap_count(final_lzs):
        raise ValueError("사후 START/LZS 검증 실패")
    recalculated, writes, metadata, previews = build_resources()
    for name, blob in recalculated.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"사후 독립 재계산 불일치: {name}")
    for name, blob in previews.items():
        if (REPORT_DIR / name).read_bytes() != blob:
            raise ValueError(f"사후 미리보기 재계산 불일치: {name}")
    check = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if check.returncode != 0 or "Everything is Ok" not in check.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_41_title_subtitle_town_runtime_postbuild_v1",
        "created_at": v40.v39.now(),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": metadata | {"expected_write_rows": len(writes), "ppsspp_launched": False},
        "checks": {
            "only_system_dat_extent_changed": True,
            "sealed_resources_reextracted_exactly": True,
            "fresh_parent_recalculation": True,
            "runtime_safe_lzs": True,
            "v7_15_40_stage_dat_preserved": True,
            "boot_eboot_preserved": True,
            "seven_zip_structure_retest": True,
        },
        "runtime_instruction": "Quarantine old PPSSPP save states before testing; use only an in-game save.",
        "status": "pass_ready_for_clean_runtime_test",
        "final_verdict": "PASS",
    }
    write_json("independent_postbuild.json", report)
    return report


def main() -> int:
    seal()
    independent_prebuild()
    build = build_iso()
    review = independent_postbuild()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print(f"subtitle: {TARGET_SUBTITLE}")
    print("PPSSPP: not launched")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
