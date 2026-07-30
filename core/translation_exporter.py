from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_PROJECT = Path(
    "workspace/translations/curated/"
    "translation_project.json"
)

DEFAULT_OUTPUT_DIR = Path(
    "workspace/translations/export"
)

# 현재 Demo00.dat 조사에서 확인한 구조용 접두 바이트.
# 번역 화면에서는 제거하지만 재삽입할 때 반드시 보존한다.
KNOWN_PREFIX_MARKERS = {
    "ﾈ": {
        "hex": "C8",
        "name": "marker_c8",
    },
    "ﾉ": {
        "hex": "C9",
        "name": "marker_c9",
    },
    "ﾊ": {
        "hex": "CA",
        "name": "marker_ca",
    },
}


def load_translation_project(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"번역 프로젝트가 없습니다: {path}"
        )

    document = json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )

    if not isinstance(document, dict):
        raise ValueError(
            "번역 프로젝트 최상위 값이 객체가 아닙니다."
        )

    translations = document.get(
        "translations"
    )

    if not isinstance(
        translations,
        list,
    ):
        raise ValueError(
            "translations 목록이 없습니다."
        )

    return document


def split_prefix(
    source: str,
) -> tuple[str, str, str, str]:
    if not source:
        return "", "", "", ""

    first = source[0]
    marker = KNOWN_PREFIX_MARKERS.get(
        first
    )

    if marker is None:
        return "", "", "", source

    return (
        first,
        str(marker["hex"]),
        str(marker["name"]),
        source[1:],
    )


def is_repeated_kanji_noise(
    source_display: str,
) -> bool:
    if len(source_display) < 4:
        return False

    if len(set(source_display)) != 1:
        return False

    codepoint = ord(
        source_display[0]
    )

    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def first_occurrence(
    occurrences: list[dict[str, Any]],
) -> dict[str, Any]:
    if not occurrences:
        return {
            "resource": "",
            "offset": 0,
            "offset_hex": "0x0",
        }

    return min(
        occurrences,
        key=lambda occurrence: (
            str(
                occurrence.get(
                    "resource",
                    "",
                )
            ),
            int(
                occurrence.get(
                    "offset",
                    0,
                )
            ),
        ),
    )


def build_export_entries(
    document: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    exported: list[
        dict[str, Any]
    ] = []

    excluded: list[
        dict[str, Any]
    ] = []

    for group in document[
        "translations"
    ]:
        source_raw = str(
            group.get(
                "source",
                "",
            )
        )

        (
            prefix_character,
            prefix_hex,
            prefix_name,
            source_display,
        ) = split_prefix(
            source_raw
        )

        if is_repeated_kanji_noise(
            source_display
        ):
            excluded.append(
                {
                    "id": group.get(
                        "id",
                        "",
                    ),
                    "source_raw": (
                        source_raw
                    ),
                    "reason": (
                        "repeated-kanji-noise"
                    ),
                    "occurrence_count": int(
                        group.get(
                            "occurrence_count",
                            0,
                        )
                    ),
                }
            )
            continue

        occurrences = list(
            group.get(
                "occurrences",
                []
            )
        )

        first = first_occurrence(
            occurrences
        )

        resources = sorted(
            {
                str(
                    occurrence.get(
                        "resource",
                        "",
                    )
                )
                for occurrence in occurrences
            }
        )

        total_capacity = int(
            group.get(
                "minimum_byte_capacity",
                0,
            )
        )

        prefix_size = (
            len(
                prefix_character.encode(
                    "shift_jis"
                )
            )
            if prefix_character
            else 0
        )

        translation_capacity = max(
            0,
            total_capacity - prefix_size,
        )

        flags: list[str] = []

        if prefix_character:
            flags.append(
                "preserve-prefix"
            )

        if not bool(
            group.get(
                "fixed_size_consistent",
                True,
            )
        ):
            flags.append(
                "variable-capacity"
            )

        boundaries = {
            str(
                occurrence.get(
                    "boundary",
                    "",
                )
            )
            for occurrence in occurrences
        }

        if "adjacent-data" in boundaries:
            flags.append(
                "adjacent-data-review"
            )

        if not source_display:
            flags.append(
                "empty-display"
            )

        exported.append(
            {
                "id": str(
                    group.get(
                        "id",
                        "",
                    )
                ),
                "source_raw": (
                    source_raw
                ),
                "source_display": (
                    source_display
                ),
                "prefix_character": (
                    prefix_character
                ),
                "prefix_hex": (
                    prefix_hex
                ),
                "prefix_name": (
                    prefix_name
                ),
                "translation": str(
                    group.get(
                        "translation",
                        "",
                    )
                ),
                "status": str(
                    group.get(
                        "status",
                        "untranslated",
                    )
                ),
                "notes": str(
                    group.get(
                        "notes",
                        "",
                    )
                ),
                "occurrence_count": int(
                    group.get(
                        "occurrence_count",
                        len(occurrences),
                    )
                ),
                "total_capacity_bytes": (
                    total_capacity
                ),
                "translation_capacity_bytes": (
                    translation_capacity
                ),
                "fixed_size_consistent": bool(
                    group.get(
                        "fixed_size_consistent",
                        True,
                    )
                ),
                "first_resource": str(
                    first.get(
                        "resource",
                        "",
                    )
                ),
                "first_offset": int(
                    first.get(
                        "offset",
                        0,
                    )
                ),
                "first_offset_hex": str(
                    first.get(
                        "offset_hex",
                        "0x0",
                    )
                ),
                "resources": resources,
                "review_flags": flags,
                "occurrences": occurrences,
            }
        )

    exported.sort(
        key=lambda entry: (
            entry["first_resource"],
            entry["first_offset"],
            entry["id"],
        )
    )

    excluded.sort(
        key=lambda entry: (
            entry["source_raw"],
            entry["id"],
        )
    )

    return exported, excluded


def save_csv(
    entries: list[dict[str, Any]],
    path: Path,
) -> None:
    fieldnames = [
        "id",
        "source_display",
        "translation",
        "status",
        "notes",
        "prefix_character",
        "prefix_hex",
        "source_raw",
        "occurrence_count",
        "translation_capacity_bytes",
        "total_capacity_bytes",
        "fixed_size_consistent",
        "first_resource",
        "first_offset_hex",
        "resources",
        "review_flags",
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for entry in entries:
            writer.writerow(
                {
                    "id": entry["id"],
                    "source_display": (
                        entry[
                            "source_display"
                        ]
                    ),
                    "translation": (
                        entry["translation"]
                    ),
                    "status": (
                        entry["status"]
                    ),
                    "notes": (
                        entry["notes"]
                    ),
                    "prefix_character": (
                        entry[
                            "prefix_character"
                        ]
                    ),
                    "prefix_hex": (
                        entry["prefix_hex"]
                    ),
                    "source_raw": (
                        entry["source_raw"]
                    ),
                    "occurrence_count": (
                        entry[
                            "occurrence_count"
                        ]
                    ),
                    "translation_capacity_bytes": (
                        entry[
                            "translation_capacity_bytes"
                        ]
                    ),
                    "total_capacity_bytes": (
                        entry[
                            "total_capacity_bytes"
                        ]
                    ),
                    "fixed_size_consistent": (
                        entry[
                            "fixed_size_consistent"
                        ]
                    ),
                    "first_resource": (
                        entry[
                            "first_resource"
                        ]
                    ),
                    "first_offset_hex": (
                        entry[
                            "first_offset_hex"
                        ]
                    ),
                    "resources": " | ".join(
                        entry["resources"]
                    ),
                    "review_flags": " | ".join(
                        entry["review_flags"]
                    ),
                }
            )


def export_translation_package(
    *,
    project_path: Path = DEFAULT_PROJECT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    document = load_translation_project(
        project_path
    )

    entries, excluded = (
        build_export_entries(
            document
        )
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    csv_path = (
        output_dir
        / "translation_master.csv"
    )
    json_path = (
        output_dir
        / "translation_master.json"
    )
    excluded_path = (
        output_dir
        / "excluded_entries.json"
    )
    readme_path = (
        output_dir
        / "README_TRANSLATION.txt"
    )
    summary_path = (
        output_dir
        / "summary.txt"
    )

    save_csv(
        entries,
        csv_path,
    )

    package = {
        "format": (
            "prinny_translator_package_v1"
        ),
        "source_project": str(
            project_path
        ),
        "source_project_sha1": (
            document.get(
                "project_sha1"
            )
        ),
        "entry_count": len(
            entries
        ),
        "excluded_count": len(
            excluded
        ),
        "entries": entries,
        "status": "pass",
    }

    json_path.write_text(
        json.dumps(
            package,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    excluded_path.write_text(
        json.dumps(
            {
                "format": (
                    "prinny_excluded_text_v1"
                ),
                "entries": excluded,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    readme_path.write_text(
        """PRINNY TRANSLATION FILE
=======================

수정할 열
---------
translation
status
notes

status 권장값
-------------
untranslated : 미번역
translated   : 번역 완료
review       : 재검토 필요
skip         : 번역하지 않음

수정하지 말아야 할 열
---------------------
id
source_raw
prefix_character
prefix_hex
first_resource
first_offset_hex

주의 사항
---------
1. CSV 파일은 UTF-8 또는 UTF-8-SIG로 저장합니다.
2. prefix_character와 prefix_hex는 구조용 바이트이므로 지우지 않습니다.
3. 제어 코드, 숫자 자리표시자, 특수 기호는 원문과 비교해 보존합니다.
4. translation_capacity_bytes는 현재 고정 공간 기준입니다.
5. 길이 초과 문장은 notes에 '길이 초과'라고 기록해도 됩니다.
6. 번역 완료 후 status를 translated로 변경합니다.
""",
        encoding="utf-8",
    )

    prefix_counts = Counter(
        entry["prefix_hex"]
        for entry in entries
        if entry["prefix_hex"]
    )

    resource_counts = Counter(
        entry["first_resource"]
        for entry in entries
    )

    lines = [
        "PRINNY TRANSLATOR PACKAGE",
        "=========================",
        (
            f"TRANSLATION ENTRIES : "
            f"{len(entries)}"
        ),
        (
            f"EXCLUDED NOISE      : "
            f"{len(excluded)}"
        ),
        (
            "PREFIXED ENTRIES    : "
            f"{sum(prefix_counts.values())}"
        ),
        "",
        "PREFIX MARKERS",
        "--------------",
    ]

    for marker, count in sorted(
        prefix_counts.items()
    ):
        lines.append(
            f"{count:6d}  {marker}"
        )

    lines.extend(
        [
            "",
            "ENTRIES BY FIRST RESOURCE",
            "-------------------------",
        ]
    )

    for resource, count in sorted(
        resource_counts.items(),
        key=lambda item: (
            -item[1],
            item[0],
        ),
    ):
        lines.append(
            f"{count:6d}  {resource}"
        )

    lines.extend(
        [
            "",
            f"CSV      : {csv_path}",
            f"JSON     : {json_path}",
            f"EXCLUDED : {excluded_path}",
            f"README   : {readme_path}",
            "STATUS   : PASS",
        ]
    )

    summary_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    return {
        "entry_count": len(entries),
        "excluded_count": len(
            excluded
        ),
        "prefixed_count": sum(
            prefix_counts.values()
        ),
        "output_dir": str(
            output_dir
        ),
        "status": "pass",
    }
