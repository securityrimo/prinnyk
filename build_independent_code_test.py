#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from build_font_canary import (
    SOURCE_START,
    SOURCE_SYSTEM,
    align_up,
    build_literal_lzs,
    parse_nispack_start_entry,
    parse_start_records,
    read_u32,
)
from build_independent_hangul_test import (
    rebuild_start_archive,
    resource_blob,
)
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive


# 새 독립 코드
JIS_CODE = 0x3665
SJIS_CODE = bytes.fromhex("8B E3")
FNT_TABLE_INDEX = 0x085E

# 기존 ウ 글리프를 임시로 빌려 사용
TEST_CHARACTER = "ウ"
TEST_CHARACTER_JIS = 0x2526
TEST_CHARACTER_TABLE = 0x01E1
TEST_GLYPH_INDEX = 0x013F

# 실제 현재 화면에 보이는 문장의 마지막 の
DEMO_RESOURCE = "Demo00.dat"
DEMO_OFFSET = 0x2E
EXPECTED_OLD_BYTES = bytes.fromhex("82 CC")

# Unicode 테이블에는 가로 등록해 왕복 매핑도 확인
HANGUL_CHARACTER = "가"
HANGUL_UNICODE = 0xAC00

# 재활용할 기존 문자 九
RECLAIMED_CHARACTER = "九"
RECLAIMED_UNICODE = 0x4E5D
RECLAIMED_GLYPH_INDEX = 0x0320

OUTPUT_DIR = Path("workspace/test/independent_code")
OUTPUT_START = OUTPUT_DIR / "start_independent_code.dat"
OUTPUT_LZS = OUTPUT_DIR / "start_independent_code.lzs"
OUTPUT_SYSTEM = OUTPUT_DIR / "SYSTEM_independent_code.DAT"
OUTPUT_MANIFEST = OUTPUT_DIR / "manifest.json"


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def read_u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def write_u16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", data, offset, value)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    original_start = SOURCE_START.read_bytes()
    records = parse_start_records(original_start)

    record_map = {
        str(record["name"]).casefold(): record
        for record in records
    }

    required = [
        "font.fnt",
        "font.txp",
        "jis2ucs.bin",
        "ucs2jis.bin",
        DEMO_RESOURCE,
    ]

    for name in required:
        if name.casefold() not in record_map:
            raise ValueError(f"리소스를 찾지 못했습니다: {name}")

    original_fnt = resource_blob(
        original_start,
        record_map["font.fnt"],
    )
    original_txp = resource_blob(
        original_start,
        record_map["font.txp"],
    )
    original_jis2ucs = resource_blob(
        original_start,
        record_map["jis2ucs.bin"],
    )
    original_ucs2jis = resource_blob(
        original_start,
        record_map["ucs2jis.bin"],
    )
    original_demo = resource_blob(
        original_start,
        record_map[DEMO_RESOURCE.casefold()],
    )

    # 기존 ウ 글리프 매핑 검증
    existing_test_glyph = read_u16(
        original_fnt,
        2 + TEST_CHARACTER_TABLE * 2,
    )

    if existing_test_glyph != TEST_GLYPH_INDEX:
        raise ValueError(
            "ウ 글리프 검증 실패: "
            f"actual=0x{existing_test_glyph:04X}, "
            f"expected=0x{TEST_GLYPH_INDEX:04X}"
        )

    existing_test_unicode = read_u16(
        original_jis2ucs,
        TEST_CHARACTER_JIS * 2,
    )

    if existing_test_unicode != ord(TEST_CHARACTER):
        raise ValueError(
            "ウ Unicode 매핑 검증 실패: "
            f"U+{existing_test_unicode:04X}"
        )

    # EB40의 font.fnt 항목을 기존 ウ 글리프에 연결
    patched_fnt = bytearray(original_fnt)
    candidate_map_offset = 2 + FNT_TABLE_INDEX * 2

    old_candidate_glyph = read_u16(
        patched_fnt,
        candidate_map_offset,
    )

    if old_candidate_glyph != RECLAIMED_GLYPH_INDEX:
        raise ValueError(
            "재활용 후보 글리프가 예상과 다릅니다: "
            f"actual=0x{old_candidate_glyph:04X}, "
            f"expected=0x{RECLAIMED_GLYPH_INDEX:04X}"
        )

    write_u16(
        patched_fnt,
        candidate_map_offset,
        TEST_GLYPH_INDEX,
    )

    # JIS 2675 → Unicode 가
    patched_jis2ucs = bytearray(original_jis2ucs)
    jis2ucs_offset = JIS_CODE * 2

    old_candidate_unicode = read_u16(
        patched_jis2ucs,
        jis2ucs_offset,
    )

    if old_candidate_unicode != RECLAIMED_UNICODE:
        raise ValueError(
            "재활용 후보 Unicode가 예상과 다릅니다: "
            f"actual=U+{old_candidate_unicode:04X}, "
            f"expected=U+{RECLAIMED_UNICODE:04X}"
        )

    write_u16(
        patched_jis2ucs,
        jis2ucs_offset,
        HANGUL_UNICODE,
    )

    # Unicode 가 → JIS 2675
    patched_ucs2jis = bytearray(original_ucs2jis)
    ucs2jis_offset = HANGUL_UNICODE * 2

    if read_u16(patched_ucs2jis, ucs2jis_offset) != 0:
        raise ValueError("가 역방향 매핑이 비어 있지 않습니다.")

    write_u16(
        patched_ucs2jis,
        ucs2jis_offset,
        JIS_CODE,
    )

    # 현재 화면에 보이는 문장의 の만 EB40으로 교체
    patched_demo = bytearray(original_demo)

    actual_old_bytes = bytes(
        patched_demo[DEMO_OFFSET:DEMO_OFFSET + 2]
    )

    if actual_old_bytes != EXPECTED_OLD_BYTES:
        raise ValueError(
            "Demo00.dat 대상 위치 검증 실패: "
            f"actual={actual_old_bytes.hex(' ').upper()}, "
            f"expected={EXPECTED_OLD_BYTES.hex(' ').upper()}"
        )

    patched_demo[
        DEMO_OFFSET:
        DEMO_OFFSET + 2
    ] = SJIS_CODE

    replacements = {
        "font.fnt": bytes(patched_fnt),
        "jis2ucs.bin": bytes(patched_jis2ucs),
        "ucs2jis.bin": bytes(patched_ucs2jis),
        DEMO_RESOURCE.casefold(): bytes(patched_demo),
    }

    rebuilt_start = rebuild_start_archive(
        original_start,
        records,
        replacements,
    )

    # 이번 테스트는 크기가 절대 변하면 안 된다.
    if len(rebuilt_start) != len(original_start):
        raise ValueError(
            "start.dat 크기가 변경됐습니다: "
            f"0x{len(original_start):X} -> "
            f"0x{len(rebuilt_start):X}"
        )

    OUTPUT_START.write_bytes(rebuilt_start)

    # font.txp는 바이트 단위로 동일해야 한다.
    rebuilt_records = parse_start_records(rebuilt_start)
    rebuilt_map = {
        str(record["name"]).casefold(): record
        for record in rebuilt_records
    }

    rebuilt_txp = resource_blob(
        rebuilt_start,
        rebuilt_map["font.txp"],
    )

    if rebuilt_txp != original_txp:
        raise ValueError("font.txp가 변경됐습니다.")

    rebuilt_fnt = resource_blob(
        rebuilt_start,
        rebuilt_map["font.fnt"],
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
        candidate_map_offset,
    ) != TEST_GLYPH_INDEX:
        raise ValueError("재구성 후 font.fnt 검증 실패")

    if read_u16(
        rebuilt_jis2ucs,
        jis2ucs_offset,
    ) != HANGUL_UNICODE:
        raise ValueError("재구성 후 jis2ucs 검증 실패")

    if read_u16(
        rebuilt_ucs2jis,
        ucs2jis_offset,
    ) != JIS_CODE:
        raise ValueError("재구성 후 ucs2jis 검증 실패")

    if rebuilt_demo[
        DEMO_OFFSET:
        DEMO_OFFSET + 2
    ] != SJIS_CODE:
        raise ValueError("재구성 후 Demo00.dat 검증 실패")

    archive = StartRuntimeArchive.load(OUTPUT_START)

    if len(archive.records) != len(records):
        raise ValueError("start.dat 리소스 수가 변경됐습니다.")

    original_system = SOURCE_SYSTEM.read_bytes()
    start_entry = parse_nispack_start_entry(original_system)

    old_lzs_offset = int(start_entry["data_offset"])
    old_lzs_size = int(start_entry["size"])
    old_lzs = original_system[
        old_lzs_offset:
        old_lzs_offset + old_lzs_size
    ]

    extension = old_lzs[0:4]
    flag = read_u32(old_lzs, 0x0C) & 0xFF

    new_lzs = build_literal_lzs(
        rebuilt_start,
        extension,
        flag,
    )
    OUTPUT_LZS.write_bytes(new_lzs)

    decoded_start, decoded_header = decompress_buffer(new_lzs)

    if decoded_start != rebuilt_start:
        raise ValueError("LZS 왕복 검증 실패")

    patched_system = bytearray(original_system)
    new_lzs_offset = align_up(len(patched_system), 0x800)

    patched_system.extend(
        b"\x00" * (
            new_lzs_offset - len(patched_system)
        )
    )
    patched_system.extend(new_lzs)

    entry_offset = int(start_entry["entry_offset"])

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

    patched_system_bytes = bytes(patched_system)
    OUTPUT_SYSTEM.write_bytes(patched_system_bytes)

    manifest = {
        "format": "prinny_independent_code_test_v1",
        "code": {
            "jis": f"0x{JIS_CODE:04X}",
            "sjis": SJIS_CODE.hex(" ").upper(),
            "font_table_index": f"0x{FNT_TABLE_INDEX:04X}",
            "temporary_glyph": TEST_CHARACTER,
            "temporary_glyph_index": f"0x{TEST_GLYPH_INDEX:04X}",
        },
        "demo": {
            "resource": DEMO_RESOURCE,
            "offset": f"0x{DEMO_OFFSET:X}",
            "old_bytes": EXPECTED_OLD_BYTES.hex(" ").upper(),
            "new_bytes": SJIS_CODE.hex(" ").upper(),
            "expected_screen_text": "やりごたえバッチリウ",
        },
        "sizes": {
            "original_start": len(original_start),
            "rebuilt_start": len(rebuilt_start),
            "original_txp": len(original_txp),
            "rebuilt_txp": len(rebuilt_txp),
        },
        "hashes": {
            "original_start": sha1(original_start),
            "rebuilt_start": sha1(rebuilt_start),
            "original_txp": sha1(original_txp),
            "rebuilt_txp": sha1(rebuilt_txp),
            "patched_system": sha1(patched_system_bytes),
        },
        "lzs_header": decoded_header,
        "outputs": {
            "start": str(OUTPUT_START),
            "lzs": str(OUTPUT_LZS),
            "system": str(OUTPUT_SYSTEM),
        },
        "status": "pass",
    }

    OUTPUT_MANIFEST.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print("INDEPENDENT CODE TEST")
    print("=====================")
    print("SHIFT-JIS        : 8B E3")
    print("TEMP GLYPH       : ウ")
    print("TEMP GLYPH INDEX : 0x0119")
    print("DEMO OFFSET      : Demo00.dat+0x2E")
    print("EXPECTED TEXT    : やりごたえバッチリウ")
    print(
        f"START SIZE       : "
        f"0x{len(original_start):X} -> "
        f"0x{len(rebuilt_start):X}"
    )
    print(
        f"TXP SIZE         : "
        f"0x{len(original_txp):X} -> "
        f"0x{len(rebuilt_txp):X}"
    )
    print()
    print("SYSTEM  :", OUTPUT_SYSTEM)
    print("MANIFEST:", OUTPUT_MANIFEST)
    print()
    print("SELF TEST: PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
