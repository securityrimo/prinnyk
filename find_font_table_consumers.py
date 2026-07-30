#!/usr/bin/env python3

import struct
from pathlib import Path

import dump_boot_font_functions as mips


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/font_table_consumers.txt"
)

# 폰트 런타임 객체 필드
FIELD_COUNT = 0x80
FIELD_TABLE = 0x84
FIELD_RESOURCE = 0x88

# 이미 확인한 초기화 함수
INIT_START = 0x08898C90
INIT_END = 0x08898DFC

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
    0x23: "lw",
    0x24: "lbu",
    0x25: "lhu",
    0x28: "sb",
    0x29: "sh",
    0x2B: "sw",
}


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def register_name(index: int) -> str:
    return "$" + REGISTER_NAMES[index]


def instruction_fields(word: int) -> dict:
    return {
        "opcode": (word >> 26) & 0x3F,
        "rs": (word >> 21) & 0x1F,
        "rt": (word >> 16) & 0x1F,
        "rd": (word >> 11) & 0x1F,
        "shift": (word >> 6) & 0x1F,
        "funct": word & 0x3F,
        "immediate": mips.signed16(
            word & 0xFFFF
        ),
    }


def find_table_pointer_reads(
    data: bytes,
    sections: list[dict],
) -> list[dict]:
    results = []

    for section in sections:
        if not (section["flags"] & 0x4):
            continue

        if (
            section["offset"] + section["size"]
            > len(data)
        ):
            continue

        for relative in range(
            0,
            section["size"] - 3,
            4,
        ):
            offset = section["offset"] + relative
            address = section["vaddr"] + relative
            word = u32(data, offset)
            fields = instruction_fields(word)

            # lw destination, +0x84(base)
            if (
                fields["opcode"] == 0x23
                and fields["immediate"]
                == FIELD_TABLE
            ):
                results.append(
                    {
                        "section": section,
                        "address": address,
                        "offset": offset,
                        "base": fields["rs"],
                        "destination": fields["rt"],
                    }
                )

    return results


def inspect_nearby(
    data: bytes,
    sections: list[dict],
    hit: dict,
    before: int = 20,
    after: int = 36,
) -> tuple[list[str], dict]:
    section = hit["section"]
    center = hit["address"]

    start = max(
        section["vaddr"],
        center - before * 4,
    )

    end = min(
        section["vaddr"] + section["size"],
        center + (after + 1) * 4,
    )

    lines = []

    summary = {
        "count_field_reads": 0,
        "resource_field_reads": 0,
        "table_value_reads": 0,
        "shift_by_one": 0,
        "multiply_by_two": 0,
        "calls": [],
    }

    table_register = hit["destination"]

    for address in range(start, end, 4):
        offset = mips.va_to_offset(
            sections,
            address,
        )

        word = u32(data, offset)
        fields = instruction_fields(word)

        decoded = mips.decode_instruction(
            word,
            address,
        )

        marker = "  "
        notes = []

        if address == center:
            marker = ">>"
            notes.append(
                "FONT TABLE POINTER LOAD"
            )

        opcode = fields["opcode"]
        immediate = fields["immediate"]

        if opcode in MEMORY_NAMES:
            if immediate == FIELD_COUNT:
                summary["count_field_reads"] += 1
                notes.append(
                    "FONT COUNT FIELD"
                )

            if immediate == FIELD_RESOURCE:
                summary[
                    "resource_field_reads"
                ] += 1
                notes.append(
                    "FONT RESOURCE FIELD"
                )

            # +0x84에서 가져온 레지스터를
            # 바로 16비트 배열처럼 읽는 경우
            if (
                opcode in (0x21, 0x25)
                and fields["rs"]
                == table_register
            ):
                summary[
                    "table_value_reads"
                ] += 1

                notes.append(
                    "DIRECT 16-BIT TABLE READ"
                )

        # sll rd, rt, 1
        if (
            opcode == 0x00
            and fields["funct"] == 0x00
            and fields["shift"] == 1
        ):
            summary["shift_by_one"] += 1
            notes.append(
                "INDEX × 2"
            )

        # addiu reg, reg, 2는 포인터 순회 후보
        if (
            opcode == 0x09
            and immediate == 2
        ):
            summary[
                "multiply_by_two"
            ] += 1
            notes.append(
                "+2 BYTE STEP"
            )

        if opcode == 0x03:
            target = mips.jump_target(
                address,
                word,
            )

            summary["calls"].append(target)
            notes.append(
                f"CALL 0x{target:08X}"
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
                + ", ".join(notes)
            )

        lines.append(line)

    return lines, summary


def main() -> int:
    data = BOOT_PATH.read_bytes()

    if data[:4] != b"\x7FELF":
        raise ValueError(
            "BOOT.BIN이 ELF가 아닙니다."
        )

    sections = mips.parse_sections(data)

    hits = find_table_pointer_reads(
        data,
        sections,
    )

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_lines = []

    output_lines.append(
        "FONT TABLE CONSUMER SEARCH"
    )
    output_lines.append(
        "=========================="
    )
    output_lines.append(
        f"FIELD COUNT    : +0x{FIELD_COUNT:X}"
    )
    output_lines.append(
        f"FIELD TABLE    : +0x{FIELD_TABLE:X}"
    )
    output_lines.append(
        f"FIELD RESOURCE : +0x{FIELD_RESOURCE:X}"
    )
    output_lines.append(
        f"TOTAL +0x84 LW : {len(hits)}"
    )

    runtime_hits = [
        hit
        for hit in hits
        if not (
            INIT_START
            <= hit["address"]
            < INIT_END
        )
    ]

    output_lines.append(
        f"OUTSIDE INIT   : {len(runtime_hits)}"
    )

    for index, hit in enumerate(
        hits,
        start=1,
    ):
        inside_init = (
            INIT_START
            <= hit["address"]
            < INIT_END
        )

        context, summary = inspect_nearby(
            data,
            sections,
            hit,
        )

        output_lines.append("")
        output_lines.append("=" * 96)
        output_lines.append(
            f"[{index}] "
            f"0x{hit['address']:08X} "
            f"SECTION={hit['section']['name']} "
            f"BASE={register_name(hit['base'])} "
            f"TABLE={register_name(hit['destination'])} "
            f"TYPE={'INITIALIZER' if inside_init else 'RUNTIME CANDIDATE'}"
        )
        output_lines.append("=" * 96)

        output_lines.extend(context)

        output_lines.append("")
        output_lines.append("LOCAL SUMMARY")
        output_lines.append(
            f"  +0x80 accesses       : "
            f"{summary['count_field_reads']}"
        )
        output_lines.append(
            f"  +0x88 accesses       : "
            f"{summary['resource_field_reads']}"
        )
        output_lines.append(
            f"  table-register lhu/lh: "
            f"{summary['table_value_reads']}"
        )
        output_lines.append(
            f"  index ×2 instructions: "
            f"{summary['shift_by_one']}"
        )
        output_lines.append(
            f"  +2 byte steps        : "
            f"{summary['multiply_by_two']}"
        )

        call_targets = sorted(
            set(summary["calls"])
        )

        output_lines.append(
            "  calls                : "
            + (
                ", ".join(
                    f"0x{target:08X}"
                    for target in call_targets
                )
                if call_targets
                else "NONE"
            )
        )

    output = "\n".join(output_lines) + "\n"

    REPORT_PATH.write_text(
        output,
        encoding="utf-8",
    )

    print(output, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
