#!/usr/bin/env python3
"""Repair town sign orientation and seal the already-applied Korean town UI.

V7.15.39 correctly embedded the countdown and tutorial Korean resources, but
runtime captures were taken after loading an older PPSSPP save state.  A PSP
save state restores executable RAM and GPU text/texture caches, so those two
resources remained Japanese.  The direction sign atlas was freshly streamed
from the ISO and exposed a separate issue: the model mirrors only its text UV
strips.  V7.15.40 therefore pre-mirrors the two text strips while preserving
the boards, arrows, palette, and every other ISO resource.
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import prinny1_v7_15_39_town_sign_deadline_korean_iso as v39
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_29_title_plaque_white_index_iso import extract_start
from prinny1_v7_15_35_candidate_text_runtime_repair_iso import (
    record_map,
    resource_blob,
    sha256_bytes,
    sha256_file,
)


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_15_39_town_sign_deadline_korean"
    / "prinny_korean_v7_15_39_town_sign_deadline_korean.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_40_town_runtime_orientation"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_40_town_runtime_orientation.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_40_town_runtime_orientation_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_40_town_runtime_orientation"

EXPECTED_BASE_SIZE = 500_465_664
EXPECTED_BASE_SHA256 = "348ff0aef29e29b09dc798bc05d16a2b13812d357d38d04369a37fba546bd021"
EXPECTED_BASE_FILES = {
    "BOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
    "EBOOT.BIN": (1_128_036, "64583952280bd9af2f860fada696c0a7e0d332102bcc575036dc908a84617e7c"),
    "SYSTEM.DAT": (4_070_251, "c5d03f9bae13099feaf5e20b7802f74cdc2f799e404cd3f5f2fc087bc020c342"),
    "STAGE.DAT": (155_647_296, "6be1bc49640a9f83ea4a89e5e974293170f5a9f301a88a828464f21c68dbda96"),
}
EXPECTED_SIGN_BLOCK_SHA256 = "08bf199efeda805f55db1c83b5f4de525afed16eee6de5395d6327d703094b88"
EXPECTED_EVIDENCE = (
    (Path("/home/hyuk/사진/푯말.png"), "d345f3fb83de1a491da7e8f3d6ca0b27c0ba935a1c0584000bf238d4db515376"),
    (Path("/home/hyuk/사진/마왕성으로.png"), "780f55a0df8bc0044845e021fd256722c1d8689514b7166d58fca7d73c303c36"),
    (Path("/home/hyuk/사진/다음구역으로.png"), "cf56b332201c0a39b9250e3327b8cb298077a28b498c11f139f500b1e5daddd8"),
    (Path("/home/hyuk/사진/궁극의 디저트 제작 기한까지\n남은 %%시간.png"), "710083db82aa078de63efbe6d46a50112816feffb895758060266eceb7a25025"),
    (Path("/home/hyuk/사진/남은 %%시간.png"), "162a036a9678497fbddf8e566158e1e22ffdce79460f8a16542901e85e7a7f62"),
)

ISO_FILES = v39.ISO_FILES
SIGN_TEXTURES = v39.SIGN_TEXTURES
SIGN_BLOCK_SIZE = v39.SIGN_BLOCK_SIZE
TEXT_BOXES = ((20, 7, 115, 40), (120, 7, 220, 40))


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
    return {name: find_iso_file(iso, path) for name, path in ISO_FILES.items()}


def iso_blob(iso: Path, name: str, records: dict[str, dict] | None = None) -> bytes:
    records = exact_iso_records(iso) if records is None else records
    return read_iso_file(iso, records[name])


def restore_board_without_text(source: Image.Image) -> Image.Image:
    """Rebuild only the upper plank paint, retaining the original silhouette."""
    result = source.copy()
    for x0, x1 in ((20, 114), (120, 220)):
        for y in range(7, 40):
            base = ((177, 140, 79), (184, 146, 83), (169, 132, 75), (181, 142, 80))[(y // 4) % 4]
            for x in range(x0, x1):
                if source.getpixel((x, y))[3] == 0:
                    continue
                noise = ((x * 17 + y * 31) % 11) - 5
                result.putpixel(
                    (x, y), tuple(max(0, min(255, value + noise)) for value in base) + (255,)
                )
        for y, color in ((26, (143, 106, 62, 255)), (27, (200, 164, 96, 255))):
            for x in range(x0, x1):
                if source.getpixel((x, y))[3]:
                    result.putpixel((x, y), color)

    arrow_mask = Image.new("L", source.size, 0)
    mask_pixels = arrow_mask.load()
    source_pixels = source.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, _alpha = source_pixels[x, y]
            is_red = red > 100 and red > green * 1.35 and red > blue * 1.5
            is_green = green > 65 and green > red * 1.18 and green > blue * 1.2
            if is_red or is_green:
                mask_pixels[x, y] = 255
    arrow_mask = arrow_mask.filter(ImageFilter.MaxFilter(5))
    result.paste(source, (0, 0), arrow_mask)
    return result


def sign_target_image(source: Image.Image) -> Image.Image:
    if source.size != (256, 128) or source.mode != "RGBA":
        raise ValueError("표지판 원본 이미지 형식 불일치")
    result = restore_board_without_text(source)
    layer = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(str(v39.KOREAN_FONT), 12)
    v39.draw_centered(draw, "마왕성으로", TEXT_BOXES[0], font)
    v39.draw_centered(draw, "다음 구역으로", TEXT_BOXES[1], font)

    # The model mirrors only these text UV strips.  Pre-mirror the letters so
    # the final on-screen result is left-to-right while leaving arrows intact.
    for box in TEXT_BOXES:
        mirrored = layer.crop(box).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        result.alpha_composite(mirrored, (box[0], box[1]))
    return result


def patch_sign_block(base_block: bytes) -> tuple[bytes, Image.Image, Image.Image, dict]:
    source, before_indices = v39.decode_sign_block(base_block)
    target = sign_target_image(source)
    palette = v39.palette_from_sign_block(base_block)
    cache: dict[tuple[int, int, int, int], int] = {}
    after_indices = before_indices.copy()
    for position, (before_rgba, after_rgba) in enumerate(zip(source.getdata(), target.getdata())):
        if before_rgba == after_rgba:
            continue
        color = tuple(after_rgba)
        if color not in cache:
            cache[color] = v39.nearest_palette_index(color, palette)
        after_indices[position] = cache[color]
    final = bytearray(base_block)
    final[1040:] = v39.swizzle_psp(bytes(after_indices), 256, 128)
    final_bytes = bytes(final)
    raw_preview, decoded_indices = v39.decode_sign_block(final_bytes)
    if decoded_indices != after_indices or final_bytes[:1040] != base_block[:1040]:
        raise ValueError("표지판 팔레트/헤더 또는 스위즐 왕복 불일치")

    predicted = raw_preview.copy()
    for box in TEXT_BOXES:
        corrected = predicted.crop(box).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        predicted.paste(corrected, (box[0], box[1]))
    return final_bytes, raw_preview, predicted, {
        "left_text": "마왕성으로",
        "right_text": "다음 구역으로",
        "raw_atlas_text_orientation": "pre_mirrored_for_model_text_uv",
        "predicted_screen_text_orientation": "normal_left_to_right",
        "changed_logical_pixels": sum(a != b for a, b in zip(before_indices, after_indices)),
        "changed_packed_bytes": sum(a != b for a, b in zip(base_block, final_bytes)),
        "header_palette_unchanged": True,
        "arrows_not_mirrored": True,
    }


def png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.resize((1024, 512), Image.Resampling.NEAREST).save(output, format="PNG")
    return output.getvalue()


def patch_stage(base_stage: bytes) -> tuple[bytes, list[dict], dict, dict[str, bytes]]:
    blocks = []
    for name, record_offset, texture_offset in SIGN_TEXTURES:
        start = record_offset + texture_offset
        block = base_stage[start:start + SIGN_BLOCK_SIZE]
        if sha256_bytes(block) != EXPECTED_SIGN_BLOCK_SHA256:
            raise ValueError(f"V7.15.39 표지판 기준 블록 불일치: {name}@0x{start:X}")
        blocks.append((name, start, block))
    if len({block for _name, _start, block in blocks}) != 1:
        raise ValueError("17개 표지판 기준 블록이 동일하지 않습니다")

    final_block, raw_preview, predicted_preview, metadata = patch_sign_block(blocks[0][2])
    final_stage = bytearray(base_stage)
    writes = []
    for sequence, (name, start, block) in enumerate(blocks, 1):
        final_stage[start:start + SIGN_BLOCK_SIZE] = final_block
        writes.append({
            "id": f"P1-V7.15.40-SIGN-{sequence:02d}",
            "target": f"STAGE.DAT/{name}/texture_06",
            "operation": "pre_mirror_text_strips_for_runtime_uv",
            "offset_hex": f"0x{start + 1040:X}",
            "length": 256 * 128,
            "before_sha256": sha256_bytes(block[1040:]),
            "after_sha256": sha256_bytes(final_block[1040:]),
            "boundary": "256x128_8bpp_swizzled_pixels_only",
        })
    previews = {
        "direction_signs_raw_atlas_preview.png": png_bytes(raw_preview),
        "direction_signs_predicted_screen_preview.png": png_bytes(predicted_preview),
    }
    return bytes(final_stage), writes, metadata | {"patched_copies": 17}, previews


def verify_embedded_korean(base: dict[str, bytes]) -> dict:
    if base["BOOT.BIN"] != base["EBOOT.BIN"]:
        raise ValueError("BOOT/EBOOT 미러 불일치")
    boot = base["BOOT.BIN"]
    for number, offset in v39.NONPAREN_OFFSETS.items():
        raw = v39.make_countdown(number)
        if boot[offset:offset + len(raw)] != raw:
            raise ValueError(f"남은 시간 문자열 불일치: {number}")
    expected_pointers = [
        v39.pointer_for_file_offset(v39.NONPAREN_OFFSETS[number])
        for number in range(10, 0, -1)
    ]
    actual_pointers = [struct.unpack_from("<I", boot, offset)[0] for offset in v39.COUNTDOWN_POINTERS]
    if actual_pointers != expected_pointers:
        raise ValueError("남은 시간 포인터 불일치")

    start, lzs, _row, _rows = extract_start(base["SYSTEM.DAT"])
    tutorial = v39.tutorial_checks(start)
    runtime, _records = v39.runtime_from_start(start)
    expected_strip = v39.target_header_strip(runtime)
    rendered = Image.new("L", (260, 14), 0)
    for index, character in enumerate(v39.SOURCE_HEADER):
        mapping = runtime.mapping_for_char(character)
        rendered.paste(runtime.decode_glyph(int(mapping["glyph_index"])), (index * 20, 0))
    if rendered.tobytes() != expected_strip.tobytes():
        raise ValueError("궁극의 디저트 첫 줄 글리프 스트립 불일치")
    if v39.overlap_count(lzs):
        raise ValueError("부모 START.LZS 겹침 역참조 발견")
    return {
        "countdown_header": "궁극의 디저트 완성 기한까지",
        "countdown_dynamic": "남은 시간 N시간",
        "countdown_slots": 10,
        "countdown_pointers": 10,
        "tutorial": tutorial,
        "start_lzs_overlap_backreferences": 0,
        "runtime_test_requirement": "cold_boot_without_loading_ppsspp_save_state",
        "reason": "save_state_restores_old_executable_ram_and_gpu_text_cache",
    }


def build_resources() -> tuple[dict[str, bytes], list[dict], dict, dict[str, bytes]]:
    records = exact_iso_records(BASE_ISO)
    base = {name: iso_blob(BASE_ISO, name, records) for name in ISO_FILES}
    for name, (size, digest) in EXPECTED_BASE_FILES.items():
        if len(base[name]) != size or sha256_bytes(base[name]) != digest:
            raise ValueError(f"부모 {name} 봉인값 불일치")
    embedded = verify_embedded_korean(base)
    final_stage, writes, sign_meta, previews = patch_stage(base["STAGE.DAT"])
    final = dict(base)
    final["STAGE.DAT"] = final_stage
    if any(final[name] != base[name] for name in ("BOOT.BIN", "EBOOT.BIN", "SYSTEM.DAT")):
        raise ValueError("비대상 ISO 자원이 변경됨")
    return final, writes, {"direction_signs": sign_meta, "embedded_korean": embedded}, previews


def input_seal() -> None:
    if not BASE_ISO.is_file() or BASE_ISO.stat().st_size != EXPECTED_BASE_SIZE:
        raise ValueError("V7.15.39 부모 ISO 크기 불일치")
    if sha256_file(BASE_ISO) != EXPECTED_BASE_SHA256:
        raise ValueError("V7.15.39 부모 ISO 해시 불일치")
    if not v39.KOREAN_FONT.is_file():
        raise FileNotFoundError(v39.KOREAN_FONT)
    for path, digest in EXPECTED_EVIDENCE:
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"사용자 캡처 봉인값 불일치: {path}")


def seal() -> dict:
    input_seal()
    final, writes, metadata, previews = build_resources()
    if OUTPUT_ISO.exists() or RESOURCE_DIR.exists() or REPORT_DIR.exists():
        raise ValueError("V7.15.40 출력 또는 보고서 경로가 이미 존재합니다")
    RESOURCE_DIR.mkdir(parents=True)
    REPORT_DIR.mkdir(parents=True)
    for name, blob in final.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    for name, blob in previews.items():
        (REPORT_DIR / name).write_bytes(blob)
    write_csv("expected_writes.csv", writes)
    report = {
        "format": "prinny1_v7_15_40_town_runtime_orientation_preflight_v1",
        "created_at": v39.now(),
        "authorization": "user_reported_unchanged_runtime_and_reversed_sign_text_2026_08_08",
        "base_iso": {"path": str(BASE_ISO), "size": BASE_ISO.stat().st_size, "sha256": sha256_file(BASE_ISO)},
        "evidence": [{"path": str(path), "sha256": digest} for path, digest in EXPECTED_EVIDENCE],
        "sealed_resources": {name: {"size": len(blob), "sha256": sha256_bytes(blob)} for name, blob in final.items()},
        "sealed_previews": {name: sha256_bytes(blob) for name, blob in previews.items()},
        "expected_write_rows": len(writes),
        "repair": metadata,
        "checks": {
            "only_stage_dat_targeted": True,
            "direction_text_pre_mirrored": True,
            "board_arrows_palette_preserved": True,
            "countdown_and_tutorial_korean_embedded": True,
            "cold_boot_required_for_runtime_test": True,
            "external_textures_used": False,
        },
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json("preflight.json", report)
    return report


def independent_prebuild() -> dict:
    input_seal()
    final, writes, metadata, previews = build_resources()
    for name, blob in final.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"독립 사전 봉인 자원 불일치: {name}")
    for name, blob in previews.items():
        if (REPORT_DIR / name).read_bytes() != blob:
            raise ValueError(f"독립 사전 미리보기 불일치: {name}")
    with (REPORT_DIR / "expected_writes.csv").open(encoding="utf-8-sig") as handle:
        sealed_rows = list(csv.DictReader(handle))
    if len(sealed_rows) != len(writes):
        raise ValueError("독립 사전 Expected Write 수 불일치")
    report = {
        "format": "prinny1_v7_15_40_town_runtime_orientation_prebuild_v1",
        "created_at": v39.now(),
        "verified": metadata,
        "checks": {
            "fresh_parent_recalculation": True,
            "sealed_resources_exact": True,
            "sealed_expected_writes_exact_count": True,
            "boot_eboot_system_unchanged": True,
            "countdown_tutorial_static_proof": True,
        },
        "status": "pass_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    write_json("independent_prebuild.json", report)
    return report


def verify_iso_outside_stage(candidate: Path, stage_record: dict) -> None:
    left = int(stage_record["extent_lba"]) * SECTOR_SIZE
    right = left + int(stage_record["data_length"])
    if candidate.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 크기 변경")
    if hash_range(BASE_ISO, 0, left) != hash_range(candidate, 0, left):
        raise ValueError("STAGE.DAT 앞 ISO 범위 변경")
    if hash_range(BASE_ISO, right, BASE_ISO.stat().st_size) != hash_range(candidate, right, candidate.stat().st_size):
        raise ValueError("STAGE.DAT 뒤 ISO 범위 변경")


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
    stage = (RESOURCE_DIR / "STAGE.DAT").read_bytes()
    record = records["STAGE.DAT"]
    if len(stage) != int(record["data_length"]):
        raise ValueError("STAGE.DAT 크기 변경")
    with temporary.open("r+b") as handle:
        handle.seek(int(record["extent_lba"]) * SECTOR_SIZE)
        handle.write(stage)
        handle.flush()
        os.fsync(handle.fileno())
    verify_iso_outside_stage(temporary, record)
    check = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if check.returncode != 0 or "Everything is Ok" not in check.stdout:
        raise ValueError("ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_40_town_runtime_orientation_iso_v1",
        "created_at": v39.now(),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "checks": {"only_stage_dat_extent_changed": True, "seven_zip_structure_test": True, "parent_not_overwritten": True},
        "status": "built_independent_postbuild_review_required",
    }
    write_json("build_report.json", report)
    return report


def independent_postbuild() -> dict:
    base_records = exact_iso_records(BASE_ISO)
    final_records = exact_iso_records(OUTPUT_ISO)
    for name in ISO_FILES:
        if (base_records[name]["extent_lba"], base_records[name]["data_length"]) != (
            final_records[name]["extent_lba"], final_records[name]["data_length"]
        ):
            raise ValueError(f"사후 ISO 자원 경계 변경: {name}")
    verify_iso_outside_stage(OUTPUT_ISO, base_records["STAGE.DAT"])
    for name in ISO_FILES:
        extracted = iso_blob(OUTPUT_ISO, name, final_records)
        if extracted != (RESOURCE_DIR / name).read_bytes():
            raise ValueError(f"사후 ISO 재추출 불일치: {name}")
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
        "format": "prinny1_v7_15_40_town_runtime_orientation_postbuild_v1",
        "created_at": v39.now(),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": metadata | {"expected_write_rows": len(writes), "ppsspp_launched": False},
        "checks": {
            "only_stage_dat_extent_changed": True,
            "sealed_resources_reextracted_exactly": True,
            "fresh_parent_recalculation": True,
            "boot_eboot_system_preserved": True,
            "direction_sign_texture_copies_exact": 17,
            "countdown_tutorial_korean_embedded": True,
            "seven_zip_structure_retest": True,
        },
        "runtime_instruction": "Fully restart the game; do not load a PPSSPP save state made before V7.15.40.",
        "status": "pass_ready_for_cold_boot_ppsspp_runtime_test",
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
    print("direction signs: 17 pre-mirrored text strips")
    print("countdown/tutorial: embedded Korean verified; cold boot required")
    print("PPSSPP: not launched")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
