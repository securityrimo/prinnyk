#!/usr/bin/env python3

import struct
from pathlib import Path


INPUT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

TARGET_NAMES = [
    b"font.fnt",
    b"font.txp",
    b"jis2ucs.bin",
    b"ucs2jis.bin",
]


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def sign16(value: int) -> int:
    if value & 0x8000:
        return value - 0x10000

    return value


def read_c_string(
    data: bytes,
    offset: int,
) -> str:
    if offset < 0 or offset >= len(data):
        return ""

    end = data.find(b"\x00", offset)

    if end < 0:
        end = len(data)

    return data[offset:end].decode(
        "ascii",
        errors="replace",
    )


def find_all(
    data: bytes,
    needle: bytes,
):
    position = 0

    while True:
        position = data.find(
            needle,
            position,
        )

        if position < 0:
            return

        yield position
        position += 1


def decode_instruction(
    word: int,
    address: int,
) -> str:
    opcode = (word >> 26) & 0x3F
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    rd = (word >> 11) & 0x1F
    funct = word & 0x3F
    immediate = word & 0xFFFF

    registers = [
        "zero", "at", "v0", "v1",
        "a0", "a1", "a2", "a3",
        "t0", "t1", "t2", "t3",
        "t4", "t5", "t6", "t7",
        "s0", "s1", "s2", "s3",
        "s4", "s5", "s6", "s7",
        "t8", "t9", "k0", "k1",
        "gp", "sp", "fp", "ra",
    ]

    if word == 0:
        return "nop"

    if opcode == 0x0F:
        return (
            f"lui ${registers[rt]}, "
            f"0x{immediate:04X}"
        )

    if opcode == 0x09:
        return (
            f"addiu ${registers[rt]}, "
            f"${registers[rs]}, "
            f"{sign16(immediate)}"
        )

    if opcode == 0x0D:
        return (
            f"ori ${registers[rt]}, "
            f"${registers[rs]}, "
            f"0x{immediate:04X}"
        )

    if opcode == 0x23:
        return (
            f"lw ${registers[rt]}, "
            f"{sign16(immediate)}"
            f"(${registers[rs]})"
        )

    if opcode == 0x2B:
        return (
            f"sw ${registers[rt]}, "
            f"{sign16(immediate)}"
            f"(${registers[rs]})"
        )

    if opcode == 0x02:
        target = (
            ((address + 4) & 0xF0000000)
            | ((word & 0x03FFFFFF) << 2)
        )

        return f"j 0x{target:08X}"

    if opcode == 0x03:
        target = (
            ((address + 4) & 0xF0000000)
            | ((word & 0x03FFFFFF) << 2)
        )

        return f"jal 0x{target:08X}"

    if opcode == 0 and funct == 0x08:
        return f"jr ${registers[rs]}"

    if opcode == 0 and funct == 0x21:
        return (
            f"addu ${registers[rd]}, "
            f"${registers[rs]}, "
            f"${registers[rt]}"
        )

    return f".word 0x{word:08X}"


def main() -> int:
    data = INPUT_PATH.read_bytes()

    if data[:4] != b"\x7FELF":
        raise ValueError("BOOT.BIN이 ELF 파일이 아닙니다.")

    if data[4] != 1 or data[5] != 1:
        raise ValueError(
            "ELF32 little-endian 형식이 아닙니다."
        )

    program_header_offset = u32(data, 0x1C)
    section_header_offset = u32(data, 0x20)

    program_header_size = u16(data, 0x2A)
    program_header_count = u16(data, 0x2C)

    section_header_size = u16(data, 0x2E)
    section_header_count = u16(data, 0x30)
    section_name_index = u16(data, 0x32)

    segments = []

    for index in range(program_header_count):
        offset = (
            program_header_offset
            + index * program_header_size
        )

        (
            segment_type,
            file_offset,
            virtual_address,
            physical_address,
            file_size,
            memory_size,
            flags,
            alignment,
        ) = struct.unpack_from(
            "<IIIIIIII",
            data,
            offset,
        )

        segments.append(
            {
                "index": index,
                "type": segment_type,
                "offset": file_offset,
                "vaddr": virtual_address,
                "filesz": file_size,
                "memsz": memory_size,
                "flags": flags,
                "align": alignment,
            }
        )

    raw_sections = []

    for index in range(section_header_count):
        offset = (
            section_header_offset
            + index * section_header_size
        )

        fields = struct.unpack_from(
            "<IIIIIIIIII",
            data,
            offset,
        )

        raw_sections.append(
            {
                "index": index,
                "name_offset": fields[0],
                "type": fields[1],
                "flags": fields[2],
                "vaddr": fields[3],
                "offset": fields[4],
                "size": fields[5],
            }
        )

    name_section = raw_sections[
        section_name_index
    ]

    section_name_data = data[
        name_section["offset"]:
        name_section["offset"]
        + name_section["size"]
    ]

    sections = []

    for section in raw_sections:
        section = dict(section)

        section["name"] = read_c_string(
            section_name_data,
            section["name_offset"],
        )

        sections.append(section)

    def offset_to_va(file_offset: int):
        for segment in segments:
            if segment["type"] != 1:
                continue

            start = segment["offset"]
            end = start + segment["filesz"]

            if start <= file_offset < end:
                return (
                    segment["vaddr"]
                    + file_offset
                    - start
                )

        for section in sections:
            start = section["offset"]
            end = start + section["size"]

            if start <= file_offset < end:
                return (
                    section["vaddr"]
                    + file_offset
                    - start
                )

        return None

    def section_at_offset(file_offset: int) -> str:
        for section in sections:
            start = section["offset"]
            end = start + section["size"]

            if start <= file_offset < end:
                return section["name"] or "<unnamed>"

        return "<outside sections>"

    executable_sections = [
        section
        for section in sections
        if (
            section["flags"] & 0x4
            and section["size"] >= 4
            and section["offset"] + section["size"]
            <= len(data)
        )
    ]

    def find_code_references(
        target_address: int,
    ):
        matches = []

        for section in executable_sections:
            instruction_count = (
                section["size"] // 4
            )

            for instruction_index in range(
                instruction_count
            ):
                first_offset = (
                    section["offset"]
                    + instruction_index * 4
                )

                first_word = u32(
                    data,
                    first_offset,
                )

                first_opcode = (
                    first_word >> 26
                ) & 0x3F

                if first_opcode != 0x0F:
                    continue

                base_register = (
                    first_word >> 16
                ) & 0x1F

                high_value = (
                    first_word & 0xFFFF
                )

                # 컴파일러가 LUI와 하위 주소 명령 사이에
                # 몇 개의 독립 명령을 넣을 수 있다.
                for distance in range(1, 13):
                    second_index = (
                        instruction_index
                        + distance
                    )

                    if second_index >= instruction_count:
                        break

                    second_offset = (
                        section["offset"]
                        + second_index * 4
                    )

                    second_word = u32(
                        data,
                        second_offset,
                    )

                    opcode = (
                        second_word >> 26
                    ) & 0x3F

                    source_register = (
                        second_word >> 21
                    ) & 0x1F

                    destination_register = (
                        second_word >> 16
                    ) & 0x1F

                    immediate = (
                        second_word & 0xFFFF
                    )

                    if source_register != base_register:
                        continue

                    if opcode == 0x09:
                        candidate = (
                            (high_value << 16)
                            + sign16(immediate)
                        ) & 0xFFFFFFFF

                        operation = "ADDIU"

                    elif opcode == 0x0D:
                        candidate = (
                            (high_value << 16)
                            | immediate
                        )

                        operation = "ORI"

                    else:
                        continue

                    if candidate != target_address:
                        continue

                    first_address = (
                        section["vaddr"]
                        + instruction_index * 4
                    )

                    second_address = (
                        section["vaddr"]
                        + second_index * 4
                    )

                    matches.append(
                        {
                            "section": section,
                            "first_offset": first_offset,
                            "second_offset": second_offset,
                            "first_address": first_address,
                            "second_address": second_address,
                            "first_word": first_word,
                            "second_word": second_word,
                            "operation": operation,
                            "destination_register":
                                destination_register,
                        }
                    )

        return matches

    def print_code_match(match: dict) -> None:
        print(
            f'    SECTION={match["section"]["name"]} '
            f'FILE=0x{match["first_offset"]:X} '
            f'VA=0x{match["first_address"]:08X} '
            f'DISTANCE='
            f'{(match["second_offset"] - match["first_offset"]) // 4}'
        )

        context_start = max(
            match["section"]["offset"],
            match["first_offset"] - 8,
        )

        context_end = min(
            match["section"]["offset"]
            + match["section"]["size"],
            match["second_offset"] + 12,
        )

        for offset in range(
            context_start,
            context_end,
            4,
        ):
            word = u32(data, offset)

            address = (
                match["section"]["vaddr"]
                + offset
                - match["section"]["offset"]
            )

            marker = (
                ">>"
                if offset in (
                    match["first_offset"],
                    match["second_offset"],
                )
                else "  "
            )

            print(
                f"      {marker} "
                f"0x{address:08X}  "
                f"{word:08X}  "
                f"{decode_instruction(word, address)}"
            )

    print("BOOT.BIN ELF MAP")
    print("================")
    print("FILE SIZE:", f"0x{len(data):X}")

    print()
    print("LOAD SEGMENTS")
    print("=============")

    for segment in segments:
        if segment["type"] != 1:
            continue

        print(
            f'[{segment["index"]}] '
            f'FILE=0x{segment["offset"]:X}'
            f'~0x{segment["offset"] + segment["filesz"]:X} '
            f'VA=0x{segment["vaddr"]:08X}'
            f'~0x{segment["vaddr"] + segment["memsz"]:08X} '
            f'FLAGS=0x{segment["flags"]:X}'
        )

    print()
    print("EXECUTABLE SECTIONS")
    print("===================")

    for section in executable_sections:
        print(
            f'{section["name"]:<16} '
            f'FILE=0x{section["offset"]:X}'
            f'~0x{section["offset"] + section["size"]:X} '
            f'VA=0x{section["vaddr"]:08X}'
            f'~0x{section["vaddr"] + section["size"]:08X}'
        )

    for target_name in TARGET_NAMES:
        print()
        print("=" * 72)
        print("TARGET:", target_name.decode("ascii"))
        print("=" * 72)

        string_offsets = list(
            find_all(
                data,
                target_name + b"\x00",
            )
        )

        if not string_offsets:
            print("STRING NOT FOUND")
            continue

        for string_offset in string_offsets:
            string_address = offset_to_va(
                string_offset
            )

            print(
                f"STRING FILE OFFSET : "
                f"0x{string_offset:X}"
            )

            print(
                f"STRING SECTION     : "
                f"{section_at_offset(string_offset)}"
            )

            if string_address is None:
                print("STRING VA          : UNMAPPED")
                continue

            print(
                f"STRING VA          : "
                f"0x{string_address:08X}"
            )

            direct_refs = find_code_references(
                string_address
            )

            print(
                "DIRECT CODE REFS    :",
                len(direct_refs),
            )

            for match in direct_refs:
                print_code_match(match)

            pointer_bytes = struct.pack(
                "<I",
                string_address,
            )

            pointer_offsets = [
                offset
                for offset in find_all(
                    data,
                    pointer_bytes,
                )
                if offset % 4 == 0
            ]

            print(
                "POINTER LITERALS    :",
                len(pointer_offsets),
            )

            for pointer_offset in pointer_offsets:
                pointer_address = offset_to_va(
                    pointer_offset
                )

                print(
                    f"  FILE=0x{pointer_offset:X} "
                    f"SECTION="
                    f"{section_at_offset(pointer_offset)} "
                    f"VA="
                    f"{'UNMAPPED' if pointer_address is None else f'0x{pointer_address:08X}'}"
                )

                if pointer_address is None:
                    continue

                pointer_refs = find_code_references(
                    pointer_address
                )

                print(
                    "  CODE REFS TO POINTER:",
                    len(pointer_refs),
                )

                for match in pointer_refs:
                    print_code_match(match)

    print()
    print("DONE")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
