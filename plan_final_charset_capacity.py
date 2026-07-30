#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from probe_textaware_font_capacity import (
    BYTES_PER_GLYPH,
    FNT_PATH,
    TXP_PATH,
    TXP_PIXEL_OFFSET,
    character_class,
    decode_double_byte,
    is_sjis_lead,
    is_sjis_trail,
    read_u16,
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
    "workspace/font/final_charset_plan"
)

# 앞쪽 글리프는 시스템용 문자일 가능성을 고려해
# 번역에 사용되지 않더라도 회수하지 않는다.
MIN_RECLAIM_GLYPH = 0x0100


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(
            f"번역 CSV가 없습니다: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        required = {
            "id",
            "source_display",
            "translation",
            "status",
        }

        fields = set(
            reader.fieldnames or []
        )

        missing = required - fields

        if missing:
            raise ValueError(
                "번역 CSV 필수 열 누락: "
                + ", ".join(
                    sorted(missing)
                )
            )

        return [
            {
                key: value or ""
                for key, value in row.items()
            }
            for row in reader
        ]


def load_master(
    path: Path,
) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(
            f"번역 기준 JSON이 없습니다: {path}"
        )

    document = json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )

    entries = document.get(
        "entries"
    )

    if not isinstance(entries, list):
        raise ValueError(
            "translation_master.json에 "
            "entries 목록이 없습니다."
        )

    return {
        str(entry.get("id", "")): entry
        for entry in entries
    }


def load_font() -> tuple[
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

    pixel_bytes = (
        len(txp)
        - TXP_PIXEL_OFFSET
    )

    if pixel_bytes < 0:
        raise ValueError(
            "font.txp의 픽셀 시작 위치가 "
            "파일 크기보다 큽니다."
        )

    if (
        pixel_bytes
        % BYTES_PER_GLYPH
        != 0
    ):
        raise ValueError(
            "font.txp 글리프 영역이 "
            "140바이트 단위가 아닙니다."
        )

    glyph_count = (
        pixel_bytes
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
            if not is_sjis_trail(
                trail
            ):
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

            groups[
                glyph_index
            ].append(
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
                        f"{lead:02X} "
                        f"{trail:02X}"
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
                }
            )

    return groups


def select_alias(
    aliases: list[dict[str, Any]],
) -> dict[str, Any]:
    priority = {
        "kanji": 0,
        "other": 1,
        "katakana": 2,
        "hiragana": 3,
        "fullwidth": 4,
        "punctuation": 5,
    }

    return min(
        aliases,
        key=lambda alias: (
            priority.get(
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

    master = load_master(
        MASTER_JSON
    )

    (
        table,
        table_count,
        glyph_count,
    ) = load_font()

    groups = build_glyph_groups(
        table,
        table_count,
        glyph_count,
    )

    required_hangul: set[str] = set()
    final_double_characters: set[str] = (
        set()
    )
    final_single_characters: set[str] = (
        set()
    )
    preserved_glyphs: set[int] = set()
    unsupported_characters: set[str] = (
        set()
    )
    missing_font_mappings: set[str] = (
        set()
    )

    translated_rows = 0
    skipped_rows = 0

    csv_ids: set[str] = set()

    for row in rows:
        identifier = row[
            "id"
        ].strip()

        if identifier in csv_ids:
            raise ValueError(
                f"중복 ID: {identifier}"
            )

        csv_ids.add(identifier)

        master_entry = master.get(
            identifier
        )

        if master_entry is None:
            raise ValueError(
                f"기준 JSON에 없는 ID: "
                f"{identifier}"
            )

        status = row.get(
            "status",
            "",
        ).strip().casefold()

        source = row.get(
            "source_display",
            "",
        )

        translation = row.get(
            "translation",
            "",
        )

        if status == "skip":
            final_text = source
            skipped_rows += 1
        elif translation:
            final_text = translation
            translated_rows += 1
        else:
            final_text = source
            skipped_rows += 1

        for character in final_text:
            codepoint = ord(
                character
            )

            if (
                0xAC00
                <= codepoint
                <= 0xD7A3
            ):
                required_hangul.add(
                    character
                )
                continue

            try:
                encoded = character.encode(
                    "shift_jis",
                    errors="strict",
                )
            except UnicodeEncodeError:
                unsupported_characters.add(
                    character
                )
                continue

            if len(encoded) == 1:
                final_single_characters.add(
                    character
                )
                continue

            if (
                len(encoded) != 2
                or not is_sjis_lead(
                    encoded[0]
                )
                or not is_sjis_trail(
                    encoded[1]
                )
            ):
                unsupported_characters.add(
                    character
                )
                continue

            final_double_characters.add(
                character
            )

            table_index = (
                table_index_from_sjis(
                    encoded[0],
                    encoded[1],
                )
            )

            if not (
                0 <= table_index
                < table_count
            ):
                missing_font_mappings.add(
                    character
                )
                continue

            glyph_index = table[
                table_index
            ]

            if not (
                0 < glyph_index
                < glyph_count
            ):
                missing_font_mappings.add(
                    character
                )
                continue

            preserved_glyphs.add(
                glyph_index
            )

    missing_csv_ids = (
        set(master)
        - csv_ids
    )

    # 시스템 영역으로 간주하는 앞쪽 글리프는
    # 최종 문자열에서 사용되지 않아도 보존한다.
    reserved_low_glyphs = {
        glyph_index
        for glyph_index in groups
        if (
            glyph_index
            < MIN_RECLAIM_GLYPH
        )
    }

    preserved_glyphs.update(
        reserved_low_glyphs
    )

    strict_candidates: list[
        dict[str, Any]
    ] = []

    review_candidates: list[
        dict[str, Any]
    ] = []

    for glyph_index, aliases in (
        groups.items()
    ):
        if glyph_index in preserved_glyphs:
            continue

        if (
            glyph_index
            < MIN_RECLAIM_GLYPH
        ):
            continue

        selected = select_alias(
            aliases
        )

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
            "alias_count": len(
                aliases
            ),
            "aliases": aliases,
        }

        # 모든 별칭이 한자인 글리프를
        # 가장 안전한 회수 대상으로 취급한다.
        if all(
            alias["class"] == "kanji"
            for alias in aliases
        ):
            strict_candidates.append(
                candidate
            )
        else:
            review_candidates.append(
                candidate
            )

    candidate_sort = lambda item: (
        int(item["glyph_index"]),
        int(item["sjis_value"]),
    )

    strict_candidates.sort(
        key=candidate_sort
    )

    review_candidates.sort(
        key=candidate_sort
    )

    required_count = len(
        required_hangul
    )

    strict_capacity = len(
        strict_candidates
    )

    total_capacity = (
        strict_capacity
        + len(review_candidates)
    )

    strict_margin = (
        strict_capacity
        - required_count
    )

    total_margin = (
        total_capacity
        - required_count
    )

    if (
        unsupported_characters
        or missing_font_mappings
        or missing_csv_ids
    ):
        status = "invalid-final-charset"
        exit_code = 3
    elif strict_margin >= 0:
        status = "pass"
        exit_code = 0
    elif total_margin >= 0:
        status = "review-capacity-required"
        exit_code = 2
    else:
        status = "insufficient-capacity"
        exit_code = 2

    report = {
        "format": (
            "prinny_final_charset_plan_v2"
        ),
        "translated_rows": (
            translated_rows
        ),
        "skipped_rows": skipped_rows,
        "table_count": table_count,
        "glyph_count": glyph_count,
        "mapped_glyph_groups": len(
            groups
        ),
        "reserved_low_glyphs": len(
            reserved_low_glyphs
        ),
        "final_single_characters": (
            "".join(
                sorted(
                    final_single_characters
                )
            )
        ),
        "final_double_characters": (
            "".join(
                sorted(
                    final_double_characters
                )
            )
        ),
        "final_double_character_count": (
            len(final_double_characters)
        ),
        "preserved_glyph_count": (
            len(preserved_glyphs)
        ),
        "required_hangul": (
            "".join(
                sorted(required_hangul)
            )
        ),
        "required_hangul_count": (
            required_count
        ),
        "strict_capacity": (
            strict_capacity
        ),
        "review_capacity": len(
            review_candidates
        ),
        "total_capacity": (
            total_capacity
        ),
        "strict_margin": (
            strict_margin
        ),
        "total_margin": (
            total_margin
        ),
        "unsupported_characters": (
            "".join(
                sorted(
                    unsupported_characters
                )
            )
        ),
        "missing_font_mappings": (
            "".join(
                sorted(
                    missing_font_mappings
                )
            )
        ),
        "missing_csv_ids": sorted(
            missing_csv_ids
        ),
        "strict_candidates": (
            strict_candidates
        ),
        "review_candidates": (
            review_candidates
        ),
        "status": status,
    }

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = (
        OUTPUT_DIR
        / "final_charset_plan.json"
    )

    text_path = (
        OUTPUT_DIR
        / "final_charset_plan.txt"
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
        "FINAL TRANSLATED CHARSET PLAN V2",
        "================================",
        (
            "TRANSLATED ROWS       : "
            f"{translated_rows}"
        ),
        (
            "SKIPPED/FALLBACK ROWS : "
            f"{skipped_rows}"
        ),
        (
            "GLYPH COUNT           : "
            f"{glyph_count}"
        ),
        (
            "MAPPED GLYPH GROUPS   : "
            f"{len(groups)}"
        ),
        (
            "RESERVED LOW GLYPHS   : "
            f"{len(reserved_low_glyphs)}"
        ),
        (
            "FINAL DOUBLE CHARS    : "
            f"{len(final_double_characters)}"
        ),
        (
            "PRESERVED GLYPHS      : "
            f"{len(preserved_glyphs)}"
        ),
        (
            "REQUIRED HANGUL       : "
            f"{required_count}"
        ),
        (
            "STRICT KANJI CAPACITY : "
            f"{strict_capacity}"
        ),
        (
            "REVIEW CAPACITY       : "
            f"{len(review_candidates)}"
        ),
        (
            "TOTAL CAPACITY        : "
            f"{total_capacity}"
        ),
        (
            "STRICT MARGIN         : "
            f"{strict_margin:+d}"
        ),
        (
            "TOTAL MARGIN          : "
            f"{total_margin:+d}"
        ),
        (
            "UNSUPPORTED CHARS     : "
            f"{len(unsupported_characters)}"
        ),
        (
            "MISSING FONT MAPPINGS : "
            f"{len(missing_font_mappings)}"
        ),
        (
            "MISSING CSV IDS       : "
            f"{len(missing_csv_ids)}"
        ),
        "",
        "FIRST STRICT CANDIDATES",
        "-----------------------",
    ]

    for number, candidate in enumerate(
        strict_candidates[:80],
        start=1,
    ):
        lines.append(
            f"{number:3d}. "
            f"CHAR={candidate['character']!r} "
            f"SJIS={candidate['sjis']} "
            f"TABLE={candidate['table_index_hex']} "
            f"GLYPH={candidate['glyph_index_hex']} "
            f"ALIASES={candidate['alias_count']}"
        )

    lines.extend(
        [
            "",
            f"JSON  : {json_path}",
            f"HANGUL: {hangul_path}",
            f"STATUS: {status.upper()}",
        ]
    )

    output = "\n".join(lines)

    text_path.write_text(
        output + "\n",
        encoding="utf-8",
    )

    print(output)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
