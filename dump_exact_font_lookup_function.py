#!/usr/bin/env python3

import struct
from pathlib import Path

import dump_boot_font_functions as mips


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/exact_font_lookup_function.txt"
)

# 실제 font.fnt 조회가 있는 첫 번째 함수 주변
START_ADDRESS = 0x08899700
END_ADDRESS = 0x08899A50

IMPORTANT = {
    0x08899980: "첫 번째 인덱스 계산 분기",
    0x08899988: "대체 인덱스 계산",
    0x0889998C: "값 × 3",
    0x08899990: "값 × 192",
    0x08899994: "다른 입력값 - 0x40",
    0x08899998: "인덱스에 0x5F 추가",
    0x0889999C: "최종 테이블 인덱스 계산",
    0x088999A0: "테이블 바이트 오프셋 = 인덱스 × 2",
    0x088999BC: "font.fnt 테이블 포인터 로드",
    0x088999C0: "테이블 포인터 + 바이트 오프셋",
    0x088999DC: "최종 글리프 인덱스 읽기",
}


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


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

    branch_likely_names = {
        0x14: "beql",
        0x15: "bnel",
        0x16: "blezl",
        0x17: "bgtzl",
    }

    if opcode in branch_likely_names:
        name = branch_likely_names[opcode]
        target = branch_target(
            address,
            immediate,
        )

        if opcode in (0x14, 0x15):
            return (
                f"{name} "
                f"${registers[rs]}, "
                f"${registers[rt]}, "
                f"0x{target:08X}"
            )

        return (
            f"{name} "
            f"${registers[rs]}, "
            f"0x{target:08X}"
        )

    return mips.decode_instruction(
        word,
        address,
    )


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
            "시작 주소가 ELF 섹션에 없습니다."
        )

    lines = []

    lines.append("EXACT FONT LOOKUP FUNCTION")
    lines.append("==========================")
    lines.append(
        f"RANGE: "
        f"0x{START_ADDRESS:08X}"
        f"~0x{END_ADDRESS:08X}"
    )
    lines.append(
        "TARGET LOOKUP: "
        "0x088999BC~0x088999DC"
    )
    lines.append("")

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

        note = IMPORTANT.get(address)

        marker = ">>" if note else "  "

        line = (
            f"{marker} "
            f"0x{address:08X}  "
            f"FILE=0x{offset:X}  "
            f"{word:08X}  "
            f"{decoded}"
        )

        if note:
            line += f"    <<< {note}"

        lines.append(line)

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
