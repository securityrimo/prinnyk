#!/usr/bin/env python3

import struct
from pathlib import Path

import dump_boot_font_functions as mips


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/exact_charset_function.txt"
)

START_ADDRESS = 0x0883A528
MAX_SIZE = 0x800
RETURN_WORD = 0x03E00008  # jr $ra


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
            "BOOT.BIN이 ELF 파일이 아닙니다."
        )

    sections = mips.parse_sections(data)

    section = mips.section_for_va(
        sections,
        START_ADDRESS,
    )

    if section is None:
        raise ValueError(
            f"주소를 포함하는 섹션이 없습니다: "
            f"0x{START_ADDRESS:08X}"
        )

    maximum_address = min(
        START_ADDRESS + MAX_SIZE,
        section["vaddr"] + section["size"],
    )

    instructions = []
    call_targets = []

    address = START_ADDRESS
    found_return = False

    while address < maximum_address:
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

        instructions.append(
            (
                address,
                offset,
                word,
                decoded,
            )
        )

        opcode = (word >> 26) & 0x3F

        if opcode == 0x03:
            call_targets.append(
                mips.jump_target(
                    address,
                    word,
                )
            )

        if word == RETURN_WORD:
            # jr $ra의 지연 슬롯도 포함
            delay_address = address + 4

            if delay_address < maximum_address:
                delay_offset = mips.va_to_offset(
                    sections,
                    delay_address,
                )

                delay_word = read_u32(
                    data,
                    delay_offset,
                )

                delay_decoded = (
                    mips.decode_instruction(
                        delay_word,
                        delay_address,
                    )
                )

                instructions.append(
                    (
                        delay_address,
                        delay_offset,
                        delay_word,
                        delay_decoded,
                    )
                )

            found_return = True
            break

        address += 4

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as report:
        print(
            "EXACT CHARSET FUNCTION",
            file=report,
        )

        print(
            "======================",
            file=report,
        )

        print(
            f"START   : 0x{START_ADDRESS:08X}",
            file=report,
        )

        print(
            f"SECTION : {section['name']}",
            file=report,
        )

        print(
            f"RETURN  : "
            f"{'FOUND' if found_return else 'NOT FOUND'}",
            file=report,
        )

        if instructions:
            end_address = (
                instructions[-1][0] + 4
            )

            print(
                f"RANGE   : "
                f"0x{START_ADDRESS:08X}"
                f"~0x{end_address:08X}",
                file=report,
            )

            print(
                f"SIZE    : "
                f"0x{end_address - START_ADDRESS:X}",
                file=report,
            )

        print(file=report)

        for (
            instruction_address,
            file_offset,
            word,
            decoded,
        ) in instructions:
            print(
                f"0x{instruction_address:08X}  "
                f"FILE=0x{file_offset:X}  "
                f"{word:08X}  "
                f"{decoded}",
                file=report,
            )

        print(file=report)
        print(
            "CALL TARGETS",
            file=report,
        )

        print(
            "============",
            file=report,
        )

        if not call_targets:
            print(
                "NONE",
                file=report,
            )
        else:
            for target in sorted(
                set(call_targets)
            ):
                print(
                    f"0x{target:08X}",
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
