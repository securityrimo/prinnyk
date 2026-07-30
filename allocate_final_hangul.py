#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_PLAN = Path(
    "workspace/font/final_charset_plan/"
    "final_charset_plan.json"
)

DEFAULT_TRANSLATIONS = Path(
    "workspace/translations/export/"
    "translation_master.csv"
)

DEFAULT_OUTPUT_DIR = Path(
    "workspace/font/final_allocation"
)


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()

    with path.open("rb") as handle:
        while block := handle.read(
            1024 * 1024
        ):
            digest.update(block)

    return digest.hexdigest()


def load_plan(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"최종 문자셋 계획이 없습니다: {path}"
        )

    document = json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )

    if not isinstance(document, dict):
        raise ValueError(
            "문자셋 계획 최상위 값이 객체가 아닙니다."
        )

    required_fields = {
        "required_hangul",
        "required_hangul_count",
        "strict_candidates",
        "review_candidates",
        "status",
    }

    missing = (
        required_fields
        - set(document)
    )

    if missing:
        raise ValueError(
            "문자셋 계획 필드 누락: "
            + ", ".join(
                sorted(missing)
            )
        )

    return document


def load_hangul_frequency(
    path: Path,
) -> Counter[str]:
    if not path.is_file():
        raise FileNotFoundError(
            f"번역 CSV가 없습니다: {path}"
        )

    frequency: Counter[str] = Counter()

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        fields = set(
            reader.fieldnames or []
        )

        if "translation" not in fields:
            raise ValueError(
                "번역 CSV에 translation 열이 없습니다."
            )

        for row in reader:
            translation = (
                row.get(
                    "translation"
                )
                or ""
            )

            for character in translation:
                if (
                    0xAC00
                    <= ord(character)
                    <= 0xD7A3
                ):
                    frequency[
                        character
                    ] += 1

    return frequency


def parse_sjis(
    candidate: dict[str, Any],
) -> tuple[int, int]:
    value = candidate.get(
        "sjis_value"
    )

    if isinstance(value, int):
        return (
            (value >> 8) & 0xFF,
            value & 0xFF,
        )

    text = str(
        candidate.get(
            "sjis",
            "",
        )
    ).replace(
        " ",
        "",
    )

    if len(text) != 4:
        raise ValueError(
            f"잘못된 SJIS 값: {candidate}"
        )

    value = int(
        text,
        16,
    )

    return (
        (value >> 8) & 0xFF,
        value & 0xFF,
    )


def candidate_sort_key(
    candidate: dict[str, Any],
) -> tuple[int, int, int]:
    return (
        int(
            candidate.get(
                "alias_count",
                1,
            )
        ),
        int(
            candidate.get(
                "glyph_index",
                0,
            )
        ),
        int(
            candidate.get(
                "sjis_value",
                0,
            )
        ),
    )


def allocate(
    *,
    plan: dict[str, Any],
    frequency: Counter[str],
    allow_review: bool,
) -> dict[str, Any]:
    unsupported = str(
        plan.get(
            "unsupported_characters",
            "",
        )
    )

    missing_mappings = str(
        plan.get(
            "missing_font_mappings",
            "",
        )
    )

    missing_ids = list(
        plan.get(
            "missing_csv_ids",
            [],
        )
    )

    if unsupported:
        raise ValueError(
            "지원 불가 문자가 남아 있습니다: "
            f"{unsupported!r}"
        )

    if missing_mappings:
        raise ValueError(
            "폰트 매핑이 없는 문자가 남아 있습니다: "
            f"{missing_mappings!r}"
        )

    if missing_ids:
        raise ValueError(
            "번역 CSV에서 누락된 ID가 있습니다: "
            f"{len(missing_ids)}개"
        )

    required_from_plan = set(
        str(
            plan[
                "required_hangul"
            ]
        )
    )

    required_from_csv = set(
        frequency
    )

    if (
        required_from_plan
        != required_from_csv
    ):
        only_plan = sorted(
            required_from_plan
            - required_from_csv
        )

        only_csv = sorted(
            required_from_csv
            - required_from_plan
        )

        raise ValueError(
            "문자셋 계획과 현재 CSV가 다릅니다. "
            f"계획에만 있음={only_plan[:20]}, "
            f"CSV에만 있음={only_csv[:20]}. "
            "문자셋 계획을 다시 실행하세요."
        )

    hangul_order = sorted(
        required_from_csv,
        key=lambda character: (
            -frequency[character],
            ord(character),
        ),
    )

    strict_candidates = sorted(
        list(
            plan[
                "strict_candidates"
            ]
        ),
        key=candidate_sort_key,
    )

    review_candidates = sorted(
        list(
            plan[
                "review_candidates"
            ]
        ),
        key=candidate_sort_key,
    )

    selected: list[
        tuple[
            dict[str, Any],
            str,
        ]
    ] = [
        (
            candidate,
            "strict",
        )
        for candidate
        in strict_candidates
    ]

    if (
        len(selected)
        < len(hangul_order)
        and allow_review
    ):
        selected.extend(
            (
                candidate,
                "review",
            )
            for candidate
            in review_candidates
        )

    if len(selected) < len(
        hangul_order
    ):
        shortage = (
            len(hangul_order)
            - len(selected)
        )

        raise RuntimeError(
            "글리프 용량이 부족합니다. "
            f"필요={len(hangul_order)}, "
            f"사용 가능={len(selected)}, "
            f"부족={shortage}, "
            f"검토 후보 허용={allow_review}"
        )

    selected = selected[
        :len(hangul_order)
    ]

    allocations: list[
        dict[str, Any]
    ] = []

    mapping: dict[
        str,
        dict[str, Any]
    ] = {}

    used_sjis: set[int] = set()
    used_glyphs: set[int] = set()
    used_tables: set[int] = set()

    for index, (
        hangul,
        selected_item,
    ) in enumerate(
        zip(
            hangul_order,
            selected,
            strict=True,
        ),
        start=1,
    ):
        candidate, safety = (
            selected_item
        )

        lead, trail = parse_sjis(
            candidate
        )

        sjis_value = (
            lead << 8
        ) | trail

        glyph_index = int(
            candidate[
                "glyph_index"
            ]
        )

        table_index = int(
            candidate[
                "table_index"
            ]
        )

        if sjis_value in used_sjis:
            raise ValueError(
                f"중복 SJIS 배정: "
                f"{lead:02X} {trail:02X}"
            )

        if glyph_index in used_glyphs:
            raise ValueError(
                f"중복 글리프 배정: "
                f"0x{glyph_index:04X}"
            )

        if table_index in used_tables:
            raise ValueError(
                f"중복 테이블 배정: "
                f"0x{table_index:04X}"
            )

        used_sjis.add(
            sjis_value
        )
        used_glyphs.add(
            glyph_index
        )
        used_tables.add(
            table_index
        )

        aliases = list(
            candidate.get(
                "aliases",
                [],
            )
        )

        record = {
            "index": index,
            "hangul": hangul,
            "unicode": (
                f"U+{ord(hangul):04X}"
            ),
            "frequency": int(
                frequency[hangul]
            ),
            "safety": safety,
            "sjis": (
                f"{lead:02X} "
                f"{trail:02X}"
            ),
            "sjis_value": (
                sjis_value
            ),
            "lead": lead,
            "trail": trail,
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
            "replaces": str(
                candidate.get(
                    "character",
                    "",
                )
            ),
            "replaces_unicode": str(
                candidate.get(
                    "unicode",
                    "",
                )
            ),
            "alias_count": int(
                candidate.get(
                    "alias_count",
                    len(aliases),
                )
            ),
            "aliases": aliases,
        }

        allocations.append(
            record
        )

        mapping[
            hangul
        ] = record

    strict_used = sum(
        allocation["safety"]
        == "strict"
        for allocation
        in allocations
    )

    review_used = sum(
        allocation["safety"]
        == "review"
        for allocation
        in allocations
    )

    return {
        "format": (
            "prinny_hangul_allocation_v2"
        ),
        "required_count": len(
            hangul_order
        ),
        "strict_used": strict_used,
        "review_used": review_used,
        "unused_selected_capacity": (
            len(selected)
            - len(hangul_order)
        ),
        "hangul_order": "".join(
            hangul_order
        ),
        "allocations": allocations,
        "mapping": mapping,
        "status": "pass",
    }


def save_result(
    *,
    result: dict[str, Any],
    output_dir: Path,
    plan_path: Path,
    translation_path: Path,
) -> None:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = (
        output_dir
        / "hangul_allocation.json"
    )

    text_path = (
        output_dir
        / "hangul_allocation.txt"
    )

    result[
        "source_plan"
    ] = str(plan_path)

    result[
        "source_plan_sha1"
    ] = file_sha1(
        plan_path
    )

    result[
        "source_translation"
    ] = str(
        translation_path
    )

    result[
        "source_translation_sha1"
    ] = file_sha1(
        translation_path
    )

    json_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "FINAL HANGUL ALLOCATION",
        "=======================",
        (
            "REQUIRED HANGUL : "
            f"{result['required_count']}"
        ),
        (
            "STRICT USED     : "
            f"{result['strict_used']}"
        ),
        (
            "REVIEW USED     : "
            f"{result['review_used']}"
        ),
        "",
        "FIRST ALLOCATIONS",
        "-----------------",
    ]

    for allocation in result[
        "allocations"
    ][:100]:
        lines.append(
            f"{allocation['index']:4d}. "
            f"{allocation['hangul']!r} "
            f"FREQ={allocation['frequency']:5d} "
            f"SJIS={allocation['sjis']} "
            f"TABLE={allocation['table_index_hex']} "
            f"GLYPH={allocation['glyph_index_hex']} "
            f"REPLACES={allocation['replaces']!r} "
            f"SAFETY={allocation['safety']}"
        )

    lines.extend(
        [
            "",
            f"JSON  : {json_path}",
            "STATUS: PASS",
        ]
    )

    text_path.write_text(
        "\n".join(lines)
        + "\n",
        encoding="utf-8",
    )

    print(
        "\n".join(lines)
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "최종 번역에 필요한 한글을 "
            "회수 가능한 Shift-JIS 글리프에 "
            "결정적으로 배정합니다."
        )
    )

    parser.add_argument(
        "--plan",
        type=Path,
        default=DEFAULT_PLAN,
    )

    parser.add_argument(
        "--translations",
        type=Path,
        default=DEFAULT_TRANSLATIONS,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )

    parser.add_argument(
        "--allow-review",
        action="store_true",
        help=(
            "strict 후보가 부족할 때 "
            "review 후보도 사용합니다."
        ),
    )

    return parser


def main() -> int:
    arguments = (
        build_parser().parse_args()
    )

    plan = load_plan(
        arguments.plan
    )

    frequency = (
        load_hangul_frequency(
            arguments.translations
        )
    )

    result = allocate(
        plan=plan,
        frequency=frequency,
        allow_review=(
            arguments.allow_review
        ),
    )

    save_result(
        result=result,
        output_dir=(
            arguments.output_dir
        ),
        plan_path=arguments.plan,
        translation_path=(
            arguments.translations
        ),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
