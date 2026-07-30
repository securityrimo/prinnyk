#!/usr/bin/env python3

import struct
from pathlib import Path

import dump_boot_font_functions as mips


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/charset_codec_helpers.txt"
)

RANGES = [
    (
        "external input decoder",
        0x08839ECC,
        0x08839F48,
    ),
    (
        "external output encoder",
        0x08839F48,
        0x0883A024,
    ),
    (
        "game string code decoder",
        0x0883A024,
        0x0883A1A0,
    ),
    (
        "game string code encoder",
        0x0883A1A0,
        0x0883A368,
    ),
]


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def main() -> int:
    data = BOOT_PATH.read_bytes()

    if data[:4] != b"\x7FELF":
        raise ValueError(
            "BOOT.BIN이 ELF가 아닙니다."
        )

    sections = mips.parse_sections(data)

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as report:
        print(
            "CHARSET CODEC HELPERS",
            file=report,
        )
        print(
            "=====================",
            file=report,
        )

        for label, start, end in RANGES:
            print(file=report)
            print("=" * 88, file=report)
            print(label, file=report)
            print("=" * 88, file=report)
            print(
                f"RANGE: "
                f"0x{start:08X}~0x{end:08X} "
                f"SIZE=0x{end - start:X}",
                file=report,
            )
            print(file=report)

            for address in range(
                start,
                end,
                4,
            ):
                offset = mips.va_to_offset(
                    sections,
                    address,
                )

                word = read_u32(
                    data,
                    offset,
                )

                decoded = (
                    mips.decode_instruction(
                        word,
                        address,
                    )
                )

                print(
                    f"0x{address:08X}  "
                    f"FILE=0x{offset:X}  "
                    f"{word:08X}  "
                    f"{decoded}",
                    file=report,
                )

    print(
        REPORT_PATH.read_text(
            encoding="utf-8",
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
