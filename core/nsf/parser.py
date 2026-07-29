#!/usr/bin/env python3

import json
import os
from pathlib import Path


HEADER_SIZE = 0x20
PRIMARY_TABLE_OFFSET = 0x20
TABLE_ENTRY_SIZE = 8
AUXILIARY_ENTRY_SIZE = 4


class NSFParseError(Exception):
    """NSF 구조가 예상 범위를 벗어났을 때 발생한다."""


def read_u32(data: bytes, offset: int) -> int:
    end = offset + 4

    if offset < 0 or end > len(data):
        raise NSFParseError(
            f"u32 읽기 범위 오류: "
            f"offset=0x{offset:X}, "
            f"file_size=0x{len(data):X}"
        )

    return int.from_bytes(
        data[offset:end],
        byteorder="little",
        signed=False,
    )


def parse_header(data: bytes) -> dict:
    if len(data) < HEADER_SIZE:
        raise NSFParseError(
            f"파일이 헤더보다 작습니다: "
            f"file_size=0x{len(data):X}"
        )

    return {
        "unknown_00": read_u32(data, 0x00),
        "blob_size": read_u32(data, 0x04),
        "primary_count": read_u32(data, 0x08),
        "auxiliary_count": read_u32(data, 0x0C),
        "secondary_count": read_u32(data, 0x10),
        "unknown_14": read_u32(data, 0x14),
        "unknown_18": read_u32(data, 0x18),
        "unknown_1c": read_u32(data, 0x1C),
        "raw_hex": data[:HEADER_SIZE].hex(" "),
    }


def parse_primary_table(
    data: bytes,
    table_offset: int,
    count: int,
) -> list[dict]:
    table_end = table_offset + count * TABLE_ENTRY_SIZE

    if table_end > len(data):
        raise NSFParseError(
            f"1차 테이블이 파일 범위를 벗어납니다: "
            f"table_end=0x{table_end:X}, "
            f"file_size=0x{len(data):X}"
        )

    entries = []

    for index in range(count):
        entry_offset = table_offset + index * TABLE_ENTRY_SIZE

        reference_value = read_u32(data, entry_offset)
        link_value = read_u32(data, entry_offset + 4)

        entries.append(
            {
                "index": index,
                "table_offset": entry_offset,
                "table_offset_hex": f"0x{entry_offset:X}",
                "reference_value": reference_value,
                "reference_value_hex": (
                    f"0x{reference_value:08X}"
                ),
                "link_value": link_value,
                "link_value_hex": f"0x{link_value:X}",
                # 이전 조사 스크립트 호환용
                "relative_start": link_value,
                "relative_start_hex": f"0x{link_value:X}",
                "raw_hex": data[
                    entry_offset:
                    entry_offset + TABLE_ENTRY_SIZE
                ].hex(" "),
            }
        )

    return entries


def parse_secondary_table(
    data: bytes,
    table_offset: int,
    count: int,
    blob_size: int,
) -> list[dict]:
    table_end = table_offset + count * TABLE_ENTRY_SIZE

    if table_end > len(data):
        raise NSFParseError(
            f"2차 테이블이 파일 범위를 벗어납니다: "
            f"table_end=0x{table_end:X}, "
            f"file_size=0x{len(data):X}"
        )

    entries = []

    for index in range(count):
        entry_offset = table_offset + index * TABLE_ENTRY_SIZE

        value_a = read_u32(data, entry_offset)
        value_b = read_u32(data, entry_offset + 4)

        if (
            value_a <= value_b
            and value_a < blob_size
            and value_b < blob_size
        ):
            entry_type = "range"
            range_valid = True
        elif value_a > value_b:
            entry_type = "special_pair"
            range_valid = False
        else:
            entry_type = "invalid_range"
            range_valid = False

        entries.append(
            {
                "index": index,
                "table_offset": entry_offset,
                "table_offset_hex": f"0x{entry_offset:X}",
                "value_a": value_a,
                "value_a_hex": f"0x{value_a:X}",
                "value_b": value_b,
                "value_b_hex": f"0x{value_b:X}",
                # 범위형 NSF와의 호환용
                "relative_start": value_a,
                "relative_start_hex": f"0x{value_a:X}",
                "relative_end": value_b,
                "relative_end_hex": f"0x{value_b:X}",
                "entry_type": entry_type,
                "range_valid": range_valid,
                "raw_hex": data[
                    entry_offset:
                    entry_offset + TABLE_ENTRY_SIZE
                ].hex(" "),
            }
        )

    return entries


def parse_auxiliary_table(
    data: bytes,
    table_offset: int,
    count: int,
    blob_offset: int,
    blob_size: int,
) -> list[dict]:
    table_end = (
        table_offset + count * AUXILIARY_ENTRY_SIZE
    )

    if table_end > len(data):
        raise NSFParseError(
            f"보조 테이블이 파일 범위를 벗어납니다: "
            f"table_end=0x{table_end:X}, "
            f"file_size=0x{len(data):X}"
        )

    entries = []

    for index in range(count):
        entry_offset = (
            table_offset + index * AUXILIARY_ENTRY_SIZE
        )

        value = read_u32(data, entry_offset)
        inside_blob = value < blob_size

        entries.append(
            {
                "index": index,
                "table_offset": entry_offset,
                "table_offset_hex": f"0x{entry_offset:X}",
                "value": value,
                "value_hex": f"0x{value:X}",
                "inside_blob": inside_blob,
                "candidate_file_offset": (
                    blob_offset + value
                    if inside_blob
                    else None
                ),
                "candidate_file_offset_hex": (
                    f"0x{blob_offset + value:X}"
                    if inside_blob
                    else None
                ),
                "raw_hex": data[
                    entry_offset:
                    entry_offset + AUXILIARY_ENTRY_SIZE
                ].hex(" "),
            }
        )

    return entries


def build_primary_entries(
    data: bytes,
    blob_offset: int,
    primary_table: list[dict],
    secondary_table: list[dict],
    auxiliary_table: list[dict],
) -> tuple[list[dict], dict]:
    secondary_by_a = {}

    for secondary in secondary_table:
        secondary_by_a.setdefault(
            secondary["value_a"],
            [],
        ).append(secondary)

    auxiliary_by_value = {}

    for auxiliary in auxiliary_table:
        auxiliary_by_value.setdefault(
            auxiliary["value"],
            [],
        ).append(auxiliary)

    entries = []
    used_secondary_indices = set()
    used_auxiliary_indices = set()

    unresolved_primary_indices = []
    ambiguous_primary_indices = []
    secondary_link_count = 0
    auxiliary_link_count = 0

    for primary in primary_table:
        primary_index = primary["index"]
        link_value = primary["link_value"]

        secondary_matches = secondary_by_a.get(
            link_value,
            [],
        )

        auxiliary_matches = auxiliary_by_value.get(
            link_value,
            [],
        )

        base_entry = {
            "index": primary_index,
            "primary_index": primary_index,
            "reference_value": primary["reference_value"],
            "reference_value_hex": primary[
                "reference_value_hex"
            ],
            # 이전 조사 스크립트 호환용
            "primary_unknown_value": primary[
                "reference_value"
            ],
            "primary_unknown_value_hex": primary[
                "reference_value_hex"
            ],
            "link_value": link_value,
            "link_value_hex": f"0x{link_value:X}",
        }

        if len(secondary_matches) == 1:
            secondary = secondary_matches[0]
            secondary_index = secondary["index"]

            used_secondary_indices.add(secondary_index)
            secondary_link_count += 1

            base_entry.update(
                {
                    "link_kind": "secondary",
                    "secondary_index": secondary_index,
                    "auxiliary_index": None,
                    "secondary_entry_type": secondary[
                        "entry_type"
                    ],
                    "relative_start": secondary["value_a"],
                    "relative_start_hex": secondary[
                        "value_a_hex"
                    ],
                    "relative_end": secondary["value_b"],
                    "relative_end_hex": secondary[
                        "value_b_hex"
                    ],
                }
            )

            if secondary["range_valid"]:
                absolute_start = (
                    blob_offset + secondary["value_a"]
                )

                absolute_end_exclusive = (
                    blob_offset + secondary["value_b"] + 1
                )

                if absolute_end_exclusive > len(data):
                    raise NSFParseError(
                        f"PRIMARY {primary_index} 데이터가 "
                        f"파일 범위를 벗어납니다: "
                        f"end=0x{absolute_end_exclusive:X}"
                    )

                chunk = data[
                    absolute_start:absolute_end_exclusive
                ]

                base_entry.update(
                    {
                        "data_status": "extracted",
                        "file_start": absolute_start,
                        "file_start_hex": (
                            f"0x{absolute_start:X}"
                        ),
                        "file_end": (
                            absolute_end_exclusive - 1
                        ),
                        "file_end_hex": (
                            f"0x{absolute_end_exclusive - 1:X}"
                        ),
                        "size": len(chunk),
                        "hex": chunk.hex(" "),
                    }
                )
            else:
                base_entry.update(
                    {
                        "data_status": "special_pair",
                        "file_start": None,
                        "file_start_hex": None,
                        "file_end": None,
                        "file_end_hex": None,
                        "size": None,
                        "hex": None,
                    }
                )

        elif not secondary_matches and len(auxiliary_matches) == 1:
            auxiliary = auxiliary_matches[0]
            auxiliary_index = auxiliary["index"]

            used_auxiliary_indices.add(auxiliary_index)
            auxiliary_link_count += 1

            candidate_file_offset = auxiliary[
                "candidate_file_offset"
            ]

            base_entry.update(
                {
                    "link_kind": "auxiliary",
                    "secondary_index": None,
                    "auxiliary_index": auxiliary_index,
                    "secondary_entry_type": None,
                    "relative_start": link_value,
                    "relative_start_hex": (
                        f"0x{link_value:X}"
                    ),
                    "relative_end": None,
                    "relative_end_hex": None,
                    "data_status": "offset_without_range",
                    "file_start": candidate_file_offset,
                    "file_start_hex": auxiliary[
                        "candidate_file_offset_hex"
                    ],
                    "file_end": None,
                    "file_end_hex": None,
                    "size": None,
                    "hex": None,
                }
            )

        elif (
            len(secondary_matches) > 1
            or len(auxiliary_matches) > 1
            or (
                secondary_matches
                and auxiliary_matches
            )
        ):
            ambiguous_primary_indices.append(primary_index)

            base_entry.update(
                {
                    "link_kind": "ambiguous",
                    "secondary_indices": [
                        item["index"]
                        for item in secondary_matches
                    ],
                    "auxiliary_indices": [
                        item["index"]
                        for item in auxiliary_matches
                    ],
                    "data_status": "not_extracted",
                    "relative_start": link_value,
                    "relative_start_hex": (
                        f"0x{link_value:X}"
                    ),
                    "relative_end": None,
                    "relative_end_hex": None,
                    "file_start": None,
                    "file_start_hex": None,
                    "file_end": None,
                    "file_end_hex": None,
                    "size": None,
                    "hex": None,
                }
            )

        else:
            unresolved_primary_indices.append(primary_index)

            base_entry.update(
                {
                    "link_kind": "unresolved",
                    "secondary_index": None,
                    "auxiliary_index": None,
                    "data_status": "not_extracted",
                    "relative_start": link_value,
                    "relative_start_hex": (
                        f"0x{link_value:X}"
                    ),
                    "relative_end": None,
                    "relative_end_hex": None,
                    "file_start": None,
                    "file_start_hex": None,
                    "file_end": None,
                    "file_end_hex": None,
                    "size": None,
                    "hex": None,
                }
            )

        entries.append(base_entry)

    return entries, {
        "used_secondary_indices": sorted(
            used_secondary_indices
        ),
        "used_auxiliary_indices": sorted(
            used_auxiliary_indices
        ),
        "unresolved_primary_indices": (
            unresolved_primary_indices
        ),
        "ambiguous_primary_indices": (
            ambiguous_primary_indices
        ),
        "secondary_link_count": secondary_link_count,
        "auxiliary_link_count": auxiliary_link_count,
    }


def classify_secondary_hierarchy(
    secondary_table: list[dict],
    directly_used_indices: set[int],
) -> dict:
    valid_ranges = [
        entry
        for entry in secondary_table
        if entry["range_valid"]
    ]

    nested_indices = []
    orphan_range_indices = []

    for child in valid_ranges:
        child_index = child["index"]

        if child_index in directly_used_indices:
            continue

        child_start = child["value_a"]
        child_end = child["value_b"]
        child_size = child_end - child_start + 1

        has_parent = False

        for parent in valid_ranges:
            if parent["index"] == child_index:
                continue

            parent_start = parent["value_a"]
            parent_end = parent["value_b"]
            parent_size = parent_end - parent_start + 1

            if (
                parent_size > child_size
                and parent_start <= child_start
                and child_end <= parent_end
            ):
                has_parent = True
                break

        if has_parent:
            nested_indices.append(child_index)
        else:
            orphan_range_indices.append(child_index)

    special_pair_indices = [
        entry["index"]
        for entry in secondary_table
        if entry["entry_type"] == "special_pair"
    ]

    invalid_range_indices = [
        entry["index"]
        for entry in secondary_table
        if entry["entry_type"] == "invalid_range"
    ]

    return {
        "nested_secondary_indices": nested_indices,
        "orphan_range_indices": orphan_range_indices,
        "special_pair_indices": special_pair_indices,
        "invalid_range_indices": invalid_range_indices,
    }


def analyze_nsf(
    path: str | os.PathLike,
) -> dict:
    source = Path(path)

    if not source.is_file():
        raise FileNotFoundError(
            f"NSF 파일을 찾을 수 없습니다: {source}"
        )

    data = source.read_bytes()
    file_size = len(data)

    header = parse_header(data)

    blob_size = header["blob_size"]
    primary_count = header["primary_count"]
    auxiliary_count = header["auxiliary_count"]
    secondary_count = header["secondary_count"]

    if primary_count <= 0:
        raise NSFParseError(
            f"잘못된 1차 테이블 개수입니다: "
            f"{primary_count}"
        )

    if secondary_count <= 0:
        raise NSFParseError(
            f"잘못된 2차 테이블 개수입니다: "
            f"{secondary_count}"
        )

    if blob_size <= 0 or blob_size > file_size:
        raise NSFParseError(
            f"잘못된 blob 크기입니다: "
            f"blob_size=0x{blob_size:X}, "
            f"file_size=0x{file_size:X}"
        )

    primary_table_size = (
        primary_count * TABLE_ENTRY_SIZE
    )

    secondary_table_offset = (
        PRIMARY_TABLE_OFFSET + primary_table_size
    )

    secondary_table_size = (
        secondary_count * TABLE_ENTRY_SIZE
    )

    auxiliary_table_offset = (
        secondary_table_offset + secondary_table_size
    )

    auxiliary_table_size = (
        auxiliary_count * AUXILIARY_ENTRY_SIZE
    )

    calculated_blob_offset = (
        auxiliary_table_offset + auxiliary_table_size
    )

    blob_offset_from_size = file_size - blob_size

    if calculated_blob_offset != blob_offset_from_size:
        raise NSFParseError(
            f"계산한 blob 위치와 파일 크기로 구한 위치가 "
            f"다릅니다: "
            f"calculated=0x{calculated_blob_offset:X}, "
            f"from_size=0x{blob_offset_from_size:X}"
        )

    primary_table = parse_primary_table(
        data=data,
        table_offset=PRIMARY_TABLE_OFFSET,
        count=primary_count,
    )

    secondary_table = parse_secondary_table(
        data=data,
        table_offset=secondary_table_offset,
        count=secondary_count,
        blob_size=blob_size,
    )

    auxiliary_table = parse_auxiliary_table(
        data=data,
        table_offset=auxiliary_table_offset,
        count=auxiliary_count,
        blob_offset=calculated_blob_offset,
        blob_size=blob_size,
    )

    entries, link_info = build_primary_entries(
        data=data,
        blob_offset=calculated_blob_offset,
        primary_table=primary_table,
        secondary_table=secondary_table,
        auxiliary_table=auxiliary_table,
    )

    hierarchy = classify_secondary_hierarchy(
        secondary_table=secondary_table,
        directly_used_indices=set(
            link_info["used_secondary_indices"]
        ),
    )

    non_primary_secondary_indices = [
        entry["index"]
        for entry in secondary_table
        if entry["index"]
        not in set(link_info["used_secondary_indices"])
    ]

    auxiliary_outside_blob_indices = [
        entry["index"]
        for entry in auxiliary_table
        if not entry["inside_blob"]
    ]

    warnings = []

    if link_info["unresolved_primary_indices"]:
        warnings.append(
            f"연결 대상을 찾지 못한 1차 엔트리가 "
            f"{len(link_info['unresolved_primary_indices'])}개 "
            f"있습니다."
        )

    if link_info["ambiguous_primary_indices"]:
        warnings.append(
            f"연결 대상이 여러 개인 1차 엔트리가 "
            f"{len(link_info['ambiguous_primary_indices'])}개 "
            f"있습니다."
        )

    if hierarchy["invalid_range_indices"]:
        warnings.append(
            f"blob 범위를 벗어난 2차 범위 후보가 "
            f"{len(hierarchy['invalid_range_indices'])}개 "
            f"있습니다."
        )

    if auxiliary_outside_blob_indices:
        warnings.append(
            f"blob 범위 밖의 보조 테이블 값이 "
            f"{len(auxiliary_outside_blob_indices)}개 "
            f"있습니다."
        )

    return {
        "format": "NSF",
        "file": source.name,
        "source": str(source),
        "file_size": file_size,
        "file_size_hex": f"0x{file_size:X}",
        "header": header,
        "count": primary_count,
        "primary_count": primary_count,
        "secondary_count": secondary_count,
        "auxiliary_count": auxiliary_count,
        "layout": {
            "header_offset": 0,
            "header_offset_hex": "0x0",
            "header_size": HEADER_SIZE,
            "header_size_hex": f"0x{HEADER_SIZE:X}",
            "primary_table_offset": PRIMARY_TABLE_OFFSET,
            "primary_table_offset_hex": (
                f"0x{PRIMARY_TABLE_OFFSET:X}"
            ),
            "primary_table_size": primary_table_size,
            "primary_table_size_hex": (
                f"0x{primary_table_size:X}"
            ),
            "secondary_table_offset": secondary_table_offset,
            "secondary_table_offset_hex": (
                f"0x{secondary_table_offset:X}"
            ),
            "secondary_table_size": secondary_table_size,
            "secondary_table_size_hex": (
                f"0x{secondary_table_size:X}"
            ),
            "auxiliary_table_offset": auxiliary_table_offset,
            "auxiliary_table_offset_hex": (
                f"0x{auxiliary_table_offset:X}"
            ),
            "auxiliary_table_size": auxiliary_table_size,
            "auxiliary_table_size_hex": (
                f"0x{auxiliary_table_size:X}"
            ),
            "blob_offset": calculated_blob_offset,
            "blob_offset_hex": (
                f"0x{calculated_blob_offset:X}"
            ),
            "blob_size": blob_size,
            "blob_size_hex": f"0x{blob_size:X}",
        },
        "entry_order": "primary_table_order",
        "warnings": warnings,
        "secondary_link_count": (
            link_info["secondary_link_count"]
        ),
        "auxiliary_link_count": (
            link_info["auxiliary_link_count"]
        ),
        "unresolved_primary_indices": (
            link_info["unresolved_primary_indices"]
        ),
        "ambiguous_primary_indices": (
            link_info["ambiguous_primary_indices"]
        ),
        "non_primary_secondary_indices": (
            non_primary_secondary_indices
        ),
        # 이전 필드명 호환용
        "unreferenced_secondary_indices": (
            non_primary_secondary_indices
        ),
        "nested_secondary_indices": (
            hierarchy["nested_secondary_indices"]
        ),
        "orphan_range_indices": (
            hierarchy["orphan_range_indices"]
        ),
        "special_pair_indices": (
            hierarchy["special_pair_indices"]
        ),
        "invalid_range_indices": (
            hierarchy["invalid_range_indices"]
        ),
        "auxiliary_outside_blob_indices": (
            auxiliary_outside_blob_indices
        ),
        "primary_table": primary_table,
        "secondary_table": secondary_table,
        "auxiliary_table": auxiliary_table,
        "entries": entries,
    }


def main() -> int:
    import argparse

    argument_parser = argparse.ArgumentParser(
        description="Prinny NSF 구조 분석기"
    )

    argument_parser.add_argument(
        "file",
        help="분석할 NSF 파일",
    )

    args = argument_parser.parse_args()

    try:
        result = analyze_nsf(args.file)
    except (OSError, NSFParseError) as error:
        print(f"ERROR: {error}")
        return 1

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
