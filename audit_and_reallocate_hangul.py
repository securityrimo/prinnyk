#!/usr/bin/env python3
from __future__ import annotations

import bisect
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PLAN_PATH = Path(
    "workspace/font/final_charset_plan/"
    "final_charset_plan.json"
)

TRANSLATION_CSV = Path(
    "workspace/translations/export/"
    "translation_master.csv"
)

MASTER_JSON = Path(
    "workspace/translations/export/"
    "translation_master.json"
)

RAW_CATALOG = Path(
    "workspace/translations/catalog/"
    "catalog.json"
)

RUNTIME_DIR = Path(
    "workspace/unpack/START_runtime"
)

OUTPUT_DIR = Path(
    "workspace/font/audited_allocation"
)

EXCLUDED_FILES = {
    "font.fnt",
    "font.txp",
    "jis2ucs.bin",
    "ucs2jis.bin",
}

MAX_EXAMPLES = 6


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"필수 파일이 없습니다: {path}"
        )

    document = json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )

    if not isinstance(document, dict):
        raise ValueError(
            f"JSON 최상위 값이 객체가 아닙니다: {path}"
        )

    return document


def sha1_file(
    path: Path,
) -> str:
    digest = hashlib.sha1()

    with path.open("rb") as handle:
        while True:
            block = handle.read(
                1024 * 1024
            )

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def resource_key(
    value: str | Path,
) -> str:
    return Path(value).name.casefold()


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
                "translation 열이 없습니다."
            )

        for row in reader:
            translation = (
                row.get("translation")
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


def merge_intervals(
    intervals: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    normalized = sorted(
        (
            int(start),
            int(end),
        )
        for start, end in intervals
        if int(end) > int(start)
    )

    merged: list[
        tuple[int, int]
    ] = []

    for start, end in normalized:
        if (
            not merged
            or start > merged[-1][1]
        ):
            merged.append(
                (
                    start,
                    end,
                )
            )
            continue

        previous_start, previous_end = (
            merged[-1]
        )

        merged[-1] = (
            previous_start,
            max(
                previous_end,
                end,
            ),
        )

    return merged


def prepare_intervals(
    mapping: dict[
        str,
        list[tuple[int, int]]
    ],
) -> dict[
    str,
    tuple[
        list[int],
        list[tuple[int, int]],
    ]
]:
    prepared: dict[
        str,
        tuple[
            list[int],
            list[tuple[int, int]],
        ]
    ] = {}

    for resource, intervals in (
        mapping.items()
    ):
        merged = merge_intervals(
            intervals
        )

        prepared[resource] = (
            [
                interval[0]
                for interval in merged
            ],
            merged,
        )

    return prepared


def contains_span(
    prepared: dict[
        str,
        tuple[
            list[int],
            list[tuple[int, int]],
        ]
    ],
    resource: str,
    offset: int,
    size: int = 2,
) -> bool:
    item = prepared.get(
        resource
    )

    if item is None:
        return False

    starts, intervals = item

    index = (
        bisect.bisect_right(
            starts,
            offset,
        )
        - 1
    )

    if index < 0:
        return False

    start, end = intervals[index]

    return (
        start <= offset
        and offset + size <= end
    )


def build_translated_intervals(
    master: dict[str, Any],
) -> tuple[
    dict[
        str,
        list[tuple[int, int]]
    ],
    set[str],
]:
    entries = master.get(
        "entries"
    )

    if not isinstance(entries, list):
        raise ValueError(
            "translation_master.json에 "
            "entries 목록이 없습니다."
        )

    intervals: dict[
        str,
        list[tuple[int, int]]
    ] = defaultdict(list)

    resources: set[str] = set()

    for entry in entries:
        occurrences = entry.get(
            "occurrences",
            []
        )

        if not isinstance(
            occurrences,
            list,
        ):
            continue

        for occurrence in occurrences:
            resource = resource_key(
                str(
                    occurrence.get(
                        "resource",
                        "",
                    )
                )
            )

            if not resource:
                continue

            start = int(
                occurrence.get(
                    "offset",
                    0,
                )
            )

            length = int(
                occurrence.get(
                    "byte_length",
                    0,
                )
            )

            if length <= 0:
                continue

            intervals[resource].append(
                (
                    start,
                    start + length,
                )
            )

            resources.add(resource)

    return intervals, resources


def build_catalog_intervals(
    catalog: dict[str, Any],
) -> dict[
    str,
    list[tuple[int, int]]
]:
    entries = catalog.get(
        "entries"
    )

    if not isinstance(entries, list):
        raise ValueError(
            "원시 catalog.json에 "
            "entries 목록이 없습니다."
        )

    intervals: dict[
        str,
        list[tuple[int, int]]
    ] = defaultdict(list)

    for entry in entries:
        resource = resource_key(
            str(
                entry.get(
                    "resource",
                    "",
                )
            )
        )

        if not resource:
            continue

        start = int(
            entry.get(
                "offset",
                0,
            )
        )

        end_value = entry.get(
            "end"
        )

        if end_value is None:
            end = (
                start
                + int(
                    entry.get(
                        "byte_length",
                        0,
                    )
                )
            )
        else:
            end = int(end_value)

        if end <= start:
            continue

        intervals[resource].append(
            (
                start,
                end,
            )
        )

    return intervals


def parse_sjis_value(
    candidate: dict[str, Any],
) -> int:
    value = candidate.get(
        "sjis_value"
    )

    if isinstance(value, int):
        return value

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
            f"잘못된 SJIS 후보: {candidate}"
        )

    return int(
        text,
        16,
    )


def add_example(
    stat: dict[str, Any],
    category: str,
    *,
    resource: str,
    offset: int,
    data: bytes,
) -> None:
    examples = stat[
        "examples"
    ][category]

    if len(examples) >= MAX_EXAMPLES:
        return

    context_start = max(
        0,
        offset - 12,
    )

    context_end = min(
        len(data),
        offset + 14,
    )

    context = data[
        context_start:
        context_end
    ]

    examples.append(
        {
            "resource": resource,
            "offset": offset,
            "offset_hex": (
                f"0x{offset:X}"
            ),
            "context_hex": (
                context
                .hex(" ")
                .upper()
            ),
            "context_text": (
                context.decode(
                    "shift_jis",
                    errors="replace",
                )
            ),
        }
    )


def candidate_sort_key(
    item: dict[str, Any],
) -> tuple[int, int, int, int]:
    audit = item["audit"]

    return (
        int(
            audit[
                "catalog_noise_hits"
            ]
        ),
        int(
            audit["raw_hits"]
        ),
        int(
            item.get(
                "alias_count",
                1,
            )
        ),
        int(
            item.get(
                "glyph_index",
                0,
            )
        ),
    )


def main() -> int:
    plan = load_json(
        PLAN_PATH
    )

    master = load_json(
        MASTER_JSON
    )

    raw_catalog = load_json(
        RAW_CATALOG
    )

    if not RUNTIME_DIR.is_dir():
        raise FileNotFoundError(
            f"런타임 폴더가 없습니다: "
            f"{RUNTIME_DIR}"
        )

    required_hangul = set(
        str(
            plan.get(
                "required_hangul",
                "",
            )
        )
    )

    frequency = load_hangul_frequency(
        TRANSLATION_CSV
    )

    if required_hangul != set(
        frequency
    ):
        raise ValueError(
            "최종 문자셋 계획과 현재 "
            "번역 CSV의 한글 목록이 다릅니다. "
            "plan_final_charset_capacity.py를 "
            "다시 실행하세요."
        )

    candidates = list(
        plan.get(
            "strict_candidates",
            [],
        )
    )

    if not candidates:
        raise ValueError(
            "strict 후보가 없습니다."
        )

    (
        translated_intervals,
        trusted_resources,
    ) = build_translated_intervals(
        master
    )

    catalog_intervals = (
        build_catalog_intervals(
            raw_catalog
        )
    )

    translated_prepared = (
        prepare_intervals(
            translated_intervals
        )
    )

    catalog_prepared = (
        prepare_intervals(
            catalog_intervals
        )
    )

    candidate_by_sjis: dict[
        int,
        dict[str, Any]
    ] = {}

    stats: dict[
        int,
        dict[str, Any]
    ] = {}

    for candidate in candidates:
        sjis_value = parse_sjis_value(
            candidate
        )

        if sjis_value in candidate_by_sjis:
            raise ValueError(
                "후보 간 SJIS 코드 중복: "
                f"0x{sjis_value:04X}"
            )

        candidate_by_sjis[
            sjis_value
        ] = candidate

        stats[
            sjis_value
        ] = {
            "covered_hits": 0,
            "trusted_text_hits": 0,
            "catalog_noise_hits": 0,
            "raw_hits": 0,
            "files": set(),
            "examples": {
                "trusted_text": [],
                "catalog_noise": [],
                "raw": [],
            },
        }

    scanned_files = 0
    scanned_bytes = 0

    for path in sorted(
        RUNTIME_DIR.rglob("*")
    ):
        if not path.is_file():
            continue

        resource = resource_key(
            path
        )

        if resource in EXCLUDED_FILES:
            continue

        data = path.read_bytes()

        scanned_files += 1
        scanned_bytes += len(data)

        for offset in range(
            max(
                0,
                len(data) - 1,
            )
        ):
            sjis_value = (
                data[offset] << 8
            ) | data[offset + 1]

            stat = stats.get(
                sjis_value
            )

            if stat is None:
                continue

            stat["files"].add(
                resource
            )

            if contains_span(
                translated_prepared,
                resource,
                offset,
            ):
                stat[
                    "covered_hits"
                ] += 1
                continue

            in_catalog = contains_span(
                catalog_prepared,
                resource,
                offset,
            )

            if (
                in_catalog
                and resource
                in trusted_resources
            ):
                stat[
                    "trusted_text_hits"
                ] += 1

                add_example(
                    stat,
                    "trusted_text",
                    resource=resource,
                    offset=offset,
                    data=data,
                )

                continue

            if in_catalog:
                stat[
                    "catalog_noise_hits"
                ] += 1

                add_example(
                    stat,
                    "catalog_noise",
                    resource=resource,
                    offset=offset,
                    data=data,
                )

                continue

            stat["raw_hits"] += 1

            add_example(
                stat,
                "raw",
                resource=resource,
                offset=offset,
                data=data,
            )

    audited_candidates: list[
        dict[str, Any]
    ] = []

    safe_candidates: list[
        dict[str, Any]
    ] = []

    unsafe_candidates: list[
        dict[str, Any]
    ] = []

    for sjis_value, candidate in (
        candidate_by_sjis.items()
    ):
        stat = stats[
            sjis_value
        ]

        audit = {
            "covered_hits": int(
                stat["covered_hits"]
            ),
            "trusted_text_hits": int(
                stat[
                    "trusted_text_hits"
                ]
            ),
            "catalog_noise_hits": int(
                stat[
                    "catalog_noise_hits"
                ]
            ),
            "raw_hits": int(
                stat["raw_hits"]
            ),
            "file_count": len(
                stat["files"]
            ),
            "files": sorted(
                stat["files"]
            ),
            "examples": (
                stat["examples"]
            ),
        }

        copied = {
            **candidate,
            "audit": audit,
        }

        audited_candidates.append(
            copied
        )

        if (
            audit[
                "trusted_text_hits"
            ]
            == 0
        ):
            safe_candidates.append(
                copied
            )
        else:
            unsafe_candidates.append(
                copied
            )

    safe_candidates.sort(
        key=candidate_sort_key
    )

    unsafe_candidates.sort(
        key=lambda item: (
            -int(
                item["audit"][
                    "trusted_text_hits"
                ]
            ),
            int(
                item.get(
                    "glyph_index",
                    0,
                )
            ),
        )
    )

    hangul_order = sorted(
        required_hangul,
        key=lambda character: (
            -frequency[character],
            ord(character),
        ),
    )

    required_count = len(
        hangul_order
    )

    if len(
        safe_candidates
    ) < required_count:
        status = (
            "insufficient-audited-capacity"
        )

        selected_candidates = (
            safe_candidates
        )

        exit_code = 2
    else:
        status = "pass"

        selected_candidates = (
            safe_candidates[
                :required_count
            ]
        )

        exit_code = 0

    allocations: list[
        dict[str, Any]
    ] = []

    mapping: dict[
        str,
        dict[str, Any]
    ] = {}

    for index, (
        hangul,
        candidate,
    ) in enumerate(
        zip(
            hangul_order,
            selected_candidates,
        ),
        start=1,
    ):
        sjis_value = parse_sjis_value(
            candidate
        )

        lead = (
            sjis_value >> 8
        ) & 0xFF

        trail = (
            sjis_value
            & 0xFF
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
            "safety": (
                "audited-strict"
            ),
            "sjis": (
                f"{lead:02X} "
                f"{trail:02X}"
            ),
            "sjis_value": (
                sjis_value
            ),
            "lead": lead,
            "trail": trail,
            "table_index": int(
                candidate[
                    "table_index"
                ]
            ),
            "table_index_hex": str(
                candidate[
                    "table_index_hex"
                ]
            ),
            "glyph_index": int(
                candidate[
                    "glyph_index"
                ]
            ),
            "glyph_index_hex": str(
                candidate[
                    "glyph_index_hex"
                ]
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
                    1,
                )
            ),
            "audit": candidate[
                "audit"
            ],
        }

        allocations.append(
            record
        )

        mapping[hangul] = record

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    report = {
        "format": (
            "prinny_glyph_residual_audit_v1"
        ),
        "scanned_files": (
            scanned_files
        ),
        "scanned_bytes": (
            scanned_bytes
        ),
        "strict_candidate_count": len(
            candidates
        ),
        "safe_candidate_count": len(
            safe_candidates
        ),
        "unsafe_candidate_count": len(
            unsafe_candidates
        ),
        "required_hangul_count": (
            required_count
        ),
        "capacity_margin": (
            len(safe_candidates)
            - required_count
        ),
        "selected_count": len(
            allocations
        ),
        "safe_candidates": (
            safe_candidates
        ),
        "unsafe_candidates": (
            unsafe_candidates
        ),
        "status": status,
    }

    allocation = {
        "format": (
            "prinny_hangul_allocation_v3"
        ),
        "required_count": (
            required_count
        ),
        "selected_count": len(
            allocations
        ),
        "capacity_margin": (
            len(safe_candidates)
            - required_count
        ),
        "source_plan": str(
            PLAN_PATH
        ),
        "source_plan_sha1": (
            sha1_file(
                PLAN_PATH
            )
        ),
        "source_translation": str(
            TRANSLATION_CSV
        ),
        "source_translation_sha1": (
            sha1_file(
                TRANSLATION_CSV
            )
        ),
        "hangul_order": "".join(
            hangul_order
        ),
        "allocations": allocations,
        "mapping": mapping,
        "status": status,
    }

    audit_json = (
        OUTPUT_DIR
        / "residual_audit.json"
    )

    allocation_json = (
        OUTPUT_DIR
        / "hangul_allocation.json"
    )

    text_path = (
        OUTPUT_DIR
        / "summary.txt"
    )

    audit_json.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    allocation_json.write_text(
        json.dumps(
            allocation,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "FINAL GLYPH RESIDUAL AUDIT",
        "==========================",
        (
            "SCANNED FILES       : "
            f"{scanned_files}"
        ),
        (
            "SCANNED BYTES       : "
            f"{scanned_bytes}"
        ),
        (
            "STRICT CANDIDATES   : "
            f"{len(candidates)}"
        ),
        (
            "SAFE CANDIDATES     : "
            f"{len(safe_candidates)}"
        ),
        (
            "UNSAFE CANDIDATES   : "
            f"{len(unsafe_candidates)}"
        ),
        (
            "REQUIRED HANGUL     : "
            f"{required_count}"
        ),
        (
            "AUDITED MARGIN      : "
            f"{len(safe_candidates) - required_count:+d}"
        ),
        (
            "SELECTED ALLOCATION : "
            f"{len(allocations)}"
        ),
        "",
        "FIRST UNSAFE CANDIDATES",
        "-----------------------",
    ]

    for number, candidate in enumerate(
        unsafe_candidates[:40],
        start=1,
    ):
        audit = candidate[
            "audit"
        ]

        lines.append(
            f"{number:3d}. "
            f"CHAR={candidate.get('character')!r} "
            f"SJIS={candidate.get('sjis')} "
            f"GLYPH={candidate.get('glyph_index_hex')} "
            f"TEXT_HITS={audit['trusted_text_hits']} "
            f"RAW_HITS={audit['raw_hits']}"
        )

        for example in audit[
            "examples"
        ]["trusted_text"][:2]:
            lines.append(
                "     "
                f"{example['resource']}"
                f"@{example['offset_hex']} "
                f"{example['context_text']!r}"
            )

    lines.extend(
        [
            "",
            f"AUDIT      : {audit_json}",
            f"ALLOCATION : {allocation_json}",
            f"STATUS     : {status.upper()}",
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
