#!/usr/bin/env python3

import hashlib
import struct
from pathlib import Path


START_PATH = Path(
    "workspace/unpack/SYSTEM_fixed/start.dat"
)

OLD_DIRECTORY = Path(
    "workspace/unpack/START_fixed_legacy"
)

NEW_DIRECTORY = Path(
    "workspace/unpack/START_runtime"
)

TARGET_NAMES = {
    "font.fnt",
    "font.txp",
    "jis2ucs.bin",
    "ucs2jis.bin",
}

RECORD_SIZE = 0x20
OFFSET_FIELD = 0x04
NAME_FIELD = 0x08
NAME_SIZE = 0x18


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def safe_name(name: str, index: int) -> str:
    name = Path(name).name.strip()

    if not name:
        return f"resource_{index:03d}.bin"

    return name


def main() -> int:
    data = START_PATH.read_bytes()

    if len(data) < RECORD_SIZE:
        raise ValueError(
            "start.dat이 너무 작습니다."
        )

    count = u32(data, 0x00)

    table_end = count * RECORD_SIZE

    if table_end > len(data):
        raise ValueError(
            f"레코드 테이블 범위가 파일을 벗어납니다: "
            f"0x{table_end:X}"
        )

    records = []

    for index in range(count):
        base = index * RECORD_SIZE

        resource_offset = u32(
            data,
            base + OFFSET_FIELD,
        )

        raw_name = data[
            base + NAME_FIELD:
            base + NAME_FIELD + NAME_SIZE
        ]

        raw_name = raw_name.split(
            b"\x00",
            1,
        )[0]

        name = raw_name.decode(
            "ascii",
            errors="replace",
        )

        records.append(
            {
                "index": index,
                "base": base,
                "name": safe_name(
                    name,
                    index,
                ),
                "offset": resource_offset,
            }
        )

    for index, record in enumerate(records):
        if index + 1 < len(records):
            end_offset = records[
                index + 1
            ]["offset"]
        else:
            end_offset = len(data)

        record["end"] = end_offset
        record["size"] = (
            end_offset
            - record["offset"]
        )

        valid = (
            0 <= record["offset"]
            <= end_offset
            <= len(data)
        )

        record["valid"] = valid

        if valid:
            blob = data[
                record["offset"]:
                end_offset
            ]

            record["sha1"] = sha1(blob)
        else:
            record["sha1"] = None

    print("START.DAT RUNTIME EXTRACTION")
    print("============================")
    print("FILE        :", START_PATH)
    print("FILE SIZE   :", f"0x{len(data):X}")
    print("RECORD COUNT:", count)
    print("TABLE END   :", f"0x{table_end:X}")
    print("FIRST DATA  :", f"0x{records[0]['offset']:X}")
    print()

    print("TARGET RECORDS")
    print("==============")

    for record in records:
        if record["name"] not in TARGET_NAMES:
            continue

        print()
        print(
            f"[{record['index']}] "
            f"{record['name']}"
        )
        print(
            f"  RECORD BASE : "
            f"0x{record['base']:X}"
        )
        print(
            f"  OFFSET +0x04: "
            f"0x{record['offset']:X}"
        )
        print(
            f"  END         : "
            f"0x{record['end']:X}"
        )
        print(
            f"  SIZE        : "
            f"0x{record['size']:X} "
            f"({record['size']} bytes)"
        )
        print(
            f"  VALID       : "
            f"{record['valid']}"
        )

        if record["valid"]:
            blob = data[
                record["offset"]:
                record["end"]
            ]

            print(
                f"  SHA1        : "
                f"{record['sha1']}"
            )
            print(
                f"  FIRST 16    : "
                f"{blob[:16].hex(' ').upper()}"
            )

        wrong_field_offset = (
            record["base"]
            + NAME_FIELD
            + 0x1C
        )

        if wrong_field_offset + 4 <= len(data):
            wrong_value = u32(
                data,
                wrong_field_offset,
            )

            print(
                f"  NAME+0x1C   : "
                f"0x{wrong_value:X}"
            )

            if (
                record["index"] + 1
                < len(records)
            ):
                next_offset = records[
                    record["index"] + 1
                ]["offset"]

                print(
                    "  EQUALS NEXT :",
                    wrong_value == next_offset,
                )

    NEW_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    written_paths = {}

    for record in records:
        if not record["valid"]:
            continue

        name = record["name"]
        output_path = NEW_DIRECTORY / name

        if output_path.exists() or name in written_paths:
            stem = output_path.stem
            suffix = output_path.suffix

            output_path = (
                NEW_DIRECTORY
                / f"{stem}_{record['index']:03d}{suffix}"
            )

        blob = data[
            record["offset"]:
            record["end"]
        ]

        output_path.write_bytes(blob)
        written_paths[name] = output_path

    print()
    print("EXTRACTION")
    print("==========")
    print("OUTPUT:", NEW_DIRECTORY)
    print(
        "FILES :",
        len(
            [
                record
                for record in records
                if record["valid"]
            ]
        ),
    )

    runtime_hashes = {}

    for record in records:
        if not record["valid"]:
            continue

        key = (
            record["size"],
            record["sha1"],
        )

        runtime_hashes.setdefault(
            key,
            [],
        ).append(record)

    print()
    print("OLD FILE IDENTIFICATION")
    print("=======================")

    for target_name in sorted(TARGET_NAMES):
        old_path = OLD_DIRECTORY / target_name

        print()
        print("OLD FILE:", old_path)

        if not old_path.is_file():
            print("  NOT FOUND")
            continue

        old_data = old_path.read_bytes()
        old_sha1 = sha1(old_data)

        print(
            "  SIZE:",
            f"0x{len(old_data):X}",
        )
        print(
            "  SHA1:",
            old_sha1,
        )

        matches = runtime_hashes.get(
            (
                len(old_data),
                old_sha1,
            ),
            [],
        )

        if not matches:
            print(
                "  RUNTIME RECORD MATCH: NONE"
            )
            continue

        for match in matches:
            print(
                "  RUNTIME RECORD MATCH:",
                f"[{match['index']}] "
                f"{match['name']}"
            )

    print()
    print("NEW TARGET FILES")
    print("================")

    for target_name in sorted(TARGET_NAMES):
        path = NEW_DIRECTORY / target_name

        if not path.is_file():
            print(
                f"{target_name}: NOT FOUND"
            )
            continue

        file_data = path.read_bytes()

        print(
            f"{target_name}: "
            f"SIZE=0x{len(file_data):X} "
            f"SHA1={sha1(file_data)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
