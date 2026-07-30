#!/usr/bin/env python3

import struct
from collections import defaultdict
from pathlib import Path


FONT_MAP_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

FONT_TEXTURE_PATH = Path(
    "workspace/unpack/START_runtime/font.txp"
)

JIS2UCS_PATH = Path(
    "workspace/unpack/START_runtime/jis2ucs.bin"
)

REPORT_PATH = Path(
    "workspace/reports/runtime_font_map_analysis.txt"
)

FONT_TEXTURE_HEADER = 0xA0
BYTES_PER_GLYPH = 0xA0

# NSF에서 현재 2바이트 단위라고 가정해 정렬했던 값.
# 아직 실제 고정 길이 문자 코드라고 확정한 것은 아니다.
KNOWN = [
    ("の", bytes.fromhex("00 43")),
    ("ウ", bytes.fromhex("0B 43")),
    ("ワ", bytes.fromhex("1E 00")),
    ("サ", bytes.fromhex("32 00")),
    ("命", bytes.fromhex("22 00")),
]


def unpack_u16_le(data: bytes) -> list[int]:
    if len(data) % 2:
        raise ValueError(
            "파일 크기가 2의 배수가 아닙니다."
        )

    return list(
        struct.unpack(
            f"<{len(data) // 2}H",
            data,
        )
    )


def get_jis_code(character: str) -> int:
    encoded = character.encode("iso2022_jp")
    marker = b"\x1B$B"

    position = encoded.find(marker)

    if position < 0:
        raise ValueError(
            f"JIS 변환 실패: {character}"
        )

    start = position + len(marker)

    return int.from_bytes(
        encoded[start:start + 2],
        byteorder="big",
    )


def jis_94_index(jis_code: int) -> int:
    row = (jis_code >> 8) & 0xFF
    cell = jis_code & 0xFF

    return (
        (row - 0x21) * 94
        + (cell - 0x21)
    )


def jis_96_index(jis_code: int) -> int:
    row = (jis_code >> 8) & 0xFF
    cell = jis_code & 0xFF

    return (
        (row - 0x20) * 96
        + (cell - 0x20)
    )


def unicode_from_jis(
    jis2ucs: list[int],
    jis_code: int,
) -> int | None:
    if not 0 <= jis_code < len(jis2ucs):
        return None

    value = jis2ucs[jis_code]

    if value == 0:
        return None

    return value


def describe_entry(
    font_entries: list[int],
    jis2ucs: list[int],
    index: int,
) -> str:
    if not 0 <= index < len(font_entries):
        return "OUT-OF-RANGE"

    value = font_entries[index]
    unicode_value = unicode_from_jis(
        jis2ucs,
        value,
    )

    if unicode_value is None:
        return (
            f"FONT_VALUE=0x{value:04X} "
            f"UNICODE=NONE"
        )

    try:
        character = chr(unicode_value)
    except ValueError:
        character = "?"

    return (
        f"FONT_VALUE=0x{value:04X} "
        f"UNICODE=U+{unicode_value:04X} "
        f"CHAR={character!r}"
    )


def main() -> int:
    font_data = FONT_MAP_PATH.read_bytes()
    texture_data = FONT_TEXTURE_PATH.read_bytes()
    jis2ucs_data = JIS2UCS_PATH.read_bytes()

    font_entries = unpack_u16_le(font_data)
    jis2ucs = unpack_u16_le(jis2ucs_data)

    if len(texture_data) < FONT_TEXTURE_HEADER:
        raise ValueError(
            "font.txp가 예상보다 작습니다."
        )

    bitmap_size = (
        len(texture_data)
        - FONT_TEXTURE_HEADER
    )

    if bitmap_size % BYTES_PER_GLYPH:
        raise ValueError(
            "font.txp 글리프 영역 크기가 "
            "0xA0의 배수가 아닙니다."
        )

    glyph_count = (
        bitmap_size
        // BYTES_PER_GLYPH
    )

    value_positions = defaultdict(list)

    for index, value in enumerate(font_entries):
        value_positions[value].append(index)

    unique_count = len(set(font_entries))
    fixed_points = sum(
        1
        for index, value in enumerate(font_entries)
        if index == value
    )

    first_glyph_entries = font_entries[
        :glyph_count
    ]

    first_glyph_unicode_count = sum(
        1
        for value in first_glyph_entries
        if unicode_from_jis(jis2ucs, value)
        is not None
    )

    lines = []

    lines.append("RUNTIME FONT MAP ANALYSIS")
    lines.append("=========================")
    lines.append(f"FONT MAP    : {FONT_MAP_PATH}")
    lines.append(f"MAP SIZE    : 0x{len(font_data):X}")
    lines.append(
        f"MAP ENTRIES : {len(font_entries)} "
        f"(0x{len(font_entries):X})"
    )
    lines.append(
        f"VALUE RANGE : "
        f"0x{min(font_entries):04X}"
        f"~0x{max(font_entries):04X}"
    )
    lines.append(f"UNIQUE      : {unique_count}")
    lines.append(f"FIXED POINTS: {fixed_points}")
    lines.append("")
    lines.append(
        f"FONT TEXTURE: {FONT_TEXTURE_PATH}"
    )
    lines.append(
        f"TEXTURE SIZE: 0x{len(texture_data):X}"
    )
    lines.append(
        f"GLYPH COUNT : {glyph_count} "
        f"(0x{glyph_count:X})"
    )
    lines.append(
        f"FIRST {glyph_count} MAP ENTRIES "
        f"WITH VALID UNICODE: "
        f"{first_glyph_unicode_count}"
    )

    lines.append("")
    lines.append("FIRST 32 FONT MAP ENTRIES")
    lines.append("=========================")

    for index in range(
        min(32, len(font_entries))
    ):
        lines.append(
            f"[0x{index:04X}] "
            f"{describe_entry(
                font_entries,
                jis2ucs,
                index,
            )}"
        )

    lines.append("")
    lines.append("KNOWN CHARACTER LOOKUPS")
    lines.append("=======================")

    for character, raw_bytes in KNOWN:
        jis_code = get_jis_code(character)
        unicode_code = ord(character)

        raw_be = int.from_bytes(
            raw_bytes,
            byteorder="big",
        )

        raw_le = int.from_bytes(
            raw_bytes,
            byteorder="little",
        )

        grid94 = jis_94_index(jis_code)
        grid96 = jis_96_index(jis_code)

        direct_positions = value_positions.get(
            jis_code,
            [],
        )

        unicode_positions = []

        for index, value in enumerate(
            font_entries
        ):
            mapped_unicode = unicode_from_jis(
                jis2ucs,
                value,
            )

            if mapped_unicode == unicode_code:
                unicode_positions.append(index)

        glyph_positions = [
            index
            for index in unicode_positions
            if index < glyph_count
        ]

        lines.append("")
        lines.append(
            f"{character} "
            f"UNICODE=U+{unicode_code:04X} "
            f"JIS=0x{jis_code:04X} "
            f"SJIS={character.encode('shift_jis').hex(' ').upper()}"
        )

        lines.append(
            f"  NSF BYTES : "
            f"{raw_bytes.hex(' ').upper()}"
        )
        lines.append(
            f"  RAW BE    : 0x{raw_be:04X}"
        )
        lines.append(
            f"  RAW LE    : 0x{raw_le:04X}"
        )

        lines.append(
            "  FONT VALUE == JIS POSITIONS: "
            + (
                ", ".join(
                    f"0x{index:04X}"
                    for index in direct_positions[:30]
                )
                if direct_positions
                else "NONE"
            )
        )

        lines.append(
            "  FONT→JIS→UNICODE POSITIONS : "
            + (
                ", ".join(
                    f"0x{index:04X}"
                    for index in unicode_positions[:30]
                )
                if unicode_positions
                else "NONE"
            )
        )

        lines.append(
            "  POSITIONS INSIDE GLYPHS    : "
            + (
                ", ".join(
                    f"0x{index:04X}"
                    for index in glyph_positions
                )
                if glyph_positions
                else "NONE"
            )
        )

        candidates = [
            ("RAW_BE", raw_be),
            ("RAW_LE", raw_le),
            ("JIS_DIRECT", jis_code),
            ("JIS_94_GRID", grid94),
            ("JIS_96_GRID", grid96),
        ]

        lines.append("  CANDIDATE INDEX LOOKUPS:")

        for name, index in candidates:
            lines.append(
                f"    {name:<12} "
                f"INDEX=0x{index:04X} "
                f"{describe_entry(
                    font_entries,
                    jis2ucs,
                    index,
                )}"
            )

        lines.append("  DIRECT RELATION TESTS:")

        for raw_name, raw_value in (
            ("RAW_BE", raw_be),
            ("RAW_LE", raw_le),
        ):
            if 0 <= raw_value < len(
                font_entries
            ):
                mapped = font_entries[
                    raw_value
                ]

                lines.append(
                    f"    FONT[{raw_name}] "
                    f"== JIS: "
                    f"{mapped == jis_code} "
                    f"(0x{mapped:04X})"
                )
            else:
                lines.append(
                    f"    FONT[{raw_name}] "
                    f"== JIS: OUT-OF-RANGE"
                )

            raw_positions = value_positions.get(
                raw_value,
                [],
            )

            lines.append(
                f"    VALUE {raw_name} POSITIONS: "
                + (
                    ", ".join(
                        f"0x{index:04X}"
                        for index in raw_positions[:20]
                    )
                    if raw_positions
                    else "NONE"
                )
            )

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = "\n".join(lines) + "\n"

    REPORT_PATH.write_text(
        output,
        encoding="utf-8",
    )

    print(output, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
