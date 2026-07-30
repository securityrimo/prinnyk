from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterator


DEFAULT_RUNTIME_DIR = Path(
    "workspace/unpack/START_runtime"
)

DEFAULT_OUTPUT_DIR = Path(
    "workspace/translations/catalog"
)

EXCLUDED_NAMES = {
    "font.fnt",
    "font.txp",
    "jis2ucs.bin",
    "ucs2jis.bin",
}

EXCLUDED_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".gim",
    ".tm2",
    ".txp",
    ".fnt",
    ".at3",
    ".wav",
    ".ogg",
    ".adx",
    ".pmf",
}


def is_sjis_lead(value: int) -> bool:
    return (
        0x81 <= value <= 0x9F
        or 0xE0 <= value <= 0xFC
    )


def is_sjis_trail(value: int) -> bool:
    return (
        0x40 <= value <= 0xFC
        and value != 0x7F
    )


def decode_sjis_pair(
    lead: int,
    trail: int,
) -> str | None:
    try:
        decoded = bytes(
            (lead, trail)
        ).decode(
            "shift_jis",
            errors="strict",
        )
    except UnicodeDecodeError:
        return None

    if len(decoded) != 1:
        return None

    return decoded


def character_class(character: str) -> str:
    codepoint = ord(character)

    if (
        0x3040 <= codepoint <= 0x309F
    ):
        return "hiragana"

    if (
        0x30A0 <= codepoint <= 0x30FF
    ):
        return "katakana"

    if (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    ):
        return "kanji"

    if (
        0x3000 <= codepoint <= 0x303F
    ):
        return "punctuation"

    if (
        0xFF00 <= codepoint <= 0xFFEF
    ):
        return "fullwidth"

    if (
        0x20 <= codepoint <= 0x7E
    ):
        return "ascii"

    return "other"


def is_japanese_text_character(
    character: str,
) -> bool:
    return character_class(
        character
    ) in {
        "hiragana",
        "katakana",
        "kanji",
        "punctuation",
        "fullwidth",
    }


def read_token(
    data: bytes,
    offset: int,
) -> tuple[str, int] | None:
    value = data[offset]

    if 0x20 <= value <= 0x7E:
        return chr(value), 1

    if 0xA1 <= value <= 0xDF:
        try:
            character = bytes(
                (value,)
            ).decode(
                "shift_jis",
                errors="strict",
            )
        except UnicodeDecodeError:
            return None

        return character, 1

    if (
        is_sjis_lead(value)
        and offset + 1 < len(data)
        and is_sjis_trail(
            data[offset + 1]
        )
    ):
        character = decode_sjis_pair(
            value,
            data[offset + 1],
        )

        if character is None:
            return None

        return character, 2

    return None


def scan_runs(
    data: bytes,
) -> Iterator[dict[str, Any]]:
    offset = 0
    data_size = len(data)

    while offset < data_size:
        tokens: list[
            tuple[int, int, str]
        ] = []

        cursor = offset

        while cursor < data_size:
            token = read_token(
                data,
                cursor,
            )

            if token is None:
                break

            character, byte_length = token

            tokens.append(
                (
                    cursor,
                    byte_length,
                    character,
                )
            )

            cursor += byte_length

        while (
            tokens
            and tokens[0][2].isspace()
        ):
            tokens.pop(0)

        while (
            tokens
            and tokens[-1][2].isspace()
        ):
            tokens.pop()

        if tokens:
            start = tokens[0][0]
            end = (
                tokens[-1][0]
                + tokens[-1][1]
            )

            text = "".join(
                token[2]
                for token in tokens
            )

            japanese_count = sum(
                is_japanese_text_character(
                    character
                )
                for character in text
            )

            kanji_count = sum(
                character_class(character)
                == "kanji"
                for character in text
            )

            kana_count = sum(
                character_class(character)
                in {
                    "hiragana",
                    "katakana",
                }
                for character in text
            )

            accepted = (
                len(text) >= 4
                and (
                    japanese_count >= 2
                    or (
                        japanese_count >= 1
                        and len(text) >= 6
                    )
                )
            )

            if accepted:
                japanese_ratio = (
                    japanese_count
                    / len(text)
                )

                if (
                    japanese_count >= 4
                    and japanese_ratio >= 0.6
                ):
                    confidence = "high"
                elif japanese_count >= 2:
                    confidence = "medium"
                else:
                    confidence = "low"

                yield {
                    "offset": start,
                    "end": end,
                    "byte_length": (
                        end - start
                    ),
                    "character_length": len(
                        text
                    ),
                    "source": text,
                    "source_hex": (
                        data[start:end]
                        .hex(" ")
                        .upper()
                    ),
                    "japanese_count": (
                        japanese_count
                    ),
                    "kanji_count": (
                        kanji_count
                    ),
                    "kana_count": (
                        kana_count
                    ),
                    "confidence": confidence,
                    "next_byte": (
                        data[end]
                        if end < data_size
                        else None
                    ),
                }

                offset = end
                continue

        offset += 1


def context_hex(
    data: bytes,
    start: int,
    end: int,
    radius: int = 16,
) -> str:
    context_start = max(
        0,
        start - radius,
    )
    context_end = min(
        len(data),
        end + radius,
    )

    return (
        data[
            context_start:
            context_end
        ]
        .hex(" ")
        .upper()
    )


def build_catalog(
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
) -> dict[str, Any]:
    if not runtime_dir.is_dir():
        raise FileNotFoundError(
            f"런타임 리소스 폴더가 없습니다: "
            f"{runtime_dir}"
        )

    entries: list[
        dict[str, Any]
    ] = []

    resource_counts: Counter[str] = (
        Counter()
    )

    files = [
        path
        for path in sorted(
            runtime_dir.rglob("*")
        )
        if (
            path.is_file()
            and path.name.casefold()
            not in EXCLUDED_NAMES
            and path.suffix.casefold()
            not in EXCLUDED_SUFFIXES
        )
    ]

    for path in files:
        try:
            data = path.read_bytes()
        except OSError as error:
            print(
                f"SKIP: {path}: {error}"
            )
            continue

        relative = str(
            path.relative_to(
                runtime_dir
            )
        )

        for run in scan_runs(data):
            offset = int(
                run["offset"]
            )
            end = int(
                run["end"]
            )

            identifier = (
                f"{relative}@0x{offset:X}"
            )

            entry = {
                "id": identifier,
                "resource": relative,
                **run,
                "context_hex": context_hex(
                    data,
                    offset,
                    end,
                ),
                "translation": "",
                "status": "untranslated",
                "notes": "",
            }

            entries.append(entry)
            resource_counts[
                relative
            ] += 1

    entries.sort(
        key=lambda item: (
            str(item["resource"]),
            int(item["offset"]),
        )
    )

    source_hash = hashlib.sha1()

    for entry in entries:
        source_hash.update(
            str(entry["id"]).encode(
                "utf-8"
            )
        )
        source_hash.update(
            str(entry["source"]).encode(
                "utf-8"
            )
        )

    return {
        "format": (
            "prinny_text_catalog_v1"
        ),
        "runtime_directory": str(
            runtime_dir
        ),
        "scanned_files": len(files),
        "entry_count": len(entries),
        "resource_count": len(
            resource_counts
        ),
        "catalog_sha1": (
            source_hash.hexdigest()
        ),
        "resource_entries": dict(
            sorted(
                resource_counts.items()
            )
        ),
        "entries": entries,
        "status": "pass",
    }


def save_catalog(
    catalog: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> None:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = (
        output_dir / "catalog.json"
    )
    jsonl_path = (
        output_dir / "catalog.jsonl"
    )
    csv_path = (
        output_dir / "catalog.csv"
    )
    template_path = (
        output_dir
        / "translation_template.json"
    )
    summary_path = (
        output_dir / "summary.txt"
    )

    json_path.write_text(
        json.dumps(
            catalog,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with jsonl_path.open(
        "w",
        encoding="utf-8",
    ) as handle:
        for entry in catalog["entries"]:
            handle.write(
                json.dumps(
                    entry,
                    ensure_ascii=False,
                )
                + "\n"
            )

    fieldnames = [
        "id",
        "resource",
        "offset",
        "offset_hex",
        "byte_length",
        "confidence",
        "source",
        "translation",
        "status",
        "notes",
    ]

    with csv_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()

        for entry in catalog["entries"]:
            writer.writerow(
                {
                    "id": entry["id"],
                    "resource": (
                        entry["resource"]
                    ),
                    "offset": (
                        entry["offset"]
                    ),
                    "offset_hex": (
                        f"0x{int(entry['offset']):X}"
                    ),
                    "byte_length": (
                        entry["byte_length"]
                    ),
                    "confidence": (
                        entry["confidence"]
                    ),
                    "source": (
                        entry["source"]
                    ),
                    "translation": "",
                    "status": (
                        "untranslated"
                    ),
                    "notes": "",
                }
            )

    template = {
        "format": (
            "prinny_translation_project_v1"
        ),
        "catalog_sha1": (
            catalog["catalog_sha1"]
        ),
        "translations": [
            {
                "id": entry["id"],
                "resource": (
                    entry["resource"]
                ),
                "offset": (
                    f"0x{int(entry['offset']):X}"
                ),
                "source": (
                    entry["source"]
                ),
                "translation": "",
                "status": (
                    "untranslated"
                ),
                "notes": "",
            }
            for entry in catalog["entries"]
        ],
    }

    template_path.write_text(
        json.dumps(
            template,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary_lines = [
        "PRINNY TEXT CATALOG",
        "===================",
        (
            "SCANNED FILES : "
            f"{catalog['scanned_files']}"
        ),
        (
            "RESOURCES     : "
            f"{catalog['resource_count']}"
        ),
        (
            "TEXT ENTRIES  : "
            f"{catalog['entry_count']}"
        ),
        (
            "CATALOG SHA1  : "
            f"{catalog['catalog_sha1']}"
        ),
        "",
        "TOP RESOURCES",
        "-------------",
    ]

    top_resources = sorted(
        catalog[
            "resource_entries"
        ].items(),
        key=lambda item: (
            -int(item[1]),
            item[0],
        ),
    )[:40]

    for resource, count in top_resources:
        summary_lines.append(
            f"{count:6d}  {resource}"
        )

    summary_lines.extend(
        [
            "",
            f"JSON     : {json_path}",
            f"JSONL    : {jsonl_path}",
            f"CSV      : {csv_path}",
            f"TEMPLATE : {template_path}",
            "STATUS   : PASS",
        ]
    )

    summary_path.write_text(
        "\n".join(
            summary_lines
        )
        + "\n",
        encoding="utf-8",
    )
