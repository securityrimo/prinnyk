#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from build_font_canary import (
    BYTES_PER_GLYPH,
    SOURCE_START,
    SOURCE_SYSTEM,
    TXP_PIXEL_OFFSET,
    align_up,
    build_literal_lzs,
    encode_4bpp,
    find_start_record,
    parse_nispack_start_entry,
    parse_start_records,
    read_u32,
)
from build_hangul_canary import (
    find_korean_font,
    render_hangul,
)
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive


CHARACTER = "가"
UNICODE_VALUE = 0xAC00

JIS_CODE = 0x7521
SJIS_CODE = bytes.fromhex("EB 40")
FNT_TABLE_INDEX = 0x1F3C

DEMO_RESOURCE = "Demo00.dat"
DEMO_OFFSET = 0xA8
EXPECTED_DEMO_BYTES = bytes.fromhex("82 CC")

GLYPH_WIDTH = 20
GLYPH_HEIGHT = 14
CURRENT_TXP_HEIGHT = 32872
CURRENT_GLYPH_COUNT = 2348
NEW_GLYPH_INDEX = CURRENT_GLYPH_COUNT

OUTPUT_DIR = Path(
    "workspace/test/independent_hangul"
)
OUTPUT_START = OUTPUT_DIR / "start_independent_hangul.dat"
OUTPUT_LZS = OUTPUT_DIR / "start_independent_hangul.lzs"
OUTPUT_SYSTEM = (
    OUTPUT_DIR / "SYSTEM_independent_hangul.DAT"
)
OUTPUT_PREVIEW = (
    OUTPUT_DIR / "independent_hangul_preview.png"
)
OUTPUT_MANIFEST = OUTPUT_DIR / "manifest.json"


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def read_u16(
    data: bytes | bytearray,
    offset: int,
) -> int:
    return struct.unpack_from(
        "<H",
        data,
        offset,
    )[0]


def write_u16(
    data: bytearray,
    offset: int,
    value: int,
) -> None:
    struct.pack_into(
        "<H",
        data,
        offset,
        value,
    )


def resource_blob(
    start_data: bytes,
    record: dict[str, int | str],
) -> bytes:
    start = int(record["data_offset"])
    end = int(record["end"])

    return start_data[start:end]


def rebuild_start_archive(
    original: bytes,
    records: list[dict[str, int | str]],
    replacements: dict[str, bytes],
) -> bytes:
    count = read_u32(original, 0)
    table_end = count * 0x20

    if len(records) != count:
        raise ValueError(
            "start.dat 레코드 수가 일치하지 않습니다."
        )

    first_data_offset = int(
        records[0]["data_offset"]
    )

    if first_data_offset < table_end:
        raise ValueError(
            "첫 리소스 오프셋이 목차보다 앞에 있습니다."
        )

    rebuilt = bytearray(
        original[:first_data_offset]
    )

    for record in records:
        name = str(record["name"])
        record_offset = int(
            record["record_offset"]
        )

        new_offset = len(rebuilt)

        struct.pack_into(
            "<I",
            rebuilt,
            record_offset + 0x04,
            new_offset,
        )

        blob = replacements.get(
            name.casefold()
        )

        if blob is None:
            blob = resource_blob(
                original,
                record,
            )

        rebuilt.extend(blob)

    return bytes(rebuilt)


def patch_font_fnt(
    blob: bytes,
) -> tuple[bytes, dict[str, Any]]:
    patched = bytearray(blob)

    table_count = read_u16(
        patched,
        0,
    )

    if FNT_TABLE_INDEX >= table_count:
        raise ValueError(
            "font.fnt 인덱스가 범위를 벗어났습니다."
        )

    map_offset = (
        2 + FNT_TABLE_INDEX * 2
    )

    old_glyph = read_u16(
        patched,
        map_offset,
    )

    if old_glyph != 0:
        raise ValueError(
            "선택 코드가 이미 글리프에 연결돼 있습니다: "
            f"0x{old_glyph:04X}"
        )

    write_u16(
        patched,
        map_offset,
        NEW_GLYPH_INDEX,
    )

    return bytes(patched), {
        "table_count": table_count,
        "table_index": FNT_TABLE_INDEX,
        "table_index_hex": (
            f"0x{FNT_TABLE_INDEX:04X}"
        ),
        "old_glyph": old_glyph,
        "new_glyph": NEW_GLYPH_INDEX,
        "new_glyph_hex": (
            f"0x{NEW_GLYPH_INDEX:04X}"
        ),
        "map_offset": map_offset,
        "map_offset_hex": (
            f"0x{map_offset:X}"
        ),
    }


def patch_font_txp(
    blob: bytes,
    glyph: bytes,
) -> tuple[bytes, dict[str, Any]]:
    if len(glyph) != BYTES_PER_GLYPH:
        raise ValueError(
            "추가할 글리프 크기가 잘못됐습니다."
        )

    patched = bytearray(blob)

    width = read_u16(
        patched,
        0x00,
    )
    height = read_u16(
        patched,
        0x02,
    )

    if width != GLYPH_WIDTH:
        raise ValueError(
            f"예상하지 못한 TXP 너비: {width}"
        )

    if height != CURRENT_TXP_HEIGHT:
        raise ValueError(
            f"예상하지 못한 TXP 높이: {height}"
        )

    expected_size = (
        TXP_PIXEL_OFFSET
        + width * height // 2
    )

    if len(patched) != expected_size:
        raise ValueError(
            "TXP 크기 검증 실패: "
            f"actual=0x{len(patched):X}, "
            f"expected=0x{expected_size:X}"
        )

    calculated_glyph_count = (
        height // GLYPH_HEIGHT
    )

    if calculated_glyph_count != CURRENT_GLYPH_COUNT:
        raise ValueError(
            "현재 글리프 수가 예상과 다릅니다: "
            f"{calculated_glyph_count}"
        )

    new_height = (
        height + GLYPH_HEIGHT
    )

    write_u16(
        patched,
        0x02,
        new_height,
    )
    patched.extend(glyph)

    new_expected_size = (
        TXP_PIXEL_OFFSET
        + width * new_height // 2
    )

    if len(patched) != new_expected_size:
        raise ValueError(
            "확장 TXP 크기 검증 실패."
        )

    return bytes(patched), {
        "width": width,
        "old_height": height,
        "new_height": new_height,
        "old_size": len(blob),
        "new_size": len(patched),
        "appended_bytes": len(glyph),
        "new_glyph_index": NEW_GLYPH_INDEX,
        "new_glyph_index_hex": (
            f"0x{NEW_GLYPH_INDEX:04X}"
        ),
    }


def patch_jis2ucs(
    blob: bytes,
) -> tuple[bytes, dict[str, Any]]:
    patched = bytearray(blob)
    offset = JIS_CODE * 2

    if offset + 2 > len(patched):
        raise ValueError(
            "jis2ucs 오프셋이 범위를 벗어났습니다."
        )

    old_value = read_u16(
        patched,
        offset,
    )

    if old_value != 0:
        raise ValueError(
            "선택 JIS 코드에 Unicode가 이미 있습니다: "
            f"U+{old_value:04X}"
        )

    write_u16(
        patched,
        offset,
        UNICODE_VALUE,
    )

    return bytes(patched), {
        "offset": offset,
        "offset_hex": f"0x{offset:X}",
        "old_value": old_value,
        "new_value": UNICODE_VALUE,
        "new_value_hex": (
            f"U+{UNICODE_VALUE:04X}"
        ),
    }


def patch_ucs2jis(
    blob: bytes,
) -> tuple[bytes, dict[str, Any]]:
    patched = bytearray(blob)
    offset = UNICODE_VALUE * 2

    if offset + 2 > len(patched):
        raise ValueError(
            "ucs2jis 오프셋이 범위를 벗어났습니다."
        )

    old_value = read_u16(
        patched,
        offset,
    )

    if old_value != 0:
        raise ValueError(
            "가 문자의 JIS 매핑이 이미 있습니다: "
            f"0x{old_value:04X}"
        )

    write_u16(
        patched,
        offset,
        JIS_CODE,
    )

    return bytes(patched), {
        "offset": offset,
        "offset_hex": f"0x{offset:X}",
        "old_value": old_value,
        "new_value": JIS_CODE,
        "new_value_hex": (
            f"0x{JIS_CODE:04X}"
        ),
    }


def patch_demo(
    blob: bytes,
) -> tuple[bytes, dict[str, Any]]:
    patched = bytearray(blob)

    actual = bytes(
        patched[
            DEMO_OFFSET:
            DEMO_OFFSET + 2
        ]
    )

    if actual != EXPECTED_DEMO_BYTES:
        raise ValueError(
            "Demo00.dat 테스트 위치가 예상과 다릅니다: "
            f"actual={actual.hex(' ').upper()}, "
            f"expected={EXPECTED_DEMO_BYTES.hex(' ').upper()}"
        )

    before_start = max(
        0,
        DEMO_OFFSET - 20,
    )
    before_end = min(
        len(patched),
        DEMO_OFFSET + 22,
    )

    before_context = bytes(
        patched[before_start:before_end]
    )

    patched[
        DEMO_OFFSET:
        DEMO_OFFSET + 2
    ] = SJIS_CODE

    after_context = bytes(
        patched[before_start:before_end]
    )

    return bytes(patched), {
        "offset": DEMO_OFFSET,
        "offset_hex": (
            f"0x{DEMO_OFFSET:X}"
        ),
        "old_bytes": (
            EXPECTED_DEMO_BYTES.hex(" ").upper()
        ),
        "new_bytes": (
            SJIS_CODE.hex(" ").upper()
        ),
        "before_context_hex": (
            before_context.hex(" ").upper()
        ),
        "before_context_text": (
            before_context.decode(
                "shift_jis",
                errors="replace",
            )
        ),
        "after_context_hex": (
            after_context.hex(" ").upper()
        ),
        "expected_screen_text": (
            "オススメ가難易度ッス。"
        ),
    }


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
    preview.save(
        OUTPUT_PREVIEW
    )

    original_start = SOURCE_START.read_bytes()
    records = parse_start_records(
        original_start
    )

    required_names = [
        "font.fnt",
        "font.txp",
        "jis2ucs.bin",
        "ucs2jis.bin",
        DEMO_RESOURCE,
    ]

    record_map = {
        str(record["name"]).casefold(): record
        for record in records
    }

    for name in required_names:
        if name.casefold() not in record_map:
            raise ValueError(
                f"start.dat에서 리소스를 찾지 못했습니다: {name}"
            )

    font_fnt_original = resource_blob(
        original_start,
        record_map["font.fnt"],
    )
    font_txp_original = resource_blob(
        original_start,
        record_map["font.txp"],
    )
    jis2ucs_original = resource_blob(
        original_start,
        record_map["jis2ucs.bin"],
    )
    ucs2jis_original = resource_blob(
        original_start,
        record_map["ucs2jis.bin"],
    )
    demo_original = resource_blob(
        original_start,
        record_map[DEMO_RESOURCE.casefold()],
    )

    font_fnt_patched, fnt_report = (
        patch_font_fnt(
            font_fnt_original
        )
    )
    font_txp_patched, txp_report = (
        patch_font_txp(
            font_txp_original,
            encoded_glyph,
        )
    )
    jis2ucs_patched, jis2ucs_report = (
        patch_jis2ucs(
            jis2ucs_original
        )
    )
    ucs2jis_patched, ucs2jis_report = (
        patch_ucs2jis(
            ucs2jis_original
        )
    )
    demo_patched, demo_report = (
        patch_demo(
            demo_original
        )
    )

    replacements = {
        "font.fnt": font_fnt_patched,
        "font.txp": font_txp_patched,
        "jis2ucs.bin": jis2ucs_patched,
        "ucs2jis.bin": ucs2jis_patched,
        DEMO_RESOURCE.casefold(): demo_patched,
    }

    rebuilt_start = rebuild_start_archive(
        original_start,
        records,
        replacements,
    )

    expected_start_size = (
        len(original_start)
        + BYTES_PER_GLYPH
    )

    if len(rebuilt_start) != expected_start_size:
        raise ValueError(
            "재구성 start.dat 크기가 예상과 다릅니다: "
            f"actual=0x{len(rebuilt_start):X}, "
            f"expected=0x{expected_start_size:X}"
        )

    OUTPUT_START.write_bytes(
        rebuilt_start
    )

    archive = StartRuntimeArchive.load(
        OUTPUT_START
    )

    if len(archive.records) != len(records):
        raise ValueError(
            "재구성 후 리소스 수가 달라졌습니다."
        )

    # 재구성된 리소스 내용을 다시 직접 검증한다.
    rebuilt_records = parse_start_records(
        rebuilt_start
    )
    rebuilt_map = {
        str(record["name"]).casefold(): record
        for record in rebuilt_records
    }

    rebuilt_fnt = resource_blob(
        rebuilt_start,
        rebuilt_map["font.fnt"],
    )
    rebuilt_txp = resource_blob(
        rebuilt_start,
        rebuilt_map["font.txp"],
    )
    rebuilt_jis2ucs = resource_blob(
        rebuilt_start,
        rebuilt_map["jis2ucs.bin"],
    )
    rebuilt_ucs2jis = resource_blob(
        rebuilt_start,
        rebuilt_map["ucs2jis.bin"],
    )
    rebuilt_demo = resource_blob(
        rebuilt_start,
        rebuilt_map[DEMO_RESOURCE.casefold()],
    )

    if read_u16(
        rebuilt_fnt,
        2 + FNT_TABLE_INDEX * 2,
    ) != NEW_GLYPH_INDEX:
        raise ValueError(
            "재구성 후 font.fnt 매핑 검증 실패"
        )

    if read_u16(
        rebuilt_txp,
        0x02,
    ) != CURRENT_TXP_HEIGHT + GLYPH_HEIGHT:
        raise ValueError(
            "재구성 후 TXP 높이 검증 실패"
        )

    if read_u16(
        rebuilt_jis2ucs,
        JIS_CODE * 2,
    ) != UNICODE_VALUE:
        raise ValueError(
            "재구성 후 jis2ucs 검증 실패"
        )

    if read_u16(
        rebuilt_ucs2jis,
        UNICODE_VALUE * 2,
    ) != JIS_CODE:
        raise ValueError(
            "재구성 후 ucs2jis 검증 실패"
        )

    if rebuilt_demo[
        DEMO_OFFSET:
        DEMO_OFFSET + 2
    ] != SJIS_CODE:
        raise ValueError(
            "재구성 후 Demo00.dat 검증 실패"
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
            "독립 한글 LZS 왕복 검증 실패"
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

    verified_lzs_offset = int(
        verified_entry["data_offset"]
    )
    verified_lzs_size = int(
        verified_entry["size"]
    )

    verified_lzs = patched_system_bytes[
        verified_lzs_offset:
        verified_lzs_offset
        + verified_lzs_size
    ]

    verified_start, _ = decompress_buffer(
        verified_lzs
    )

    if verified_start != rebuilt_start:
        raise ValueError(
            "SYSTEM.DAT 내부 start.dat 검증 실패"
        )

    manifest = {
        "format": (
            "prinny_independent_hangul_test_v1"
        ),
        "character": {
            "text": CHARACTER,
            "unicode": UNICODE_VALUE,
            "unicode_hex": (
                f"U+{UNICODE_VALUE:04X}"
            ),
            "jis": JIS_CODE,
            "jis_hex": (
                f"0x{JIS_CODE:04X}"
            ),
            "sjis_hex": (
                SJIS_CODE.hex(" ").upper()
            ),
            "font_path": str(font_path),
        },
        "font_fnt": fnt_report,
        "font_txp": txp_report,
        "jis2ucs": jis2ucs_report,
        "ucs2jis": ucs2jis_report,
        "demo_patch": demo_report,
        "source": {
            "start_path": str(SOURCE_START),
            "start_size": len(original_start),
            "start_sha1": sha1(original_start),
            "system_path": str(SOURCE_SYSTEM),
            "system_size": len(original_system),
            "system_sha1": sha1(original_system),
        },
        "output": {
            "start_path": str(OUTPUT_START),
            "start_size": len(rebuilt_start),
            "start_sha1": sha1(rebuilt_start),
            "lzs_path": str(OUTPUT_LZS),
            "lzs_size": len(new_lzs),
            "lzs_sha1": sha1(new_lzs),
            "system_path": str(OUTPUT_SYSTEM),
            "system_size": len(
                patched_system_bytes
            ),
            "system_sha1": sha1(
                patched_system_bytes
            ),
            "preview_path": str(
                OUTPUT_PREVIEW
            ),
            "new_lzs_offset": (
                new_lzs_offset
            ),
            "new_lzs_offset_hex": (
                f"0x{new_lzs_offset:X}"
            ),
        },
        "lzs_header": decoded_header,
        "expected_screen_text": (
            "オススメ가難易度ッス。"
        ),
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

    print("INDEPENDENT HANGUL BUILD")
    print("========================")
    print(
        f"CHARACTER         : "
        f"{CHARACTER} U+{UNICODE_VALUE:04X}"
    )
    print(
        f"JIS               : "
        f"0x{JIS_CODE:04X}"
    )
    print(
        f"SHIFT-JIS         : "
        f"{SJIS_CODE.hex(' ').upper()}"
    )
    print(
        f"FONT TABLE INDEX  : "
        f"0x{FNT_TABLE_INDEX:04X}"
    )
    print(
        f"NEW GLYPH INDEX   : "
        f"0x{NEW_GLYPH_INDEX:04X}"
    )
    print(
        f"TXP HEIGHT        : "
        f"{CURRENT_TXP_HEIGHT} -> "
        f"{CURRENT_TXP_HEIGHT + GLYPH_HEIGHT}"
    )
    print(
        f"START SIZE        : "
        f"0x{len(original_start):X} -> "
        f"0x{len(rebuilt_start):X}"
    )
    print(
        f"DEMO PATCH        : "
        f"{DEMO_RESOURCE}+0x{DEMO_OFFSET:X}"
    )
    print(
        f"EXPECTED TEXT     : "
        f"オススメ가難易度ッス。"
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
