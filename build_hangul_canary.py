#!/usr/bin/env python3
from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from build_font_canary import (
    BYTES_PER_GLYPH,
    EXPECTED_GLYPH_INDEX,
    SOURCE_START,
    SOURCE_SYSTEM,
    TARGET_TABLE_INDEX,
    TXP_PIXEL_OFFSET,
    align_up,
    build_literal_lzs,
    decode_name,
    encode_4bpp,
    find_start_record,
    parse_nispack_start_entry,
    parse_start_records,
    read_u32,
    sha1,
)
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive


CHARACTER = "가"

OUTPUT_DIR = Path(
    "workspace/test/hangul_canary"
)
OUTPUT_START = OUTPUT_DIR / "start_hangul_canary.dat"
OUTPUT_LZS = OUTPUT_DIR / "start_hangul_canary.lzs"
OUTPUT_SYSTEM = OUTPUT_DIR / "SYSTEM_hangul_canary.DAT"
OUTPUT_PREVIEW = OUTPUT_DIR / "hangul_canary_preview.png"
OUTPUT_MANIFEST = OUTPUT_DIR / "manifest.json"


def find_korean_font() -> Path:
    result = subprocess.run(
        [
            "fc-match",
            "-f",
            "%{file}\n",
            "sans:lang=ko",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    for line in result.stdout.splitlines():
        path = Path(line.strip())

        if path.is_file():
            return path

    raise FileNotFoundError(
        "한글을 지원하는 시스템 폰트를 찾지 못했습니다."
    )


def render_hangul(
    font_path: Path,
) -> tuple[list[list[int]], Image.Image]:
    scale = 4
    width = 20
    height = 14

    canvas = Image.new(
        "L",
        (width * scale, height * scale),
        0,
    )
    draw = ImageDraw.Draw(canvas)

    font = ImageFont.truetype(
        str(font_path),
        52,
    )

    bbox = draw.textbbox(
        (0, 0),
        CHARACTER,
        font=font,
    )

    glyph_width = bbox[2] - bbox[0]
    glyph_height = bbox[3] - bbox[1]

    x = (
        canvas.width - glyph_width
    ) // 2 - bbox[0]

    y = (
        canvas.height - glyph_height
    ) // 2 - bbox[1]

    draw.text(
        (x, y),
        CHARACTER,
        font=font,
        fill=255,
    )

    reduced = canvas.resize(
        (width, height),
        Image.Resampling.LANCZOS,
    )

    pixels: list[list[int]] = []

    for row_index in range(height):
        row: list[int] = []

        for column_index in range(width):
            value = reduced.getpixel(
                (column_index, row_index)
            )

            # 0~255를 4bpp 0~15로 변환
            row.append(
                max(
                    0,
                    min(
                        15,
                        round(value / 17),
                    ),
                )
            )

        pixels.append(row)

    preview = reduced.resize(
        (width * 12, height * 12),
        Image.Resampling.NEAREST,
    )

    return pixels, preview


def main() -> int:
    if not SOURCE_START.is_file():
        raise FileNotFoundError(
            f"start.dat 없음: {SOURCE_START}"
        )

    if not SOURCE_SYSTEM.is_file():
        raise FileNotFoundError(
            f"SYSTEM.DAT 없음: {SOURCE_SYSTEM}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    font_path = find_korean_font()
    pixels, preview = render_hangul(
        font_path
    )
    encoded_glyph = encode_4bpp(
        pixels
    )

    original_start = SOURCE_START.read_bytes()
    records = parse_start_records(
        original_start
    )

    font_fnt = find_start_record(
        records,
        "font.fnt",
    )
    font_txp = find_start_record(
        records,
        "font.txp",
    )

    fnt_offset = int(
        font_fnt["data_offset"]
    )
    txp_offset = int(
        font_txp["data_offset"]
    )
    txp_size = int(
        font_txp["size"]
    )

    table_count = struct.unpack_from(
        "<H",
        original_start,
        fnt_offset,
    )[0]

    if TARGET_TABLE_INDEX >= table_count:
        raise ValueError(
            "대상 폰트 테이블 인덱스가 범위를 벗어났습니다."
        )

    glyph_index = struct.unpack_from(
        "<H",
        original_start,
        fnt_offset
        + 2
        + TARGET_TABLE_INDEX * 2,
    )[0]

    if glyph_index != EXPECTED_GLYPH_INDEX:
        raise ValueError(
            "の 글리프 인덱스가 예상값과 다릅니다: "
            f"0x{glyph_index:04X}"
        )

    glyph_offset_in_txp = (
        TXP_PIXEL_OFFSET
        + glyph_index * BYTES_PER_GLYPH
    )

    if (
        glyph_offset_in_txp
        + BYTES_PER_GLYPH
        > txp_size
    ):
        raise ValueError(
            "글리프 위치가 font.txp 범위를 벗어났습니다."
        )

    absolute_offset = (
        txp_offset
        + glyph_offset_in_txp
    )

    patched_start = bytearray(
        original_start
    )

    original_glyph = bytes(
        patched_start[
            absolute_offset:
            absolute_offset
            + BYTES_PER_GLYPH
        ]
    )

    patched_start[
        absolute_offset:
        absolute_offset
        + BYTES_PER_GLYPH
    ] = encoded_glyph

    changed_bytes = sum(
        before != after
        for before, after
        in zip(
            original_glyph,
            encoded_glyph,
        )
    )

    if changed_bytes == 0:
        raise ValueError(
            "생성된 한글 글리프가 원본과 동일합니다."
        )

    patched_start_bytes = bytes(
        patched_start
    )
    OUTPUT_START.write_bytes(
        patched_start_bytes
    )
    preview.save(
        OUTPUT_PREVIEW
    )

    original_system = SOURCE_SYSTEM.read_bytes()
    start_entry = parse_nispack_start_entry(
        original_system
    )

    old_lzs_offset = int(
        start_entry["data_offset"]
    )
    old_lzs_size = int(
        start_entry["size"]
    )

    old_lzs = original_system[
        old_lzs_offset:
        old_lzs_offset + old_lzs_size
    ]

    extension = old_lzs[0:4]
    flag = read_u32(
        old_lzs,
        0x0C,
    ) & 0xFF

    new_lzs = build_literal_lzs(
        patched_start_bytes,
        extension,
        flag,
    )
    OUTPUT_LZS.write_bytes(
        new_lzs
    )

    decoded_start, decoded_header = (
        decompress_buffer(new_lzs)
    )

    if decoded_start != patched_start_bytes:
        raise ValueError(
            "한글 카나리 LZS 왕복 검증 실패"
        )

    new_system = bytearray(
        original_system
    )

    new_lzs_offset = align_up(
        len(new_system),
        0x800,
    )

    new_system.extend(
        b"\x00"
        * (
            new_lzs_offset
            - len(new_system)
        )
    )
    new_system.extend(
        new_lzs
    )

    entry_offset = int(
        start_entry["entry_offset"]
    )

    struct.pack_into(
        "<I",
        new_system,
        entry_offset + 0x20,
        new_lzs_offset,
    )
    struct.pack_into(
        "<I",
        new_system,
        entry_offset + 0x24,
        len(new_lzs),
    )

    new_system_bytes = bytes(
        new_system
    )
    OUTPUT_SYSTEM.write_bytes(
        new_system_bytes
    )

    # 패치된 start.dat 구조 확인
    archive = StartRuntimeArchive.load(
        OUTPUT_START
    )

    if archive.find_record("font.txp") is None:
        raise ValueError(
            "패치된 start.dat에서 font.txp를 찾지 못했습니다."
        )

    # SYSTEM.DAT 내부 새 LZS 확인
    verified_entry = parse_nispack_start_entry(
        new_system_bytes
    )

    verified_offset = int(
        verified_entry["data_offset"]
    )
    verified_size = int(
        verified_entry["size"]
    )

    verified_lzs = new_system_bytes[
        verified_offset:
        verified_offset + verified_size
    ]

    verified_start, _ = decompress_buffer(
        verified_lzs
    )

    if verified_start != patched_start_bytes:
        raise ValueError(
            "SYSTEM.DAT 내부 한글 카나리 검증 실패"
        )

    manifest = {
        "format": "prinny_hangul_canary_v1",
        "character": CHARACTER,
        "font_path": str(font_path),
        "table_index": TARGET_TABLE_INDEX,
        "table_index_hex": (
            f"0x{TARGET_TABLE_INDEX:04X}"
        ),
        "glyph_index": glyph_index,
        "glyph_index_hex": (
            f"0x{glyph_index:04X}"
        ),
        "glyph_offset_in_txp": (
            glyph_offset_in_txp
        ),
        "glyph_offset_in_txp_hex": (
            f"0x{glyph_offset_in_txp:X}"
        ),
        "changed_bytes": changed_bytes,
        "source_start_sha1": sha1(
            original_start
        ),
        "patched_start_sha1": sha1(
            patched_start_bytes
        ),
        "source_system_sha1": sha1(
            original_system
        ),
        "patched_system_sha1": sha1(
            new_system_bytes
        ),
        "new_lzs_offset": (
            new_lzs_offset
        ),
        "new_lzs_size": len(
            new_lzs
        ),
        "decoded_header": (
            decoded_header
        ),
        "outputs": {
            "start": str(OUTPUT_START),
            "lzs": str(OUTPUT_LZS),
            "system": str(OUTPUT_SYSTEM),
            "preview": str(OUTPUT_PREVIEW),
        },
        "status": "pass",
    }

    OUTPUT_MANIFEST.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("HANGUL CANARY BUILD")
    print("===================")
    print(f"CHARACTER       : {CHARACTER}")
    print(f"FONT            : {font_path}")
    print(
        f"TABLE INDEX     : "
        f"0x{TARGET_TABLE_INDEX:04X}"
    )
    print(
        f"GLYPH INDEX     : "
        f"0x{glyph_index:04X}"
    )
    print(
        f"CHANGED BYTES   : "
        f"{changed_bytes}"
    )
    print(
        f"NEW LZS OFFSET  : "
        f"0x{new_lzs_offset:X}"
    )
    print()
    print("START   :", OUTPUT_START)
    print("LZS     :", OUTPUT_LZS)
    print("SYSTEM  :", OUTPUT_SYSTEM)
    print("PREVIEW :", OUTPUT_PREVIEW)
    print("MANIFEST:", OUTPUT_MANIFEST)
    print()
    print("SELF TEST: PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
