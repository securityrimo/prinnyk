#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


PROJECT = Path(
    "workspace/translations/curated/"
    "translation_project.json"
)

REPORT = Path(
    "workspace/reports/"
    "text_structure_markers.txt"
)


def is_halfwidth_katakana(
    character: str,
) -> bool:
    return (
        len(character) == 1
        and 0xFF61 <= ord(character) <= 0xFF9F
    )


def is_repeated_noise(
    source: str,
) -> bool:
    text = source

    if (
        text
        and is_halfwidth_katakana(
            text[0]
        )
    ):
        text = text[1:]

    return (
        len(text) >= 4
        and len(set(text)) == 1
    )


def main() -> int:
    if not PROJECT.is_file():
        raise FileNotFoundError(
            f"번역 프로젝트 없음: {PROJECT}"
        )

    document = json.loads(
        PROJECT.read_text(
            encoding="utf-8"
        )
    )

    groups = document[
        "translations"
    ]

    prefix_counts: Counter[str] = Counter()
    prefix_occurrences: Counter[str] = Counter()
    examples: dict[
        str,
        list[tuple[str, int, str, str]]
    ] = defaultdict(list)

    repeated_noise: list[
        tuple[str, int, str, str]
    ] = []

    for group in groups:
        source = str(
            group["source"]
        )
        occurrences = group[
            "occurrences"
        ]
        occurrence_count = int(
            group["occurrence_count"]
        )

        if (
            source
            and is_halfwidth_katakana(
                source[0]
            )
        ):
            prefix = source[0]
            first = occurrences[0]

            prefix_counts[prefix] += 1
            prefix_occurrences[
                prefix
            ] += occurrence_count

            if len(
                examples[prefix]
            ) < 20:
                examples[prefix].append(
                    (
                        source,
                        occurrence_count,
                        str(
                            first["resource"]
                        ),
                        str(
                            first["offset_hex"]
                        ),
                    )
                )

        if is_repeated_noise(
            source
        ):
            first = occurrences[0]

            repeated_noise.append(
                (
                    source,
                    occurrence_count,
                    str(
                        first["resource"]
                    ),
                    str(
                        first["offset_hex"]
                    ),
                )
            )

    lines: list[str] = [
        "TEXT STRUCTURE MARKER PROBE",
        "===========================",
        f"UNIQUE TEXTS          : {len(groups)}",
        (
            "HALFWIDTH-PREFIX TEXTS: "
            f"{sum(prefix_counts.values())}"
        ),
        (
            "PREFIX OCCURRENCES   : "
            f"{sum(prefix_occurrences.values())}"
        ),
        (
            "REPEATED NOISE       : "
            f"{len(repeated_noise)}"
        ),
        "",
        "LEADING HALFWIDTH MARKERS",
        "-------------------------",
    ]

    for prefix, count in (
        prefix_counts.most_common()
    ):
        encoded = prefix.encode(
            "shift_jis"
        )

        lines.append(
            f"{prefix!r} "
            f"U+{ord(prefix):04X} "
            f"SJIS={encoded.hex(' ').upper()} "
            f"UNIQUE={count} "
            f"USES={prefix_occurrences[prefix]}"
        )

        for (
            source,
            uses,
            resource,
            offset,
        ) in examples[prefix]:
            lines.append(
                f"    USES={uses:4d} "
                f"{resource}@{offset} "
                f"{source!r}"
            )

        lines.append("")

    lines.extend(
        [
            "REPEATED-CHARACTER NOISE",
            "------------------------",
        ]
    )

    for (
        source,
        uses,
        resource,
        offset,
    ) in repeated_noise[:100]:
        lines.append(
            f"USES={uses:4d} "
            f"{resource}@{offset} "
            f"{source!r}"
        )

    lines.extend(
        [
            "",
            f"REPORT: {REPORT}",
            "STATUS: PASS",
        ]
    )

    REPORT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = "\n".join(lines)

    REPORT.write_text(
        output + "\n",
        encoding="utf-8",
    )

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
