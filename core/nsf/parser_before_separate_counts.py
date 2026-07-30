#!/usr/bin/env python3

import json
import os
from pathlib import Path


HEADER_SIZE = 0x20
TABLE_ENTRY_SIZE = 8
PRIMARY_TABLE_OFFSET = 0x20


class NSFParseError(Exception):
    """NSF 파일 구조가 예상 범위를 벗어날 때 발생한다."""


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
        "count_08": read_u32(data, 0x08),
        "unknown_0c": read_u32(data, 0x0C),
        "count_10": read_u32(data, 0x10),
        "unknown_14": read_u32(data, 0x14),
        "unknown_18": read_u32(data, 0x18),
        "unknown_1c": read_u32(data, 0x1C),
        "raw_hex": data[:HEADER_SIZE].hex(" "),
    }


def parse_primary_table(
    data: bytes,
    offset: int,
    count: int,
) -> list[dict]:
    table_end = offset + count * TABLE_ENTRY_SIZE

    if table_end > len(data):
        raise NSFParseError(
            f"1차 테이블이 파일 범위를 벗어납니다: "
            f"table_end=0x{table_end:X}, "
            f"file_size=0x{len(data):X}"
        )

    entries = []

    for index in range(count):
        entry_offset = offset + index * TABLE_ENTRY_SIZE

        reference_value = read_u32(
            data,
            entry_offset,
        )

        relative_start = read_u32(
            data,
            entry_offset + 4,
        )

        entries.append(
            {
                "index": index,
                "table_offset": entry_offset,
                "table_offset_hex": f"0x{entry_offset:X}",
                "reference_value": reference_value,
                "reference_value_hex": (
                    f"0x{reference_value:08X}"
                ),
                "relative_start": relative_start,
                "relative_start_hex": (
                    f"0x{relative_start:X}"
                ),
                "raw_hex": data[
                    entry_offset:
                    entry_offset + TABLE_ENTRY_SIZE
                ].hex(" "),
            }
        )

    return entries


def parse_secondary_table(
    data: bytes,
    offset: int,
    count: int,
) -> list[dict]:
    table_end = offset + count * TABLE_ENTRY_SIZE

    if table_end > len(data):
        raise NSFParseError(
            f"2차 테이블이 파일 범위를 벗어납니다: "
            f"table_end=0x{table_end:X}, "
            f"file_size=0x{len(data):X}"
        )

    entries = []

    for index in range(count):
        entry_offset = offset + index * TABLE_ENTRY_SIZE

        relative_start = read_u32(
            data,
            entry_offset,
        )

        relative_end = read_u32(
            data,
            entry_offset + 4,
        )

        entries.append(
            {
                "index": index,
                "table_offset": entry_offset,
                "table_offset_hex": f"0x{entry_offset:X}",
                "relative_start": relative_start,
                "relative_start_hex": (
                    f"0x{relative_start:X}"
                ),
                "relative_end": relative_end,
                "relative_end_hex": (
                    f"0x{relative_end:X}"
                ),
                "raw_hex": data[
                    entry_offset:
                    entry_offset + TABLE_ENTRY_SIZE
                ].hex(" "),
            }
        )

    return entries


def validate_secondary_table(
    secondary_table: list[dict],
    blob_size: int,
) -> list[str]:
    warnings = []
    seen_starts = set()
    previous_end = None

    for entry in secondary_table:
        index = entry["index"]
        relative_start = entry["relative_start"]
        relative_end = entry["relative_end"]

        if relative_start in seen_starts:
            raise NSFParseError(
                f"2차 테이블에 중복 시작값이 있습니다: "
                f"0x{relative_start:X}"
            )

        seen_starts.add(relative_start)

        if relative_start > relative_end:
            raise NSFParseError(
                f"2차 테이블 엔트리 {index}의 범위가 반대입니다: "
                f"start=0x{relative_start:X}, "
                f"end=0x{relative_end:X}"
            )

        if relative_end >= blob_size:
            raise NSFParseError(
                f"2차 테이블 엔트리 {index}가 "
                f"blob 범위를 벗어납니다: "
                f"end=0x{relative_end:X}, "
                f"blob_size=0x{blob_size:X}"
            )

        if previous_end is None:
            if relative_start != 0:
                warnings.append(
                    f"2차 테이블의 첫 범위가 "
                    f"0이 아닌 위치에서 시작합니다: "
                    f"0x{relative_start:X}"
                )
        elif relative_start != previous_end + 1:
            warnings.append(
                f"2차 테이블 엔트리 {index - 1}과 "
                f"{index} 사이가 연속적이지 않습니다: "
                f"previous_end=0x{previous_end:X}, "
                f"current_start=0x{relative_start:X}"
            )

        previous_end = relative_end

    if previous_end is not None:
        expected_end = blob_size - 1

        if previous_end != expected_end:
            warnings.append(
                f"2차 테이블의 마지막 범위가 "
                f"blob 끝과 다릅니다: "
                f"table_end=0x{previous_end:X}, "
                f"blob_end=0x{expected_end:X}"
            )

    return warnings


def build_entries(
    data: bytes,
    blob_offset: int,
    primary_table: list[dict],
    secondary_table: list[dict],
) -> tuple[list[dict], list[str]]:
    warnings = []

    secondary_by_start = {
        entry["relative_start"]: entry
        for entry in secondary_table
    }

    entries = []
    matched_secondary_indices = set()
    seen_primary_starts = set()

    for primary in primary_table:
        primary_index = primary["index"]
        relative_start = primary["relative_start"]

        if relative_start in seen_primary_starts:
            warnings.append(
                f"1차 테이블에 중복 시작값이 있습니다: "
                f"0x{relative_start:X}"
            )

        seen_primary_starts.add(relative_start)

        secondary = secondary_by_start.get(relative_start)

        if secondary is None:
            raise NSFParseError(
                f"1차 테이블 엔트리 {primary_index}의 시작값과 "
                f"일치하는 2차 테이블 범위가 없습니다: "
                f"start=0x{relative_start:X}"
            )

        secondary_index = secondary["index"]
        relative_end = secondary["relative_end"]

        matched_secondary_indices.add(secondary_index)

        absolute_start = blob_offset + relative_start
        absolute_end_exclusive = (
            blob_offset + relative_end + 1
        )

        if absolute_start < blob_offset:
            raise NSFParseError(
                f"엔트리 {primary_index} 시작 위치 오류: "
                f"0x{absolute_start:X}"
            )

        if absolute_end_exclusive > len(data):
            raise NSFParseError(
                f"엔트리 {primary_index}가 "
                f"파일 범위를 벗어납니다: "
                f"end=0x{absolute_end_exclusive:X}, "
                f"file_size=0x{len(data):X}"
            )

        chunk = data[
            absolute_start:absolute_end_exclusive
        ]

        entries.append(
            {
                "index": primary_index,
                "primary_index": primary_index,
                "secondary_index": secondary_index,
                "reference_value": primary["reference_value"],
                "reference_value_hex": primary[
                    "reference_value_hex"
                ],
                # 기존 조사 스크립트와의 호환용 이름
                "primary_unknown_value": primary[
                    "reference_value"
                ],
                "primary_unknown_value_hex": primary[
                    "reference_value_hex"
                ],
                "relative_start": relative_start,
                "relative_start_hex": (
                    f"0x{relative_start:X}"
                ),
                "relative_end": relative_end,
                "relative_end_hex": (
                    f"0x{relative_end:X}"
                ),
                "file_start": absolute_start,
                "file_start_hex": (
                    f"0x{absolute_start:X}"
                ),
                "file_end": absolute_end_exclusive - 1,
                "file_end_hex": (
                    f"0x{absolute_end_exclusive - 1:X}"
                ),
                "size": len(chunk),
                "hex": chunk.hex(" "),
            }
        )

    unmatched = [
        entry["index"]
        for entry in secondary_table
        if entry["index"] not in matched_secondary_indices
    ]

    if unmatched:
        warnings.append(
            "1차 테이블에서 참조하지 않는 "
            f"2차 테이블 엔트리: {unmatched}"
        )

    return entries, warnings


def analyze_nsf(path: str | os.PathLike) -> dict:
    source = Path(path)

    if not source.is_file():
        raise FileNotFoundError(
            f"NSF 파일을 찾을 수 없습니다: {source}"
        )

    data = source.read_bytes()
    file_size = len(data)

    header = parse_header(data)

    blob_size = header["blob_size"]
    count_08 = header["count_08"]
    count_10 = header["count_10"]

    if count_08 != count_10:
        raise NSFParseError(
            f"헤더의 엔트리 수가 서로 다릅니다: "
            f"0x08={count_08}, "
            f"0x10={count_10}"
        )

    count = count_10

    if count <= 0:
        raise NSFParseError(
            f"잘못된 엔트리 수입니다: {count}"
        )

    primary_table_size = count * TABLE_ENTRY_SIZE
    secondary_table_size = count * TABLE_ENTRY_SIZE

    secondary_table_offset = (
        PRIMARY_TABLE_OFFSET + primary_table_size
    )

    calculated_blob_offset = (
        secondary_table_offset + secondary_table_size
    )

    if blob_size > file_size:
        raise NSFParseError(
            f"blob 크기가 파일보다 큽니다: "
            f"blob_size=0x{blob_size:X}, "
            f"file_size=0x{file_size:X}"
        )

    blob_offset_from_size = file_size - blob_size

    if calculated_blob_offset != blob_offset_from_size:
        raise NSFParseError(
            f"계산한 blob 위치와 "
            f"파일 크기로 구한 위치가 다릅니다: "
            f"calculated=0x{calculated_blob_offset:X}, "
            f"from_size=0x{blob_offset_from_size:X}"
        )

    primary_table = parse_primary_table(
        data=data,
        offset=PRIMARY_TABLE_OFFSET,
        count=count,
    )

    secondary_table = parse_secondary_table(
        data=data,
        offset=secondary_table_offset,
        count=count,
    )

    warnings = validate_secondary_table(
        secondary_table=secondary_table,
        blob_size=blob_size,
    )

    entries, mapping_warnings = build_entries(
        data=data,
        blob_offset=calculated_blob_offset,
        primary_table=primary_table,
        secondary_table=secondary_table,
    )

    warnings.extend(mapping_warnings)

    return {
        "format": "NSF",
        "file": source.name,
        "source": str(source),
        "file_size": file_size,
        "file_size_hex": f"0x{file_size:X}",
        "header": header,
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
            "blob_offset": calculated_blob_offset,
            "blob_offset_hex": (
                f"0x{calculated_blob_offset:X}"
            ),
            "blob_size": blob_size,
            "blob_size_hex": f"0x{blob_size:X}",
        },
        "count": count,
        "entry_order": "primary_table_order",
        "warnings": warnings,
        "primary_table": primary_table,
        "secondary_table": secondary_table,
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
