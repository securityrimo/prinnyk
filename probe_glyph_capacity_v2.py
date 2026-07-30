#!/usr/bin/env python3
from __future__ import annotations

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


REPORT_PATH = Path(
    "workspace/reports/glyph_capacity_v2.json"
)

TEXT_REPORT_PATH = Path(
    "workspace/reports/glyph_capacity_v2.txt"
)

MAX_PRINTED = 80


def load_font() -> tuple[
    bytes,
    bytes,
    list[int],
    int,
    int,
]:
    for path in (
        FNT_PATH,
        TXP_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(
                f"필수 파일 없음: {path}"
            )

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
            "font.txp가 픽셀 오프셋보다 작습니다."
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
        fnt,
        txp,
        table,
        table_count,
        glyph_count,
    )


def collect_text_usage() -> tuple[
    Counter[bytes],
    Counter[bytes],
    dict[str, Any],
]:
    text_usage: Counter[bytes] = Counter()
    raw_usage: Counter[bytes] = Counter()

    scan_files = [
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

    files_with_text = 0
    detected_runs = 0
    multibyte_characters = 0

    for path in scan_files:
        try:
            data = path.read_bytes()
        except OSError as error:
            print(
                f"SKIP: {path}: {error}"
            )
            continue

        (
            file_text_usage,
            file_runs,
            file_multibyte_count,
        ) = scan_text_runs(
            data
        )

        file_raw_usage = count_raw_pairs(
            data
        )

        text_usage.update(
            file_text_usage
        )
        raw_usage.update(
            file_raw_usage
        )

        if file_runs:
            files_with_text += 1

        detected_runs += file_runs
        multibyte_characters += (
            file_multibyte_count
        )

    statistics = {
        "scanned_files": len(
            scan_files
        ),
        "files_with_text": (
            files_with_text
        ),
        "detected_text_runs": (
            detected_runs
        ),
        "multibyte_characters": (
            multibyte_characters
        ),
    }

    return (
        text_usage,
        raw_usage,
        statistics,
    )


def build_glyph_groups(
    table: list[int],
    table_count: int,
    glyph_count: int,
    text_usage: Counter[bytes],
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
        if not is_sjis_lead(
            lead
        ):
            continue

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
                    "text_uses": (
                        text_usage[pair]
                    ),
                    "raw_uses": (
                        raw_usage[pair]
                    ),
                }
            )

    return groups


def candidate_from_group(
    glyph_index: int,
    aliases: list[dict[str, Any]],
) -> dict[str, Any] | None:
    text_uses = sum(
        int(alias["text_uses"])
        for alias in aliases
    )

    # 같은 글리프에 연결된 코드 중 하나라도
    # 텍스트에서 사용되면 재활용하지 않는다.
    if text_uses != 0:
        return None

    kanji_aliases = [
        alias
        for alias in aliases
        if alias["class"] == "kanji"
    ]

    if not kanji_aliases:
        return None

    # 원시 바이너리 출현이 가장 적은 코드를
    # 대표 재활용 코드로 선택한다.
    selected = min(
        kanji_aliases,
        key=lambda alias: (
            int(alias["raw_uses"]),
            int(alias["sjis_value"]),
        ),
    )

    raw_uses = sum(
        int(alias["raw_uses"])
        for alias in aliases
    )

    return {
        "character": (
            selected["character"]
        ),
        "unicode": (
            selected["unicode"]
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
            selected["table_index_hex"]
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
        "kanji_alias_count": len(
            kanji_aliases
        ),
        "text_uses": text_uses,
        "raw_uses": raw_uses,
        "selected_raw_uses": int(
            selected["raw_uses"]
        ),
        "aliases": sorted(
            aliases,
            key=lambda alias: int(
                alias["sjis_value"]
            ),
        ),
    }


def main() -> int:
    (
        _fnt,
        _txp,
        table,
        table_count,
        glyph_count,
    ) = load_font()

    (
        text_usage,
        raw_usage,
        scan_statistics,
    ) = collect_text_usage()

    groups = build_glyph_groups(
        table,
        table_count,
        glyph_count,
        text_usage,
        raw_usage,
    )

    used_glyphs: set[int] = set()
    candidates: list[
        dict[str, Any]
    ] = []

    for glyph_index, aliases in (
        groups.items()
    ):
        if any(
            int(alias["text_uses"]) > 0
            for alias in aliases
        ):
            used_glyphs.add(
                glyph_index
            )
            continue

        candidate = candidate_from_group(
            glyph_index,
            aliases,
        )

        if candidate is not None:
            candidates.append(
                candidate
            )

    # Tier A:
    # 텍스트 사용 0, 원시 바이너리 사용도 0
    tier_a = [
        candidate
        for candidate in candidates
        if int(
            candidate["raw_uses"]
        ) == 0
    ]

    # Tier B:
    # 텍스트 사용은 0이나 원시 바이너리에서
    # 우연히 같은 바이트가 발견된 후보
    tier_b = [
        candidate
        for candidate in candidates
        if int(
            candidate["raw_uses"]
        ) > 0
    ]

    sort_key = lambda item: (
        int(item["raw_uses"]),
        int(item["selected_raw_uses"]),
        int(item["glyph_index"]),
    )

    tier_a.sort(
        key=sort_key
    )
    tier_b.sort(
        key=sort_key
    )

    report = {
        "format": (
            "prinny_glyph_capacity_v2"
        ),
        "runtime_directory": str(
            RUNTIME_DIR
        ),
        "table_count": table_count,
        "glyph_count": glyph_count,
        **scan_statistics,
        "mapped_glyph_groups": len(
            groups
        ),
        "text_used_glyphs": len(
            used_glyphs
        ),
        "tier_a_count": len(
            tier_a
        ),
        "tier_b_count": len(
            tier_b
        ),
        "total_reclaimable_count": (
            len(tier_a)
            + len(tier_b)
        ),
        "tier_a": tier_a,
        "tier_b": tier_b,
        "status": "pass",
    }

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines: list[str] = []

    lines.append(
        "GLYPH-AWARE FONT CAPACITY V2"
    )
    lines.append(
        "============================"
    )
    lines.append(
        f"TABLE COUNT             : {table_count}"
    )
    lines.append(
        f"GLYPH COUNT             : {glyph_count}"
    )
    lines.append(
        "SCANNED FILES           : "
        f"{scan_statistics['scanned_files']}"
    )
    lines.append(
        "DETECTED TEXT RUNS      : "
        f"{scan_statistics['detected_text_runs']}"
    )
    lines.append(
        "MAPPED GLYPH GROUPS     : "
        f"{len(groups)}"
    )
    lines.append(
        "TEXT-USED GLYPHS        : "
        f"{len(used_glyphs)}"
    )
    lines.append(
        "TIER A SAFE GLYPHS      : "
        f"{len(tier_a)}"
    )
    lines.append(
        "TIER B REVIEW GLYPHS    : "
        f"{len(tier_b)}"
    )
    lines.append(
        "TOTAL RECLAIMABLE       : "
        f"{len(tier_a) + len(tier_b)}"
    )
    lines.append("")
    lines.append("TIER A CANDIDATES")
    lines.append("-----------------")

    for number, item in enumerate(
        tier_a[
            :MAX_PRINTED
        ],
        start=1,
    ):
        lines.append(
            f"{number:3d}. "
            f"CHAR={item['character']!r} "
            f"{item['unicode']} "
            f"SJIS={item['sjis']} "
            f"TABLE={item['table_index_hex']} "
            f"GLYPH={item['glyph_index_hex']} "
            f"ALIASES={item['alias_count']} "
            f"RAW={item['raw_uses']}"
        )

    lines.append("")
    lines.append(
        f"REPORT: {REPORT_PATH}"
    )
    lines.append("STATUS: PASS")

    output = "\n".join(
        lines
    )

    TEXT_REPORT_PATH.write_text(
        output + "\n",
        encoding="utf-8",
    )

    print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
