#!/usr/bin/env python3
from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path


RUNTIME_DIR = Path("workspace/unpack/START_runtime")

FNT_PATH = RUNTIME_DIR / "font.fnt"
TXP_PATH = RUNTIME_DIR / "font.txp"

REPORT_PATH = Path(
    "workspace/reports/textaware_font_capacity.json"
)

TXP_PIXEL_OFFSET = 0x50
BYTES_PER_GLYPH = 140
MAX_PRINTED_CANDIDATES = 50

# 글꼴 자체와 매핑 테이블은 대사 검색에서 제외한다.
EXCLUDED_NAMES = {
    "font.fnt",
    "font.txp",
    "jis2ucs.bin",
    "ucs2jis.bin",
}


def read_u16(
    data: bytes,
    offset: int,
) -> int:
    return struct.unpack_from(
        "<H",
        data,
        offset,
    )[0]


def is_sjis_lead(
    value: int,
) -> bool:
    return (
        0x81 <= value <= 0x9F
        or 0xE0 <= value <= 0xFC
    )


def is_sjis_trail(
    value: int,
) -> bool:
    return (
        0x40 <= value <= 0xFC
        and value != 0x7F
    )


def lead_slot(
    lead: int,
) -> int:
    if 0x81 <= lead <= 0x9F:
        return lead - 0x81

    if 0xE0 <= lead <= 0xFC:
        return lead - 0xC1

    raise ValueError(
        f"잘못된 Shift-JIS 리드 바이트: 0x{lead:02X}"
    )


def table_index_from_sjis(
    lead: int,
    trail: int,
) -> int:
    # core.font_runtime.FontRuntime과 같은 계산식
    return (
        0x1F
        + trail
        + lead_slot(lead) * 0xC0
    )


def decode_double_byte(
    lead: int,
    trail: int,
) -> str | None:
    pair = bytes((lead, trail))

    try:
        decoded = pair.decode(
            "shift_jis",
            errors="strict",
        )
    except UnicodeDecodeError:
        return None

    if len(decoded) != 1:
        return None

    return decoded


def character_class(
    character: str,
) -> str:
    codepoint = ord(character)

    if (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    ):
        return "kanji"

    if 0x3040 <= codepoint <= 0x309F:
        return "hiragana"

    if 0x30A0 <= codepoint <= 0x30FF:
        return "katakana"

    if 0x3000 <= codepoint <= 0x303F:
        return "punctuation"

    if 0xFF00 <= codepoint <= 0xFFEF:
        return "fullwidth"

    return "other"


def safe_reclaim_class(
    character: str,
) -> bool:
    # 현재 단계에서는 미사용 한자만 안전 후보로 취급한다.
    return character_class(character) == "kanji"


def scan_text_runs(
    data: bytes,
) -> tuple[
    Counter[bytes],
    int,
    int,
]:
    """
    실제 문자열처럼 보이는 연속 구간에서만
    Shift-JIS 2바이트 문자를 집계한다.

    인정 조건:
      - 2바이트 문자가 2개 이상
      - 또는 2바이트 문자 1개 이상이며 전체 길이 4자 이상
    """
    used_pairs: Counter[bytes] = Counter()
    run_count = 0
    multibyte_character_count = 0

    index = 0
    size = len(data)

    while index < size:
        start = index
        tokens: list[
            tuple[str, bytes | None]
        ] = []

        while index < size:
            value = data[index]

            # 일반 ASCII 문자
            if 0x20 <= value <= 0x7E:
                tokens.append(
                    (
                        chr(value),
                        None,
                    )
                )
                index += 1
                continue

            # 반각 가타카나
            if 0xA1 <= value <= 0xDF:
                try:
                    character = bytes(
                        (value,)
                    ).decode(
                        "shift_jis",
                        errors="strict",
                    )
                except UnicodeDecodeError:
                    break

                tokens.append(
                    (
                        character,
                        None,
                    )
                )
                index += 1
                continue

            # Shift-JIS 2바이트 문자
            if (
                is_sjis_lead(value)
                and index + 1 < size
                and is_sjis_trail(
                    data[index + 1]
                )
            ):
                trail = data[index + 1]
                character = decode_double_byte(
                    value,
                    trail,
                )

                if character is None:
                    break

                pair = bytes(
                    (value, trail)
                )

                tokens.append(
                    (
                        character,
                        pair,
                    )
                )
                index += 2
                continue

            break

        multibyte_tokens = [
            pair
            for _, pair in tokens
            if pair is not None
        ]

        accepted = (
            len(multibyte_tokens) >= 2
            or (
                len(multibyte_tokens) >= 1
                and len(tokens) >= 4
            )
        )

        if accepted:
            run_count += 1

            for pair in multibyte_tokens:
                used_pairs[pair] += 1
                multibyte_character_count += 1

        if index == start:
            index += 1
        elif not accepted and index < size:
            # 현재 정지 바이트 다음부터 다시 탐색
            index += 1

    return (
        used_pairs,
        run_count,
        multibyte_character_count,
    )


def count_raw_pairs(
    data: bytes,
) -> Counter[bytes]:
    """
    참고용 원시 바이트 출현 횟수다.
    후보 제외 조건으로 사용하지 않는다.
    """
    counts: Counter[bytes] = Counter()

    for index in range(
        0,
        len(data) - 1,
    ):
        lead = data[index]
        trail = data[index + 1]

        if not is_sjis_lead(lead):
            continue

        if not is_sjis_trail(trail):
            continue

        if decode_double_byte(
            lead,
            trail,
        ) is None:
            continue

        counts[
            bytes((lead, trail))
        ] += 1

    return counts


def main() -> int:
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

    glyph_count = (
        len(txp) - TXP_PIXEL_OFFSET
    ) // BYTES_PER_GLYPH

    if (
        len(txp) - TXP_PIXEL_OFFSET
    ) % BYTES_PER_GLYPH != 0:
        raise ValueError(
            "font.txp 글리프 영역 크기가 "
            "140바이트 단위가 아닙니다."
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

    # 현재 검증된 런타임 매핑을 자체 검사한다.
    known_checks = [
        (
            bytes.fromhex("82 CC"),
            0x01AB,
            0x011A,
            "の",
        ),
        (
            bytes.fromhex("8B E3"),
            0x0882,
            0x0334,
            "九",
        ),
        (
            bytes.fromhex("83 45"),
            0x01E4,
            0x0142,
            "ウ",
        ),
    ]

    for (
        pair,
        expected_table,
        expected_glyph,
        character,
    ) in known_checks:
        actual_table = (
            table_index_from_sjis(
                pair[0],
                pair[1],
            )
        )

        if actual_table != expected_table:
            raise ValueError(
                f"{character} 테이블 계산 실패: "
                f"0x{actual_table:04X} != "
                f"0x{expected_table:04X}"
            )

        actual_glyph = table[
            actual_table
        ]

        if actual_glyph != expected_glyph:
            raise ValueError(
                f"{character} 글리프 계산 실패: "
                f"0x{actual_glyph:04X} != "
                f"0x{expected_glyph:04X}"
            )

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

    text_usage: Counter[bytes] = Counter()
    raw_usage: Counter[bytes] = Counter()

    files_with_text = 0
    total_runs = 0
    total_multibyte_characters = 0

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
        ) = scan_text_runs(data)

        file_raw_usage = count_raw_pairs(
            data
        )

        text_usage.update(
            file_text_usage
        )
        raw_usage.update(
            file_raw_usage
        )

        if file_runs > 0:
            files_with_text += 1

        total_runs += file_runs
        total_multibyte_characters += (
            file_multibyte_count
        )

    mappings: list[
        dict[str, object]
    ] = []

    glyph_reference_counts: Counter[int] = (
        Counter()
    )

    # 먼저 전체 유효 문자→글리프 참조 수 계산
    for lead in (
        list(range(0x81, 0xA0))
        + list(range(0xE0, 0xFD))
    ):
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

            if table_index >= table_count:
                continue

            glyph_index = table[
                table_index
            ]

            if not (
                0 < glyph_index
                < glyph_count
            ):
                continue

            glyph_reference_counts[
                glyph_index
            ] += 1

            pair = bytes(
                (lead, trail)
            )

            mappings.append(
                {
                    "character": character,
                    "unicode": (
                        f"U+{ord(character):04X}"
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
                    "glyph_index": (
                        glyph_index
                    ),
                    "glyph_index_hex": (
                        f"0x{glyph_index:04X}"
                    ),
                    "text_uses": (
                        text_usage[pair]
                    ),
                    "raw_uses": (
                        raw_usage[pair]
                    ),
                    "class": (
                        character_class(
                            character
                        )
                    ),
                }
            )

    candidates: list[
        dict[str, object]
    ] = []

    for mapping in mappings:
        glyph_index = int(
            mapping["glyph_index"]
        )

        reference_count = (
            glyph_reference_counts[
                glyph_index
            ]
        )

        mapping[
            "glyph_reference_count"
        ] = reference_count

        safe = (
            int(mapping["text_uses"]) == 0
            and reference_count == 1
            and safe_reclaim_class(
                str(mapping["character"])
            )
        )

        mapping["safe_candidate"] = safe

        if safe:
            candidates.append(
                mapping
            )

    # 원시 바이너리 출현 횟수가 낮은 후보부터 정렬한다.
    candidates.sort(
        key=lambda item: (
            int(item["raw_uses"]),
            -int(item["sjis_value"]),
        )
    )

    report = {
        "format": (
            "prinny_textaware_font_capacity_v1"
        ),
        "runtime_directory": str(
            RUNTIME_DIR
        ),
        "table_count": table_count,
        "glyph_count": glyph_count,
        "scanned_files": len(
            scan_files
        ),
        "files_with_text": (
            files_with_text
        ),
        "detected_text_runs": (
            total_runs
        ),
        "detected_multibyte_characters": (
            total_multibyte_characters
        ),
        "valid_mappings": len(
            mappings
        ),
        "safe_candidate_count": len(
            candidates
        ),
        "candidates": candidates,
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

    print("TEXT-AWARE FONT CAPACITY")
    print("========================")
    print(
        f"TABLE COUNT            : "
        f"{table_count}"
    )
    print(
        f"GLYPH COUNT            : "
        f"{glyph_count}"
    )
    print(
        f"SCANNED FILES          : "
        f"{len(scan_files)}"
    )
    print(
        f"FILES WITH TEXT        : "
        f"{files_with_text}"
    )
    print(
        f"DETECTED TEXT RUNS     : "
        f"{total_runs}"
    )
    print(
        f"MULTIBYTE CHARACTERS   : "
        f"{total_multibyte_characters}"
    )
    print(
        f"VALID FONT MAPPINGS    : "
        f"{len(mappings)}"
    )
    print(
        f"SAFE KANJI CANDIDATES  : "
        f"{len(candidates)}"
    )
    print()

    for number, item in enumerate(
        candidates[
            :MAX_PRINTED_CANDIDATES
        ],
        start=1,
    ):
        print(
            f"{number:3d}. "
            f"CHAR={item['character']!r} "
            f"{item['unicode']} "
            f"SJIS={item['sjis']} "
            f"TABLE={item['table_index_hex']} "
            f"GLYPH={item['glyph_index_hex']} "
            f"TEXT={item['text_uses']} "
            f"RAW={item['raw_uses']} "
            f"REFS={item['glyph_reference_count']}"
        )

    print()
    print("REPORT:", REPORT_PATH)
    print("STATUS: PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
