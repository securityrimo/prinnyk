#!/usr/bin/env python3

import csv
import json
import struct
from collections import defaultdict
from pathlib import Path


INPUT_PATH = Path(
    "workspace/analysis/G9system.nsf.json"
)

OUTPUT_PATH = Path(
    "workspace/analysis/G9system.groups.csv"
)


def find_header(raw: bytes, header: bytes) -> int | None:
    position = raw.find(header)

    if position < 0:
        return None

    return position


def decode_value(
    raw: bytes,
    position: int,
) -> tuple[str, int | None]:
    value_type = raw[position]

    if value_type == 0x01:
        if position + 1 >= len(raw):
            return "u8-truncated", None

        return "u8", raw[position + 1]

    if value_type == 0x04:
        end = position + 5

        if end > len(raw):
            return "u32-truncated", None

        value = int.from_bytes(
            raw[position + 1:end],
            byteorder="little",
            signed=False,
        )

        return "u32", value

    return f"unknown-0x{value_type:02X}", None


def decode_entry(entry: dict) -> dict:
    raw = bytes.fromhex(entry["hex"])

    if len(raw) < 17:
        raise ValueError(
            f'엔트리 {entry["index"]}가 너무 짧습니다.'
        )

    expected_prefix = bytes.fromhex(
        "43 0A 00 32"
    )

    if not raw.startswith(expected_prefix):
        raise ValueError(
            f'엔트리 {entry["index"]}의 시작 패턴이 다릅니다.'
        )

    key = int.from_bytes(
        raw[4:6],
        byteorder="little",
        signed=False,
    )

    arg1_type = raw[6]
    arg1_value = raw[7]

    arg2_type = raw[8]
    arg2_value = raw[9]

    position_1e = find_header(
        raw,
        bytes.fromhex("43 1E 00 32"),
    )

    if position_1e is None:
        raise ValueError(
            f'엔트리 {entry["index"]}에 43 1E 헤더가 없습니다.'
        )

    value_type, value = decode_value(
        raw,
        position_1e + 4,
    )

    extra_kind = "none"
    extra_values = ""

    position_15 = find_header(
        raw,
        bytes.fromhex("43 15 00 32"),
    )

    position_3e = find_header(
        raw,
        bytes.fromhex("44 3E 00 32"),
    )

    position_3f = find_header(
        raw,
        bytes.fromhex("44 3F 00 32"),
    )

    if position_15 is not None:
        payload = raw[position_15 + 4:-1]

        if len(payload) == 14:
            float1, float2, float3 = struct.unpack(
                "<fff",
                payload[:12],
            )

            extra_kind = "43_15_float3"
            extra_values = (
                f"{float1:.6f},"
                f"{float2:.6f},"
                f"{float3:.6f},"
                f"{payload[12:].hex(' ').upper()}"
            )
        else:
            extra_kind = "43_15_unknown"
            extra_values = payload.hex(" ").upper()

    elif position_3e is not None and position_3f is not None:
        payload_3e = raw[position_3e + 4:position_3f]
        payload_3f = raw[position_3f + 4:-1]

        extra_kind = "44_3E_3F"
        extra_values = (
            f"3E={payload_3e.hex(' ').upper()} "
            f"3F={payload_3f.hex(' ').upper()}"
        )

    return {
        "index": entry["index"],
        "key": key,
        "key_hex": f"0x{key:04X}",
        "arg1_type": arg1_type,
        "arg1_value": arg1_value,
        "arg2_type": arg2_type,
        "arg2_value": arg2_value,
        "value_type": value_type,
        "value": value,
        "extra_kind": extra_kind,
        "extra_values": extra_values,
        "size": entry["size"],
        "raw_hex": entry["hex"].upper(),
    }


def main() -> int:
    if not INPUT_PATH.is_file():
        print(
            f"ERROR: 분석 JSON이 없습니다: {INPUT_PATH}"
        )
        return 1

    with INPUT_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        nsf = json.load(file)

    records = [
        decode_entry(entry)
        for entry in nsf["entries"]
    ]

    groups = defaultdict(list)

    for record in records:
        groups[record["key"]].append(record)

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "index",
        "key",
        "key_hex",
        "arg1_type",
        "arg1_value",
        "arg2_type",
        "arg2_value",
        "value_type",
        "value",
        "extra_kind",
        "extra_values",
        "size",
        "raw_hex",
    ]

    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(records)

    repeated_groups = {
        key: group
        for key, group in groups.items()
        if len(group) > 1
    }

    print("FILE:", nsf["file"])
    print("ENTRIES:", len(records))
    print("UNIQUE KEYS:", len(groups))
    print("REPEATED KEYS:", len(repeated_groups))
    print("CSV:", OUTPUT_PATH)

    print()
    print("REPEATED KEY GROUPS")
    print("-------------------")

    for key, group in sorted(
        repeated_groups.items(),
        key=lambda item: (
            -len(item[1]),
            item[0],
        ),
    ):
        print()
        print(
            f"KEY 0x{key:04X} "
            f"COUNT {len(group)}"
        )

        for record in group:
            value = record["value"]

            if value is None:
                value_text = "None"
            else:
                value_text = (
                    f"{value} / 0x{value:X}"
                )

            print(
                f'  ENTRY {record["index"]:03d} '
                f'A1=0x{record["arg1_value"]:02X} '
                f'A2=0x{record["arg2_value"]:02X} '
                f'VALUE={record["value_type"]}:{value_text} '
                f'EXTRA={record["extra_kind"]}'
            )

    print()
    print("SPECIAL ENTRIES")
    print("---------------")

    for record in records:
        if record["extra_kind"] == "none":
            continue

        print(
            f'ENTRY {record["index"]:03d} '
            f'KEY={record["key_hex"]} '
            f'EXTRA={record["extra_kind"]} '
            f'{record["extra_values"]}'
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
