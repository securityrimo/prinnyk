#!/usr/bin/env python3

import json
import os
from pathlib import Path


HEADER_SIZE = 0x20
TABLE_ENTRY_SIZE = 8
PRIMARY_TABLE_OFFSET = 0x20


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
        "unknown_0c": read_u32(data, 0x0C),
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
        entry_offset = (
            table_offset + index * TABLE_ENTRY_SIZE
        )

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
    table_offset: int,
    count: int,
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
        entry_offset = (
            table_offset + index * TABLE_ENTRY_SIZE
        )

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
) -> None:
    starts = {}

    for entry in secondary_table:
        index = entry["index"]
        relative_start = entry["relative_start"]
        relative_end = entry["relative_end"]

        if relative_start > relative_end:
            raise NSFParseError(
                f"2차 테이블 엔트리 {index}의 범위가 반대입니다: "
                f"start=0x{relative_start:X}, "
                f"end=0x{relative_end:X}"
            )

        if relative_start >= blob_size:
            raise NSFParseError(
                f"2차 테이블 엔트리 {index}의 시작값이 "
                f"blob 범위를 벗어납니다: "
                f"start=0x{relative_start:X}, "
                f"blob_size=0x{blob_size:X}"
            )

        if relative_end >= blob_size:
            raise NSFParseError(
                f"2차 테이블 엔트리 {index}의 끝값이 "
                f"blob 범위를 벗어납니다: "
                f"end=0x{relative_end:X}, "
                f"blob_size=0x{blob_size:X}"
            )

        if relative_start in starts:
            previous_index = starts[relative_start]

            raise NSFParseError(
                f"2차 테이블 시작값이 중복됩니다: "
                f"start=0x{relative_start:X}, "
                f"indices={previous_index},{index}"
            )

        starts[relative_start] = index


def build_entries(
    data: bytes,
    blob_offset: int,
    primary_table: list[dict],
    secondary_table: list[dict],
) -> tuple[list[dict], list[int]]:
    secondary_by_start = {
        entry["relative_start"]: entry
        for entry in secondary_table
    }

    entries = []
    used_secondary_indices = set()

    for primary in primary_table:
        primary_index = primary["index"]
        relative_start = primary["relative_start"]

        secondary = secondary_by_start.get(relative_start)

        if secondary is None:
            raise NSFParseError(
                f"1차 테이블 엔트리 {primary_index}와 "
                f"일치하는 2차 테이블 범위가 없습니다: "
                f"start=0x{relative_start:X}"
            )

        secondary_index = secondary["index"]
        relative_end = secondary["relative_end"]

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

        used_secondary_indices.add(secondary_index)

        entries.append(
            {
                "index": primary_index,
                "primary_index": primary_index,
                "secondary_index": secondary_index,
                "reference_value": primary[
                    "reference_value"
                ],
                "reference_value_hex": primary[
                    "reference_value_hex"
                ],
                # 기존 조사 스크립트와의 호환용 필드
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

    unreferenced_secondary_indices = [
        entry["index"]
        for entry in secondary_table
        if entry["index"] not in used_secondary_indices
    ]

    return entries, unreferenced_secondary_indices


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

    if blob_size <= 0:
        raise NSFParseError(
            f"잘못된 blob 크기입니다: "
            f"0x{blob_size:X}"
        )

    if blob_size > file_size:
        raise NSFParseError(
            f"blob 크기가 파일보다 큽니다: "
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

    calculated_blob_offset = (
        secondary_table_offset + secondary_table_size
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
    )

    validate_secondary_table(
        secondary_table=secondary_table,
        blob_size=blob_size,
    )

    entries, unreferenced_secondary_indices = build_entries(
        data=data,
        blob_offset=calculated_blob_offset,
        primary_table=primary_table,
        secondary_table=secondary_table,
    )

    warnings = []

    if unreferenced_secondary_indices:
        warnings.append(
            f"1차 테이블에서 직접 참조하지 않는 "
            f"2차 테이블 엔트리가 "
            f"{len(unreferenced_secondary_indices)}개 있습니다."
        )

    return {
        "format": "NSF",
        "file": source.name,
        "source": str(source),
        "file_size": file_size,
        "file_size_hex": f"0x{file_size:X}",
        "header": header,
        # 이전 분석 코드와의 호환용
        "count": primary_count,
        "primary_count": primary_count,
        "secondary_count": secondary_count,
        "layout": {
            "header_offset": 0,
            "header_offset_hex": "0x0",
            "header_size": HEADER_SIZE,
            "header_size_hex": (
                f"0x{HEADER_SIZE:X}"
            ),
            "primary_table_offset": (
                PRIMARY_TABLE_OFFSET
            ),
            "primary_table_offset_hex": (
                f"0x{PRIMARY_TABLE_OFFSET:X}"
            ),
            "primary_table_size": primary_table_size,
            "primary_table_size_hex": (
                f"0x{primary_table_size:X}"
            ),
            "secondary_table_offset": (
                secondary_table_offset
            ),
            "secondary_table_offset_hex": (
                f"0x{secondary_table_offset:X}"
            ),
            "secondary_table_size": (
                secondary_table_size
            ),
            "secondary_table_size_hex": (
                f"0x{secondary_table_size:X}"
            ),
            "blob_offset": calculated_blob_offset,
            "blob_offset_hex": (
                f"0x{calculated_blob_offset:X}"
            ),
            "blob_size": blob_size,
            "blob_size_hex": (
                f"0x{blob_size:X}"
            ),
        },
        "entry_order": "primary_table_order",
        "warnings": warnings,
        "unreferenced_secondary_indices": (
            unreferenced_secondary_indices
        ),
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
