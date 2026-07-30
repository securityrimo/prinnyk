#!/usr/bin/env python3

import struct
from pathlib import Path

import dump_boot_font_functions as mips


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/charset_global_xrefs.txt"
)

TARGETS = {
    0x08A2960C: "charset fallback/default",
    0x08A29610: "jis2ucs.bin pointer",
    0x08A29614: "ucs2jis.bin pointer",
}

MEMORY_OPCODES = {
    0x20: "lb",
    0x21: "lh",
    0x23: "lw",
    0x24: "lbu",
    0x25: "lhu",
    0x28: "sb",
    0x29: "sh",
    0x2B: "sw",
}


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def find_xrefs(
    data: bytes,
    sections: list[dict],
    target_address: int,
) -> list[dict]:
    results = []
    seen = set()

    for section in sections:
        if not (section["flags"] & 0x4):
            continue

        section_start = section["offset"]
        section_end = section_start + section["size"]

        if section_end > len(data):
            continue

        instruction_count = section["size"] // 4

        for first_index in range(instruction_count):
            first_offset = (
                section_start
                + first_index * 4
            )

            first_word = read_u32(
                data,
                first_offset,
            )

            first_opcode = (
                first_word >> 26
            ) & 0x3F

            # LUI 명령만 시작점으로 검사한다.
            if first_opcode != 0x0F:
                continue

            base_register = (
                first_word >> 16
            ) & 0x1F

            high_value = (
                first_word & 0xFFFF
            ) << 16

            # 컴파일러가 중간에 독립 명령을 배치할 수 있다.
            for distance in range(1, 13):
                second_index = (
                    first_index
                    + distance
                )

                if second_index >= instruction_count:
                    break

                second_offset = (
                    section_start
                    + second_index * 4
                )

                second_word = read_u32(
                    data,
                    second_offset,
                )

                opcode = (
                    second_word >> 26
                ) & 0x3F

                rs = (
                    second_word >> 21
                ) & 0x1F

                immediate = (
                    second_word & 0xFFFF
                )

                if rs != base_register:
                    continue

                operation = None
                calculated_address = None

                if opcode in MEMORY_OPCODES:
                    calculated_address = (
                        high_value
                        + mips.signed16(immediate)
                    ) & 0xFFFFFFFF

                    operation = MEMORY_OPCODES[
                        opcode
                    ]

                elif opcode == 0x09:
                    calculated_address = (
                        high_value
                        + mips.signed16(immediate)
                    ) & 0xFFFFFFFF

                    operation = "addiu"

                elif opcode == 0x0D:
                    calculated_address = (
                        high_value
                        | immediate
                    )

                    operation = "ori"

                if calculated_address != target_address:
                    continue

                first_address = (
                    section["vaddr"]
                    + first_index * 4
                )

                second_address = (
                    section["vaddr"]
                    + second_index * 4
                )

                key = (
                    first_address,
                    second_address,
                )

                if key in seen:
                    continue

                seen.add(key)

                results.append(
                    {
                        "section": section,
                        "lui_address": first_address,
                        "xref_address": second_address,
                        "operation": operation,
                        "distance": distance,
                    }
                )

    return sorted(
        results,
        key=lambda item: item["xref_address"],
    )


def print_context(
    output,
    data: bytes,
    sections: list[dict],
    hit: dict,
    before: int = 12,
    after: int = 12,
) -> None:
    section = hit["section"]
    center = hit["xref_address"]

    start = max(
        section["vaddr"],
        center - before * 4,
    )

    end = min(
        section["vaddr"] + section["size"],
        center + (after + 1) * 4,
    )

    for address in range(start, end, 4):
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

        if address == hit["xref_address"]:
            marker = ">>"
        elif address == hit["lui_address"]:
            marker = "**"
        else:
            marker = "  "

        print(
            f"{marker} "
            f"0x{address:08X}  "
            f"FILE=0x{offset:X}  "
            f"{word:08X}  "
            f"{decoded}",
            file=output,
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

    with REPORT_PATH.open(
        "w",
        encoding="utf-8",
    ) as report:
        print(
            "CHARSET GLOBAL CROSS REFERENCES",
            file=report,
        )
        print(
            "===============================",
            file=report,
        )

        for target_address, label in TARGETS.items():
            hits = find_xrefs(
                data,
                sections,
                target_address,
            )

            print(file=report)
            print("=" * 88, file=report)
            print(
                f"{label}: 0x{target_address:08X}",
                file=report,
            )
            print("=" * 88, file=report)
            print(
                f"XREF COUNT: {len(hits)}",
                file=report,
            )

            for index, hit in enumerate(
                hits,
                start=1,
            ):
                print(file=report)
                print(
                    f"[{index}] "
                    f"XREF=0x{hit['xref_address']:08X} "
                    f"LUI=0x{hit['lui_address']:08X} "
                    f"OP={hit['operation']} "
                    f"DISTANCE={hit['distance']} "
                    f"SECTION={hit['section']['name']}",
                    file=report,
                )

                print_context(
                    report,
                    data,
                    sections,
                    hit,
                )

    print(
        REPORT_PATH.read_text(
            encoding="utf-8",
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
