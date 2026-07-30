#!/usr/bin/env python3

import struct
from pathlib import Path

import dump_boot_font_functions as mips


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/font_runtime_init.txt"
)

# font.txp 전역 주소를 인수로 받는 함수
START_ADDRESS = 0x08898C90

# 다음에 확인된 관련 함수 시작 주소
END_ADDRESS = 0x08898DFC

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

MEMORY_OPCODES = {
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


def read_u32(
    data: bytes,
    offset: int,
) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def register_name(index: int) -> str:
    return "$" + REGISTER_NAMES[index]


def describe_access(word: int) -> str:
    opcode = (word >> 26) & 0x3F

    if opcode not in MEMORY_OPCODES:
        return ""

    base_register = (
        word >> 21
    ) & 0x1F

    target_register = (
        word >> 16
    ) & 0x1F

    immediate = mips.signed16(
        word & 0xFFFF
    )

    description = (
        f"{MEMORY_OPCODES[opcode]} "
        f"{register_name(target_register)}, "
        f"{immediate:+#x}"
        f"({register_name(base_register)})"
    )

    if immediate == 0x88:
        description += (
            "  <<< FONT.FNT POINTER CANDIDATE"
        )

    return description


def main() -> int:
    data = BOOT_PATH.read_bytes()

    if data[:4] != b"\x7FELF":
        raise ValueError(
            "BOOT.BIN이 ELF 파일이 아닙니다."
        )

    sections = mips.parse_sections(data)

    start_section = mips.section_for_va(
        sections,
        START_ADDRESS,
    )

    end_section = mips.section_for_va(
        sections,
        END_ADDRESS - 4,
    )

    if (
        start_section is None
        or end_section is None
        or start_section != end_section
    ):
        raise ValueError(
            "지정한 함수 범위가 동일 섹션에 없습니다."
        )

    lines = []

    lines.append("FONT RUNTIME INITIALIZER")
    lines.append("========================")
    lines.append(
        f"RANGE  : "
        f"0x{START_ADDRESS:08X}"
        f"~0x{END_ADDRESS:08X}"
    )
    lines.append(
        f"SIZE   : "
        f"0x{END_ADDRESS - START_ADDRESS:X}"
    )
    lines.append(
        "INPUT  : "
        "$a0 = &global_font_txp "
        "(0x08A54188)"
    )
    lines.append(
        "TARGET : "
        "global_font_fnt is "
        "+0x88 from that address"
    )
    lines.append("")

    access_88_count = 0
    call_targets = []

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

        decoded = mips.decode_instruction(
            word,
            address,
        )

        annotation = describe_access(word)

        if "+0x88(" in annotation:
            access_88_count += 1

        opcode = (word >> 26) & 0x3F

        if opcode == 0x03:
            call_target = mips.jump_target(
                address,
                word,
            )

            call_targets.append(call_target)

            annotation += (
                f"  <<< CALL "
                f"0x{call_target:08X}"
            )

        line = (
            f"0x{address:08X}  "
            f"FILE=0x{offset:X}  "
            f"{word:08X}  "
            f"{decoded}"
        )

        if annotation:
            line += f"    [{annotation}]"

        lines.append(line)

    lines.append("")
    lines.append("SUMMARY")
    lines.append("=======")
    lines.append(
        f"+0x88 MEMORY ACCESS COUNT: "
        f"{access_88_count}"
    )

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
