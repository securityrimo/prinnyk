#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from pathlib import Path


DEFAULT_FNT = Path(
    "workspace/unpack/START_runtime/font.fnt"
)
DEFAULT_TXP = Path(
    "workspace/unpack/START_runtime/font.txp"
)
DEFAULT_REPORT = Path(
    "workspace/reports/font_capacity.json"
)

DEFAULT_PIXEL_OFFSET = 0x50
DEFAULT_BYTES_PER_GLYPH = 0x8C
DEFAULT_HANGUL_TARGET = 2350


def parse_integer(value: str) -> int:
    return int(value, 0)


def compress_ranges(
    values: list[int],
) -> list[dict[str, int | str]]:
    if not values:
        return []

    sorted_values = sorted(set(values))
    output: list[dict[str, int | str]] = []

    start = sorted_values[0]
    previous = start

    for value in sorted_values[1:]:
        if value == previous + 1:
            previous = value
            continue

        output.append(
            {
                "start": start,
                "end": previous,
                "start_hex": f"0x{start:04X}",
                "end_hex": f"0x{previous:04X}",
                "count": previous - start + 1,
            }
        )

        start = value
        previous = value

    output.append(
        {
            "start": start,
            "end": previous,
            "start_hex": f"0x{start:04X}",
            "end_hex": f"0x{previous:04X}",
            "count": previous - start + 1,
        }
    )

    return output


def load_font_table(
    path: Path,
) -> tuple[int, list[int]]:
    data = path.read_bytes()

    if len(data) < 2:
        raise ValueError(
            f"font.fnt가 너무 작습니다: {path}"
        )

    table_count = struct.unpack_from(
        "<H",
        data,
        0,
    )[0]

    expected_size = 2 + table_count * 2

    if len(data) != expected_size:
        raise ValueError(
            "font.fnt 크기가 테이블 항목 수와 "
            f"일치하지 않습니다: "
            f"actual=0x{len(data):X}, "
            f"expected=0x{expected_size:X}"
        )

    table = list(
        struct.unpack_from(
            f"<{table_count}H",
            data,
            2,
        )
    )

    return table_count, table


def analyze_glyphs(
    path: Path,
    pixel_offset: int,
    bytes_per_glyph: int,
) -> tuple[int, set[int], set[int]]:
    data = path.read_bytes()

    if pixel_offset < 0:
        raise ValueError(
            "pixel offset은 0 이상이어야 합니다."
        )

    if bytes_per_glyph < 1:
        raise ValueError(
            "bytes per glyph는 1 이상이어야 합니다."
        )

    if len(data) < pixel_offset:
        raise ValueError(
            "font.txp가 pixel offset보다 작습니다."
        )

    payload = data[pixel_offset:]

    if len(payload) % bytes_per_glyph != 0:
        raise ValueError(
            "font.txp 픽셀 데이터 크기가 "
            "글리프 크기로 나누어떨어지지 않습니다: "
            f"payload=0x{len(payload):X}, "
            f"glyph=0x{bytes_per_glyph:X}"
        )

    glyph_count = (
        len(payload) // bytes_per_glyph
    )

    zero_glyphs: set[int] = set()
    uniform_glyphs: set[int] = set()

    for index in range(glyph_count):
        start = index * bytes_per_glyph
        end = start + bytes_per_glyph
        block = payload[start:end]

        if not any(block):
            zero_glyphs.add(index)

        if len(set(block)) == 1:
            uniform_glyphs.add(index)

    return (
        glyph_count,
        zero_glyphs,
        uniform_glyphs,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prinny 런타임 폰트의 글리프 및 "
            "매핑 여유 용량을 분석합니다."
        )
    )

    parser.add_argument(
        "--font-fnt",
        type=Path,
        default=DEFAULT_FNT,
    )
    parser.add_argument(
        "--font-txp",
        type=Path,
        default=DEFAULT_TXP,
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
    )
    parser.add_argument(
        "--pixel-offset",
        type=parse_integer,
        default=DEFAULT_PIXEL_OFFSET,
    )
    parser.add_argument(
        "--bytes-per-glyph",
        type=parse_integer,
        default=DEFAULT_BYTES_PER_GLYPH,
    )
    parser.add_argument(
        "--target",
        type=int,
        default=DEFAULT_HANGUL_TARGET,
        help="비교할 목표 글리프 수",
    )

    args = parser.parse_args()

    if args.target < 0:
        raise ValueError(
            "--target은 0 이상이어야 합니다."
        )

    table_count, table = load_font_table(
        args.font_fnt
    )

    (
        glyph_count,
        zero_glyphs,
        uniform_glyphs,
    ) = analyze_glyphs(
        args.font_txp,
        args.pixel_offset,
        args.bytes_per_glyph,
    )

    invalid_mappings = [
        {
            "table_index": index,
            "glyph_index": glyph_index,
        }
        for index, glyph_index in enumerate(table)
        if glyph_index >= glyph_count
    ]

    reference_counts = Counter(table)

    referenced_glyphs = {
        glyph_index
        for glyph_index in table
        if glyph_index < glyph_count
    }

    all_glyphs = set(range(glyph_count))

    unreferenced_glyphs = sorted(
        all_glyphs - referenced_glyphs
    )

    unreferenced_zero_glyphs = sorted(
        set(unreferenced_glyphs)
        & zero_glyphs
    )

    unreferenced_uniform_glyphs = sorted(
        set(unreferenced_glyphs)
        & uniform_glyphs
    )

    duplicate_references = sum(
        count - 1
        for count in reference_counts.values()
        if count > 1
    )

    zero_mapped_table_entries = (
        reference_counts.get(0, 0)
    )

    report = {
        "format": "prinny_font_capacity_v1",
        "font_fnt": {
            "path": str(args.font_fnt),
            "size": args.font_fnt.stat().st_size,
            "table_entries": table_count,
        },
        "font_txp": {
            "path": str(args.font_txp),
            "size": args.font_txp.stat().st_size,
            "pixel_offset": args.pixel_offset,
            "bytes_per_glyph": (
                args.bytes_per_glyph
            ),
            "glyph_count": glyph_count,
        },
        "mapping": {
            "unique_referenced_glyphs": (
                len(referenced_glyphs)
            ),
            "unreferenced_glyphs": (
                len(unreferenced_glyphs)
            ),
            "duplicate_table_references": (
                duplicate_references
            ),
            "zero_mapped_table_entries": (
                zero_mapped_table_entries
            ),
            "invalid_mapping_count": (
                len(invalid_mappings)
            ),
            "invalid_mappings": invalid_mappings,
        },
        "bitmap": {
            "all_zero_glyphs": len(zero_glyphs),
            "uniform_glyphs": (
                len(uniform_glyphs)
            ),
            "unreferenced_zero_glyphs": (
                len(unreferenced_zero_glyphs)
            ),
            "unreferenced_uniform_glyphs": (
                len(unreferenced_uniform_glyphs)
            ),
        },
        "capacity": {
            "target": args.target,
            "unused_only_capacity": (
                len(unreferenced_glyphs)
            ),
            "unused_only_shortfall": max(
                0,
                args.target
                - len(unreferenced_glyphs),
            ),
            "total_existing_slots": glyph_count,
            "total_slot_shortfall": max(
                0,
                args.target - glyph_count,
            ),
        },
        "candidates": {
            "unreferenced_indices": (
                unreferenced_glyphs
            ),
            "unreferenced_ranges": (
                compress_ranges(
                    unreferenced_glyphs
                )
            ),
            "unreferenced_zero_indices": (
                unreferenced_zero_glyphs
            ),
            "unreferenced_zero_ranges": (
                compress_ranges(
                    unreferenced_zero_glyphs
                )
            ),
        },
        "most_referenced": [
            {
                "glyph_index": glyph_index,
                "glyph_hex": (
                    f"0x{glyph_index:04X}"
                ),
                "reference_count": count,
            }
            for glyph_index, count
            in reference_counts.most_common(20)
        ],
    }

    args.report.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.report.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("FONT CAPACITY PROBE")
    print("===================")
    print(
        f"FNT TABLE ENTRIES      : "
        f"{table_count}"
    )
    print(
        f"GLYPH SLOTS           : "
        f"{glyph_count}"
    )
    print(
        f"UNIQUE REFERENCED     : "
        f"{len(referenced_glyphs)}"
    )
    print(
        f"UNREFERENCED SLOTS    : "
        f"{len(unreferenced_glyphs)}"
    )
    print(
        f"ZERO-MAPPED CODES     : "
        f"{zero_mapped_table_entries}"
    )
    print(
        f"ZERO BITMAP GLYPHS    : "
        f"{len(zero_glyphs)}"
    )
    print(
        f"UNREF + ZERO BITMAP   : "
        f"{len(unreferenced_zero_glyphs)}"
    )
    print(
        f"DUPLICATE REFERENCES : "
        f"{duplicate_references}"
    )
    print(
        f"INVALID MAPPINGS      : "
        f"{len(invalid_mappings)}"
    )
    print()
    print(
        f"TARGET                : "
        f"{args.target}"
    )
    print(
        f"UNUSED-ONLY SHORTFALL : "
        f"{report['capacity']['unused_only_shortfall']}"
    )
    print(
        f"TOTAL-SLOT SHORTFALL  : "
        f"{report['capacity']['total_slot_shortfall']}"
    )

    if unreferenced_glyphs:
        sample = " ".join(
            f"0x{value:04X}"
            for value in unreferenced_glyphs[:32]
        )
        print()
        print(
            "UNREFERENCED SAMPLE   :",
            sample,
        )

    print()
    print("REPORT:", args.report)

    return 0 if not invalid_mappings else 1


if __name__ == "__main__":
    raise SystemExit(main())
