#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from build_font_canary import (
    BYTES_PER_GLYPH,
    SOURCE_START,
    SOURCE_SYSTEM,
    TXP_PIXEL_OFFSET,
    align_up,
    build_literal_lzs,
    encode_4bpp,
    parse_nispack_start_entry,
    parse_start_records,
    read_u32,
)
from build_hangul_canary import (
    find_korean_font,
    render_hangul,
)
from build_independent_hangul_test import (
    rebuild_start_archive,
    resource_blob,
)
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive


CHARACTER = "가"

# 사용되지 않는 유효 문자 九
RECLAIMED_CHARACTER = "九"
RECLAIMED_SJIS = bytes.fromhex("8B E3")
RECLAIMED_GLYPH_INDEX = 0x0334

DEMO_RESOURCE = "Demo00.dat"
DEMO_OFFSET = 0x2E
EXPECTED_OLD_BYTES = bytes.fromhex("82 CC")

OUTPUT_DIR = Path(
    "workspace/test/reclaimed_hangul"
)
OUTPUT_START = OUTPUT_DIR / "start_reclaimed_hangul.dat"
OUTPUT_LZS = OUTPUT_DIR / "start_reclaimed_hangul.lzs"
OUTPUT_SYSTEM = (
    OUTPUT_DIR / "SYSTEM_reclaimed_hangul.DAT"
)
OUTPUT_PREVIEW = (
    OUTPUT_DIR / "reclaimed_hangul_preview.png"
)
OUTPUT_MANIFEST = OUTPUT_DIR / "manifest.json"


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


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

    if len(encoded_glyph) != BYTES_PER_GLYPH:
        raise ValueError(
            "한글 글리프 크기가 잘못됐습니다."
        )

    preview.save(OUTPUT_PREVIEW)

    original_start = SOURCE_START.read_bytes()
    records = parse_start_records(
        original_start
    )

    record_map = {
        str(record["name"]).casefold(): record
        for record in records
    }

    for name in [
        "font.txp",
        DEMO_RESOURCE,
    ]:
        if name.casefold() not in record_map:
            raise ValueError(
                f"리소스를 찾지 못했습니다: {name}"
            )

    original_txp = resource_blob(
        original_start,
        record_map["font.txp"],
    )
    original_demo = resource_blob(
        original_start,
        record_map[DEMO_RESOURCE.casefold()],
    )

    patched_txp = bytearray(
        original_txp
    )

    width = struct.unpack_from(
        "<H",
        patched_txp,
        0x00,
    )[0]
    height = struct.unpack_from(
        "<H",
        patched_txp,
        0x02,
    )[0]

    if width != 20:
        raise ValueError(
            f"예상하지 못한 TXP 너비: {width}"
        )

    if height != 32872:
        raise ValueError(
            f"예상하지 못한 TXP 높이: {height}"
        )

    glyph_offset = (
        TXP_PIXEL_OFFSET
        + RECLAIMED_GLYPH_INDEX
        * BYTES_PER_GLYPH
    )
    glyph_end = (
        glyph_offset
        + BYTES_PER_GLYPH
    )

    if glyph_end > len(patched_txp):
        raise ValueError(
            "재활용 글리프 위치가 TXP 범위를 벗어났습니다."
        )

    original_glyph = bytes(
        patched_txp[
            glyph_offset:
            glyph_end
        ]
    )

    patched_txp[
        glyph_offset:
        glyph_end
    ] = encoded_glyph

    changed_glyph_bytes = sum(
        old != new
        for old, new in zip(
            original_glyph,
            encoded_glyph,
        )
    )

    if changed_glyph_bytes == 0:
        raise ValueError(
            "가 글리프가 기존 九 글리프와 동일합니다."
        )

    # 크기와 헤더는 절대 변경하지 않는다.
    if len(patched_txp) != len(original_txp):
        raise ValueError(
            "font.txp 크기가 변경됐습니다."
        )

    if struct.unpack_from(
        "<H",
        patched_txp,
        0x02,
    )[0] != height:
        raise ValueError(
            "font.txp 높이가 변경됐습니다."
        )

    patched_demo = bytearray(
        original_demo
    )

    actual_old_bytes = bytes(
        patched_demo[
            DEMO_OFFSET:
            DEMO_OFFSET + 2
        ]
    )

    if actual_old_bytes != EXPECTED_OLD_BYTES:
        raise ValueError(
            "Demo00.dat 대상 바이트가 예상과 다릅니다: "
            f"actual={actual_old_bytes.hex(' ').upper()}, "
            f"expected={EXPECTED_OLD_BYTES.hex(' ').upper()}"
        )

    patched_demo[
        DEMO_OFFSET:
        DEMO_OFFSET + 2
    ] = RECLAIMED_SJIS

    replacements = {
        "font.txp": bytes(patched_txp),
        DEMO_RESOURCE.casefold(): bytes(patched_demo),
    }

    rebuilt_start = rebuild_start_archive(
        original_start,
        records,
        replacements,
    )

    if len(rebuilt_start) != len(original_start):
        raise ValueError(
            "start.dat 크기가 변경됐습니다: "
            f"0x{len(original_start):X} -> "
            f"0x{len(rebuilt_start):X}"
        )

    OUTPUT_START.write_bytes(
        rebuilt_start
    )

    rebuilt_records = parse_start_records(
        rebuilt_start
    )
    rebuilt_map = {
        str(record["name"]).casefold(): record
        for record in rebuilt_records
    }

    rebuilt_txp = resource_blob(
        rebuilt_start,
        rebuilt_map["font.txp"],
    )
    rebuilt_demo = resource_blob(
        rebuilt_start,
        rebuilt_map[DEMO_RESOURCE.casefold()],
    )

    if len(rebuilt_txp) != len(original_txp):
        raise ValueError(
            "재구성 후 TXP 크기가 변경됐습니다."
        )

    if rebuilt_txp[
        glyph_offset:
        glyph_end
    ] != encoded_glyph:
        raise ValueError(
            "재구성 후 가 글리프 검증 실패"
        )

    if rebuilt_demo[
        DEMO_OFFSET:
        DEMO_OFFSET + 2
    ] != RECLAIMED_SJIS:
        raise ValueError(
            "재구성 후 대사 코드 검증 실패"
        )

    archive = StartRuntimeArchive.load(
        OUTPUT_START
    )

    if len(archive.records) != len(records):
        raise ValueError(
            "start.dat 리소스 수가 변경됐습니다."
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
        rebuilt_start,
        extension,
        flag,
    )
    OUTPUT_LZS.write_bytes(
        new_lzs
    )

    decoded_start, decoded_header = (
        decompress_buffer(new_lzs)
    )

    if decoded_start != rebuilt_start:
        raise ValueError(
            "LZS 왕복 검증 실패"
        )

    patched_system = bytearray(
        original_system
    )

    new_lzs_offset = align_up(
        len(patched_system),
        0x800,
    )

    patched_system.extend(
        b"\x00" * (
            new_lzs_offset
            - len(patched_system)
        )
    )
    patched_system.extend(
        new_lzs
    )

    entry_offset = int(
        start_entry["entry_offset"]
    )

    struct.pack_into(
        "<I",
        patched_system,
        entry_offset + 0x20,
        new_lzs_offset,
    )
    struct.pack_into(
        "<I",
        patched_system,
        entry_offset + 0x24,
        len(new_lzs),
    )

    patched_system_bytes = bytes(
        patched_system
    )
    OUTPUT_SYSTEM.write_bytes(
        patched_system_bytes
    )

    verified_entry = parse_nispack_start_entry(
        patched_system_bytes
    )
    verified_offset = int(
        verified_entry["data_offset"]
    )
    verified_size = int(
        verified_entry["size"]
    )

    verified_start, _ = decompress_buffer(
        patched_system_bytes[
            verified_offset:
            verified_offset + verified_size
        ]
    )

    if verified_start != rebuilt_start:
        raise ValueError(
            "SYSTEM.DAT 내부 start.dat 검증 실패"
        )

    manifest = {
        "format": (
            "prinny_reclaimed_hangul_test_v1"
        ),
        "character": CHARACTER,
        "font_path": str(font_path),
        "reclaimed": {
            "character": RECLAIMED_CHARACTER,
            "sjis": (
                RECLAIMED_SJIS.hex(" ").upper()
            ),
            "glyph_index": (
                RECLAIMED_GLYPH_INDEX
            ),
            "glyph_index_hex": (
                f"0x{RECLAIMED_GLYPH_INDEX:04X}"
            ),
            "glyph_offset": glyph_offset,
            "glyph_offset_hex": (
                f"0x{glyph_offset:X}"
            ),
            "changed_glyph_bytes": (
                changed_glyph_bytes
            ),
        },
        "demo": {
            "resource": DEMO_RESOURCE,
            "offset": DEMO_OFFSET,
            "offset_hex": (
                f"0x{DEMO_OFFSET:X}"
            ),
            "old_bytes": (
                EXPECTED_OLD_BYTES.hex(" ").upper()
            ),
            "new_bytes": (
                RECLAIMED_SJIS.hex(" ").upper()
            ),
            "expected_text": (
                "やりごたえバッチリ가"
            ),
        },
        "sizes": {
            "original_start": len(original_start),
            "rebuilt_start": len(rebuilt_start),
            "original_txp": len(original_txp),
            "rebuilt_txp": len(rebuilt_txp),
        },
        "hashes": {
            "original_txp": sha1(original_txp),
            "patched_txp": sha1(
                bytes(patched_txp)
            ),
            "patched_system": sha1(
                patched_system_bytes
            ),
        },
        "lzs_header": decoded_header,
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

    print("RECLAIMED HANGUL TEST")
    print("=====================")
    print(f"CHARACTER         : {CHARACTER}")
    print(
        f"RECLAIMED CODE    : "
        f"{RECLAIMED_CHARACTER} / "
        f"{RECLAIMED_SJIS.hex(' ').upper()}"
    )
    print(
        f"GLYPH INDEX       : "
        f"0x{RECLAIMED_GLYPH_INDEX:04X}"
    )
    print(
        f"GLYPH OFFSET      : "
        f"0x{glyph_offset:X}"
    )
    print(
        f"CHANGED BYTES     : "
        f"{changed_glyph_bytes}"
    )
    print(
        f"TXP SIZE          : "
        f"0x{len(original_txp):X} -> "
        f"0x{len(patched_txp):X}"
    )
    print(
        f"TXP HEIGHT        : "
        f"{height} -> {height}"
    )
    print(
        f"START SIZE        : "
        f"0x{len(original_start):X} -> "
        f"0x{len(rebuilt_start):X}"
    )
    print(
        f"EXPECTED TEXT     : "
        f"やりごたえバッチリ가"
    )
    print()
    print("SYSTEM  :", OUTPUT_SYSTEM)
    print("PREVIEW :", OUTPUT_PREVIEW)
    print("MANIFEST:", OUTPUT_MANIFEST)
    print()
    print("SELF TEST: PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
