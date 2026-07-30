#!/usr/bin/env python3

import struct
from pathlib import Path


FONT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

REPORT_PATH = Path(
    "workspace/reports/font_sjis_dense_verify.txt"
)

# 아틀라스에서 확인한 실제 글리프 인덱스
KNOWN = [
    ("の", 0x00D0),
    ("ウ", 0x0118),
    ("サ", 0x0127),
    ("ワ", 0x0158),
    ("命", 0x072E),
]


def parse_font_table(
    data: bytes,
) -> list[int]:
    if len(data) < 2:
        raise ValueError(
            "font.fnt가 너무 작습니다."
        )

    count = struct.unpack_from(
        "<H",
        data,
        0,
    )[0]

    expected_size = (
        2
        + count * 2
    )

    if len(data) != expected_size:
        raise ValueError(
            "font.fnt 크기 불일치: "
            f"actual=0x{len(data):X}, "
            f"expected=0x{expected_size:X}"
        )

    return list(
        struct.unpack_from(
            f"<{count}H",
            data,
            2,
        )
    )


def lead_slot(lead: int) -> int:
    if 0x81 <= lead <= 0x9F:
        return lead - 0x81

    if 0xE0 <= lead <= 0xFC:
        return (
            31
            + lead
            - 0xE0
        )

    raise ValueError(
        f"잘못된 Shift-JIS 리드 바이트: "
        f"0x{lead:02X}"
    )


def trail_slot(trail: int) -> int:
    if 0x40 <= trail <= 0x7E:
        return trail - 0x40

    if 0x80 <= trail <= 0xFC:
        # 0x7F은 Shift-JIS 트레일 바이트에서 제외된다.
        return trail - 0x41

    raise ValueError(
        f"잘못된 Shift-JIS 트레일 바이트: "
        f"0x{trail:02X}"
    )


def dense_sjis_index(
    encoded: bytes,
) -> int:
    if len(encoded) == 1:
        return encoded[0]

    if len(encoded) != 2:
        raise ValueError(
            "1바이트 또는 2바이트 "
            "Shift-JIS만 지원합니다."
        )

    lead = encoded[0]
    trail = encoded[1]

    return (
        0x100
        + lead_slot(lead) * 188
        + trail_slot(trail)
    )


def find_value_positions(
    table: list[int],
    value: int,
) -> list[int]:
    return [
        index
        for index, entry in enumerate(table)
        if entry == value
    ]


def main() -> int:
    font_data = FONT_PATH.read_bytes()
    table = parse_font_table(font_data)

    # 표준 Shift-JIS 유효 조합을 압축한 기본 범위
    lead_count = 31 + 29
    dense_base_count = (
        0x100
        + lead_count * 188
    )

    lines = []

    lines.append(
        "SHIFT-JIS DENSE FONT MAP VERIFICATION"
    )
    lines.append(
        "====================================="
    )
    lines.append(
        f"FONT FILE       : {FONT_PATH}"
    )
    lines.append(
        f"FILE SIZE       : 0x{len(font_data):X}"
    )
    lines.append(
        f"TABLE ENTRIES   : "
        f"0x{len(table):X} ({len(table)})"
    )
    lines.append(
        f"DENSE BASE SIZE : "
        f"0x{dense_base_count:X} "
        f"({dense_base_count})"
    )
    lines.append(
        f"EXTRA ENTRIES   : "
        f"0x{len(table) - dense_base_count:X}"
    )
    lines.append("")

    match_count = 0

    for character, expected_glyph in KNOWN:
        encoded = character.encode(
            "shift_jis"
        )

        dense_index = dense_sjis_index(
            encoded
        )

        if dense_index >= len(table):
            lines.append(
                f"{character}: "
                f"INDEX=0x{dense_index:04X} "
                f"OUT-OF-RANGE"
            )
            lines.append("")
            continue

        actual_glyph = table[
            dense_index
        ]

        matched = (
            actual_glyph
            == expected_glyph
        )

        match_count += int(matched)

        positions = find_value_positions(
            table,
            expected_glyph,
        )

        lines.append(
            f"{character} "
            f"UNICODE=U+{ord(character):04X}"
        )
        lines.append(
            f"  SHIFT-JIS     : "
            f"{encoded.hex(' ').upper()}"
        )

        if len(encoded) == 2:
            lines.append(
                f"  LEAD SLOT     : "
                f"{lead_slot(encoded[0])}"
            )
            lines.append(
                f"  TRAIL SLOT    : "
                f"{trail_slot(encoded[1])}"
            )

        lines.append(
            f"  DENSE INDEX   : "
            f"0x{dense_index:04X}"
        )
        lines.append(
            f"  TABLE OFFSET  : "
            f"0x{2 + dense_index * 2:05X}"
        )
        lines.append(
            f"  GLYPH RESULT  : "
            f"0x{actual_glyph:04X}"
        )
        lines.append(
            f"  ATLAS EXPECT  : "
            f"0x{expected_glyph:04X}"
        )
        lines.append(
            f"  RESULT        : "
            f"{'MATCH' if matched else 'MISMATCH'}"
        )
        lines.append(
            "  EXPECTED GLYPH VALUE POSITIONS: "
            + (
                ", ".join(
                    f"0x{position:04X}"
                    for position in positions[:20]
                )
                if positions
                else "NONE"
            )
        )
        lines.append("")

    lines.append("FINAL RESULT")
    lines.append("============")
    lines.append(
        f"SHIFT-JIS → GLYPH: "
        f"{match_count}/{len(KNOWN)}"
    )

    if match_count == len(KNOWN):
        lines.append("")
        lines.append(
            "CONFIRMED:"
        )
        lines.append(
            "font.fnt는 압축된 Shift-JIS "
            "슬롯 → 글리프 인덱스 테이블입니다."
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
