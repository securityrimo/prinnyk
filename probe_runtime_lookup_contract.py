#!/usr/bin/env python3
from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path
from types import FunctionType
from typing import Iterable


MODULE_NAME = "core.font_runtime"

REPORTS = [
    Path("workspace/reports/exact_font_lookup_function.txt"),
    Path("workspace/reports/font_lookup_dataflow.txt"),
    Path("workspace/reports/exact_font_runtime_map.txt"),
    Path("workspace/reports/runtime_font_map_analysis.txt"),
    Path("workspace/reports/font_packed_jis_verify.txt"),
    Path("workspace/reports/font_sjis_dense_verify.txt"),
    Path("workspace/reports/font_table_at_glyphs.txt"),
    Path("workspace/reports/font_txp_runtime_parser.txt"),
]

KEYWORDS = (
    "packed",
    "shift_jis",
    "sjis",
    "jis",
    "glyph",
    "table_index",
    "font.fnt",
    "font.txp",
    "pixel_offset",
    "0x244e",
    "0x3665",
    "8b e3",
    "4e5d",
    "九",
    "の",
)

REPORT_PATTERN = re.compile(
    r"九|の|8B[ :]?E3|82[ :]?CC|"
    r"3665|244E|4E5D|306E|"
    r"glyph|packed|SJIS|JIS|font\.fnt|font\.txp",
    re.IGNORECASE,
)


def source_of(obj: object) -> str | None:
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):
        return None


def matching_ranges(
    lines: list[str],
    *,
    radius: int = 5,
) -> list[tuple[int, int]]:
    hits: list[int] = []

    for index, line in enumerate(lines):
        lowered = line.casefold()

        if any(
            keyword.casefold() in lowered
            for keyword in KEYWORDS
        ):
            hits.append(index)

    ranges: list[tuple[int, int]] = []

    for hit in hits:
        start = max(0, hit - radius)
        end = min(len(lines), hit + radius + 1)

        if ranges and start <= ranges[-1][1]:
            previous_start, previous_end = ranges[-1]
            ranges[-1] = (
                previous_start,
                max(previous_end, end),
            )
        else:
            ranges.append((start, end))

    return ranges


def print_source_excerpt(
    title: str,
    obj: object,
) -> None:
    source = source_of(obj)

    if source is None:
        return

    lines = source.splitlines()
    ranges = matching_ranges(lines)

    if not ranges:
        return

    print()
    print("=" * 78)
    print(title)

    try:
        print("SIGNATURE:", inspect.signature(obj))
    except (TypeError, ValueError):
        pass

    print("-" * 78)

    for start, end in ranges:
        for index in range(start, end):
            print(
                f"{index + 1:4d}: {lines[index]}"
            )

        print("   ...")


def iter_module_functions(
    module: object,
) -> Iterable[tuple[str, FunctionType]]:
    for name, obj in sorted(
        vars(module).items()
    ):
        if inspect.isfunction(obj):
            yield name, obj


def iter_class_methods(
    module: object,
) -> Iterable[tuple[str, FunctionType]]:
    for class_name, cls in sorted(
        inspect.getmembers(
            module,
            inspect.isclass,
        )
    ):
        if cls.__module__ != MODULE_NAME:
            continue

        for method_name, method in sorted(
            inspect.getmembers(
                cls,
                inspect.isfunction,
            )
        ):
            yield (
                f"{class_name}.{method_name}",
                method,
            )


def print_report_matches(path: Path) -> None:
    print()
    print("=" * 78)
    print("REPORT:", path)
    print("-" * 78)

    if not path.is_file():
        print("MISSING")
        return

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    lines = text.splitlines()

    hits = [
        index
        for index, line in enumerate(lines)
        if REPORT_PATTERN.search(line)
    ]

    if not hits:
        print("관련 줄 없음")
        return

    printed: set[int] = set()
    output_count = 0

    for hit in hits:
        start = max(0, hit - 3)
        end = min(len(lines), hit + 4)

        for index in range(start, end):
            if index in printed:
                continue

            printed.add(index)
            print(
                f"{index + 1:5d}: {lines[index]}"
            )
            output_count += 1

            if output_count >= 180:
                print("... 출력 제한 도달 ...")
                return


def main() -> int:
    module = importlib.import_module(
        MODULE_NAME
    )

    print("RUNTIME FONT LOOKUP CONTRACT")
    print("============================")
    print("MODULE:", MODULE_NAME)
    print("SOURCE:", inspect.getsourcefile(module))

    print()
    print("PUBLIC CALLABLES")
    print("----------------")

    for name, obj in sorted(
        vars(module).items()
    ):
        if name.startswith("_"):
            continue

        if not (
            inspect.isfunction(obj)
            or inspect.isclass(obj)
        ):
            continue

        try:
            signature = inspect.signature(obj)
        except (TypeError, ValueError):
            signature = "(signature unavailable)"

        print(
            f"{name}: {signature}"
        )

    for name, function in iter_module_functions(
        module
    ):
        print_source_excerpt(
            f"FUNCTION: {name}",
            function,
        )

    for name, method in iter_class_methods(
        module
    ):
        print_source_excerpt(
            f"METHOD: {name}",
            method,
        )

    for report in REPORTS:
        print_report_matches(report)

    print()
    print("=" * 78)
    print("LOOKUP CONSTANTS TO VERIFY")
    print("-" * 78)
    print("の:")
    print("  Unicode : U+306E")
    print("  SJIS    : 82 CC")
    print("  JIS     : 24 4E")
    print("  known TXP slot from successful canary: 0x011A")
    print()
    print("九:")
    print("  Unicode : U+4E5D")
    print("  SJIS    : 8B E3")
    print("  JIS     : 36 65")
    print("  current guessed slot: 0x0320")
    print()
    print("STATUS: REPORT COMPLETE")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
