#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from core.font_allocator import (
    DEFAULT_CAPACITY_REPORT,
    DEFAULT_OUTPUT,
    allocate_hangul,
    save_allocation,
)
from core.font_builder import (
    DEFAULT_ALLOCATION,
    DEFAULT_OUTPUT_DIR,
    build_font_patch,
)


def load_text_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(
            f"입력 파일이 없습니다: {path}"
        )

    return path.read_text(
        encoding="utf-8-sig",
    )


def run_capacity(
    arguments: argparse.Namespace,
) -> int:
    from probe_textaware_font_capacity import (
        main as capacity_main,
    )

    return int(
        capacity_main()
    )


def run_allocate(
    arguments: argparse.Namespace,
) -> int:
    if arguments.text is not None:
        source_text = arguments.text
        source_description = "command line"
    else:
        source_text = load_text_file(
            arguments.text_file
        )
        source_description = str(
            arguments.text_file
        )

    allocation = allocate_hangul(
        source_text,
        report_path=arguments.report,
    )

    save_allocation(
        allocation,
        arguments.output,
    )

    print("HANGUL FONT ALLOCATION")
    print("======================")
    print(
        f"SOURCE        : "
        f"{source_description}"
    )
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
            f"{number:3d}. "
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


def run_build(
    arguments: argparse.Namespace,
) -> int:
    manifest = build_font_patch(
        allocation_path=arguments.allocation,
        patches_path=arguments.patches,
        output_dir=arguments.output_dir,
    )

    print("FONT BUILD")
    print("==========")
    print(
        f"GLYPHS       : "
        f"{manifest['glyph_count']}"
    )
    print(
        f"TEXT PATCHES : "
        f"{manifest['text_patch_count']}"
    )
    print(
        f"TXP SIZE     : "
        f"0x{manifest['txp']['original_size']:X} "
        f"-> "
        f"0x{manifest['txp']['patched_size']:X}"
    )
    print(
        f"TXP HEIGHT   : "
        f"{manifest['txp']['height']}"
    )
    print(
        f"START SIZE   : "
        f"0x{manifest['start']['original_size']:X} "
        f"-> "
        f"0x{manifest['start']['patched_size']:X}"
    )
    print()

    for patch in manifest[
        "text_patches"
    ]:
        print(
            f"{patch['resource']}"
            f"+{patch['offset_hex']} "
            f"{patch['source']!r} "
            f"-> "
            f"{patch['translation']!r}"
        )

    print()
    print(
        "SYSTEM  :",
        manifest["outputs"]["system"],
    )
    print(
        "PREVIEW :",
        manifest["outputs"]["preview"],
    )
    print(
        "MANIFEST:",
        manifest["outputs"]["manifest"],
    )
    print("STATUS: PASS")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toolkit.py font",
        description=(
            "Prinny 글꼴 용량 조사, 한글 배정, "
            "글꼴 및 텍스트 빌드 도구"
        ),
    )

    subparsers = parser.add_subparsers(
        dest="font_command",
        required=True,
        metavar="{capacity,allocate,build}",
    )

    capacity_parser = subparsers.add_parser(
        "capacity",
        help="재활용 가능한 글리프 슬롯을 조사합니다.",
    )
    capacity_parser.set_defaults(
        handler=run_capacity,
    )

    allocate_parser = subparsers.add_parser(
        "allocate",
        help=(
            "한글을 Shift-JIS 코드와 "
            "글리프 슬롯에 배정합니다."
        ),
    )

    source_group = (
        allocate_parser
        .add_mutually_exclusive_group(
            required=True
        )
    )

    source_group.add_argument(
        "--text",
        help="명령행 UTF-8 문자열",
    )
    source_group.add_argument(
        "--text-file",
        type=Path,
        help="UTF-8 또는 UTF-8-SIG 파일",
    )

    allocate_parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_CAPACITY_REPORT,
    )
    allocate_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    allocate_parser.set_defaults(
        handler=run_allocate,
    )

    build_parser_command = (
        subparsers.add_parser(
            "build",
            help=(
                "배정표와 텍스트 패치 문서로 "
                "SYSTEM.DAT를 빌드합니다."
            ),
        )
    )

    build_parser_command.add_argument(
        "--allocation",
        type=Path,
        default=DEFAULT_ALLOCATION,
        help=(
            "한글 배정표 JSON "
            "(기본값: workspace/font/hangul_map.json)"
        ),
    )
    build_parser_command.add_argument(
        "--patches",
        type=Path,
        required=True,
        help="텍스트 패치 정의 JSON",
    )
    build_parser_command.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "빌드 출력 폴더 "
            "(기본값: workspace/build/font)"
        ),
    )
    build_parser_command.set_defaults(
        handler=run_build,
    )

    return parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(
        argv
    )

    try:
        return int(
            arguments.handler(
                arguments
            )
        )
    except (
        FileNotFoundError,
        KeyError,
        UnicodeError,
        ValueError,
        RuntimeError,
    ) as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
