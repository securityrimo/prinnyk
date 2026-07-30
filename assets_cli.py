#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from core.assets_scanner import (
    DEFAULT_OUTPUT_DIR,
    scan_assets,
    save_asset_report,
)


def run_scan(
    arguments: argparse.Namespace,
) -> int:
    report = scan_assets(
        roots=arguments.root,
        scan_embedded=(
            not arguments.no_embedded
        ),
    )

    save_asset_report(
        report,
        output_dir=arguments.output_dir,
    )

    print("PRINNY ASSET INVENTORY")
    print("======================")
    print(
        f"FILES           : "
        f"{report['file_count']}"
    )
    print(
        f"EMBEDDED ASSETS : "
        f"{report['embedded_asset_count']}"
    )
    print(
        f"UI CANDIDATES   : "
        f"{report['ui_candidate_count']}"
    )
    print()
    print(
        "OUTPUT:",
        arguments.output_dir,
    )
    print("STATUS: PASS")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toolkit.py assets",
        description=(
            "게임 이미지·UI·미디어 자산을 "
            "검색하고 인벤토리화합니다."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="assets_command",
        required=True,
    )

    scan_parser = subparsers.add_parser(
        "scan",
        help=(
            "파일과 컨테이너 내부의 이미지 "
            "시그니처를 조사합니다."
        ),
    )
    scan_parser.add_argument(
        "--root",
        type=Path,
        action="append",
        default=None,
        help=(
            "조사할 폴더. 여러 번 지정할 수 있습니다. "
            "생략하면 START_runtime과 PSP_GAME을 조사합니다."
        ),
    )
    scan_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    scan_parser.add_argument(
        "--no-embedded",
        action="store_true",
        help="컨테이너 내부 시그니처 검색을 생략합니다.",
    )
    scan_parser.set_defaults(
        handler=run_scan,
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
        OSError,
        ValueError,
        RuntimeError,
    ) as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
