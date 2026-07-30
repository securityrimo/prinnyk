#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


DEFAULT_MIN_ASCII_LENGTH = 4
DEFAULT_MIN_SJIS_CHARS = 2


def is_ascii_printable(byte: int) -> bool:
    return 0x20 <= byte <= 0x7E


def is_sjis_lead(byte: int) -> bool:
    return (
        0x81 <= byte <= 0x9F
        or 0xE0 <= byte <= 0xFC
    )


def is_sjis_trail(byte: int) -> bool:
    return (
        0x40 <= byte <= 0xFC
        and byte != 0x7F
    )


def is_halfwidth_katakana(byte: int) -> bool:
    return 0xA1 <= byte <= 0xDF


def contains_japanese(text: str) -> bool:
    for character in text:
        code = ord(character)

        if (
            0x3040 <= code <= 0x309F
            or 0x30A0 <= code <= 0x30FF
            or 0x4E00 <= code <= 0x9FFF
            or 0xFF61 <= code <= 0xFF9F
        ):
            return True

    return False


def scan_ascii(
    raw: bytes,
    minimum_length: int,
) -> list[dict]:
    results = []
    start = None

    for position, byte in enumerate(raw):
        if is_ascii_printable(byte):
            if start is None:
                start = position
            continue

        if start is not None:
            chunk = raw[start:position]

            if len(chunk) >= minimum_length:
                results.append(
                    {
                        "offset": start,
                        "byte_length": len(chunk),
                        "encoding": "ascii",
                        "text": chunk.decode(
                            "ascii",
                            errors="strict",
                        ),
                        "raw_hex": chunk.hex(" "),
                    }
                )

            start = None

    if start is not None:
        chunk = raw[start:]

        if len(chunk) >= minimum_length:
            results.append(
                {
                    "offset": start,
                    "byte_length": len(chunk),
                    "encoding": "ascii",
                    "text": chunk.decode(
                        "ascii",
                        errors="strict",
                    ),
                    "raw_hex": chunk.hex(" "),
                }
            )

    return results


def read_sjis_unit(
    raw: bytes,
    position: int,
) -> tuple[int, bool] | None:
    byte = raw[position]

    if is_ascii_printable(byte):
        return 1, False

    if is_halfwidth_katakana(byte):
        return 1, True

    if is_sjis_lead(byte):
        if position + 1 >= len(raw):
            return None

        trail = raw[position + 1]

        if is_sjis_trail(trail):
            return 2, True

    return None


def scan_shift_jis(
    raw: bytes,
    minimum_chars: int,
) -> list[dict]:
    results = []
    position = 0

    while position < len(raw):
        first_unit = read_sjis_unit(
            raw,
            position,
        )

        if first_unit is None:
            position += 1
            continue

        start = position
        character_count = 0
        has_japanese_unit = False

        while position < len(raw):
            unit = read_sjis_unit(
                raw,
                position,
            )

            if unit is None:
                break

            unit_size, japanese_unit = unit

            position += unit_size
            character_count += 1
            has_japanese_unit = (
                has_japanese_unit or japanese_unit
            )

        chunk = raw[start:position]

        if (
            character_count >= minimum_chars
            and has_japanese_unit
        ):
            try:
                text = chunk.decode(
                    "shift_jis",
                    errors="strict",
                )
            except UnicodeDecodeError:
                text = None

            if (
                text
                and text.isprintable()
                and contains_japanese(text)
            ):
                results.append(
                    {
                        "offset": start,
                        "byte_length": len(chunk),
                        "encoding": "shift_jis",
                        "text": text,
                        "raw_hex": chunk.hex(" "),
                    }
                )

        if position == start:
            position += 1

    return results


def scan_entry(
    entry: dict,
    minimum_ascii_length: int,
    minimum_sjis_chars: int,
) -> list[dict]:
    hex_text = entry.get("hex")

    if not hex_text:
        return []

    raw = bytes.fromhex(hex_text)

    candidates = []

    candidates.extend(
        scan_ascii(
            raw,
            minimum_length=minimum_ascii_length,
        )
    )

    candidates.extend(
        scan_shift_jis(
            raw,
            minimum_chars=minimum_sjis_chars,
        )
    )

    results = []

    for candidate in candidates:
        offset_in_entry = candidate["offset"]

        relative_start = entry.get(
            "relative_start"
        )

        file_start = entry.get(
            "file_start"
        )

        if isinstance(relative_start, int):
            relative_offset = (
                relative_start + offset_in_entry
            )
        else:
            relative_offset = None

        if isinstance(file_start, int):
            file_offset = (
                file_start + offset_in_entry
            )
        else:
            file_offset = None

        results.append(
            {
                "entry_index": entry["index"],
                "primary_index": entry.get(
                    "primary_index"
                ),
                "secondary_index": entry.get(
                    "secondary_index"
                ),
                "offset_in_entry": offset_in_entry,
                "offset_in_entry_hex": (
                    f"0x{offset_in_entry:X}"
                ),
                "relative_offset": relative_offset,
                "relative_offset_hex": (
                    f"0x{relative_offset:X}"
                    if relative_offset is not None
                    else None
                ),
                "file_offset": file_offset,
                "file_offset_hex": (
                    f"0x{file_offset:X}"
                    if file_offset is not None
                    else None
                ),
                "byte_length": candidate[
                    "byte_length"
                ],
                "char_length": len(
                    candidate["text"]
                ),
                "encoding": candidate[
                    "encoding"
                ],
                "text": candidate["text"],
                "raw_hex": candidate[
                    "raw_hex"
                ],
            }
        )

    results.sort(
        key=lambda record: (
            record["offset_in_entry"],
            record["encoding"],
        )
    )

    return results


def scan_analysis(
    analysis: dict,
    minimum_ascii_length: int,
    minimum_sjis_chars: int,
) -> dict:
    strings = []
    scanned_entries = 0
    skipped_entries = 0

    for entry in analysis.get("entries", []):
        if not entry.get("hex"):
            skipped_entries += 1
            continue

        scanned_entries += 1

        strings.extend(
            scan_entry(
                entry=entry,
                minimum_ascii_length=(
                    minimum_ascii_length
                ),
                minimum_sjis_chars=(
                    minimum_sjis_chars
                ),
            )
        )

    encoding_counts = {}

    for record in strings:
        encoding = record["encoding"]

        encoding_counts[encoding] = (
            encoding_counts.get(
                encoding,
                0,
            )
            + 1
        )

    return {
        "format": "NSF_STRING_SCAN",
        "source_analysis": analysis.get(
            "source"
        ),
        "source_file": analysis.get(
            "file"
        ),
        "scanned_entries": scanned_entries,
        "skipped_entries": skipped_entries,
        "string_count": len(strings),
        "encoding_counts": encoding_counts,
        "settings": {
            "minimum_ascii_length": (
                minimum_ascii_length
            ),
            "minimum_sjis_chars": (
                minimum_sjis_chars
            ),
        },
        "strings": strings,
    }


def default_output_path(
    input_path: Path,
) -> Path:
    name = input_path.name

    if name.endswith(".nsf.json"):
        name = name[:-9] + ".strings.json"
    elif name.endswith(".json"):
        name = name[:-5] + ".strings.json"
    else:
        name = name + ".strings.json"

    return input_path.with_name(name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "NSF 분석 JSON에서 ASCII와 "
            "Shift-JIS 문자열 후보를 추출합니다."
        )
    )

    parser.add_argument(
        "analysis_json",
        help="parser가 생성한 NSF 분석 JSON",
    )

    parser.add_argument(
        "-o",
        "--output",
        help="출력 JSON 경로",
    )

    parser.add_argument(
        "--min-ascii",
        type=int,
        default=DEFAULT_MIN_ASCII_LENGTH,
        help="최소 ASCII 문자열 길이",
    )

    parser.add_argument(
        "--min-sjis",
        type=int,
        default=DEFAULT_MIN_SJIS_CHARS,
        help="최소 Shift-JIS 문자 수",
    )

    args = parser.parse_args()

    input_path = Path(args.analysis_json)

    if not input_path.is_file():
        print(
            f"ERROR: 분석 JSON을 찾을 수 없습니다: "
            f"{input_path}"
        )
        return 1

    if args.min_ascii < 1:
        print("ERROR: --min-ascii는 1 이상이어야 합니다.")
        return 1

    if args.min_sjis < 1:
        print("ERROR: --min-sjis는 1 이상이어야 합니다.")
        return 1

    try:
        with input_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            analysis = json.load(file)

        result = scan_analysis(
            analysis=analysis,
            minimum_ascii_length=args.min_ascii,
            minimum_sjis_chars=args.min_sjis,
        )
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"ERROR: {error}")
        return 1

    output_path = (
        Path(args.output)
        if args.output
        else default_output_path(input_path)
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print("FILE:", result["source_file"])
    print(
        "SCANNED ENTRIES:",
        result["scanned_entries"],
    )
    print(
        "SKIPPED ENTRIES:",
        result["skipped_entries"],
    )
    print(
        "STRING COUNT:",
        result["string_count"],
    )
    print(
        "ENCODINGS:",
        result["encoding_counts"],
    )
    print("SAVED:", output_path)

    print()
    print("FIRST 20 STRINGS")
    print("----------------")

    for record in result["strings"][:20]:
        print(
            f'ENTRY {record["entry_index"]:04d} '
            f'{record["encoding"]:10} '
            f'{record["file_offset_hex"]} '
            f'{record["text"]!r}'
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
