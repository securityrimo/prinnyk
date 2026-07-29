#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from PIL import Image

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive


SOURCE_SYSTEM = Path(
    "workspace/iso/PSP_GAME/USRDIR/SYSTEM.DAT"
)
SOURCE_START = Path(
    "workspace/unpack/SYSTEM_fixed/start.dat"
)
OUTPUT_DIR = Path(
    "workspace/test/font_canary"
)

OUTPUT_START = OUTPUT_DIR / "start_canary.dat"
OUTPUT_LZS = OUTPUT_DIR / "start_canary.lzs"
OUTPUT_SYSTEM = OUTPUT_DIR / "SYSTEM_font_canary.DAT"
OUTPUT_PREVIEW = OUTPUT_DIR / "font_canary_preview.png"
OUTPUT_MANIFEST = OUTPUT_DIR / "manifest.json"

START_RECORD_SIZE = 0x20
NISPACK_HEADER_SIZE = 0x10
NISPACK_RECORD_SIZE = 0x2C

# verify 명령으로 확정된 'の' 매핑
TARGET_CHARACTER = "の"
TARGET_TABLE_INDEX = 0x01AB
EXPECTED_GLYPH_INDEX = 0x011A

TXP_PIXEL_OFFSET = 0x50
GLYPH_WIDTH = 20
GLYPH_HEIGHT = 14
BYTES_PER_ROW = 0x0A
BYTES_PER_GLYPH = 0x8C


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def align_up(value: int, alignment: int) -> int:
    return (
        value + alignment - 1
    ) // alignment * alignment


def read_u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def decode_name(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode(
        "ascii",
        errors="replace",
    )


def parse_start_records(data: bytes) -> list[dict[str, int | str]]:
    if len(data) < 4:
        raise ValueError("start.dat가 너무 작습니다.")

    count = read_u32(data, 0)

    if count < 1 or count > 10000:
        raise ValueError(
            f"비정상적인 start.dat 항목 수: {count}"
        )

    table_end = count * START_RECORD_SIZE

    if table_end > len(data):
        raise ValueError(
            "start.dat 목차가 파일 크기를 초과합니다."
        )

    records: list[dict[str, int | str]] = []

    for index in range(count):
        record_offset = index * START_RECORD_SIZE
        data_offset = read_u32(
            data,
            record_offset + 0x04,
        )
        name = decode_name(
            data[
                record_offset + 0x08:
                record_offset + START_RECORD_SIZE
            ]
        )

        records.append(
            {
                "index": index,
                "record_offset": record_offset,
                "data_offset": data_offset,
                "name": name,
            }
        )

    for index, record in enumerate(records):
        start = int(record["data_offset"])

        if index + 1 < len(records):
            end = int(
                records[index + 1]["data_offset"]
            )
        else:
            end = len(data)

        if start < table_end or end < start or end > len(data):
            raise ValueError(
                "start.dat 리소스 범위가 잘못됐습니다: "
                f"index={index}, start=0x{start:X}, "
                f"end=0x{end:X}"
            )

        record["size"] = end - start
        record["end"] = end

    return records


def find_start_record(
    records: list[dict[str, int | str]],
    name: str,
) -> dict[str, int | str]:
    matches = [
        record
        for record in records
        if str(record["name"]).casefold()
        == name.casefold()
    ]

    if len(matches) != 1:
        raise ValueError(
            f"{name} 항목 수가 {len(matches)}개입니다."
        )

    return matches[0]


def parse_nispack_start_entry(
    data: bytes,
) -> dict[str, int | str]:
    if data[:7] != b"NISPACK":
        raise ValueError(
            "SYSTEM.DAT에 NISPACK 서명이 없습니다."
        )

    count = read_u32(data, 0x0C)

    for index in range(count):
        entry_offset = (
            NISPACK_HEADER_SIZE
            + index * NISPACK_RECORD_SIZE
        )

        if entry_offset + NISPACK_RECORD_SIZE > len(data):
            raise ValueError(
                "NISPACK 목차가 파일 크기를 초과합니다."
            )

        name = decode_name(
            data[entry_offset:entry_offset + 0x20]
        )

        if name.casefold() != "start.lzs":
            continue

        data_offset = read_u32(
            data,
            entry_offset + 0x20,
        )
        size = read_u32(
            data,
            entry_offset + 0x24,
        )

        if data_offset + size > len(data):
            raise ValueError(
                "기존 start.lzs 범위가 잘못됐습니다."
            )

        return {
            "index": index,
            "entry_offset": entry_offset,
            "data_offset": data_offset,
            "size": size,
        }

    raise ValueError(
        "SYSTEM.DAT에서 start.lzs를 찾지 못했습니다."
    )


def build_canary_pixels() -> list[list[int]]:
    pixels = [
        [0 for _ in range(GLYPH_WIDTH)]
        for _ in range(GLYPH_HEIGHT)
    ]

    for y in range(GLYPH_HEIGHT):
        diagonal = round(
            y * (GLYPH_WIDTH - 1)
            / (GLYPH_HEIGHT - 1)
        )
        reverse_diagonal = (
            GLYPH_WIDTH - 1 - diagonal
        )

        for x in range(GLYPH_WIDTH):
            border = (
                x == 0
                or x == GLYPH_WIDTH - 1
                or y == 0
                or y == GLYPH_HEIGHT - 1
            )
            cross = (
                x == diagonal
                or x == reverse_diagonal
            )

            if border or cross:
                pixels[y][x] = 0x0F

    return pixels


def encode_4bpp(
    pixels: list[list[int]],
) -> bytes:
    output = bytearray()

    for row in pixels:
        if len(row) != GLYPH_WIDTH:
            raise ValueError(
                "카나리 이미지 너비가 잘못됐습니다."
            )

        for x in range(0, GLYPH_WIDTH, 2):
            left = row[x] & 0x0F
            right = row[x + 1] & 0x0F

            # 글꼴의 4bpp 바이트당 2픽셀
            output.append(
                left | (right << 4)
            )

    if len(output) != BYTES_PER_GLYPH:
        raise ValueError(
            "생성된 글리프 크기가 잘못됐습니다: "
            f"0x{len(output):X}"
        )

    return bytes(output)


def save_preview(
    pixels: list[list[int]],
) -> None:
    scale = 12

    image = Image.new(
        "L",
        (
            GLYPH_WIDTH * scale,
            GLYPH_HEIGHT * scale,
        ),
        0,
    )

    for y, row in enumerate(pixels):
        for x, value in enumerate(row):
            if value == 0:
                continue

            for dy in range(scale):
                for dx in range(scale):
                    image.putpixel(
                        (
                            x * scale + dx,
                            y * scale + dy,
                        ),
                        255,
                    )

    image.save(OUTPUT_PREVIEW)


def build_literal_lzs(
    raw: bytes,
    extension: bytes,
    flag: int,
) -> bytes:
    if len(extension) != 4:
        raise ValueError(
            "LZS 확장자 필드는 4바이트여야 합니다."
        )

    if not 0 <= flag <= 0xFF:
        raise ValueError(
            f"잘못된 LZS 플래그: 0x{flag:X}"
        )

    encoded = bytearray()

    for value in raw:
        encoded.append(value)

        # 플래그 자체는 두 번 기록해 리터럴로 이스케이프
        if value == flag:
            encoded.append(flag)

    total_size = 0x10 + len(encoded)

    header = bytearray(0x10)
    header[0:4] = extension
    struct.pack_into(
        "<I",
        header,
        0x04,
        len(raw),
    )
    struct.pack_into(
        "<I",
        header,
        0x08,
        total_size - 4,
    )
    struct.pack_into(
        "<I",
        header,
        0x0C,
        flag,
    )

    return bytes(header + encoded)


def main() -> int:
    if not SOURCE_SYSTEM.is_file():
        raise FileNotFoundError(
            f"SYSTEM.DAT 없음: {SOURCE_SYSTEM}"
        )

    if not SOURCE_START.is_file():
        raise FileNotFoundError(
            f"start.dat 없음: {SOURCE_START}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    original_start = SOURCE_START.read_bytes()
    start_records = parse_start_records(
        original_start
    )

    font_fnt = find_start_record(
        start_records,
        "font.fnt",
    )
    font_txp = find_start_record(
        start_records,
        "font.txp",
    )

    fnt_offset = int(font_fnt["data_offset"])
    fnt_size = int(font_fnt["size"])
    txp_offset = int(font_txp["data_offset"])
    txp_size = int(font_txp["size"])

    if fnt_size != 0x5AC0:
        raise ValueError(
            "예상하지 못한 font.fnt 크기: "
            f"0x{fnt_size:X}"
        )

    if txp_size != 0x50460:
        raise ValueError(
            "예상하지 못한 font.txp 크기: "
            f"0x{txp_size:X}"
        )

    table_count = struct.unpack_from(
        "<H",
        original_start,
        fnt_offset,
    )[0]

    if TARGET_TABLE_INDEX >= table_count:
        raise ValueError(
            "대상 테이블 인덱스가 범위를 벗어났습니다."
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
            f"{TARGET_CHARACTER} 글리프가 예상과 다릅니다: "
            f"actual=0x{glyph_index:04X}, "
            f"expected=0x{EXPECTED_GLYPH_INDEX:04X}"
        )

    glyph_offset_in_txp = (
        TXP_PIXEL_OFFSET
        + glyph_index * BYTES_PER_GLYPH
    )
    glyph_end_in_txp = (
        glyph_offset_in_txp
        + BYTES_PER_GLYPH
    )

    if glyph_end_in_txp > txp_size:
        raise ValueError(
            "글리프 위치가 font.txp 범위를 벗어났습니다."
        )

    absolute_glyph_offset = (
        txp_offset + glyph_offset_in_txp
    )

    pixels = build_canary_pixels()
    canary_glyph = encode_4bpp(pixels)

    patched_start = bytearray(original_start)
    original_glyph = bytes(
        patched_start[
            absolute_glyph_offset:
            absolute_glyph_offset
            + BYTES_PER_GLYPH
        ]
    )

    patched_start[
        absolute_glyph_offset:
        absolute_glyph_offset
        + BYTES_PER_GLYPH
    ] = canary_glyph

    changed_bytes = sum(
        before != after
        for before, after
        in zip(original_glyph, canary_glyph)
    )

    if changed_bytes == 0:
        raise ValueError(
            "카나리 글리프가 원본과 동일합니다."
        )

    patched_start_bytes = bytes(patched_start)
    OUTPUT_START.write_bytes(
        patched_start_bytes
    )
    save_preview(pixels)

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

    if len(old_lzs) < 0x10:
        raise ValueError(
            "기존 start.lzs가 너무 작습니다."
        )

    extension = old_lzs[0:4]
    flag = read_u32(old_lzs, 0x0C) & 0xFF

    new_lzs = build_literal_lzs(
        patched_start_bytes,
        extension,
        flag,
    )
    OUTPUT_LZS.write_bytes(new_lzs)

    # 로컬 디코더로 새 LZS를 즉시 왕복 검증
    decoded_start, decoded_header = decompress_buffer(
        new_lzs
    )

    if decoded_start != patched_start_bytes:
        raise ValueError(
            "새 start.lzs 왕복 검증에 실패했습니다."
        )

    new_system = bytearray(original_system)

    # 기존 항목은 그대로 두고 새 start.lzs를 끝에 추가
    new_lzs_offset = align_up(
        len(new_system),
        0x800,
    )

    new_system.extend(
        b"\x00" * (
            new_lzs_offset - len(new_system)
        )
    )
    new_system.extend(new_lzs)

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

    new_system_bytes = bytes(new_system)
    OUTPUT_SYSTEM.write_bytes(
        new_system_bytes
    )

    # 생성된 start.dat 구조 검증
    archive = StartRuntimeArchive.load(
        OUTPUT_START
    )

    if archive.find_record("font.txp") is None:
        raise ValueError(
            "패치된 start.dat에서 font.txp를 찾지 못했습니다."
        )

    # 생성된 SYSTEM.DAT에서 새 엔트리를 다시 읽어 검증
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
            "생성된 SYSTEM.DAT 내부 LZS 검증 실패"
        )

    manifest = {
        "format": "prinny_font_canary_v1",
        "target": {
            "character": TARGET_CHARACTER,
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
        },
        "source": {
            "system": str(SOURCE_SYSTEM),
            "system_size": len(original_system),
            "system_sha1": sha1(original_system),
            "start": str(SOURCE_START),
            "start_size": len(original_start),
            "start_sha1": sha1(original_start),
            "old_lzs_offset": old_lzs_offset,
            "old_lzs_size": old_lzs_size,
        },
        "output": {
            "start": str(OUTPUT_START),
            "start_size": len(patched_start_bytes),
            "start_sha1": sha1(patched_start_bytes),
            "lzs": str(OUTPUT_LZS),
            "lzs_size": len(new_lzs),
            "lzs_sha1": sha1(new_lzs),
            "system": str(OUTPUT_SYSTEM),
            "system_size": len(new_system_bytes),
            "system_sha1": sha1(new_system_bytes),
            "new_lzs_offset": new_lzs_offset,
            "preview": str(OUTPUT_PREVIEW),
        },
        "lzs": {
            "extension": extension.rstrip(
                b"\x00"
            ).decode(
                "ascii",
                errors="replace",
            ),
            "flag": flag,
            "flag_hex": f"0x{flag:02X}",
            "decoded_size": len(decoded_start),
            "decoded_header": decoded_header,
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

    print("FONT CANARY BUILD")
    print("=================")
    print(
        f"TARGET          : {TARGET_CHARACTER}"
    )
    print(
        f"TABLE INDEX     : "
        f"0x{TARGET_TABLE_INDEX:04X}"
    )
    print(
        f"GLYPH INDEX     : "
        f"0x{glyph_index:04X}"
    )
    print(
        f"CHANGED BYTES   : {changed_bytes}"
    )
    print(
        f"START SIZE      : "
        f"0x{len(patched_start_bytes):X}"
    )
    print(
        f"LZS SIZE        : "
        f"0x{len(new_lzs):X}"
    )
    print(
        f"SYSTEM SIZE     : "
        f"0x{len(new_system_bytes):X}"
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
