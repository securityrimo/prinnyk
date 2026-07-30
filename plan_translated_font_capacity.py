#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from probe_textaware_font_capacity import (
    BYTES_PER_GLYPH,
    EXCLUDED_NAMES,
    FNT_PATH,
    RUNTIME_DIR,
    TXP_PATH,
    TXP_PIXEL_OFFSET,
    character_class,
    count_raw_pairs,
    decode_double_byte,
    is_sjis_lead,
    is_sjis_trail,
    read_u16,
    scan_text_runs,
    table_index_from_sjis,
)


TRANSLATION_CSV = Path(
    "workspace/translations/export/"
    "translation_master.csv"
)

MASTER_JSON = Path(
    "workspace/translations/export/"
    "translation_master.json"
)

OUTPUT_DIR = Path(
    "workspace/font/translated_plan"
)


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(
            f"번역 CSV 없음: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        return [
            {
                key: value or ""
                for key, value in row.items()
            }
            for row in csv.DictReader(handle)
        ]


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"번역 기준 JSON 없음: {path}"
        )

    document = json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )

    if not isinstance(
        document.get("entries"),
        list,
    ):
        raise ValueError(
            "translation_master.json에 "
            "entries 목록이 없습니다."
        )

    return document


def text_double_pairs(
    text: str,
) -> Counter[bytes]:
    result: Counter[bytes] = Counter()

    for character in text:
        codepoint = ord(character)

        # 한글은 앞으로 배정할 새 코드이므로
        # 기존 Shift-JIS 사용량에는 포함하지 않는다.
        if 0xAC00 <= codepoint <= 0xD7A3:
            continue

        try:
            encoded = character.encode(
                "shift_jis",
                errors="strict",
            )
        except UnicodeEncodeError:
            continue

        if (
            len(encoded) == 2
            and is_sjis_lead(encoded[0])
            and is_sjis_trail(encoded[1])
        ):
            result[encoded] += 1

    return result


def collect_original_usage() -> tuple[
    Counter[bytes],
    Counter[bytes],
    int,
]:
    text_usage: Counter[bytes] = Counter()
    raw_usage: Counter[bytes] = Counter()

    files = [
        path
        for path in sorted(
            RUNTIME_DIR.rglob("*")
        )
        if (
            path.is_file()
            and path.name.casefold()
            not in EXCLUDED_NAMES
        )
    ]

    for path in files:
        data = path.read_bytes()

        (
            file_text_usage,
            _run_count,
            _multibyte_count,
        ) = scan_text_runs(data)

        text_usage.update(
            file_text_usage
        )
        raw_usage.update(
            count_raw_pairs(data)
        )

    return (
        text_usage,
        raw_usage,
        len(files),
    )


def load_font_table() -> tuple[
    list[int],
    int,
    int,
]:
    fnt = FNT_PATH.read_bytes()
    txp = TXP_PATH.read_bytes()

    table_count = read_u16(
        fnt,
        0,
    )

    table = [
        read_u16(
            fnt,
            2 + index * 2,
        )
        for index in range(
            table_count
        )
    ]

    pixel_size = (
        len(txp)
        - TXP_PIXEL_OFFSET
    )

    if pixel_size < 0:
        raise ValueError(
            "font.txp 크기가 잘못되었습니다."
        )

    if (
        pixel_size
        % BYTES_PER_GLYPH
        != 0
    ):
        raise ValueError(
            "font.txp 글리프 영역이 "
            "140바이트 단위가 아닙니다."
        )

    glyph_count = (
        pixel_size
        // BYTES_PER_GLYPH
    )

    return (
        table,
        table_count,
        glyph_count,
    )


def build_glyph_groups(
    table: list[int],
    table_count: int,
    glyph_count: int,
    original_usage: Counter[bytes],
    remaining_usage: Counter[bytes],
    raw_usage: Counter[bytes],
) -> dict[int, list[dict[str, Any]]]:
    groups: dict[
        int,
        list[dict[str, Any]]
    ] = defaultdict(list)

    leads = (
        list(range(0x81, 0xA0))
        + list(range(0xE0, 0xFD))
    )

    for lead in leads:
        for trail in range(
            0x40,
            0xFD,
        ):
            if not is_sjis_trail(trail):
                continue

            character = decode_double_byte(
                lead,
                trail,
            )

            if character is None:
                continue

            table_index = (
                table_index_from_sjis(
                    lead,
                    trail,
                )
            )

            if not (
                0 <= table_index
                < table_count
            ):
                continue

            glyph_index = table[
                table_index
            ]

            if not (
                0 < glyph_index
                < glyph_count
            ):
                continue

            pair = bytes(
                (
                    lead,
                    trail,
                )
            )

            groups[glyph_index].append(
                {
                    "character": character,
                    "unicode": (
                        f"U+{ord(character):04X}"
                    ),
                    "class": (
                        character_class(
                            character
                        )
                    ),
                    "sjis": (
                        pair.hex(" ").upper()
                    ),
                    "sjis_value": (
                        lead << 8
                    ) | trail,
                    "table_index": (
                        table_index
                    ),
                    "table_index_hex": (
                        f"0x{table_index:04X}"
                    ),
                    "original_uses": int(
                        original_usage[pair]
                    ),
                    "remaining_uses": max(
                        0,
                        int(
                            remaining_usage[pair]
                        ),
                    ),
                    "raw_uses": int(
                        raw_usage[pair]
                    ),
                    "unaccounted_raw": max(
                        0,
                        int(raw_usage[pair])
                        - int(
                            original_usage[pair]
                        ),
                    ),
                }
            )

    return groups


def select_alias(
    aliases: list[dict[str, Any]],
) -> dict[str, Any]:
    class_priority = {
        "kanji": 0,
        "katakana": 1,
        "hiragana": 2,
        "fullwidth": 3,
        "punctuation": 4,
        "other": 5,
    }

    return min(
        aliases,
        key=lambda alias: (
            int(
                alias[
                    "unaccounted_raw"
                ]
            ),
            class_priority.get(
                str(alias["class"]),
                9,
            ),
            int(alias["sjis_value"]),
        ),
    )


def main() -> int:
    rows = load_csv(
        TRANSLATION_CSV
    )
    master = load_json(
        MASTER_JSON
    )

    master_by_id = {
        str(entry["id"]): entry
        for entry in master["entries"]
    }

    (
        original_usage,
        raw_usage,
        scanned_files,
    ) = collect_original_usage()

    remaining_usage = Counter(
        original_usage
    )

    required_hangul: set[str] = set()
    translated_rows = 0
    translated_occurrences = 0
    usage_underflows: Counter[bytes] = (
        Counter()
    )

    for row in rows:
        translation = row.get(
            "translation",
            "",
        )

        if not translation:
            continue

        identifier = row.get(
            "id",
            "",
        )

        master_entry = master_by_id.get(
            identifier
        )

        if master_entry is None:
            raise ValueError(
                f"기준 JSON에 없는 ID: "
                f"{identifier}"
            )

        occurrences = list(
            master_entry.get(
                "occurrences",
                []
            )
        )

        occurrence_count = len(
            occurrences
        )

        if occurrence_count == 0:
            occurrence_count = int(
                master_entry.get(
                    "occurrence_count",
                    1,
                )
            )

        source_raw = str(
            master_entry.get(
                "source_raw",
                master_entry.get(
                    "source_display",
                    "",
                ),
            )
        )

        removed_pairs = (
            text_double_pairs(
                source_raw
            )
        )

        added_pairs = (
            text_double_pairs(
                translation
            )
        )

        for pair, count in (
            removed_pairs.items()
        ):
            amount = (
                count
                * occurrence_count
            )

            remaining_usage[pair] -= (
                amount
            )

            if remaining_usage[pair] < 0:
                usage_underflows[
                    pair
                ] += abs(
                    remaining_usage[pair]
                )
                remaining_usage[pair] = 0

        for pair, count in (
            added_pairs.items()
        ):
            remaining_usage[pair] += (
                count
                * occurrence_count
            )

        required_hangul.update(
            character
            for character in translation
            if (
                0xAC00
                <= ord(character)
                <= 0xD7A3
            )
        )

        translated_rows += 1
        translated_occurrences += (
            occurrence_count
        )

    (
        table,
        table_count,
        glyph_count,
    ) = load_font_table()

    groups = build_glyph_groups(
        table,
        table_count,
        glyph_count,
        original_usage,
        remaining_usage,
        raw_usage,
    )

    preserved_glyphs = 0
    strict_candidates: list[
        dict[str, Any]
    ] = []
    review_candidates: list[
        dict[str, Any]
    ] = []

    freed_by_translation = 0

    for glyph_index, aliases in (
        groups.items()
    ):
        remaining_uses = sum(
            int(
                alias[
                    "remaining_uses"
                ]
            )
            for alias in aliases
        )

        if remaining_uses > 0:
            preserved_glyphs += 1
            continue

        original_uses = sum(
            int(
                alias[
                    "original_uses"
                ]
            )
            for alias in aliases
        )

        raw_uses = sum(
            int(alias["raw_uses"])
            for alias in aliases
        )

        unaccounted_raw = sum(
            int(
                alias[
                    "unaccounted_raw"
                ]
            )
            for alias in aliases
        )

        selected = select_alias(
            aliases
        )

        if original_uses > 0:
            source = (
                "freed-by-translation"
            )
            freed_by_translation += 1
        else:
            source = "originally-unused"

        candidate = {
            "character": (
                selected["character"]
            ),
            "unicode": (
                selected["unicode"]
            ),
            "class": (
                selected["class"]
            ),
            "sjis": (
                selected["sjis"]
            ),
            "sjis_value": (
                selected["sjis_value"]
            ),
            "table_index": (
                selected["table_index"]
            ),
            "table_index_hex": (
                selected[
                    "table_index_hex"
                ]
            ),
            "glyph_index": (
                glyph_index
            ),
            "glyph_index_hex": (
                f"0x{glyph_index:04X}"
            ),
            "source": source,
            "alias_count": len(
                aliases
            ),
            "original_uses": (
                original_uses
            ),
            "remaining_uses": 0,
            "raw_uses": raw_uses,
            "unaccounted_raw": (
                unaccounted_raw
            ),
            "aliases": aliases,
        }

        if unaccounted_raw == 0:
            strict_candidates.append(
                candidate
            )
        else:
            review_candidates.append(
                candidate
            )

    sort_key = lambda item: (
        0
        if item["source"]
        == "freed-by-translation"
        else 1,
        int(
            item[
                "unaccounted_raw"
            ]
        ),
        int(item["glyph_index"]),
    )

    strict_candidates.sort(
        key=sort_key
    )
    review_candidates.sort(
        key=sort_key
    )

    required_count = len(
        required_hangul
    )
    strict_capacity = len(
        strict_candidates
    )
    margin = (
        strict_capacity
        - required_count
    )

    enough = margin >= 0

    report = {
        "format": (
            "prinny_translated_font_plan_v1"
        ),
        "translated_rows": (
            translated_rows
        ),
        "translated_occurrences": (
            translated_occurrences
        ),
        "scanned_files": (
            scanned_files
        ),
        "table_count": (
            table_count
        ),
        "glyph_count": (
            glyph_count
        ),
        "mapped_glyph_groups": (
            len(groups)
        ),
        "preserved_glyphs": (
            preserved_glyphs
        ),
        "freed_by_translation": (
            freed_by_translation
        ),
        "strict_capacity": (
            strict_capacity
        ),
        "review_capacity": len(
            review_candidates
        ),
        "required_hangul_count": (
            required_count
        ),
        "capacity_margin": margin,
        "usage_underflow_pairs": (
            len(usage_underflows)
        ),
        "required_hangul": "".join(
            sorted(required_hangul)
        ),
        "strict_candidates": (
            strict_candidates
        ),
        "review_candidates": (
            review_candidates
        ),
        "status": (
            "pass"
            if enough
            else "insufficient-capacity"
        ),
    }

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = (
        OUTPUT_DIR
        / "translated_font_plan.json"
    )

    text_path = (
        OUTPUT_DIR
        / "translated_font_plan.txt"
    )

    hangul_path = (
        OUTPUT_DIR
        / "required_hangul.txt"
    )

    json_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    hangul_path.write_text(
        report["required_hangul"]
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "TRANSLATED FONT CAPACITY PLAN",
        "=============================",
        (
            f"TRANSLATED ROWS       : "
            f"{translated_rows}"
        ),
        (
            f"TRANSLATED OCCURRENCES: "
            f"{translated_occurrences}"
        ),
        (
            f"SCANNED FILES         : "
            f"{scanned_files}"
        ),
        (
            f"GLYPH COUNT           : "
            f"{glyph_count}"
        ),
        (
            f"MAPPED GLYPH GROUPS   : "
            f"{len(groups)}"
        ),
        (
            f"PRESERVED GLYPHS      : "
            f"{preserved_glyphs}"
        ),
        (
            f"FREED BY TRANSLATION  : "
            f"{freed_by_translation}"
        ),
        (
            f"STRICT CAPACITY       : "
            f"{strict_capacity}"
        ),
        (
            f"REVIEW CAPACITY       : "
            f"{len(review_candidates)}"
        ),
        (
            f"REQUIRED HANGUL       : "
            f"{required_count}"
        ),
        (
            f"CAPACITY MARGIN       : "
            f"{margin:+d}"
        ),
        (
            f"USAGE UNDERFLOW PAIRS : "
            f"{len(usage_underflows)}"
        ),
        "",
        "FIRST STRICT CANDIDATES",
        "-----------------------",
    ]

    for number, item in enumerate(
        strict_candidates[:80],
        start=1,
    ):
        lines.append(
            f"{number:3d}. "
            f"{item['source']:21s} "
            f"CHAR={item['character']!r} "
            f"SJIS={item['sjis']} "
            f"GLYPH={item['glyph_index_hex']} "
            f"USES={item['original_uses']}"
        )

    lines.extend(
        [
            "",
            f"JSON  : {json_path}",
            f"HANGUL: {hangul_path}",
            (
                "STATUS: PASS"
                if enough
                else "STATUS: INSUFFICIENT CAPACITY"
            ),
        ]
    )

    output = "\n".join(lines)

    text_path.write_text(
        output + "\n",
        encoding="utf-8",
    )

    print(output)

    return 0 if enough else 2


if __name__ == "__main__":
    raise SystemExit(main())
