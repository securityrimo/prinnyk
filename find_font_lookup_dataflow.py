#!/usr/bin/env python3

import struct
from pathlib import Path

import dump_boot_font_functions as mips


BOOT_PATH = Path(
    "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
)

REPORT_PATH = Path(
    "workspace/reports/font_lookup_dataflow.txt"
)

TABLE_FIELD = 0x84
COUNT_FIELD = 0x80
RESOURCE_FIELD = 0x88

WINDOW_SIZE = 96

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

ZERO = 0
SP = 29


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


def fields(word: int) -> dict:
    return {
        "opcode": (word >> 26) & 0x3F,
        "rs": (word >> 21) & 0x1F,
        "rt": (word >> 16) & 0x1F,
        "rd": (word >> 11) & 0x1F,
        "shift": (word >> 6) & 0x1F,
        "funct": word & 0x3F,
        "immediate_unsigned": word & 0xFFFF,
        "immediate": mips.signed16(
            word & 0xFFFF
        ),
    }


def destination_register(
    word: int,
) -> int | None:
    item = fields(word)

    opcode = item["opcode"]
    funct = item["funct"]

    # R형 산술 명령
    if opcode == 0x00:
        if funct in {
            0x00,  # sll
            0x02,  # srl
            0x03,  # sra
            0x04,  # sllv
            0x06,  # srlv
            0x07,  # srav
            0x0A,  # movz
            0x0B,  # movn
            0x10,  # mfhi
            0x12,  # mflo
            0x20,  # add
            0x21,  # addu
            0x22,  # sub
            0x23,  # subu
            0x24,  # and
            0x25,  # or
            0x26,  # xor
            0x27,  # nor
            0x2A,  # slt
            0x2B,  # sltu
        }:
            return item["rd"]

        return None

    # 즉시값 산술
    if opcode in {
        0x08,  # addi
        0x09,  # addiu
        0x0A,  # slti
        0x0B,  # sltiu
        0x0C,  # andi
        0x0D,  # ori
        0x0E,  # xori
        0x0F,  # lui
    }:
        return item["rt"]

    # 메모리 읽기
    if opcode in {
        0x20,  # lb
        0x21,  # lh
        0x22,  # lwl
        0x23,  # lw
        0x24,  # lbu
        0x25,  # lhu
        0x26,  # lwr
    }:
        return item["rt"]

    return None


def is_return(word: int) -> bool:
    return word == 0x03E00008


def is_unconditional_jump(word: int) -> bool:
    return (
        ((word >> 26) & 0x3F) == 0x02
    )


def copy_tag(tag: dict | None):
    if tag is None:
        return None

    return dict(tag)


def format_tag(tag: dict | None) -> str:
    if tag is None:
        return "NONE"

    kind = tag.get("kind", "?")

    if kind == "table":
        return (
            "FONT_TABLE "
            f"loaded@0x{tag['origin']:08X} "
            f"object={register_name(tag['object_register'])}"
        )

    if kind == "index2":
        return (
            "INDEX_X2 "
            f"source={register_name(tag['source_register'])} "
            f"created@0x{tag['origin']:08X}"
        )

    if kind == "address":
        return (
            "TABLE_ADDRESS "
            f"table@0x{tag['table_origin']:08X} "
            f"index={register_name(tag['index_register'])} "
            f"created@0x{tag['origin']:08X}"
        )

    return repr(tag)


def scan_from_table_load(
    data: bytes,
    sections: list[dict],
    section: dict,
    start_index: int,
    instructions: list[tuple[int, int, int]],
) -> list[dict]:
    start_address, _, start_word = instructions[
        start_index
    ]

    start_fields = fields(start_word)

    table_register = start_fields["rt"]
    object_register = start_fields["rs"]

    tags: list[dict | None] = [
        None
        for _ in range(32)
    ]

    tags[table_register] = {
        "kind": "table",
        "origin": start_address,
        "object_register": object_register,
    }

    matches = []

    maximum_index = min(
        len(instructions),
        start_index + WINDOW_SIZE,
    )

    for index in range(
        start_index + 1,
        maximum_index,
    ):
        address, file_offset, word = (
            instructions[index]
        )

        item = fields(word)

        opcode = item["opcode"]
        funct = item["funct"]
        rs = item["rs"]
        rt = item["rt"]
        rd = item["rd"]
        shift = item["shift"]
        immediate = item["immediate"]

        source_tags = {
            rs: copy_tag(tags[rs]),
            rt: copy_tag(tags[rt]),
        }

        destination = destination_register(
            word
        )

        if (
            destination is not None
            and destination != ZERO
        ):
            tags[destination] = None

        # move rd, rs
        # 실제 인코딩은 addu/or와 $zero 조합
        if opcode == 0x00 and funct in {
            0x21,
            0x25,
        }:
            if rt == ZERO and rd != ZERO:
                tags[rd] = copy_tag(
                    source_tags.get(rs)
                )

            elif rs == ZERO and rd != ZERO:
                tags[rd] = copy_tag(
                    source_tags.get(rt)
                )

        # addiu rt, rs, 0 역시 move처럼 처리
        elif (
            opcode == 0x09
            and immediate == 0
            and rt != ZERO
        ):
            tags[rt] = copy_tag(
                source_tags.get(rs)
            )

        # sll offset, character_code, 1
        elif (
            opcode == 0x00
            and funct == 0x00
            and shift == 1
            and rd != ZERO
        ):
            tags[rd] = {
                "kind": "index2",
                "origin": address,
                "source_register": rt,
            }

        # addu address, table, index_x2
        elif (
            opcode == 0x00
            and funct == 0x21
            and rd != ZERO
        ):
            left = source_tags.get(rs)
            right = source_tags.get(rt)

            table_tag = None
            index_tag = None

            if (
                left is not None
                and left.get("kind") == "table"
                and right is not None
                and right.get("kind") == "index2"
            ):
                table_tag = left
                index_tag = right

            elif (
                right is not None
                and right.get("kind") == "table"
                and left is not None
                and left.get("kind") == "index2"
            ):
                table_tag = right
                index_tag = left

            if (
                table_tag is not None
                and index_tag is not None
            ):
                tags[rd] = {
                    "kind": "address",
                    "origin": address,
                    "table_origin": table_tag[
                        "origin"
                    ],
                    "object_register": table_tag[
                        "object_register"
                    ],
                    "index_origin": index_tag[
                        "origin"
                    ],
                    "index_register": index_tag[
                        "source_register"
                    ],
                }

        # lhu/lh glyph, 0(table_address)
        if (
            opcode in {0x21, 0x25}
            and immediate == 0
        ):
            base_tag = source_tags.get(rs)

            if (
                base_tag is not None
                and base_tag.get("kind")
                == "address"
            ):
                matches.append(
                    {
                        "section": section,
                        "table_load_address":
                            start_address,
                        "table_register":
                            table_register,
                        "object_register":
                            object_register,
                        "index_shift_address":
                            base_tag[
                                "index_origin"
                            ],
                        "index_register":
                            base_tag[
                                "index_register"
                            ],
                        "address_build_address":
                            base_tag["origin"],
                        "lookup_address":
                            address,
                        "lookup_offset":
                            file_offset,
                        "glyph_register":
                            rt,
                        "lookup_operation":
                            "lhu"
                            if opcode == 0x25
                            else "lh",
                    }
                )

        # 함수 반환 뒤에는 이 선형 경로를 종료
        if is_return(word):
            break

        # 무조건 점프는 지연 슬롯까지만 보고 종료
        if is_unconditional_jump(word):
            if index + 1 < maximum_index:
                continue

            break

    return matches


def build_instruction_list(
    data: bytes,
    section: dict,
) -> list[tuple[int, int, int]]:
    instructions = []

    count = section["size"] // 4

    for index in range(count):
        file_offset = (
            section["offset"]
            + index * 4
        )

        address = (
            section["vaddr"]
            + index * 4
        )

        word = read_u32(
            data,
            file_offset,
        )

        instructions.append(
            (
                address,
                file_offset,
                word,
            )
        )

    return instructions


def print_context(
    lines: list[str],
    data: bytes,
    sections: list[dict],
    section: dict,
    match: dict,
) -> None:
    important = {
        match["table_load_address"]:
            "LOAD FONT TABLE POINTER",
        match["index_shift_address"]:
            "CHARACTER INDEX × 2",
        match["address_build_address"]:
            "TABLE + OFFSET",
        match["lookup_address"]:
            "READ GLYPH INDEX",
    }

    start = max(
        section["vaddr"],
        match["table_load_address"] - 8 * 4,
    )

    end = min(
        section["vaddr"] + section["size"],
        match["lookup_address"] + 9 * 4,
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

        if address in important:
            marker = ">>"
            note = (
                "    <<< "
                + important[address]
            )
        else:
            marker = "  "
            note = ""

        lines.append(
            f"{marker} "
            f"0x{address:08X}  "
            f"FILE=0x{offset:X}  "
            f"{word:08X}  "
            f"{decoded}"
            f"{note}"
        )


def main() -> int:
    data = BOOT_PATH.read_bytes()

    if data[:4] != b"\x7FELF":
        raise ValueError(
            "BOOT.BIN이 ELF 파일이 아닙니다."
        )

    sections = mips.parse_sections(data)

    all_matches = []
    non_stack_loads = []

    for section in sections:
        if not (section["flags"] & 0x4):
            continue

        if (
            section["offset"] + section["size"]
            > len(data)
        ):
            continue

        instructions = build_instruction_list(
            data,
            section,
        )

        for index, (
            address,
            file_offset,
            word,
        ) in enumerate(instructions):
            item = fields(word)

            # lw table, +0x84(object)
            if not (
                item["opcode"] == 0x23
                and item["immediate"]
                == TABLE_FIELD
            ):
                continue

            # 이전 검색의 대부분을 차지한
            # 스택 프레임 +0x84는 제외
            if item["rs"] == SP:
                continue

            non_stack_loads.append(
                {
                    "section": section,
                    "address": address,
                    "offset": file_offset,
                    "base": item["rs"],
                    "destination": item["rt"],
                }
            )

            matches = scan_from_table_load(
                data,
                sections,
                section,
                index,
                instructions,
            )

            all_matches.extend(matches)

    # 동일 lookup 주소 중복 제거
    unique_matches = {}

    for match in all_matches:
        unique_matches[
            match["lookup_address"]
        ] = match

    matches = sorted(
        unique_matches.values(),
        key=lambda item: item[
            "lookup_address"
        ],
    )

    lines = []

    lines.append(
        "FONT LOOKUP DATAFLOW SEARCH"
    )
    lines.append(
        "==========================="
    )
    lines.append(
        f"NON-STACK +0x84 LOADS : "
        f"{len(non_stack_loads)}"
    )
    lines.append(
        f"COMPLETE LOOKUP CHAINS: "
        f"{len(matches)}"
    )
    lines.append(
        f"SCAN WINDOW           : "
        f"{WINDOW_SIZE} instructions"
    )

    if matches:
        for index, match in enumerate(
            matches,
            start=1,
        ):
            lines.append("")
            lines.append("=" * 96)
            lines.append(
                f"[{index}] "
                f"LOOKUP=0x"
                f"{match['lookup_address']:08X} "
                f"SECTION="
                f"{match['section']['name']}"
            )
            lines.append("=" * 96)

            lines.append(
                "OBJECT REGISTER : "
                f"{register_name(
                    match['object_register']
                )}"
            )
            lines.append(
                "TABLE REGISTER  : "
                f"{register_name(
                    match['table_register']
                )}"
            )
            lines.append(
                "CHAR CODE REG   : "
                f"{register_name(
                    match['index_register']
                )}"
            )
            lines.append(
                "GLYPH REG       : "
                f"{register_name(
                    match['glyph_register']
                )}"
            )
            lines.append(
                "LOOKUP OP       : "
                f"{match['lookup_operation']}"
            )
            lines.append("")

            print_context(
                lines,
                data,
                sections,
                match["section"],
                match,
            )

    else:
        lines.append("")
        lines.append(
            "직선형 lw→sll→addu→lhu 체인은 "
            "발견되지 않았습니다."
        )
        lines.append(
            "비분기 후보인 비-스택 +0x84 접근만 "
            "아래에 기록합니다."
        )

        for hit in non_stack_loads:
            lines.append(
                f"  VA=0x{hit['address']:08X} "
                f"FILE=0x{hit['offset']:X} "
                f"BASE={register_name(hit['base'])} "
                f"DEST={register_name(
                    hit['destination']
                )}"
            )

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
