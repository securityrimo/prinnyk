#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_REPORT = Path(
    "workspace/reports/hangul_inventory.json"
)
DEFAULT_CHARS = Path(
    "workspace/reports/hangul_chars.txt"
)
DEFAULT_CAPACITY = 2333

AUTO_PATTERNS = (
    "prinny_translations.json",
    "*translation*.json",
    "*translated*.json",
    "*korean*.json",
    "workspace/**/*translation*.json",
    "workspace/**/*translated*.json",
    "workspace/**/*korean*.json",
    "*translation*.txt",
    "workspace/**/*translation*.txt",
)


def is_hangul_syllable(character: str) -> bool:
    codepoint = ord(character)
    return 0xAC00 <= codepoint <= 0xD7A3


def is_hangul_jamo(character: str) -> bool:
    codepoint = ord(character)

    return (
        0x1100 <= codepoint <= 0x11FF
        or 0x3130 <= codepoint <= 0x318F
        or 0xA960 <= codepoint <= 0xA97F
        or 0xD7B0 <= codepoint <= 0xD7FF
    )


def is_hangul(character: str) -> bool:
    return (
        is_hangul_syllable(character)
        or is_hangul_jamo(character)
    )


def iter_json_strings(value: Any):
    if isinstance(value, str):
        yield value
        return

    if isinstance(value, dict):
        for child in value.values():
            yield from iter_json_strings(child)
        return

    if isinstance(value, list):
        for child in value:
            yield from iter_json_strings(child)


def read_text(path: Path) -> str:
    raw = path.read_bytes()

    for encoding in (
        "utf-8-sig",
        "utf-8",
        "cp949",
    ):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise UnicodeError(
        f"텍스트 인코딩을 판별하지 못했습니다: {path}"
    )


def collect_strings(path: Path) -> list[str]:
    suffix = path.suffix.lower()

    if suffix == ".json":
        data = json.loads(
            read_text(path)
        )
        return list(iter_json_strings(data))

    if suffix in {
        ".txt",
        ".csv",
        ".tsv",
        ".md",
    }:
        return [read_text(path)]

    raise ValueError(
        f"지원하지 않는 파일 형식입니다: {path}"
    )


def discover_files() -> list[Path]:
    found: set[Path] = set()

    for pattern in AUTO_PATTERNS:
        for path in Path(".").glob(pattern):
            if not path.is_file():
                continue

            if ".git" in path.parts:
                continue

            if (
                path.parent
                == Path("workspace/reports")
            ):
                continue

            found.add(path)

    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "번역 파일에서 실제 사용되는 "
            "한글 고유문자를 수집합니다."
        )
    )

    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "분석할 JSON/TXT/CSV 파일. "
            "생략하면 번역 파일을 자동 검색합니다."
        ),
    )
    parser.add_argument(
        "--capacity",
        type=int,
        default=DEFAULT_CAPACITY,
        help="font.txp에 비파괴 추가 가능한 글리프 수",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
    )
    parser.add_argument(
        "--chars",
        type=Path,
        default=DEFAULT_CHARS,
    )

    args = parser.parse_args()

    if args.capacity < 0:
        raise ValueError(
            "--capacity는 0 이상이어야 합니다."
        )

    paths = args.paths or discover_files()

    paths = [
        path
        for path in paths
        if path.is_file()
    ]

    if not paths:
        print("HANGUL INVENTORY")
        print("================")
        print("분석할 번역 파일을 찾지 못했습니다.")
        print()
        print(
            "사용 예: python3 "
            "probe_hangul_inventory.py "
            "번역파일.json"
        )
        return 2

    total_counter: Counter[str] = Counter()
    per_file: list[dict[str, object]] = []

    for path in paths:
        file_counter: Counter[str] = Counter()
        strings = collect_strings(path)

        for text in strings:
            file_counter.update(
                character
                for character in text
                if is_hangul(character)
            )

        total_counter.update(file_counter)

        per_file.append(
            {
                "path": str(path),
                "string_values": len(strings),
                "hangul_occurrences": sum(
                    file_counter.values()
                ),
                "unique_hangul": len(file_counter),
            }
        )

    syllables = sorted(
        character
        for character in total_counter
        if is_hangul_syllable(character)
    )

    jamo = sorted(
        character
        for character in total_counter
        if is_hangul_jamo(character)
    )

    all_characters = sorted(total_counter)
    required_glyphs = len(all_characters)
    remaining = args.capacity - required_glyphs

    frequency_order = sorted(
        total_counter.items(),
        key=lambda item: (
            -item[1],
            ord(item[0]),
        ),
    )

    report = {
        "format": "prinny_hangul_inventory_v1",
        "input_files": per_file,
        "capacity": {
            "append_capacity": args.capacity,
            "required_glyphs": required_glyphs,
            "remaining_slots": max(0, remaining),
            "shortfall": max(0, -remaining),
            "fits": required_glyphs <= args.capacity,
        },
        "summary": {
            "unique_hangul": required_glyphs,
            "unique_syllables": len(syllables),
            "unique_jamo": len(jamo),
            "total_occurrences": sum(
                total_counter.values()
            ),
        },
        "characters_by_codepoint": [
            {
                "character": character,
                "codepoint": ord(character),
                "codepoint_hex": (
                    f"U+{ord(character):04X}"
                ),
                "count": total_counter[character],
                "type": (
                    "syllable"
                    if is_hangul_syllable(character)
                    else "jamo"
                ),
            }
            for character in all_characters
        ],
        "characters_by_frequency": [
            {
                "character": character,
                "codepoint_hex": (
                    f"U+{ord(character):04X}"
                ),
                "count": count,
            }
            for character, count in frequency_order
        ],
    }

    args.report.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.chars.parent.mkdir(
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

    args.chars.write_text(
        "".join(all_characters) + "\n",
        encoding="utf-8",
    )

    print("HANGUL INVENTORY")
    print("================")
    print(f"INPUT FILES       : {len(paths)}")
    print(
        f"TOTAL OCCURRENCES : "
        f"{sum(total_counter.values())}"
    )
    print(
        f"UNIQUE SYLLABLES  : "
        f"{len(syllables)}"
    )
    print(
        f"UNIQUE JAMO       : "
        f"{len(jamo)}"
    )
    print(
        f"REQUIRED GLYPHS   : "
        f"{required_glyphs}"
    )
    print(
        f"APPEND CAPACITY   : "
        f"{args.capacity}"
    )
    print(
        f"REMAINING SLOTS   : "
        f"{max(0, remaining)}"
    )
    print(
        f"SHORTFALL         : "
        f"{max(0, -remaining)}"
    )
    print(
        f"FITS              : "
        f"{required_glyphs <= args.capacity}"
    )
    print()
    print("REPORT:", args.report)
    print("CHARS :", args.chars)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
