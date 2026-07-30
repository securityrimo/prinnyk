#!/usr/bin/env python3

import struct
from collections import defaultdict
from pathlib import Path


FONT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

JIS2UCS_PATH = Path(
    "workspace/unpack/START_runtime/jis2ucs.bin"
)

REPORT_PATH = Path(
    "workspace/reports/font_table_at_glyphs.txt"
)

GLYPH_COUNT = 0x806

KNOWN = [
    ("の", 0x00D0, bytes.fromhex("00 43")),
    ("ウ", 0x0118, bytes.fromhex("0B 43")),
    ("サ", 0x0126, bytes.fromhex("32 00")),
    ("ワ", 0x0158, bytes.fromhex("1E 00")),
    ("命", 0x072E, bytes.fromhex("22 00")),
]


def unpack_u16_le(data: bytes) -> list[int]:
    if len(data) % 2:
        raise ValueError(
            "데이터 크기가 2의 배수가 아닙니다."
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


def jis_to_unicode(
    jis2ucs: list[int],
    jis_code: int,
) -> int | None:
    if not 0 <= jis_code < len(jis2ucs):
        return None

    value = jis2ucs[jis_code]

    if value == 0:
        return None

    return value


def grid94_to_jis(index: int) -> int | None:
    maximum = 94 * 94

    if not 0 <= index < maximum:
        return None

    row = index // 94 + 0x21
    cell = index % 94 + 0x21

    return (
        (row << 8)
        | cell
    )


def packed7_to_jis(index: int) -> int | None:
    row = (index >> 7) + 0x20
    cell = (index & 0x7F) + 0x20

    if not (
        0x21 <= row <= 0x7E
        and 0x21 <= cell <= 0x7E
    ):
        return None

    return (
        (row << 8)
        | cell
    )


def decode_shift_jis(value: int) -> str | None:
    if value <= 0xFF:
        raw = bytes([value])
    else:
        raw = value.to_bytes(
            2,
            byteorder="big",
        )

    try:
        text = raw.decode(
            "shift_jis",
            errors="strict",
        )
    except UnicodeDecodeError:
        return None

    if not text:
        return None

    return text


def format_unicode(value: int | None) -> str:
    if value is None:
        return "NONE"

    try:
        character = chr(value)
    except ValueError:
        character = "?"

    return (
        f"U+{value:04X} "
        f"{character!r}"
    )


def format_positions(
    positions: list[int],
    limit: int = 30,
) -> str:
    if not positions:
        return "NONE"

    shown = ", ".join(
        f"0x{position:04X}"
        for position in positions[:limit]
    )

    if len(positions) > limit:
        shown += (
            f", ... "
            f"({len(positions)} total)"
        )

    return shown


def describe_value(
    value: int,
    jis2ucs: list[int],
    expected_unicode: int,
) -> list[str]:
    descriptions = []

    direct_unicode = jis_to_unicode(
        jis2ucs,
        value,
    )

    descriptions.append(
        "DIRECT JIS      : "
        f"JIS=0x{value:04X} "
        f"UNICODE={format_unicode(direct_unicode)}"
        f"{' MATCH' if direct_unicode == expected_unicode else ''}"
    )

    grid94_jis = grid94_to_jis(value)

    if grid94_jis is None:
        descriptions.append(
            "94-GRID INDEX   : INVALID"
        )
    else:
        grid94_unicode = jis_to_unicode(
            jis2ucs,
            grid94_jis,
        )

        descriptions.append(
            "94-GRID INDEX   : "
            f"JIS=0x{grid94_jis:04X} "
            f"UNICODE={format_unicode(grid94_unicode)}"
            f"{' MATCH' if grid94_unicode == expected_unicode else ''}"
        )

    packed7_jis = packed7_to_jis(value)

    if packed7_jis is None:
        descriptions.append(
            "PACKED-7 INDEX  : INVALID"
        )
    else:
        packed7_unicode = jis_to_unicode(
            jis2ucs,
            packed7_jis,
        )

        descriptions.append(
            "PACKED-7 INDEX  : "
            f"JIS=0x{packed7_jis:04X} "
            f"UNICODE={format_unicode(packed7_unicode)}"
            f"{' MATCH' if packed7_unicode == expected_unicode else ''}"
        )

    sjis_text = decode_shift_jis(value)

    descriptions.append(
        "SHIFT-JIS VALUE : "
        + (
            repr(sjis_text)
            if sjis_text is not None
            else "INVALID"
        )
        + (
            " MATCH"
            if sjis_text == chr(expected_unicode)
            else ""
        )
    )

    return descriptions


def main() -> int:
    font_data = FONT_PATH.read_bytes()
    jis2ucs_data = JIS2UCS_PATH.read_bytes()

    if len(font_data) < 2:
        raise ValueError(
            "font.fnt가 너무 작습니다."
        )

    entry_count = struct.unpack_from(
        "<H",
        font_data,
        0,
    )[0]

    expected_size = (
        2
        + entry_count * 2
    )

    if expected_size != len(font_data):
        raise ValueError(
            "font.fnt 크기가 헤더 값과 다릅니다: "
            f"actual=0x{len(font_data):X}, "
            f"expected=0x{expected_size:X}"
        )

    # 헤더 2바이트를 제외한 실제 테이블
    table = list(
        struct.unpack_from(
            f"<{entry_count}H",
            font_data,
            2,
        )
    )

    jis2ucs = unpack_u16_le(
        jis2ucs_data
    )

    value_positions = defaultdict(list)

    for index, value in enumerate(table):
        value_positions[value].append(index)

    identity_length = 0

    for index, value in enumerate(table):
        if index != value:
            break

        identity_length += 1

    glyph_values = table[:GLYPH_COUNT]

    lines = []

    lines.append(
        "FONT TABLE VALUES AT CONFIRMED GLYPHS"
    )
    lines.append(
        "====================================="
    )
    lines.append(f"FONT FILE       : {FONT_PATH}")
    lines.append(
        f"FILE SIZE       : 0x{len(font_data):X}"
    )
    lines.append(
        f"HEADER COUNT    : 0x{entry_count:X} "
        f"({entry_count})"
    )
    lines.append("TABLE OFFSET    : 0x2")
    lines.append(
        f"GLYPH COUNT     : 0x{GLYPH_COUNT:X} "
        f"({GLYPH_COUNT})"
    )
    lines.append(
        f"IDENTITY PREFIX : {identity_length} entries"
    )
    lines.append(
        f"GLYPH VALUES    : "
        f"MIN=0x{min(glyph_values):04X} "
        f"MAX=0x{max(glyph_values):04X} "
        f"UNIQUE={len(set(glyph_values))}"
    )

    for (
        character,
        glyph_index,
        nsf_bytes,
    ) in KNOWN:
        expected_unicode = ord(character)
        standard_jis = get_jis_code(character)

        raw_be = int.from_bytes(
            nsf_bytes,
            byteorder="big",
        )

        raw_le = int.from_bytes(
            nsf_bytes,
            byteorder="little",
        )

        table_value = table[glyph_index]

        lines.append("")
        lines.append("=" * 78)
        lines.append(
            f"{character} "
            f"GLYPH=0x{glyph_index:04X} "
            f"UNICODE=U+{expected_unicode:04X} "
            f"JIS=0x{standard_jis:04X}"
        )
        lines.append("=" * 78)

        lines.append(
            f"NSF BYTES       : "
            f"{nsf_bytes.hex(' ').upper()}"
        )
        lines.append(
            f"NSF RAW BE      : 0x{raw_be:04X}"
        )
        lines.append(
            f"NSF RAW LE      : 0x{raw_le:04X}"
        )
        lines.append(
            f"TABLE[GLYPH]    : 0x{table_value:04X}"
        )

        lines.append(
            "MATCH RAW BE     : "
            f"{table_value == raw_be}"
        )
        lines.append(
            "MATCH RAW LE     : "
            f"{table_value == raw_le}"
        )
        lines.append(
            "MATCH JIS        : "
            f"{table_value == standard_jis}"
        )

        lines.append("")
        lines.append(
            "TABLE VALUE INTERPRETATIONS"
        )

        for description in describe_value(
            table_value,
            jis2ucs,
            expected_unicode,
        ):
            lines.append(
                f"  {description}"
            )

        lines.append("")
        lines.append(
            "INVERSE VALUE POSITIONS"
        )
        lines.append(
            "  TABLE VALUE : "
            + format_positions(
                value_positions.get(
                    table_value,
                    [],
                )
            )
        )
        lines.append(
            "  NSF RAW BE  : "
            + format_positions(
                value_positions.get(
                    raw_be,
                    [],
                )
            )
        )
        lines.append(
            "  NSF RAW LE  : "
            + format_positions(
                value_positions.get(
                    raw_le,
                    [],
                )
            )
        )
        lines.append(
            "  JIS VALUE   : "
            + format_positions(
                value_positions.get(
                    standard_jis,
                    [],
                )
            )
        )

        lines.append("")
        lines.append(
            "REVERSE-DIRECTION LOOKUPS"
        )

        for name, index in (
            ("NSF_RAW_BE", raw_be),
            ("NSF_RAW_LE", raw_le),
            ("STANDARD_JIS", standard_jis),
        ):
            if not 0 <= index < len(table):
                lines.append(
                    f"  TABLE[{name:<12}] "
                    f"INDEX=0x{index:04X} "
                    f"OUT-OF-RANGE"
                )
                continue

            lines.append(
                f"  TABLE[{name:<12}] "
                f"INDEX=0x{index:04X} "
                f"VALUE=0x{table[index]:04X}"
            )

        lines.append("")
        lines.append(
            "NEIGHBOURING GLYPH ENTRIES"
        )

        start = max(
            0,
            glyph_index - 4,
        )

        end = min(
            len(table),
            glyph_index + 5,
        )

        for index in range(start, end):
            marker = (
                ">>"
                if index == glyph_index
                else "  "
            )

            lines.append(
                f"{marker} "
                f"GLYPH=0x{index:04X} "
                f"VALUE=0x{table[index]:04X}"
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
