from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_CAPACITY_REPORT = Path(
    "workspace/reports/textaware_font_capacity.json"
)

DEFAULT_OUTPUT = Path(
    "workspace/font/hangul_map.json"
)


def is_hangul_syllable(character: str) -> bool:
    return (
        len(character) == 1
        and 0xAC00 <= ord(character) <= 0xD7A3
    )


def collect_unique_hangul(text: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for character in text:
        if not is_hangul_syllable(character):
            continue

        if character in seen:
            continue

        seen.add(character)
        result.append(character)

    return result


def load_safe_candidates(
    report_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not report_path.is_file():
        raise FileNotFoundError(
            f"용량 보고서가 없습니다: {report_path}"
        )

    report = json.loads(
        report_path.read_text(
            encoding="utf-8",
        )
    )

    if report.get("status") != "pass":
        raise ValueError(
            "용량 보고서 상태가 pass가 아닙니다."
        )

    candidates: list[dict[str, Any]] = []

    seen_sjis: set[str] = set()
    seen_glyphs: set[int] = set()

    for candidate in report.get(
        "candidates",
        [],
    ):
        if not bool(
            candidate.get("safe_candidate")
        ):
            continue

        if int(
            candidate.get("text_uses", -1)
        ) != 0:
            continue

        if int(
            candidate.get(
                "glyph_reference_count",
                -1,
            )
        ) != 1:
            continue

        sjis = str(
            candidate["sjis"]
        ).upper()

        glyph_index = int(
            candidate["glyph_index"]
        )

        if sjis in seen_sjis:
            raise ValueError(
                f"중복 Shift-JIS 후보: {sjis}"
            )

        if glyph_index in seen_glyphs:
            raise ValueError(
                "중복 글리프 후보: "
                f"0x{glyph_index:04X}"
            )

        seen_sjis.add(sjis)
        seen_glyphs.add(glyph_index)
        candidates.append(candidate)

    if not candidates:
        raise ValueError(
            "사용 가능한 안전 후보가 없습니다."
        )

    return report, candidates


def allocate_hangul(
    text: str,
    *,
    report_path: Path = DEFAULT_CAPACITY_REPORT,
) -> dict[str, Any]:
    hangul_characters = collect_unique_hangul(
        text
    )

    if not hangul_characters:
        raise ValueError(
            "입력에서 한글 완성형 문자를 "
            "찾지 못했습니다."
        )

    report, candidates = (
        load_safe_candidates(
            report_path
        )
    )

    if len(hangul_characters) > len(candidates):
        missing = (
            len(hangul_characters)
            - len(candidates)
        )

        raise ValueError(
            "한글 배정 용량이 부족합니다: "
            f"필요={len(hangul_characters)}, "
            f"용량={len(candidates)}, "
            f"부족={missing}"
        )

    allocations: list[
        dict[str, Any]
    ] = []

    for hangul, candidate in zip(
        hangul_characters,
        candidates,
    ):
        allocations.append(
            {
                "hangul": hangul,
                "hangul_unicode": (
                    f"U+{ord(hangul):04X}"
                ),
                "sjis": str(
                    candidate["sjis"]
                ).upper(),
                "table_index": int(
                    candidate["table_index"]
                ),
                "table_index_hex": (
                    f"0x{int(candidate['table_index']):04X}"
                ),
                "glyph_index": int(
                    candidate["glyph_index"]
                ),
                "glyph_index_hex": (
                    f"0x{int(candidate['glyph_index']):04X}"
                ),
                "replaced_character": str(
                    candidate["character"]
                ),
                "replaced_unicode": str(
                    candidate["unicode"]
                ),
                "raw_uses": int(
                    candidate["raw_uses"]
                ),
                "text_uses": int(
                    candidate["text_uses"]
                ),
                "glyph_reference_count": int(
                    candidate[
                        "glyph_reference_count"
                    ]
                ),
            }
        )

    encoded_map = {
        item["hangul"]: item["sjis"]
        for item in allocations
    }

    return {
        "format": (
            "prinny_hangul_allocation_v1"
        ),
        "source_text_sha1": hashlib.sha1(
            text.encode("utf-8")
        ).hexdigest(),
        "source_character_count": len(text),
        "unique_hangul_count": len(
            hangul_characters
        ),
        "capacity": len(candidates),
        "remaining_capacity": (
            len(candidates)
            - len(hangul_characters)
        ),
        "hangul_order": hangul_characters,
        "encoded_map": encoded_map,
        "allocations": allocations,
        "capacity_report": str(
            report_path
        ),
        "capacity_report_format": (
            report.get("format")
        ),
        "status": "pass",
    }


def save_allocation(
    allocation: dict[str, Any],
    output_path: Path = DEFAULT_OUTPUT,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            allocation,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
