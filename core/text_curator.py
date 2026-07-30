from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_RAW_CATALOG = Path(
    "workspace/translations/catalog/catalog.json"
)

DEFAULT_OUTPUT_DIR = Path(
    "workspace/translations/curated"
)

DEFAULT_INCLUDED_RESOURCES = {
    "Demo00.dat",
    "PictureBook.dat",
    "StageInfo00.dat",
    "LuckyDoll.dat",
    "LuckyItem.dat",
    "Honor.dat",
    "Collection.dat",
    "MusicShop.dat",
    "ClearTime00.dat",
    "PrinnyName.dat",
    "Character00.dat",
}

DEFAULT_EXCLUDED_RESOURCES = {
    "anime00.dat",
    "effect00.GM3",
}


def load_catalog(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"원시 카탈로그가 없습니다: {path}"
        )

    data = json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )

    if not isinstance(data, dict):
        raise ValueError(
            "카탈로그 최상위 값이 객체가 아닙니다."
        )

    if data.get("status") != "pass":
        raise ValueError(
            "카탈로그 상태가 pass가 아닙니다."
        )

    entries = data.get("entries")

    if not isinstance(entries, list):
        raise ValueError(
            "카탈로그에 entries 목록이 없습니다."
        )

    return data


def normalized_resource(
    value: str,
) -> str:
    return Path(value).name.casefold()


def boundary_class(
    next_byte: int | None,
) -> str:
    if next_byte is None:
        return "eof"

    if next_byte == 0:
        return "null"

    if next_byte in {
        0x0A,
        0x0D,
    }:
        return "newline"

    if next_byte < 0x20:
        return "control"

    if next_byte in {
        0xFE,
        0xFF,
    }:
        return "marker"

    return "adjacent-data"


def repeated_character_noise(
    text: str,
) -> bool:
    if len(text) < 8:
        return False

    most_common = Counter(
        text
    ).most_common(1)

    if not most_common:
        return False

    _, count = most_common[0]

    return (
        count / len(text)
        >= 0.75
    )


def symbol_ratio(
    text: str,
) -> float:
    if not text:
        return 1.0

    symbols = 0

    for character in text:
        if character.isspace():
            continue

        if character.isalnum():
            continue

        codepoint = ord(character)

        # 일본어 문장 부호는 정상 텍스트로 취급한다.
        if 0x3000 <= codepoint <= 0x303F:
            continue

        if character in {
            "ー",
            "・",
            "…",
            "〜",
            "～",
        }:
            continue

        symbols += 1

    return symbols / len(text)


def classify_entry(
    entry: dict[str, Any],
    *,
    minimum_japanese_ratio: float,
    maximum_character_length: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    source = str(
        entry.get(
            "source",
            "",
        )
    )

    character_length = len(
        source
    )

    japanese_count = int(
        entry.get(
            "japanese_count",
            0,
        )
    )
    kana_count = int(
        entry.get(
            "kana_count",
            0,
        )
    )
    kanji_count = int(
        entry.get(
            "kanji_count",
            0,
        )
    )

    confidence = str(
        entry.get(
            "confidence",
            "low",
        )
    )

    if character_length < 2:
        reasons.append(
            "too-short"
        )

    if character_length > maximum_character_length:
        reasons.append(
            "too-long"
        )

    if "\ufffd" in source:
        reasons.append(
            "decode-replacement"
        )

    if "\x00" in source:
        reasons.append(
            "embedded-null"
        )

    if confidence not in {
        "high",
        "medium",
    }:
        reasons.append(
            "low-confidence"
        )

    if japanese_count < 2:
        reasons.append(
            "too-few-japanese"
        )

    if (
        kana_count + kanji_count
        < 2
    ):
        reasons.append(
            "too-few-kana-kanji"
        )

    if character_length:
        japanese_ratio = (
            japanese_count
            / character_length
        )
    else:
        japanese_ratio = 0.0

    if (
        japanese_ratio
        < minimum_japanese_ratio
    ):
        reasons.append(
            "low-japanese-ratio"
        )

    if symbol_ratio(source) > 0.45:
        reasons.append(
            "too-many-symbols"
        )

    if repeated_character_noise(
        source
    ):
        reasons.append(
            "repeated-character-noise"
        )

    # 너무 긴 ASCII 연속열은 구조명·디버그 데이터일 가능성이 높다.
    ascii_run = 0
    maximum_ascii_run = 0

    for character in source:
        if (
            ord(character) < 0x80
            and not character.isspace()
        ):
            ascii_run += 1
            maximum_ascii_run = max(
                maximum_ascii_run,
                ascii_run,
            )
        else:
            ascii_run = 0

    if maximum_ascii_run >= 24:
        reasons.append(
            "long-ascii-run"
        )

    return not reasons, reasons


def create_group_id(
    source: str,
) -> str:
    digest = hashlib.sha1(
        source.encode("utf-8")
    ).hexdigest()

    return f"TXT-{digest[:12].upper()}"


def curate_catalog(
    *,
    raw_catalog_path: Path = DEFAULT_RAW_CATALOG,
    include_resources: set[str] | None = None,
    exclude_resources: set[str] | None = None,
    use_all_resources: bool = False,
    minimum_japanese_ratio: float = 0.45,
    maximum_character_length: int = 256,
) -> dict[str, Any]:
    raw_catalog = load_catalog(
        raw_catalog_path
    )

    included = {
        item.casefold()
        for item in (
            include_resources
            if include_resources is not None
            else DEFAULT_INCLUDED_RESOURCES
        )
    }

    excluded = {
        item.casefold()
        for item in (
            exclude_resources
            if exclude_resources is not None
            else DEFAULT_EXCLUDED_RESOURCES
        )
    }

    accepted_entries: list[
        dict[str, Any]
    ] = []

    rejected_counts: Counter[str] = (
        Counter()
    )

    rejected_resources: Counter[str] = (
        Counter()
    )

    raw_entries = raw_catalog[
        "entries"
    ]

    for entry in raw_entries:
        resource = str(
            entry.get(
                "resource",
                "",
            )
        )
        resource_name = (
            normalized_resource(
                resource
            )
        )

        if resource_name in excluded:
            rejected_counts[
                "excluded-resource"
            ] += 1
            rejected_resources[
                resource
            ] += 1
            continue

        if (
            not use_all_resources
            and resource_name
            not in included
        ):
            rejected_counts[
                "not-in-allowlist"
            ] += 1
            rejected_resources[
                resource
            ] += 1
            continue

        accepted, reasons = (
            classify_entry(
                entry,
                minimum_japanese_ratio=(
                    minimum_japanese_ratio
                ),
                maximum_character_length=(
                    maximum_character_length
                ),
            )
        )

        if not accepted:
            for reason in reasons:
                rejected_counts[
                    reason
                ] += 1

            rejected_resources[
                resource
            ] += 1
            continue

        copied = dict(
            entry
        )

        copied[
            "offset_hex"
        ] = (
            f"0x{int(entry['offset']):X}"
        )

        copied[
            "boundary"
        ] = boundary_class(
            entry.get(
                "next_byte"
            )
        )

        accepted_entries.append(
            copied
        )

    accepted_entries.sort(
        key=lambda item: (
            str(item["resource"]),
            int(item["offset"]),
        )
    )

    grouped: dict[
        str,
        dict[str, Any]
    ] = {}

    for entry in accepted_entries:
        source = str(
            entry["source"]
        )

        group = grouped.get(
            source
        )

        if group is None:
            group = {
                "id": (
                    create_group_id(
                        source
                    )
                ),
                "source": source,
                "translation": "",
                "status": "untranslated",
                "notes": "",
                "occurrences": [],
            }

            grouped[
                source
            ] = group

        group[
            "occurrences"
        ].append(
            {
                "resource": (
                    entry["resource"]
                ),
                "offset": (
                    entry["offset"]
                ),
                "offset_hex": (
                    entry["offset_hex"]
                ),
                "byte_length": (
                    entry["byte_length"]
                ),
                "character_length": (
                    entry[
                        "character_length"
                    ]
                ),
                "confidence": (
                    entry["confidence"]
                ),
                "boundary": (
                    entry["boundary"]
                ),
                "source_hex": (
                    entry["source_hex"]
                ),
                "context_hex": (
                    entry["context_hex"]
                ),
            }
        )

    groups = list(
        grouped.values()
    )

    for group in groups:
        occurrences = group[
            "occurrences"
        ]

        byte_lengths = sorted(
            {
                int(
                    occurrence[
                        "byte_length"
                    ]
                )
                for occurrence in occurrences
            }
        )

        group[
            "occurrence_count"
        ] = len(
            occurrences
        )
        group[
            "byte_lengths"
        ] = byte_lengths
        group[
            "minimum_byte_capacity"
        ] = min(
            byte_lengths
        )
        group[
            "maximum_byte_capacity"
        ] = max(
            byte_lengths
        )

        group[
            "fixed_size_consistent"
        ] = (
            len(byte_lengths) == 1
        )

    groups.sort(
        key=lambda item: (
            -int(
                item[
                    "occurrence_count"
                ]
            ),
            str(item["source"]),
        )
    )

    resource_counts = Counter(
        str(entry["resource"])
        for entry in accepted_entries
    )

    boundary_counts = Counter(
        str(entry["boundary"])
        for entry in accepted_entries
    )

    project_hash = hashlib.sha1()

    for group in groups:
        project_hash.update(
            str(group["id"]).encode(
                "utf-8"
            )
        )
        project_hash.update(
            str(group["source"]).encode(
                "utf-8"
            )
        )

    return {
        "format": (
            "prinny_curated_text_project_v1"
        ),
        "source_catalog": str(
            raw_catalog_path
        ),
        "source_catalog_sha1": (
            raw_catalog.get(
                "catalog_sha1"
            )
        ),
        "project_sha1": (
            project_hash.hexdigest()
        ),
        "raw_entry_count": len(
            raw_entries
        ),
        "accepted_occurrence_count": len(
            accepted_entries
        ),
        "unique_text_count": len(
            groups
        ),
        "resource_count": len(
            resource_counts
        ),
        "minimum_japanese_ratio": (
            minimum_japanese_ratio
        ),
        "maximum_character_length": (
            maximum_character_length
        ),
        "use_all_resources": (
            use_all_resources
        ),
        "included_resources": sorted(
            included
        ),
        "excluded_resources": sorted(
            excluded
        ),
        "resource_entries": dict(
            sorted(
                resource_counts.items()
            )
        ),
        "boundary_counts": dict(
            sorted(
                boundary_counts.items()
            )
        ),
        "rejected_counts": dict(
            sorted(
                rejected_counts.items()
            )
        ),
        "rejected_resources": dict(
            sorted(
                rejected_resources.items()
            )
        ),
        "entries": accepted_entries,
        "translations": groups,
        "status": "pass",
    }


def save_curated_project(
    project: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> None:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    catalog_path = (
        output_dir
        / "curated_catalog.json"
    )
    project_path = (
        output_dir
        / "translation_project.json"
    )
    csv_path = (
        output_dir
        / "translation_project.csv"
    )
    samples_path = (
        output_dir
        / "review_samples.txt"
    )
    summary_path = (
        output_dir
        / "summary.txt"
    )

    catalog_document = {
        key: value
        for key, value in project.items()
        if key != "translations"
    }

    catalog_path.write_text(
        json.dumps(
            catalog_document,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    translation_document = {
        "format": (
            "prinny_translation_project_v2"
        ),
        "project_sha1": (
            project["project_sha1"]
        ),
        "source_catalog_sha1": (
            project[
                "source_catalog_sha1"
            ]
        ),
        "translations": (
            project["translations"]
        ),
        "status": "pass",
    }

    project_path.write_text(
        json.dumps(
            translation_document,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    fieldnames = [
        "id",
        "source",
        "translation",
        "status",
        "notes",
        "occurrence_count",
        "minimum_byte_capacity",
        "maximum_byte_capacity",
        "fixed_size_consistent",
        "resources",
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

        for group in project[
            "translations"
        ]:
            resources = sorted(
                {
                    occurrence[
                        "resource"
                    ]
                    for occurrence
                    in group[
                        "occurrences"
                    ]
                }
            )

            writer.writerow(
                {
                    "id": group["id"],
                    "source": (
                        group["source"]
                    ),
                    "translation": "",
                    "status": (
                        "untranslated"
                    ),
                    "notes": "",
                    "occurrence_count": (
                        group[
                            "occurrence_count"
                        ]
                    ),
                    "minimum_byte_capacity": (
                        group[
                            "minimum_byte_capacity"
                        ]
                    ),
                    "maximum_byte_capacity": (
                        group[
                            "maximum_byte_capacity"
                        ]
                    ),
                    "fixed_size_consistent": (
                        group[
                            "fixed_size_consistent"
                        ]
                    ),
                    "resources": " | ".join(
                        resources
                    ),
                }
            )

    sample_lines = [
        "CURATED TEXT REVIEW SAMPLES",
        "===========================",
        "",
    ]

    for number, group in enumerate(
        project["translations"][:300],
        start=1,
    ):
        first = group[
            "occurrences"
        ][0]

        source = str(
            group["source"]
        )

        if len(source) > 120:
            source = (
                source[:117]
                + "..."
            )

        sample_lines.append(
            f"{number:4d}. "
            f"{group['id']} "
            f"USES={group['occurrence_count']} "
            f"CAP={group['minimum_byte_capacity']} "
            f"{first['resource']}"
            f"@{first['offset_hex']} "
            f"{source!r}"
        )

    samples_path.write_text(
        "\n".join(
            sample_lines
        )
        + "\n",
        encoding="utf-8",
    )

    summary_lines = [
        "PRINNY CURATED TEXT PROJECT",
        "===========================",
        (
            "RAW ENTRIES         : "
            f"{project['raw_entry_count']}"
        ),
        (
            "ACCEPTED OCCURRENCES: "
            f"{project['accepted_occurrence_count']}"
        ),
        (
            "UNIQUE TEXTS        : "
            f"{project['unique_text_count']}"
        ),
        (
            "RESOURCES           : "
            f"{project['resource_count']}"
        ),
        (
            "PROJECT SHA1        : "
            f"{project['project_sha1']}"
        ),
        "",
        "BOUNDARIES",
        "----------",
    ]

    for name, count in project[
        "boundary_counts"
    ].items():
        summary_lines.append(
            f"{count:6d}  {name}"
        )

    summary_lines.extend(
        [
            "",
            "ACCEPTED RESOURCES",
            "------------------",
        ]
    )

    for resource, count in sorted(
        project[
            "resource_entries"
        ].items(),
        key=lambda item: (
            -int(item[1]),
            item[0],
        ),
    ):
        summary_lines.append(
            f"{count:6d}  {resource}"
        )

    summary_lines.extend(
        [
            "",
            "REJECTION REASONS",
            "-----------------",
        ]
    )

    for reason, count in sorted(
        project[
            "rejected_counts"
        ].items(),
        key=lambda item: (
            -int(item[1]),
            item[0],
        ),
    ):
        summary_lines.append(
            f"{count:6d}  {reason}"
        )

    summary_lines.extend(
        [
            "",
            f"CATALOG : {catalog_path}",
            f"PROJECT : {project_path}",
            f"CSV     : {csv_path}",
            f"SAMPLES : {samples_path}",
            "STATUS  : PASS",
        ]
    )

    summary_path.write_text(
        "\n".join(
            summary_lines
        )
        + "\n",
        encoding="utf-8",
    )
