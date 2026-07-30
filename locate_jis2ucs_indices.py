#!/usr/bin/env python3

from pathlib import Path


TABLE_PATH = Path(
    "workspace/unpack/START_runtime/jis2ucs.bin"
)

CHARACTERS = [
    "の",
    "ウ",
    "ワ",
    "サ",
    "命",
]


def read_value(
    data: bytes,
    index: int,
    endian: str,
) -> int | None:
    offset = index * 2

    if offset < 0 or offset + 2 > len(data):
        return None

    return int.from_bytes(
        data[offset:offset + 2],
        byteorder=endian,
    )


def format_value(value: int | None) -> str:
    if value is None:
        return "OUT-OF-RANGE"

    return f"U+{value:04X}"


def main() -> int:
    data = TABLE_PATH.read_bytes()

    if len(data) % 2:
        raise ValueError(
            "테이블 크기가 2의 배수가 아닙니다."
        )

    entry_count = len(data) // 2

    print("JIS2UCS VALUE LOCATOR")
    print("=====================")
    print("FILE   :", TABLE_PATH)
    print("SIZE   :", len(data))
    print("ENTRIES:", entry_count)
    print()

    for endian in ("little", "big"):
        values = [
            int.from_bytes(
                data[offset:offset + 2],
                byteorder=endian,
            )
            for offset in range(0, len(data), 2)
        ]

        nonzero_indices = [
            index
            for index, value in enumerate(values)
            if value != 0
        ]

        print("=" * 72)
        print("ENDIAN:", endian.upper())
        print("=" * 72)
        print(
            "NONZERO:",
            len(nonzero_indices),
        )

        if nonzero_indices:
            print(
                "FIRST NONZERO INDEX:",
                f"0x{nonzero_indices[0]:04X}",
            )
            print(
                "LAST NONZERO INDEX :",
                f"0x{nonzero_indices[-1]:04X}",
            )

        print()

        for character in CHARACTERS:
            unicode_value = ord(character)

            found_indices = [
                index
                for index, value in enumerate(values)
                if value == unicode_value
            ]

            sjis = character.encode("shift_jis")

            sjis_code = int.from_bytes(
                sjis,
                byteorder="big",
            )

            iso2022 = character.encode("iso2022_jp")
            marker = b"\x1B$B"
            marker_position = iso2022.find(marker)

            jis_code = int.from_bytes(
                iso2022[
                    marker_position + 3:
                    marker_position + 5
                ],
                byteorder="big",
            )

            row = (jis_code >> 8) & 0xFF
            cell = jis_code & 0xFF

            grid_index = (
                (row - 0x21) * 94
                + (cell - 0x21)
            )

            candidates = {
                "JIS": jis_code,
                "JIS_SWAP": (
                    ((jis_code & 0xFF) << 8)
                    | (jis_code >> 8)
                ),
                "SHIFT_JIS": sjis_code,
                "SHIFT_JIS_SWAP": (
                    ((sjis_code & 0xFF) << 8)
                    | (sjis_code >> 8)
                ),
                "JIS_94_GRID": grid_index,
                "JIS_ZERO_BASED": (
                    ((row - 0x20) << 8)
                    | (cell - 0x20)
                ),
            }

            print(
                f"{character} "
                f"UNICODE=U+{unicode_value:04X} "
                f"SJIS={sjis.hex(' ').upper()} "
                f"JIS=0x{jis_code:04X}"
            )

            if found_indices:
                print(
                    "  FOUND INDICES:",
                    ", ".join(
                        f"0x{index:04X}"
                        for index in found_indices[:20]
                    ),
                )
            else:
                print(
                    "  FOUND INDICES: NONE"
                )

            print("  CANDIDATE LOOKUPS:")

            for name, index in candidates.items():
                value = read_value(
                    data,
                    index,
                    endian,
                )

                match = (
                    value == unicode_value
                )

                print(
                    f"    {name:<16} "
                    f"INDEX=0x{index:04X} "
                    f"VALUE={format_value(value)}"
                    f"{'  MATCH' if match else ''}"
                )

            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
