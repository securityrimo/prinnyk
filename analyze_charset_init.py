#!/usr/bin/env python3

import struct
from pathlib import Path

import dump_boot_font_functions as mips


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/charset_init_analysis.txt"
)

TARGET_ADDRESS = 0x0883A528


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def find_jal_callers(
    data: bytes,
    sections: list[dict],
    target: int,
) -> list[tuple[int, int, dict]]:
    callers = []

    for section in sections:
        if not (section["flags"] & 0x4):
            continue

        if section["offset"] + section["size"] > len(data):
            continue

        for relative in range(
            0,
            section["size"] - 3,
            4,
        ):
            file_offset = (
                section["offset"]
                + relative
            )

            address = (
                section["vaddr"]
                + relative
            )

            word = read_u32(
                data,
                file_offset,
            )

            opcode = (
                word >> 26
            ) & 0x3F

            if opcode != 0x03:
                continue

            destination = mips.jump_target(
                address,
                word,
            )

            if destination == target:
                callers.append(
                    (
                        address,
                        file_offset,
                        section,
                    )
                )

    return callers


def print_context(
    data: bytes,
    sections: list[dict],
    caller_address: int,
    section: dict,
    before: int = 12,
    after: int = 8,
) -> None:
    start = max(
        section["vaddr"],
        caller_address - before * 4,
    )

    end = min(
        section["vaddr"] + section["size"],
        caller_address + (after + 1) * 4,
    )

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

        decoded = mips.decode_instruction(
            word,
            address,
        )

        marker = (
            ">>"
            if address == caller_address
            else "  "
        )

        print(
            f"{marker} "
            f"0x{address:08X}  "
            f"{word:08X}  "
            f"{decoded}"
        )


def main() -> int:
    data = BOOT_PATH.read_bytes()

    if data[:4] != b"\x7FELF":
        raise ValueError(
            "BOOT.BIN이 ELF 파일이 아닙니다."
        )

    sections = mips.parse_sections(data)

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    import contextlib
    import sys

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as report:
        with contextlib.redirect_stdout(report):
            print("CHARSET INITIALIZER ANALYSIS")
            print("============================")
            print(
                "TARGET:",
                f"0x{TARGET_ADDRESS:08X}",
            )

            mips.print_function(
                data,
                sections,
                "jis2ucs / ucs2jis initializer candidate",
                TARGET_ADDRESS,
            )

            callers = find_jal_callers(
                data,
                sections,
                TARGET_ADDRESS,
            )

            print()
            print("=" * 88)
            print("ALL CALLERS")
            print("=" * 88)
            print("COUNT:", len(callers))

            for index, (
                address,
                file_offset,
                section,
            ) in enumerate(
                callers,
                start=1,
            ):
                print()
                print(
                    f"[{index}] "
                    f"VA=0x{address:08X} "
                    f"FILE=0x{file_offset:X} "
                    f"SECTION={section['name']}"
                )

                print_context(
                    data,
                    sections,
                    address,
                    section,
                )

    print("CHARSET INITIALIZER ANALYSIS")
    print("============================")
    print(
        "TARGET:",
        f"0x{TARGET_ADDRESS:08X}",
    )
    print("SAVED :", REPORT_PATH)

    text = REPORT_PATH.read_text(
        encoding="utf-8",
    )

    lines = text.splitlines()

    print()
    print("IMPORTANT LINES")
    print("===============")

    for line in lines:
        if (
            "RANGE  :" in line
            or "SIZE   :" in line
            or "CALL TARGETS:" in line
            or "COUNT:" in line
            or line.startswith("  0x")
            or line.startswith(">>")
        ):
            print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
