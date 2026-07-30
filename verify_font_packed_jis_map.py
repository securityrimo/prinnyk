#!/usr/bin/env python3

import struct
from pathlib import Path


FONT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

JIS2UCS_PATH = Path(
    "workspace/unpack/START_runtime/jis2ucs.bin"
)

REPORT_PATH = Path(
    "workspace/reports/font_packed_jis_verify.txt"
)

# 아틀라스에서 직접 확인한 글리프 위치
KNOWN = [
    ("の", 0x00D0),
    ("ウ", 0x0119),
    ("サ", 0x0126),
    ("ワ", 0x015F),
    ("命", 0x072E),
]


def u16le(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<H",
        data,
        offset,
    )[0]


def get_jis_code(character: str) -> int:
    encoded = character.encode("iso2022_jp")
    marker = b"\x1B$B"

    position = encoded.find(marker)

    if position < 0:
        raise ValueError(
            f"JIS 코드 변환 실패: {character}"
        )

    start = position + len(marker)

    return int.from_bytes(
        encoded[start:start + 2],
        byteorder="big",
    )


def packed_jis_index(jis_code: int) -> int:
    row = (jis_code >> 8) & 0xFF
    cell = jis_code & 0xFF

    if not (
        0x20 <= row <= 0x7F
        and 0x20 <= cell <= 0x7F
    ):
        raise ValueError(
            f"지원하지 않는 JIS 코드: "
            f"0x{jis_code:04X}"
        )

    return (
        ((row - 0x20) << 7)
        | (cell - 0x20)
    )


def unpack_packed_jis(index: int) -> int:
    row = (
        (index >> 7)
        + 0x20
    )

    cell = (
        (index & 0x7F)
        + 0x20
    )

    return (
        (row << 8)
        | cell
    )


def main() -> int:
    font_data = FONT_PATH.read_bytes()
    jis2ucs_data = JIS2UCS_PATH.read_bytes()

    if len(font_data) < 2:
        raise ValueError(
            "font.fnt가 너무 작습니다."
        )

    entry_count = u16le(
        font_data,
        0,
    )

    expected_size = (
        2
        + entry_count * 2
    )

    if len(font_data) != expected_size:
        raise ValueError(
            "font.fnt 크기 불일치: "
            f"실제=0x{len(font_data):X}, "
            f"예상=0x{expected_size:X}"
        )

    table = list(
        struct.unpack_from(
            f"<{entry_count}H",
            font_data,
            2,
        )
    )

    maximum_index = entry_count - 1
    maximum_jis = unpack_packed_jis(
        maximum_index,
    )

    lines = []

    lines.append(
        "PACKED JIS FONT MAP VERIFICATION"
    )
    lines.append(
        "================================"
    )
    lines.append(
        f"FONT FILE     : {FONT_PATH}"
    )
    lines.append(
        f"FILE SIZE     : 0x{len(font_data):X}"
    )
    lines.append(
        f"HEADER COUNT  : 0x{entry_count:X} "
        f"({entry_count})"
    )
    lines.append(
        f"EXPECTED SIZE : 0x{expected_size:X}"
    )
    lines.append(
        f"TABLE OFFSET  : 0x2"
    )
    lines.append(
        f"MAX INDEX     : 0x{maximum_index:04X}"
    )
    lines.append(
        f"MAX PACKED JIS: 0x{maximum_jis:04X}"
    )
    lines.append("")

    match_count = 0

    for character, expected_glyph in KNOWN:
        jis_code = get_jis_code(
            character
        )

        table_index = packed_jis_index(
            jis_code
        )

        if table_index >= entry_count:
            lines.append(
                f"{character} "
                f"JIS=0x{jis_code:04X} "
                f"INDEX=0x{table_index:04X} "
                f"OUT-OF-RANGE"
            )
            continue

        glyph_index = table[
            table_index
        ]

        reconstructed_jis = (
            unpack_packed_jis(
                table_index
            )
        )

        unicode_offset = (
            reconstructed_jis * 2
        )

        if (
            unicode_offset + 2
            <= len(jis2ucs_data)
        ):
            unicode_value = u16le(
                jis2ucs_data,
                unicode_offset,
            )
        else:
            unicode_value = 0

        matched = (
            glyph_index
            == expected_glyph
        )

        match_count += int(matched)

        lines.append(
            f"{character} "
            f"UNICODE=U+{ord(character):04X} "
            f"JIS=0x{jis_code:04X}"
        )

        lines.append(
            f"  PACKED INDEX : "
            f"0x{table_index:04X}"
        )

        lines.append(
            f"  TABLE OFFSET : "
            f"0x{2 + table_index * 2:05X}"
        )

        lines.append(
            f"  GLYPH RESULT : "
            f"0x{glyph_index:04X}"
        )

        lines.append(
            f"  ATLAS EXPECT : "
            f"0x{expected_glyph:04X}"
        )

        lines.append(
            f"  JIS2UCS      : "
            f"U+{unicode_value:04X}"
        )

        lines.append(
            f"  RESULT       : "
            f"{'MATCH' if matched else 'MISMATCH'}"
        )

        lines.append("")

    lines.append("FINAL RESULT")
    lines.append("============")
    lines.append(
        f"PACKED JIS → GLYPH: "
        f"{match_count}/{len(KNOWN)}"
    )

    if match_count == len(KNOWN):
        lines.append("")
        lines.append(
            "CONFIRMED FORMULA:"
        )
        lines.append(
            "index = "
            "((jis_hi - 0x20) << 7) "
            "| (jis_lo - 0x20)"
        )
        lines.append(
            "glyph = font_table[index]"
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
