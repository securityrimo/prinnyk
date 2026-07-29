#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.font_runtime import (
    DEFAULT_FNT,
    DEFAULT_IMAGE,
    DEFAULT_REPORT,
    DEFAULT_TXP,
    KNOWN,
    FontRuntime,
    FontRuntimeError,
)
from core.pipeline import analyze
from core.start_runtime import (
    DEFAULT_MANIFEST as DEFAULT_START_MANIFEST,
    DEFAULT_OUTPUT as DEFAULT_START_OUTPUT,
    DEFAULT_START,
    StartRuntimeError,
    run_extract as run_start_extract,
)
from core.system_unpack import (
    DEFAULT_MANIFEST as DEFAULT_SYSTEM_MANIFEST,
    DEFAULT_OUTPUT as DEFAULT_SYSTEM_OUTPUT,
    DEFAULT_SYSTEM,
    run_unpack as run_system_unpack,
)


def add_font_paths(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument(
        "--font-fnt",
        type=Path,
        default=DEFAULT_FNT,
        help=(
            "font.fnt 경로 "
            f"(기본값: {DEFAULT_FNT})"
        ),
    )

    parser.add_argument(
        "--font-txp",
        type=Path,
        default=DEFAULT_TXP,
        help=(
            "font.txp 경로 "
            f"(기본값: {DEFAULT_TXP})"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="PrinnyReverseToolkit",
        description=(
            "Prinny PSP 파일 분석 및 "
            "한글 패치 제작 도구"
        ),
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    analyze_parser = commands.add_parser(
        "analyze",
        help="파일 구조를 분석합니다.",
    )

    analyze_parser.add_argument(
        "file",
        type=Path,
        help="분석할 파일 경로",
    )

    analyze_parser.set_defaults(
        handler=run_analyze,
    )

    unpack_start_parser = commands.add_parser(
        "unpack-start",
        help=(
            "start.dat의 런타임 자원을 "
            "올바른 레코드 구조로 추출합니다."
        ),
    )

    unpack_start_parser.add_argument(
        "--start",
        type=Path,
        default=DEFAULT_START,
        help=(
            "start.dat 경로 "
            f"(기본값: {DEFAULT_START})"
        ),
    )

    unpack_start_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_START_OUTPUT,
        help=(
            "자원 출력 디렉터리 "
            f"(기본값: {DEFAULT_START_OUTPUT})"
        ),
    )

    unpack_start_parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_START_MANIFEST,
        help=(
            "manifest JSON 경로 "
            f"(기본값: {DEFAULT_START_MANIFEST})"
        ),
    )

    unpack_start_parser.set_defaults(
        handler=run_unpack_start,
    )

    unpack_system_parser = commands.add_parser(
        "unpack-system",
        help=(
            "SYSTEM.DAT에서 start.lzs를 추출하고 "
            "start.dat으로 압축 해제합니다."
        ),
    )
    unpack_system_parser.add_argument(
        "--system",
        type=Path,
        default=DEFAULT_SYSTEM,
        help=(
            "SYSTEM.DAT 경로 "
            f"(기본값: {DEFAULT_SYSTEM})"
        ),
    )
    unpack_system_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SYSTEM_OUTPUT,
        help=(
            "start.lzs/start.dat 출력 디렉터리 "
            f"(기본값: {DEFAULT_SYSTEM_OUTPUT})"
        ),
    )
    unpack_system_parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_SYSTEM_MANIFEST,
        help=(
            "manifest JSON 경로 "
            f"(기본값: {DEFAULT_SYSTEM_MANIFEST})"
        ),
    )
    unpack_system_parser.add_argument(
        "--force",
        action="store_true",
        help="기존 출력이 다를 때 덮어씁니다.",
    )
    unpack_system_parser.set_defaults(
        handler=run_unpack_system,
    )

    font_parser = commands.add_parser(
        "font",
        help=(
            "런타임 폰트를 분석하거나 "
            "렌더링합니다."
        ),
    )

    font_commands = font_parser.add_subparsers(
        dest="font_command",
        required=True,
    )

    verify_parser = font_commands.add_parser(
        "verify",
        help=(
            "확정된 폰트 구조를 "
            "자동 검증합니다."
        ),
    )

    add_font_paths(
        verify_parser
    )

    verify_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_IMAGE,
        help=(
            "검증용 PNG 출력 경로 "
            f"(기본값: {DEFAULT_IMAGE})"
        ),
    )

    verify_parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help=(
            "검증 JSON 출력 경로 "
            f"(기본값: {DEFAULT_REPORT})"
        ),
    )

    verify_parser.add_argument(
        "--scale",
        type=int,
        default=8,
        help="글리프 확대 배율",
    )

    verify_parser.set_defaults(
        handler=run_font_verify,
    )

    sample_parser = font_commands.add_parser(
        "sample",
        help=(
            "문자열을 게임 폰트로 "
            "렌더링합니다."
        ),
    )

    add_font_paths(
        sample_parser
    )

    sample_parser.add_argument(
        "text",
        help=(
            "렌더링할 Shift-JIS 지원 문자열"
        ),
    )

    sample_parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "workspace/reports/"
            "font_sample.png"
        ),
        help="샘플 PNG 출력 경로",
    )

    sample_parser.add_argument(
        "--scale",
        type=int,
        default=8,
        help="글리프 확대 배율",
    )

    sample_parser.set_defaults(
        handler=run_font_sample,
    )

    return parser


def print_title(
    title: str,
) -> None:
    print("=" * 60)
    print(title)
    print("=" * 60)


def run_analyze(
    args: argparse.Namespace,
) -> int:
    print_title(
        "PrinnyReverseToolkit - Analyze"
    )

    output = analyze(
        str(args.file)
    )

    print()
    print("SAVED:")
    print(output)

    return 0


def run_unpack_start(
    args: argparse.Namespace,
) -> int:
    return run_start_extract(
        args
    )


def run_unpack_system(
    args: argparse.Namespace,
) -> int:
    return run_system_unpack(
        args
    )


def load_font_runtime(
    args: argparse.Namespace,
) -> FontRuntime:
    return FontRuntime.load(
        fnt_path=args.font_fnt,
        txp_path=args.font_txp,
    )


def run_font_verify(
    args: argparse.Namespace,
) -> int:
    if args.scale < 1:
        raise ValueError(
            "--scale은 1 이상이어야 합니다."
        )

    runtime = load_font_runtime(
        args
    )

    result = runtime.verify()

    runtime.render_sample(
        KNOWN.keys(),
        args.output,
        args.scale,
    )

    args.report.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.report.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print_title(
        "PrinnyReverseToolkit - Font Verify"
    )

    print(
        "FONT.FNT ENTRIES :",
        f"0x{result['table_entries']:X}",
        f"({result['table_entries']})",
    )

    print(
        "TABLE COUNT MATCH:",
        result["table_count_match"],
    )

    print(
        "TXP              :",
        f"{runtime.txp['width']}×"
        f"{runtime.txp['height']}",
    )

    print(
        "PIXEL OFFSET     :",
        f"0x{runtime.txp['pixel_offset']:X}",
    )

    print(
        "GLYPH            :",
        f"{runtime.txp['width']}×"
        f"{runtime.txp['glyph_height']},",
        f"0x{runtime.txp['bytes_per_glyph']:X}",
        "bytes",
    )

    print(
        "GLYPH COUNT      :",
        f"0x{runtime.txp['glyph_count']:X}",
        f"({runtime.txp['glyph_count']})",
    )

    print(
        "GLYPH COUNT MATCH:",
        result["glyph_count_match"],
    )

    print(
        "INVALID MAP VALUES:",
        result["invalid_table_values"],
    )

    print()

    for check in result["checks"]:
        state = (
            "MATCH"
            if check["ok"]
            else "MISMATCH"
        )

        print(
            f"{check['character']} "
            f"SJIS={check['shift_jis']} "
            f"TABLE=0x"
            f"{check['table_index']:04X} "
            f"GLYPH=0x"
            f"{check['glyph_index']:04X} "
            f"{state}"
        )

    print()

    print(
        "SELF TEST:",
        f"{result['matched']}/"
        f"{result['total']}",
    )

    print(
        "REPORT   :",
        args.report,
    )

    print(
        "IMAGE    :",
        args.output,
    )

    all_valid = (
        result["matched"]
        == result["total"]
        and result["table_count_match"]
        and result["glyph_count_match"]
        and result["invalid_table_values"]
        == 0
    )

    return 0 if all_valid else 1


def run_font_sample(
    args: argparse.Namespace,
) -> int:
    if not args.text:
        raise ValueError(
            "렌더링할 문자열이 비어 있습니다."
        )

    if args.scale < 1:
        raise ValueError(
            "--scale은 1 이상이어야 합니다."
        )

    runtime = load_font_runtime(
        args
    )

    mappings = runtime.render_sample(
        args.text,
        args.output,
        args.scale,
    )

    print_title(
        "PrinnyReverseToolkit - Font Sample"
    )

    for mapping in mappings:
        print(
            f"{mapping['character']} "
            f"{mapping['unicode']} "
            f"SJIS={mapping['shift_jis']} "
            f"TABLE=0x"
            f"{mapping['table_index']:04X} "
            f"GLYPH=0x"
            f"{mapping['glyph_index']:04X}"
        )

    print()

    print(
        "IMAGE:",
        args.output,
    )

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.handler(
            args
        )

    except (
        FileNotFoundError,
        FontRuntimeError,
        StartRuntimeError,
        ValueError,
        OSError,
    ) as error:
        print(
            f"ERROR: {error}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
