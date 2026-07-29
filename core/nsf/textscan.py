#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def read_u16(raw: bytes, offset: int) -> int:
    end = offset + 2

    if offset < 0 or end > len(raw):
        raise ValueError(
            f"u16 범위 오류: offset=0x{offset:X}"
        )

    return int.from_bytes(
        raw[offset:end],
        byteorder="little",
        signed=False,
    )


def decode_string(raw: bytes) -> tuple[str, str] | None:
    if not raw:
        return None

    if all(0x20 <= byte <= 0x7E for byte in raw):
        try:
            return raw.decode("ascii"), "ascii"
        except UnicodeDecodeError:
            pass

    try:
        text = raw.decode(
            "shift_jis",
            errors="strict",
        )
    except UnicodeDecodeError:
        return None

    if not text or not text.isprintable():
        return None

    return text, "shift_jis"


def make_record(
    entry: dict,
    pattern: str,
    command_offset: int,
    string_offset: int,
    string_length: int,
    string_bytes: bytes,
    encoding: str,
    text: str,
    item_number: int | None = None,
    has_suffix: bool | None = None,
) -> dict:
    relative_start = entry.get("relative_start")
    file_start = entry.get("file_start")

    relative_offset = (
        relative_start + string_offset
        if isinstance(relative_start, int)
        else None
    )

    file_offset = (
        file_start + string_offset
        if isinstance(file_start, int)
        else None
    )

    return {
        "entry_index": entry["index"],
        "primary_index": entry.get("primary_index"),
        "secondary_index": entry.get("secondary_index"),
        "pattern": pattern,
        "item_number": item_number,
        "command_offset": command_offset,
        "command_offset_hex": f"0x{command_offset:X}",
        "offset_in_entry": string_offset,
        "offset_in_entry_hex": f"0x{string_offset:X}",
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
        "byte_length": string_length,
        "char_length": len(text),
        "encoding": encoding,
        "text": text,
        "raw_hex": string_bytes.hex(" "),
        "has_suffix_01_01": has_suffix,
        "translated": "",
    }


def scan_entry(entry: dict) -> list[dict]:
    hex_text = entry.get("hex")

    if not hex_text:
        return []

    raw = bytes.fromhex(hex_text)
    results = []
    position = 0

    while position < len(raw):
        if raw[position] != 0x47:
            position += 1
            continue

        # 형식 A:
        # 47 08 [length:u16] [string]
        if (
            position + 4 <= len(raw)
            and raw[position + 1] == 0x08
        ):
            string_length = read_u16(
                raw,
                position + 2,
            )

            string_offset = position + 4
            string_end = string_offset + string_length

            if string_end <= len(raw):
                string_bytes = raw[
                    string_offset:string_end
                ]

                decoded = decode_string(string_bytes)

                if decoded is not None:
                    text, encoding = decoded

                    results.append(
                        make_record(
                            entry=entry,
                            pattern="47_08",
                            command_offset=position,
                            string_offset=string_offset,
                            string_length=string_length,
                            string_bytes=string_bytes,
                            encoding=encoding,
                            text=text,
                        )
                    )

                    position = string_end
                    continue

        # 형식 B:
        # 47 01 01 00 01 [item:u8]
        # [length:u16] [string] 01 01
        if (
            position + 8 <= len(raw)
            and raw[
                position + 1:position + 5
            ] == b"\x01\x01\x00\x01"
        ):
            item_number = raw[position + 5]

            string_length = read_u16(
                raw,
                position + 6,
            )

            string_offset = position + 8
            string_end = string_offset + string_length

            if string_end <= len(raw):
                string_bytes = raw[
                    string_offset:string_end
                ]

                has_suffix = (
                    string_end + 2 <= len(raw)
                    and raw[
                        string_end:string_end + 2
                    ] == b"\x01\x01"
                )

                decoded = decode_string(string_bytes)

                if decoded is not None:
                    text, encoding = decoded

                    results.append(
                        make_record(
                            entry=entry,
                            pattern="47_01",
                            command_offset=position,
                            string_offset=string_offset,
                            string_length=string_length,
                            string_bytes=string_bytes,
                            encoding=encoding,
                            text=text,
                            item_number=item_number,
                            has_suffix=has_suffix,
                        )
                    )

                    position = string_end
                    continue

        position += 1

    return results


def scan_analysis(analysis: dict) -> dict:
    strings = []
    scanned_entries = 0
    skipped_entries = 0

    for entry in analysis.get("entries", []):
        if not entry.get("hex"):
            skipped_entries += 1
            continue

        scanned_entries += 1
        strings.extend(scan_entry(entry))

    strings.sort(
        key=lambda item: (
            item["entry_index"],
            item["offset_in_entry"],
        )
    )

    encoding_counts = {}
    pattern_counts = {}

    for record in strings:
        encoding = record["encoding"]
        pattern = record["pattern"]

        encoding_counts[encoding] = (
            encoding_counts.get(encoding, 0) + 1
        )

        pattern_counts[pattern] = (
            pattern_counts.get(pattern, 0) + 1
        )

    return {
        "format": "NSF_STRUCTURED_STRING_SCAN",
        "source_analysis": analysis.get("source"),
        "source_file": analysis.get("file"),
        "scanned_entries": scanned_entries,
        "skipped_entries": skipped_entries,
        "string_count": len(strings),
        "encoding_counts": encoding_counts,
        "pattern_counts": pattern_counts,
        "strings": strings,
    }


def default_output_path(input_path: Path) -> Path:
    name = input_path.name

    if name.endswith(".nsf.json"):
        name = name[:-9] + ".strings.json"
    elif name.endswith(".json"):
        name = name[:-5] + ".strings.json"
    else:
        name += ".strings.json"

    return input_path.with_name(name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "NSF 분석 JSON에서 구조가 확인된 "
            "문자열 명령을 추출합니다."
        )
    )

    parser.add_argument(
        "analysis_json",
        help="NSF 분석 JSON 경로",
    )

    parser.add_argument(
        "-o",
        "--output",
        help="출력 JSON 경로",
    )

    args = parser.parse_args()

    input_path = Path(args.analysis_json)

    if not input_path.is_file():
        print(
            "ERROR: 분석 JSON을 찾을 수 없습니다:",
            input_path,
        )
        return 1

    try:
        with input_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            analysis = json.load(file)

        result = scan_analysis(analysis)

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
        "PATTERNS:",
        result["pattern_counts"],
    )
    print(
        "ENCODINGS:",
        result["encoding_counts"],
    )
    print("SAVED:", output_path)

    print()
    print("STRINGS")
    print("-------")

    for record in result["strings"][:30]:
        print(
            f'ENTRY {record["entry_index"]:04d} '
            f'{record["pattern"]:5} '
            f'{record["encoding"]:9} '
            f'{record["file_offset_hex"]} '
            f'{record["text"]!r}'
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
