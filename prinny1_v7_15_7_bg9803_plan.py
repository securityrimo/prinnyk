#!/usr/bin/env python3
"""Restore, translate, repack, and seal the bg9803 trial information screen."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from scripts.prinny_txp_preview import decode_txp, swizzle_psp, txp_layout, unswizzle_psp


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_6_ui_images/prinny_korean_v7_15_6_ui_images.iso"
JAPANESE_TXP = ROOT / "workspace/unpack/BG_runtime/bg9803.txp"
CANDIDATE_TXP = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/bg_resources/bg9803.txp"
FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
WORKSPACE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
OUTPUT_PNG = WORKSPACE / "translated/resized/bg/bg9803.png"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_7_bg9803_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_7_bg9803_plan"
EXPECTED = {
    BASE_ISO: "384302e1aa98883b1e4ddc1e0535f78c5d303a992387fbc2d104b97cf3f538eb",
    JAPANESE_TXP: "83447cf74db7c52fcff8b51616dd17bc9e2efc5c1235c449b22859fce8d6054f",
    CANDIDATE_TXP: "4b3245268dcc9584a033e0135c20a8673a642e4d9b698915ed52145e02f64e3c",
    FONT: "faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb",
}
MAIN_LINES = (
    "체험판을 플레이해 주셔서",
    "감사합니다.",
    "이번 체험판은 액션 게임을",
    "좋아하시는 분들을 위해",
    "'적당히 도전할 만한 난이도'의",
    "스테이지를 준비했습니다.",
    "제품판은 튜토리얼도 충실하며,",
    "쉬운 스테이지부터 숙련자용",
    "도전적인 스테이지까지 폭넓게",
    "준비되어 있습니다.",
    "꼭 제품판도 플레이해 주세요!",
)
BOTTOM_LINES = (
    "프리니 ~제가 주인공이어도 되는 검까?~",
    "발매 예정일: 2008년 11월 20일(목)",
    "희망 소비자 가격: 4,980엔(세금 포함 5,229엔)",
)


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def restore_and_typeset(original: Image.Image) -> Image.Image:
    image = original.convert("RGBA")
    logo = image.crop((430, 0, 480, 48))
    background = image.crop((180, 0, 480, 198)).filter(ImageFilter.GaussianBlur(12))
    shade = Image.new("RGBA", background.size, (11, 17, 30, 205))
    background = Image.alpha_composite(background, shade)
    edited = image.copy()
    edited.paste(background, (180, 0))
    edited.paste(logo, (430, 0))
    draw = ImageDraw.Draw(edited)
    main_font = ImageFont.truetype(str(FONT), 15, index=1)
    for index, line in enumerate(MAIN_LINES):
        draw.text((184, 9 + index * 16), line, font=main_font, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
    draw.rounded_rectangle((183, 198, 470, 264), radius=11, fill=(177, 177, 181, 255))
    bottom_font = ImageFont.truetype(str(FONT), 12, index=1)
    for index, line in enumerate(BOTTOM_LINES):
        draw.text((189, 202 + index * 18), line, font=bottom_font, fill=(5, 5, 8, 255), stroke_width=1, stroke_fill=(235, 235, 235, 255))
    return edited


def repack_preserving_palette(source: bytes, edited: Image.Image) -> bytes:
    width, height, palette_colors, pixel_offset, pixel_bytes, swizzled = txp_layout(source)
    if palette_colors != 256 or edited.size != (width, height):
        raise ValueError("bg9803 TXP 레이아웃 불일치")
    palette = [tuple(source[0x10 + index * 4:0x14 + index * 4]) for index in range(256)]
    packed = source[pixel_offset:pixel_offset + pixel_bytes]
    linear = unswizzle_psp(packed, width, height) if swizzled else packed
    original = Image.frombytes("RGBA", (width, height), b"".join(bytes(palette[index]) for index in linear))
    output = bytearray(linear)
    cache: dict[tuple[int, int, int, int], int] = {}
    for position, color in enumerate(edited.convert("RGBA").getdata()):
        if color == original.getdata()[position]:
            continue
        if color not in cache:
            cache[color] = min(
                range(256),
                key=lambda index: sum((color[channel] - palette[index][channel]) ** 2 for channel in range(4)),
            )
        output[position] = cache[color]
    encoded = swizzle_psp(bytes(output), width, height) if swizzled else bytes(output)
    result = bytearray(source)
    result[pixel_offset:pixel_offset + pixel_bytes] = encoded
    return bytes(result)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.7 입력 해시 불일치: {path}")
    japanese = JAPANESE_TXP.read_bytes()
    candidate = CANDIDATE_TXP.read_bytes()
    if japanese[:1040] != candidate[:1040]:
        raise ValueError("일본어 원본과 xdelta bg9803 팔레트/헤더가 다릅니다.")
    original_image = decode_txp(JAPANESE_TXP)
    candidate_image = decode_txp(CANDIDATE_TXP)
    for y in range(original_image.height):
        for x in range(original_image.width):
            if x < 180 and original_image.getpixel((x, y)) != candidate_image.getpixel((x, y)):
                raise ValueError(f"xdelta가 패키지 그림까지 변경했습니다: ({x},{y})")
    typeset = restore_and_typeset(original_image)
    translated_txp = repack_preserving_palette(japanese, typeset)
    temporary_txp = OUTPUT_DIR / ".bg9803.preview.txp"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary_txp.write_bytes(translated_txp)
    final_image = decode_txp(temporary_txp)
    temporary_txp.unlink()
    if final_image.size != (480, 272):
        raise ValueError("bg9803 재디코드 캔버스 불일치")
    for y in range(final_image.height):
        for x in range(180):
            if final_image.getpixel((x, y)) != candidate_image.getpixel((x, y)):
                raise ValueError(f"패키지 그림 영역 변경: ({x},{y})")

    base_bg = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "BG.DAT"]))
    records = system_records(base_bg)
    record = next(row for row in records if row["name"].casefold() == "bg9803.txp")
    before = base_bg[record["data_offset"]:record["data_offset"] + record["size"]]
    if before != candidate or len(translated_txp) != record["size"]:
        raise ValueError("부모 BG.DAT bg9803 슬롯 기준 불일치")
    final_bg = bytearray(base_bg)
    final_bg[record["data_offset"]:record["data_offset"] + record["size"]] = translated_txp
    if bytes(final_bg[:record["data_offset"]]) != base_bg[:record["data_offset"]] or bytes(final_bg[record["data_offset"] + record["size"]:]) != base_bg[record["data_offset"] + record["size"]:]:
        raise ValueError("bg9803 슬롯 밖 BG.DAT 변경")

    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    final_image.save(OUTPUT_PNG, optimize=True)
    (OUTPUT_DIR / "bg9803.txp").write_bytes(translated_txp)
    (OUTPUT_DIR / "BG.DAT").write_bytes(bytes(final_bg))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / "expected_write_confirmed.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("logical_id", "target", "offset_hex", "write_span", "expected_before_hex", "write_after_hex"))
        writer.writeheader()
        writer.writerow({
            "logical_id": "P1-V7.15.7-BG9803-TXP", "target": "BG.DAT",
            "offset_hex": f"0x{record['data_offset']:X}", "write_span": record["size"],
            "expected_before_hex": before.hex().upper(), "write_after_hex": translated_txp.hex().upper(),
        })
    report = {
        "format": "prinny1_v7_15_7_bg9803_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_requested_bg9803_original_restore_korean_translation_and_ppsspp_test_2026_08_01",
        "translation": {"main_lines": list(MAIN_LINES), "bottom_lines": list(BOTTOM_LINES)},
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "sealed": {"BG.DAT": sha256_bytes(bytes(final_bg)), "bg9803.txp": sha256_bytes(translated_txp), "bg9803.png": sha256_file(OUTPUT_PNG)},
        "verified": {"canvas": [480, 272], "palette_colors": 256, "txp_size": len(translated_txp), "expected_writes": 1},
        "checks": {"japanese_original_used_for_clean_background": True, "package_art_left_180px_preserved": True, "existing_palette_and_header_preserved": True, "only_bg9803_slot_changed": True, "base_iso_modified": False, "iso_created": False},
        "status": "bg9803_resource_sealed_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PNG: {OUTPUT_PNG}")
    print(f"TXP: {len(translated_txp)} bytes")
    print(f"BG.DAT: {sha256_bytes(bytes(final_bg))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
