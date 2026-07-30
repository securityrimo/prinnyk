#!/usr/bin/env python3

import hashlib
import struct
from pathlib import Path


START_PATH = Path(
    "workspace/unpack/SYSTEM_fixed/start.dat"
)

EXTRACTED_PATH = Path(
    "workspace/unpack/START_runtime/jis2ucs.bin"
)

RESOURCE_NAME = b"jis2ucs.bin"

ENTRY_COUNT_OFFSET = 0x00
TABLE_OFFSET = 0x08
ENTRY_SIZE = 0x20
NAME_SIZE = 0x0C
RESOURCE_OFFSET_FIELD = 0x1C


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def read_u16_le(
    data: bytes,
    index: int,
    base: int = 0,
) -> int | None:
    offset = base + index * 2

    if offset < 0 or offset + 2 > len(data):
        return None

    return int.from_bytes(
        data[offset:offset + 2],
        "little",
    )


def display_value(value: int | None) -> str:
    if value is None:
        return "OUT-OF-RANGE"

    if 0x20 <= value <= 0x7E:
        character = chr(value)
        return f"U+{value:04X} {character!r}"

    return f"U+{value:04X}"


def find_identity_runs(
    data: bytes,
    minimum_length: int = 16,
) -> list[tuple[int, int]]:
    entry_count = len(data) // 2
    runs = []

    run_start = None

    for index in range(entry_count):
        value = read_u16_le(data, index)

        if value == index:
            if run_start is None:
                run_start = index
        else:
            if run_start is not None:
                length = index - run_start

                if length >= minimum_length:
                    runs.append(
                        (run_start, length)
                    )

                run_start = None

    if run_start is not None:
        length = entry_count - run_start

        if length >= minimum_length:
            runs.append(
                (run_start, length)
            )

    return runs


def find_ascii_window_bases(
    data: bytes,
) -> list[int]:
    # base + 문자코드*2 위치에 동일한 Unicode 값이
    # 연속으로 들어 있는 테이블 시작점을 찾는다.
    matches = []

    probe_codes = [
        0x20,
        0x30,
        0x41,
        0x5A,
        0x61,
        0x7A,
        0x7E,
    ]

    maximum_base = len(data) - (0x7E + 1) * 2

    for base in range(0, maximum_base + 1, 2):
        valid = True

        for code in probe_codes:
            value = read_u16_le(
                data,
                code,
                base,
            )

            if value != code:
                valid = False
                break

        if valid:
            matches.append(base)

    return matches


def main() -> int:
    start_data = START_PATH.read_bytes()
    extracted = EXTRACTED_PATH.read_bytes()

    count = read_u32(
        start_data,
        ENTRY_COUNT_OFFSET,
    )

    found = None

    for index in range(count):
        entry_offset = (
            TABLE_OFFSET
            + index * ENTRY_SIZE
        )

        name_raw = start_data[
            entry_offset:
            entry_offset + NAME_SIZE
        ]

        name = name_raw.split(
            b"\x00",
            1,
        )[0]

        if name != RESOURCE_NAME:
            continue

        # entry_offset은 레코드 시작이 아니라 이름 필드
        # 시작(record base + 0x08)을 가리킨다.
        # 데이터 오프셋은 record base + 0x04에 있으므로
        # 이름 필드 위치에서 4바이트를 되돌아가야 한다.
        resource_offset = read_u32(
            start_data,
            entry_offset - 0x04,
        )

        found = (
            index,
            entry_offset,
            resource_offset,
        )

        break

    print("JIS2UCS RESOURCE AUDIT")
    print("======================")
    print("START.DAT :", START_PATH)
    print("EXTRACTED :", EXTRACTED_PATH)
    print("COUNT     :", count)
    print()

    if found is None:
        print("RESOURCE ENTRY NOT FOUND")
        return 1

    (
        entry_index,
        entry_offset,
        resource_offset,
    ) = found

    print("RESOURCE ENTRY")
    print("==============")
    print(
        f"INDEX        : {entry_index}"
    )
    print(
        f"NAME OFFSET  : 0x{entry_offset:X}"
    )
    print(
        f"DATA OFFSET  : 0x{resource_offset:X}"
    )
    print(
        f"FILE SIZE    : 0x{len(extracted):X}"
    )

    source_slice = start_data[
        resource_offset:
        resource_offset + len(extracted)
    ]

    print()
    print("SOURCE COMPARISON")
    print("=================")
    print(
        "START SLICE SIZE:",
        len(source_slice),
    )
    print(
        "EXTRACTED SIZE  :",
        len(extracted),
    )
    print(
        "START SHA1      :",
        sha1(source_slice),
    )
    print(
        "EXTRACTED SHA1  :",
        sha1(extracted),
    )
    print(
        "BYTE IDENTICAL  :",
        source_slice == extracted,
    )

    print()
    print("FIRST 64 BYTES")
    print("==============")
    print(
        extracted[:64].hex(
            " ",
        ).upper()
    )

    indices = [
        0x0000,
        0x0001,
        0x0020,
        0x0030,
        0x0041,
        0x005A,
        0x0061,
        0x007A,
        0x007E,
        0x00A6,
        0x244E,
        0x2526,
        0x2535,
        0x256F,
        0x4C3F,
        0xA44E,
    ]

    print()
    print("DIRECT LITTLE-ENDIAN LOOKUPS")
    print("============================")

    for index in indices:
        value = read_u16_le(
            extracted,
            index,
        )

        print(
            f"INDEX=0x{index:04X} "
            f"OFFSET=0x{index * 2:05X} "
            f"VALUE={display_value(value)}"
        )

    print()
    print("IDENTITY RUNS")
    print("=============")

    runs = find_identity_runs(
        extracted,
    )

    if not runs:
        print("NONE")
    else:
        for start, length in runs[:30]:
            print(
                f"INDEX=0x{start:04X} "
                f"LENGTH={length}"
            )

    print()
    print("ASCII TABLE BASE CANDIDATES")
    print("===========================")

    bases = find_ascii_window_bases(
        extracted,
    )

    if not bases:
        print("NONE")
    else:
        for base in bases[:50]:
            print(
                f"BASE OFFSET=0x{base:X}"
            )

    print()
    print("RAW UNICODE BYTE SEARCH")
    print("=======================")

    for character in [
        "の",
        "ウ",
        "ワ",
        "サ",
        "命",
    ]:
        raw = ord(character).to_bytes(
            2,
            "little",
        )

        positions = []
        position = 0

        while True:
            position = extracted.find(
                raw,
                position,
            )

            if position < 0:
                break

            positions.append(position)
            position += 1

        formatted = (
            ", ".join(
                f"0x{position:X}"
                for position in positions[:20]
            )
            if positions
            else "NONE"
        )

        print(
            f"{character} "
            f"U+{ord(character):04X}: "
            f"{formatted}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
