from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_CSV = Path(
    "workspace/translations/export/"
    "translation_master.csv"
)

DEFAULT_MASTER_JSON = Path(
    "workspace/translations/export/"
    "translation_master.json"
)

DEFAULT_OUTPUT_DIR = Path(
    "workspace/translations/validation"
)

CONTROL_PATTERN = re.compile(
    r"""
    %[0-9$.*+\-]*[a-zA-Z]
    |\\[nrt0]
    |\{[^{}\r\n]+\}
    |<[^<>\r\n]+>
    """,
    re.VERBOSE,
)


def parse_integer(
    value: Any,
    default: int = 0,
) -> int:
    text = str(
        value if value is not None else ""
    ).strip()

    if not text:
        return default

    try:
        return int(text, 0)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return default


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"번역 기준 JSON이 없습니다: {path}"
        )

    document = json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )

    if not isinstance(document, dict):
        raise ValueError(
            "번역 기준 JSON 최상위 값이 객체가 아닙니다."
        )

    entries = document.get("entries")

    if not isinstance(entries, list):
        raise ValueError(
            "번역 기준 JSON에 entries 목록이 없습니다."
        )

    return document


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
            "translation_capacity_bytes",
        }

        fieldnames = set(
            reader.fieldnames or []
        )

        missing = required - fieldnames

        if missing:
            raise ValueError(
                "번역 CSV 필수 열 누락: "
                + ", ".join(sorted(missing))
            )

        return [
            {
                key: (
                    value
                    if value is not None
                    else ""
                )
                for key, value in row.items()
            }
            for row in reader
        ]


def encode_length(
    text: str,
) -> tuple[int, set[str], list[str]]:
    byte_length = 0
    hangul: set[str] = set()
    unsupported: list[str] = []

    for character in text:
        codepoint = ord(character)

        if 0xAC00 <= codepoint <= 0xD7A3:
            byte_length += 2
            hangul.add(character)
            continue

        try:
            encoded = character.encode(
                "shift_jis",
                errors="strict",
            )
        except UnicodeEncodeError:
            unsupported.append(character)
            continue

        byte_length += len(encoded)

    return (
        byte_length,
        hangul,
        unsupported,
    )


def control_tokens(
    text: str,
) -> Counter[str]:
    return Counter(
        CONTROL_PATTERN.findall(text)
    )


def format_characters(
    characters: list[str],
) -> str:
    unique: list[str] = []

    for character in characters:
        if character not in unique:
            unique.append(character)

    return " ".join(
        f"{character!r}(U+{ord(character):04X})"
        for character in unique
    )


def validate_translation(
    *,
    csv_path: Path = DEFAULT_CSV,
    master_json_path: Path = DEFAULT_MASTER_JSON,
) -> dict[str, Any]:
    rows = load_csv(csv_path)
    master = load_json(
        master_json_path
    )

    master_by_id = {
        str(entry.get("id", "")): entry
        for entry in master["entries"]
    }

    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    all_hangul: set[str] = set()

    category_counts: Counter[str] = Counter()
    resource_growth: Counter[str] = Counter()
    resource_overflows: Counter[str] = Counter()
    missing_master_ids: list[str] = []
    duplicate_ids: list[str] = []

    translated_rows = 0
    untranslated_rows = 0
    status_mismatch_count = 0
    total_growth = 0
    overflow_occurrences = 0

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        identifier = row["id"].strip()

        if identifier in seen_ids:
            duplicate_ids.append(identifier)
        else:
            seen_ids.add(identifier)

        master_entry = master_by_id.get(
            identifier
        )

        if master_entry is None:
            missing_master_ids.append(
                identifier
            )
            occurrences: list[
                dict[str, Any]
            ] = []
        else:
            occurrences = list(
                master_entry.get(
                    "occurrences",
                    [],
                )
            )

        source = row.get(
            "source_display",
            "",
        )
        translation = row.get(
            "translation",
            "",
        )
        status = row.get(
            "status",
            "",
        ).strip().casefold()

        capacity = parse_integer(
            row.get(
                "translation_capacity_bytes"
            )
        )

        occurrence_count = parse_integer(
            row.get(
                "occurrence_count"
            ),
            default=len(occurrences) or 1,
        )

        if translation:
            translated_rows += 1
        else:
            untranslated_rows += 1

        status_mismatch = (
            bool(translation)
            and status
            in {
                "",
                "untranslated",
                "미번역",
            }
        )

        if status_mismatch:
            status_mismatch_count += 1

        (
            encoded_length,
            hangul,
            unsupported,
        ) = encode_length(
            translation
        )

        all_hangul.update(hangul)

        original_tokens = control_tokens(
            source
        )
        translated_tokens = control_tokens(
            translation
        )

        control_mismatch = (
            original_tokens
            != translated_tokens
        )

        overflow_bytes = max(
            0,
            encoded_length - capacity,
        )

        boundaries = {
            str(
                occurrence.get(
                    "boundary",
                    "",
                )
            )
            for occurrence in occurrences
            if occurrence.get(
                "boundary"
            )
        }

        if not translation:
            category = "untranslated"
        elif unsupported:
            category = "unsupported-character"
        elif control_mismatch:
            category = "control-mismatch"
        elif overflow_bytes == 0:
            category = "fit"
        elif (
            "adjacent-data" in boundaries
            or not occurrences
        ):
            category = "overflow-risky"
        else:
            category = (
                "overflow-relocation-candidate"
            )

        category_counts[category] += 1

        occurrence_growth = (
            overflow_bytes
            * occurrence_count
        )

        total_growth += (
            occurrence_growth
        )

        if overflow_bytes:
            overflow_occurrences += (
                occurrence_count
            )

            if occurrences:
                for occurrence in occurrences:
                    resource = str(
                        occurrence.get(
                            "resource",
                            "",
                        )
                    )

                    if not resource:
                        continue

                    resource_growth[
                        resource
                    ] += overflow_bytes
                    resource_overflows[
                        resource
                    ] += 1
            else:
                resource = row.get(
                    "first_resource",
                    "",
                )

                if resource:
                    resource_growth[
                        resource
                    ] += occurrence_growth
                    resource_overflows[
                        resource
                    ] += occurrence_count

        result = {
            "row": row_number,
            "id": identifier,
            "source": source,
            "translation": translation,
            "status": status,
            "category": category,
            "capacity_bytes": capacity,
            "encoded_bytes": encoded_length,
            "overflow_bytes": overflow_bytes,
            "occurrence_count": occurrence_count,
            "occurrence_growth_bytes": (
                occurrence_growth
            ),
            "first_resource": row.get(
                "first_resource",
                "",
            ),
            "first_offset_hex": row.get(
                "first_offset_hex",
                "",
            ),
            "prefix_hex": row.get(
                "prefix_hex",
                "",
            ),
            "boundaries": sorted(
                boundaries
            ),
            "control_source": sorted(
                original_tokens.elements()
            ),
            "control_translation": sorted(
                translated_tokens.elements()
            ),
            "control_mismatch": (
                control_mismatch
            ),
            "unsupported": (
                format_characters(
                    unsupported
                )
            ),
            "hangul_count": len(
                hangul
            ),
            "status_mismatch": (
                status_mismatch
            ),
        }

        results.append(result)

    results.sort(
        key=lambda item: (
            -int(item["overflow_bytes"]),
            -int(item["occurrence_growth_bytes"]),
            str(item["first_resource"]),
            str(item["id"]),
        )
    )

    resource_report = [
        {
            "resource": resource,
            "overflow_occurrences": (
                resource_overflows[
                    resource
                ]
            ),
            "estimated_growth_bytes": (
                growth
            ),
        }
        for resource, growth in sorted(
            resource_growth.items(),
            key=lambda item: (
                -int(item[1]),
                item[0],
            ),
        )
    ]

    missing_csv_ids = sorted(
        set(master_by_id)
        - seen_ids
    )

    return {
        "format": (
            "prinny_translation_validation_v1"
        ),
        "csv": str(csv_path),
        "master_json": str(
            master_json_path
        ),
        "csv_rows": len(rows),
        "translated_rows": translated_rows,
        "untranslated_rows": (
            untranslated_rows
        ),
        "category_counts": dict(
            sorted(
                category_counts.items()
            )
        ),
        "overflow_rows": sum(
            1
            for result in results
            if int(
                result["overflow_bytes"]
            ) > 0
        ),
        "overflow_occurrences": (
            overflow_occurrences
        ),
        "estimated_total_growth_bytes": (
            total_growth
        ),
        "unique_hangul_count": len(
            all_hangul
        ),
        "required_hangul": "".join(
            sorted(all_hangul)
        ),
        "status_mismatch_count": (
            status_mismatch_count
        ),
        "duplicate_ids": sorted(
            set(duplicate_ids)
        ),
        "missing_master_ids": sorted(
            set(missing_master_ids)
        ),
        "missing_csv_ids": (
            missing_csv_ids
        ),
        "resources": resource_report,
        "results": results,
        "status": "pass",
    }


def save_validation(
    report: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> None:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = (
        output_dir / "validation.json"
    )
    csv_path = (
        output_dir / "validation.csv"
    )
    summary_path = (
        output_dir / "summary.txt"
    )
    overflow_path = (
        output_dir / "overflow_top.txt"
    )
    hangul_path = (
        output_dir / "required_hangul.txt"
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

    fieldnames = [
        "row",
        "id",
        "category",
        "source",
        "translation",
        "capacity_bytes",
        "encoded_bytes",
        "overflow_bytes",
        "occurrence_count",
        "occurrence_growth_bytes",
        "first_resource",
        "first_offset_hex",
        "prefix_hex",
        "boundaries",
        "control_mismatch",
        "unsupported",
        "status_mismatch",
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

        for result in report["results"]:
            writer.writerow(
                {
                    **{
                        field: result.get(
                            field,
                            "",
                        )
                        for field in fieldnames
                    },
                    "boundaries": " | ".join(
                        result["boundaries"]
                    ),
                }
            )

    summary_lines = [
        "PRINNY TRANSLATION VALIDATION",
        "=============================",
        (
            "CSV ROWS              : "
            f"{report['csv_rows']}"
        ),
        (
            "TRANSLATED ROWS       : "
            f"{report['translated_rows']}"
        ),
        (
            "UNTRANSLATED ROWS     : "
            f"{report['untranslated_rows']}"
        ),
        (
            "OVERFLOW ROWS         : "
            f"{report['overflow_rows']}"
        ),
        (
            "OVERFLOW OCCURRENCES  : "
            f"{report['overflow_occurrences']}"
        ),
        (
            "ESTIMATED GROWTH      : "
            f"{report['estimated_total_growth_bytes']} bytes"
        ),
        (
            "UNIQUE HANGUL         : "
            f"{report['unique_hangul_count']}"
        ),
        (
            "STATUS MISMATCH       : "
            f"{report['status_mismatch_count']}"
        ),
        (
            "DUPLICATE IDS         : "
            f"{len(report['duplicate_ids'])}"
        ),
        (
            "UNKNOWN IDS           : "
            f"{len(report['missing_master_ids'])}"
        ),
        (
            "MISSING CSV IDS       : "
            f"{len(report['missing_csv_ids'])}"
        ),
        "",
        "CATEGORIES",
        "----------",
    ]

    for category, count in report[
        "category_counts"
    ].items():
        summary_lines.append(
            f"{count:6d}  {category}"
        )

    summary_lines.extend(
        [
            "",
            "RESOURCE GROWTH ESTIMATE",
            "------------------------",
        ]
    )

    for resource in report[
        "resources"
    ]:
        summary_lines.append(
            f"{resource['estimated_growth_bytes']:8d}  "
            f"{resource['overflow_occurrences']:6d}  "
            f"{resource['resource']}"
        )

    summary_lines.extend(
        [
            "",
            f"JSON    : {json_path}",
            f"CSV     : {csv_path}",
            f"OVERFLOW: {overflow_path}",
            f"HANGUL  : {hangul_path}",
            "STATUS  : PASS",
        ]
    )

    summary_path.write_text(
        "\n".join(summary_lines)
        + "\n",
        encoding="utf-8",
    )

    overflow_lines = [
        "TOP TRANSLATION OVERFLOWS",
        "=========================",
        "",
    ]

    overflows = [
        result
        for result in report["results"]
        if int(
            result["overflow_bytes"]
        ) > 0
    ]

    for number, result in enumerate(
        overflows[:300],
        start=1,
    ):
        overflow_lines.extend(
            [
                (
                    f"{number:4d}. "
                    f"{result['id']} "
                    f"{result['category']}"
                ),
                (
                    f"      LOCATION : "
                    f"{result['first_resource']}"
                    f"@{result['first_offset_hex']}"
                ),
                (
                    f"      SIZE     : "
                    f"{result['encoded_bytes']} / "
                    f"{result['capacity_bytes']} "
                    f"(+{result['overflow_bytes']})"
                ),
                (
                    f"      USES     : "
                    f"{result['occurrence_count']} "
                    f"(growth "
                    f"{result['occurrence_growth_bytes']})"
                ),
                (
                    f"      SOURCE   : "
                    f"{result['source']!r}"
                ),
                (
                    f"      KOREAN   : "
                    f"{result['translation']!r}"
                ),
                "",
            ]
        )

    overflow_path.write_text(
        "\n".join(overflow_lines)
        + "\n",
        encoding="utf-8",
    )

    hangul_path.write_text(
        report["required_hangul"]
        + "\n",
        encoding="utf-8",
    )
