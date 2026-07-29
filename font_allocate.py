#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from core.font_allocator import (
    DEFAULT_CAPACITY_REPORT,
    DEFAULT_OUTPUT,
    allocate_hangul,
    save_allocation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "번역문에 필요한 한글을 안전한 "
            "Shift-JIS/글리프 슬롯에 배정합니다."
        )
    )

    source = parser.add_mutually_exclusive_group(
        required=True
    )

    source.add_argument(
        "--text",
        help="직접 입력할 UTF-8 번역문",
    )
    source.add_argument(
        "--text-file",
        type=Path,
        help="UTF-8 또는 UTF-8-SIG 텍스트 파일",
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_CAPACITY_REPORT,
        help=(
            "textaware_font_capacity.json 경로"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="배정표 JSON 출력 경로",
    )

    return parser


def load_input_text(
    arguments: argparse.Namespace,
) -> str:
    if arguments.text is not None:
        return arguments.text

    path: Path = arguments.text_file

    if not path.is_file():
        raise FileNotFoundError(
            f"입력 파일이 없습니다: {path}"
        )

    return path.read_text(
        encoding="utf-8-sig",
    )


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()

    text = load_input_text(
        arguments
    )

    allocation = allocate_hangul(
        text,
        report_path=arguments.report,
    )

    save_allocation(
        allocation,
        arguments.output,
    )

    print("HANGUL FONT ALLOCATION")
    print("======================")
    print(
        f"UNIQUE HANGUL : "
        f"{allocation['unique_hangul_count']}"
    )
    print(
        f"SAFE CAPACITY : "
        f"{allocation['capacity']}"
    )
    print(
        f"REMAINING     : "
        f"{allocation['remaining_capacity']}"
    )
    print()

    for number, item in enumerate(
        allocation["allocations"],
        start=1,
    ):
        print(
            f"{number:2d}. "
            f"{item['hangul']} "
            f"{item['hangul_unicode']} "
            f"-> SJIS={item['sjis']} "
            f"TABLE={item['table_index_hex']} "
            f"GLYPH={item['glyph_index_hex']} "
            f"REPLACES={item['replaced_character']!r}"
        )

    print()
    print("OUTPUT:", arguments.output)
    print("STATUS: PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
