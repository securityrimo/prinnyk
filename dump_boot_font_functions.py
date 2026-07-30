#!/usr/bin/env python3

import struct
from pathlib import Path


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

TARGETS = [
    ("font.fnt loader caller", 0x0888AF84),
    ("font.txp loader caller", 0x0888AFE4),
    ("jis2ucs loader caller",  0x0888B88C),
    ("ucs2jis loader caller",  0x0888B8E4),
    ("shared resource loader", 0x08811974),
]

REGISTER_NAMES = [
    "zero", "at", "v0", "v1",
    "a0", "a1", "a2", "a3",
    "t0", "t1", "t2", "t3",
    "t4", "t5", "t6", "t7",
    "s0", "s1", "s2", "s3",
    "s4", "s5", "s6", "s7",
    "t8", "t9", "k0", "k1",
    "gp", "sp", "fp", "ra",
]


def read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<H",
        data,
        offset,
    )[0]


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def signed16(value: int) -> int:
    if value & 0x8000:
        return value - 0x10000

    return value


def parse_sections(data: bytes) -> list[dict]:
    section_header_offset = read_u32(data, 0x20)
    section_header_size = read_u16(data, 0x2E)
    section_count = read_u16(data, 0x30)
    name_section_index = read_u16(data, 0x32)

    raw_sections = []

    for index in range(section_count):
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

    names_section = raw_sections[
        name_section_index
    ]

    names = data[
        names_section["offset"]:
        names_section["offset"]
        + names_section["size"]
    ]

    for section in raw_sections:
        name_offset = section["name_offset"]
        name_end = names.find(
            b"\x00",
            name_offset,
        )

        if name_end < 0:
            name_end = len(names)

        section["name"] = names[
            name_offset:name_end
        ].decode(
            "ascii",
            errors="replace",
        )

    return raw_sections


def section_for_va(
    sections: list[dict],
    address: int,
) -> dict | None:
    for section in sections:
        start = section["vaddr"]
        end = start + section["size"]

        if start <= address < end:
            return section

    return None


def va_to_offset(
    sections: list[dict],
    address: int,
) -> int:
    section = section_for_va(
        sections,
        address,
    )

    if section is None:
        raise ValueError(
            f"주소가 ELF 섹션에 없습니다: "
            f"0x{address:08X}"
        )

    return (
        section["offset"]
        + address
        - section["vaddr"]
    )


def register(index: int) -> str:
    return "$" + REGISTER_NAMES[index]


def branch_target(
    address: int,
    immediate: int,
) -> int:
    return (
        address
        + 4
        + signed16(immediate) * 4
    ) & 0xFFFFFFFF


def jump_target(
    address: int,
    word: int,
) -> int:
    return (
        ((address + 4) & 0xF0000000)
        | ((word & 0x03FFFFFF) << 2)
    )


def decode_instruction(
    word: int,
    address: int,
) -> str:
    opcode = (word >> 26) & 0x3F
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    rd = (word >> 11) & 0x1F
    shift = (word >> 6) & 0x1F
    funct = word & 0x3F
    immediate = word & 0xFFFF

    if word == 0:
        return "nop"

    if opcode == 0x00:
        if funct == 0x00:
            return (
                f"sll {register(rd)}, "
                f"{register(rt)}, {shift}"
            )

        if funct == 0x02:
            return (
                f"srl {register(rd)}, "
                f"{register(rt)}, {shift}"
            )

        if funct == 0x03:
            return (
                f"sra {register(rd)}, "
                f"{register(rt)}, {shift}"
            )

        if funct == 0x04:
            return (
                f"sllv {register(rd)}, "
                f"{register(rt)}, {register(rs)}"
            )

        if funct == 0x06:
            return (
                f"srlv {register(rd)}, "
                f"{register(rt)}, {register(rs)}"
            )

        if funct == 0x07:
            return (
                f"srav {register(rd)}, "
                f"{register(rt)}, {register(rs)}"
            )

        if funct == 0x08:
            return f"jr {register(rs)}"

        if funct == 0x09:
            return (
                f"jalr {register(rd)}, "
                f"{register(rs)}"
            )

        if funct == 0x10:
            return f"mfhi {register(rd)}"

        if funct == 0x12:
            return f"mflo {register(rd)}"

        if funct == 0x18:
            return (
                f"mult {register(rs)}, "
                f"{register(rt)}"
            )

        if funct == 0x19:
            return (
                f"multu {register(rs)}, "
                f"{register(rt)}"
            )

        if funct == 0x1A:
            return (
                f"div {register(rs)}, "
                f"{register(rt)}"
            )

        if funct == 0x1B:
            return (
                f"divu {register(rs)}, "
                f"{register(rt)}"
            )

        if funct == 0x21:
            if rt == 0:
                return (
                    f"move {register(rd)}, "
                    f"{register(rs)}"
                )

            if rs == 0:
                return (
                    f"move {register(rd)}, "
                    f"{register(rt)}"
                )

            return (
                f"addu {register(rd)}, "
                f"{register(rs)}, {register(rt)}"
            )

        if funct == 0x23:
            return (
                f"subu {register(rd)}, "
                f"{register(rs)}, {register(rt)}"
            )

        if funct == 0x24:
            return (
                f"and {register(rd)}, "
                f"{register(rs)}, {register(rt)}"
            )

        if funct == 0x25:
            return (
                f"or {register(rd)}, "
                f"{register(rs)}, {register(rt)}"
            )

        if funct == 0x26:
            return (
                f"xor {register(rd)}, "
                f"{register(rs)}, {register(rt)}"
            )

        if funct == 0x27:
            return (
                f"nor {register(rd)}, "
                f"{register(rs)}, {register(rt)}"
            )

        if funct == 0x2A:
            return (
                f"slt {register(rd)}, "
                f"{register(rs)}, {register(rt)}"
            )

        if funct == 0x2B:
            return (
                f"sltu {register(rd)}, "
                f"{register(rs)}, {register(rt)}"
            )

    if opcode == 0x01:
        target = branch_target(
            address,
            immediate,
        )

        names = {
            0x00: "bltz",
            0x01: "bgez",
            0x10: "bltzal",
            0x11: "bgezal",
        }

        name = names.get(rt)

        if name:
            return (
                f"{name} {register(rs)}, "
                f"0x{target:08X}"
            )

    if opcode == 0x02:
        return (
            f"j 0x"
            f"{jump_target(address, word):08X}"
        )

    if opcode == 0x03:
        return (
            f"jal 0x"
            f"{jump_target(address, word):08X}"
        )

    if opcode == 0x04:
        target = branch_target(
            address,
            immediate,
        )

        if rs == rt:
            return f"b 0x{target:08X}"

        return (
            f"beq {register(rs)}, "
            f"{register(rt)}, 0x{target:08X}"
        )

    if opcode == 0x05:
        return (
            f"bne {register(rs)}, "
            f"{register(rt)}, "
            f"0x{branch_target(address, immediate):08X}"
        )

    if opcode == 0x06:
        return (
            f"blez {register(rs)}, "
            f"0x{branch_target(address, immediate):08X}"
        )

    if opcode == 0x07:
        return (
            f"bgtz {register(rs)}, "
            f"0x{branch_target(address, immediate):08X}"
        )

    if opcode in (0x08, 0x09):
        name = (
            "addi"
            if opcode == 0x08
            else "addiu"
        )

        value = signed16(immediate)

        if rs == 0:
            return (
                f"li {register(rt)}, "
                f"{value}"
            )

        return (
            f"{name} {register(rt)}, "
            f"{register(rs)}, {value}"
        )

    if opcode == 0x0A:
        return (
            f"slti {register(rt)}, "
            f"{register(rs)}, "
            f"{signed16(immediate)}"
        )

    if opcode == 0x0B:
        return (
            f"sltiu {register(rt)}, "
            f"{register(rs)}, "
            f"{signed16(immediate)}"
        )

    if opcode == 0x0C:
        return (
            f"andi {register(rt)}, "
            f"{register(rs)}, "
            f"0x{immediate:04X}"
        )

    if opcode == 0x0D:
        if rs == 0:
            return (
                f"li {register(rt)}, "
                f"0x{immediate:04X}"
            )

        return (
            f"ori {register(rt)}, "
            f"{register(rs)}, "
            f"0x{immediate:04X}"
        )

    if opcode == 0x0E:
        return (
            f"xori {register(rt)}, "
            f"{register(rs)}, "
            f"0x{immediate:04X}"
        )

    if opcode == 0x0F:
        return (
            f"lui {register(rt)}, "
            f"0x{immediate:04X}"
        )

    memory_operations = {
        0x20: "lb",
        0x21: "lh",
        0x22: "lwl",
        0x23: "lw",
        0x24: "lbu",
        0x25: "lhu",
        0x26: "lwr",
        0x28: "sb",
        0x29: "sh",
        0x2A: "swl",
        0x2B: "sw",
        0x2E: "swr",
    }

    if opcode in memory_operations:
        return (
            f"{memory_operations[opcode]} "
            f"{register(rt)}, "
            f"{signed16(immediate)}"
            f"({register(rs)})"
        )

    return f".word 0x{word:08X}"


def is_stack_prologue(word: int) -> bool:
    opcode = (word >> 26) & 0x3F
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    immediate = word & 0xFFFF

    return (
        opcode == 0x09
        and rs == 29
        and rt == 29
        and signed16(immediate) < 0
    )


def is_return(word: int) -> bool:
    return word == 0x03E00008


def find_function_start(
    data: bytes,
    sections: list[dict],
    target_address: int,
) -> int:
    section = section_for_va(
        sections,
        target_address,
    )

    if section is None:
        raise ValueError(
            f"섹션을 찾지 못했습니다: "
            f"0x{target_address:08X}"
        )

    minimum = max(
        section["vaddr"],
        target_address - 0x600,
    )

    address = target_address & ~3

    while address >= minimum:
        offset = va_to_offset(
            sections,
            address,
        )

        word = read_u32(data, offset)

        if is_stack_prologue(word):
            return address

        address -= 4

    return max(
        section["vaddr"],
        target_address - 0x80,
    )


def find_function_end(
    data: bytes,
    sections: list[dict],
    start_address: int,
) -> int:
    section = section_for_va(
        sections,
        start_address,
    )

    maximum = min(
        section["vaddr"] + section["size"],
        start_address + 0x1000,
    )

    address = start_address

    while address + 4 < maximum:
        offset = va_to_offset(
            sections,
            address,
        )

        word = read_u32(data, offset)

        if is_return(word):
            # jr $ra의 지연 슬롯까지 포함
            return address + 8

        address += 4

    return min(
        maximum,
        start_address + 0x200,
    )


def print_function(
    data: bytes,
    sections: list[dict],
    label: str,
    target_address: int,
) -> None:
    start = find_function_start(
        data,
        sections,
        target_address,
    )

    end = find_function_end(
        data,
        sections,
        start,
    )

    section = section_for_va(
        sections,
        target_address,
    )

    print()
    print("=" * 88)
    print(label)
    print("=" * 88)
    print(
        "TARGET :",
        f"0x{target_address:08X}",
    )
    print(
        "SECTION:",
        section["name"],
    )
    print(
        "RANGE  :",
        f"0x{start:08X}~0x{end:08X}",
    )
    print(
        "SIZE   :",
        f"0x{end - start:X}",
    )
    print()

    call_targets = []

    for address in range(start, end, 4):
        offset = va_to_offset(
            sections,
            address,
        )

        word = read_u32(
            data,
            offset,
        )

        decoded = decode_instruction(
            word,
            address,
        )

        marker = (
            ">>"
            if address == target_address
            else "  "
        )

        print(
            f"{marker} "
            f"0x{address:08X}  "
            f"{word:08X}  "
            f"{decoded}"
        )

        opcode = (word >> 26) & 0x3F

        if opcode == 0x03:
            call_targets.append(
                jump_target(address, word)
            )

    print()
    print("CALL TARGETS:")

    if not call_targets:
        print("  NONE")
    else:
        for call_target in sorted(
            set(call_targets)
        ):
            print(
                f"  0x{call_target:08X}"
            )


def main() -> int:
    data = BOOT_PATH.read_bytes()

    if data[:4] != b"\x7FELF":
        raise ValueError(
            "BOOT.BIN이 ELF가 아닙니다."
        )

    sections = parse_sections(data)

    for label, address in TARGETS:
        print_function(
            data,
            sections,
            label,
            address,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
