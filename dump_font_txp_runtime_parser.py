#!/usr/bin/env python3

import struct
from pathlib import Path

import dump_boot_font_functions as mips


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/font_txp_runtime_parser.txt"
)

# font.txp 포인터가 들어 있는 폰트 객체 주소를 받아
# 내부 필드를 초기화하는 함수
START_ADDRESS = 0x08814B6C
END_ADDRESS = 0x08814E6C

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

MEMORY_NAMES = {
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

IMPORTANT_FIELDS = {
    0x00: "raw font.txp resource pointer",
    0x04: "font texture field +0x04",
    0x08: "font texture field +0x08",
    0x0C: "runtime glyph-data pointer",
    0x10: "font texture field +0x10",
    0x80: "font.fnt entry count",
    0x84: "font.fnt table pointer",
    0x88: "font.fnt resource pointer",
    0x8C: "allocated work buffer A",
    0x90: "allocated work buffer B",
    0x94: "runtime state",
}


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def register_name(index: int) -> str:
    return "$" + REGISTER_NAMES[index]


def branch_target(
    address: int,
    immediate: int,
) -> int:
    return (
        address
        + 4
        + mips.signed16(immediate) * 4
    ) & 0xFFFFFFFF


def decode_extended(
    word: int,
    address: int,
) -> str:
    opcode = (word >> 26) & 0x3F
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    immediate = word & 0xFFFF

    likely_names = {
        0x14: "beql",
        0x15: "bnel",
        0x16: "blezl",
        0x17: "bgtzl",
    }

    if opcode in likely_names:
        name = likely_names[opcode]
        target = branch_target(
            address,
            immediate,
        )

        if opcode in (0x14, 0x15):
            return (
                f"{name} "
                f"{register_name(rs)}, "
                f"{register_name(rt)}, "
                f"0x{target:08X}"
            )

        return (
            f"{name} "
            f"{register_name(rs)}, "
            f"0x{target:08X}"
        )

    return mips.decode_instruction(
        word,
        address,
    )


def describe_instruction(
    word: int,
    address: int,
) -> list[str]:
    notes = []

    opcode = (word >> 26) & 0x3F
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    immediate = mips.signed16(
        word & 0xFFFF
    )

    if opcode in MEMORY_NAMES:
        operation = MEMORY_NAMES[opcode]

        if immediate in IMPORTANT_FIELDS:
            notes.append(
                f"{operation} "
                f"{register_name(rt)}, "
                f"+0x{immediate:X}"
                f"({register_name(rs)}) "
                f"[{IMPORTANT_FIELDS[immediate]}]"
            )

    if opcode == 0x03:
        target = mips.jump_target(
            address,
            word,
        )

        notes.append(
            f"CALL 0x{target:08X}"
        )

    # 140바이트 글리프 크기와 관련된 상수
    constants = {
        0x000A: "10 bytes per glyph row",
        0x000E: "14 glyph rows",
        0x0014: "20 pixel width",
        0x008C: "140-byte glyph",
        0x00A0: "160-byte raw record candidate",
    }

    unsigned_immediate = word & 0xFFFF

    if unsigned_immediate in constants:
        notes.append(
            f"CONSTANT 0x{unsigned_immediate:X}: "
            f"{constants[unsigned_immediate]}"
        )

    return notes


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
            "시작 주소를 포함하는 섹션이 없습니다."
        )

    lines = []

    lines.append(
        "FONT.TXP RUNTIME PARSER"
    )
    lines.append(
        "======================="
    )
    lines.append(
        f"RANGE : "
        f"0x{START_ADDRESS:08X}"
        f"~0x{END_ADDRESS:08X}"
    )
    lines.append(
        "INPUT : $a0 = font runtime object "
        "(0x08A54188)"
    )
    lines.append(
        "FOCUS : object +0x0C runtime glyph-data pointer"
    )
    lines.append("")

    call_targets = []
    field_accesses = []

    for address in range(
        START_ADDRESS,
        END_ADDRESS,
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

        decoded = decode_extended(
            word,
            address,
        )

        notes = describe_instruction(
            word,
            address,
        )

        opcode = (word >> 26) & 0x3F

        if opcode == 0x03:
            call_targets.append(
                mips.jump_target(
                    address,
                    word,
                )
            )

        immediate = mips.signed16(
            word & 0xFFFF
        )

        if (
            opcode in MEMORY_NAMES
            and immediate in IMPORTANT_FIELDS
        ):
            field_accesses.append(
                (
                    address,
                    immediate,
                    MEMORY_NAMES[opcode],
                )
            )

        marker = (
            ">>"
            if notes
            else "  "
        )

        line = (
            f"{marker} "
            f"0x{address:08X}  "
            f"FILE=0x{offset:X}  "
            f"{word:08X}  "
            f"{decoded}"
        )

        if notes:
            line += (
                "    <<< "
                + " | ".join(notes)
            )

        lines.append(line)

    lines.append("")
    lines.append("SUMMARY")
    lines.append("=======")

    lines.append("IMPORTANT FIELD ACCESSES:")

    if field_accesses:
        for address, field, operation in field_accesses:
            lines.append(
                f"  0x{address:08X} "
                f"{operation} "
                f"+0x{field:X} "
                f"[{IMPORTANT_FIELDS[field]}]"
            )
    else:
        lines.append("  NONE")

    lines.append("")

    lines.append("CALL TARGETS:")

    if call_targets:
        for target in sorted(
            set(call_targets)
        ):
            lines.append(
                f"  0x{target:08X}"
            )
    else:
        lines.append("  NONE")

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
