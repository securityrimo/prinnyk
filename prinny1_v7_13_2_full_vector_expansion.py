#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_DEFAULT = Path.home() / "PrinnyReverseToolkit"
DRIVE_DEFAULT = Path("/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd")
ROOT_DEFAULT = DRIVE_DEFAULT / "PSP_Localization_Work"

HANGUL_RE = re.compile(r"[가-힣]")
TRANSLATION_KEYS = (
    "translation",
    "translated",
    "korean",
    "target_text",
    "ko",
    "replacement_text",
)
HEX_KEYS = (
    "replacement_hex",
    "after_hex",
    "patched_hex",
    "encoded_hex",
    "translation_hex",
    "replacement_bytes",
)
MAX_FILE_SIZE = 40 * 1024 * 1024
MAX_VECTOR_COUNT = 20000
MIN_ACCEPTED_VECTORS = 20
MIN_ACCEPTED_COVERAGE = 0.80


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV 헤더가 없습니다: {path}")
        return [
            {str(key): value or "" for key, value in row.items()}
            for row in reader
        ]


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def clean_hex(value: Any) -> str:
    raw = re.sub(r"[^0-9A-Fa-f]", "", str(value or ""))

    if not raw or len(raw) % 2:
        return ""

    return raw.upper()


def first_value(
    record: dict[str, Any],
    keys: tuple[str, ...],
) -> str:
    lowered = {
        str(key).casefold(): value
        for key, value in record.items()
    }

    for key in keys:
        value = lowered.get(key.casefold())

        if value not in (None, "", [], {}):
            return str(value)

    return ""


def parse_integer(value: Any) -> int | None:
    match = re.search(r"0x[0-9A-Fa-f]+|\d+", str(value or ""))

    if not match:
        return None

    try:
        return int(match.group(0), 0)
    except ValueError:
        return None


def strip_zero_padding(
    data: bytes,
    maximum: int = 512,
) -> tuple[bytes, int]:
    removed = 0

    while data.endswith(b"\x00") and removed < maximum:
        data = data[:-1]
        removed += 1

    return data, removed


def cp932_bytes(character: str) -> bytes | None:
    try:
        return character.encode("cp932")
    except UnicodeEncodeError:
        return None


def split_vector(
    text: str,
    encoded: bytes,
) -> tuple[
    list[tuple[str, str]] | None,
    str,
]:
    position = 0
    pieces: list[tuple[str, str]] = []

    for character in text:
        if HANGUL_RE.fullmatch(character):
            if position + 2 > len(encoded):
                return None, "hangul_byte_shortage"

            value = encoded[position:position + 2]
            pieces.append(
                (character, value.hex().upper())
            )
            position += 2
            continue

        expected = cp932_bytes(character)

        if expected is None:
            return None, (
                f"non_hangul_cp932_unencodable:{character}"
            )

        width = len(expected)

        if position + width > len(encoded):
            return None, "cp932_byte_shortage"

        actual = encoded[position:position + width]

        if actual != expected:
            return None, (
                f"cp932_mismatch:{character}:"
                f"{actual.hex().upper()}!="
                f"{expected.hex().upper()}"
            )

        pieces.append(
            (character, actual.hex().upper())
        )
        position += width

    if position != len(encoded):
        return None, (
            f"unconsumed_bytes:{len(encoded) - position}"
        )

    return pieces, ""


def walk_json(value: Any, callback) -> None:
    if isinstance(value, dict):
        callback(value)

        for child in value.values():
            walk_json(child, callback)

    elif isinstance(value, list):
        for child in value:
            walk_json(child, callback)


def collect_all_vectors(
    project: Path,
    work_root: Path,
    output: Path,
) -> list[dict[str, str]]:
    vectors: dict[
        tuple[str, str],
        dict[str, str],
    ] = {}

    roots = (
        project,
        work_root / "reports",
        work_root / "build",
        work_root / "exports",
    )

    blocked_fragments = (
        "prinny2",
        "psp_localization_studio",
        "prinny1_v7_13_2_full_vector_expansion",
    )

    def add_record(
        record: dict[str, Any],
        source: Path,
        row_number: int,
    ) -> None:
        translation = first_value(
            record,
            TRANSLATION_KEYS,
        ).strip()
        expected_hex = clean_hex(
            first_value(record, HEX_KEYS)
        )

        if not translation or not expected_hex:
            return
        if not HANGUL_RE.search(translation):
            return

        key = (translation, expected_hex)

        vectors.setdefault(
            key,
            {
                "translation": translation,
                "expected_hex": expected_hex,
                "evidence_file": str(source),
                "evidence_row": str(row_number),
            },
        )

    for root in roots:
        if not root.exists():
            continue

        for path in root.rglob("*"):
            if len(vectors) >= MAX_VECTOR_COUNT:
                break
            if not path.is_file():
                continue
            if path.suffix.casefold() not in {".csv", ".json"}:
                continue

            lowered = str(path).casefold()

            if any(
                fragment in lowered
                for fragment in blocked_fragments
            ):
                continue
            if output in path.parents:
                continue
            if any(
                part.casefold() in {
                    ".git",
                    "__pycache__",
                    "node_modules",
                }
                or part.startswith(".prinny")
                for part in path.parts
            ):
                continue

            try:
                size = path.stat().st_size
            except OSError:
                continue

            if not 0 < size <= MAX_FILE_SIZE:
                continue

            try:
                if path.suffix.casefold() == ".csv":
                    for row_number, record in enumerate(
                        read_csv(path),
                        start=1,
                    ):
                        add_record(
                            record,
                            path,
                            row_number,
                        )

                else:
                    counter = [1]

                    def callback(
                        record: dict[str, Any],
                    ) -> None:
                        add_record(
                            record,
                            path,
                            counter[0],
                        )
                        counter[0] += 1

                    value = json.loads(
                        path.read_text(
                            encoding="utf-8-sig"
                        )
                    )
                    walk_json(value, callback)

            except Exception:
                continue

    return list(vectors.values())


def parse_vectors(
    vectors: list[dict[str, str]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Counter[str]],
]:
    rows: list[dict[str, Any]] = []
    observations: dict[
        str,
        Counter[str],
    ] = defaultdict(Counter)

    for index, vector in enumerate(vectors, start=1):
        text = vector["translation"]
        expected_hex = vector["expected_hex"]
        raw = bytes.fromhex(expected_hex)
        trimmed, padding = strip_zero_padding(raw)
        pieces, reason = split_vector(text, trimmed)

        row = {
            "vector_index": index,
            "translation": text,
            "expected_hex": expected_hex,
            "trimmed_hex": trimmed.hex().upper(),
            "trailing_zero_padding": padding,
            "parse_status": (
                "usable"
                if pieces is not None
                else "rejected"
            ),
            "parse_reason": reason,
            "evidence_file": vector["evidence_file"],
            "evidence_row": vector["evidence_row"],
        }
        rows.append(row)

        if pieces is None:
            continue

        for character, encoded_hex in pieces:
            if HANGUL_RE.fullmatch(character):
                observations[character][
                    encoded_hex
                ] += 1

    return rows, observations


def build_stable_map(
    observations: dict[str, Counter[str]],
) -> tuple[
    dict[str, str],
    dict[str, int],
    dict[str, list[str]],
]:
    mapping: dict[str, str] = {}
    support: dict[str, int] = {}
    conflicts: dict[str, list[str]] = {}

    for character, counts in observations.items():
        if len(counts) == 1:
            encoded_hex, count = next(
                iter(counts.items())
            )
            mapping[character] = encoded_hex
            support[character] = int(count)
        else:
            conflicts[character] = [
                f"{encoded_hex}:{count}"
                for encoded_hex, count
                in counts.most_common()
            ]

    return mapping, support, conflicts


def encode_with_map(
    text: str,
    mapping: dict[str, str],
) -> tuple[str, list[str], str]:
    output = bytearray()
    missing: list[str] = []

    for character in text:
        if HANGUL_RE.fullmatch(character):
            encoded_hex = mapping.get(character)

            if not encoded_hex:
                missing.append(character)
                continue

            output.extend(
                bytes.fromhex(encoded_hex)
            )
            continue

        encoded = cp932_bytes(character)

        if encoded is None:
            return "", sorted(set(missing)), (
                f"cp932_unencodable:{character}"
            )

        output.extend(encoded)

    if missing:
        return "", sorted(set(missing)), (
            "missing_hangul_map"
        )

    return output.hex().upper(), [], ""


def validate_vectors(
    vectors: list[dict[str, str]],
    mapping: dict[str, str],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
]:
    rows: list[dict[str, Any]] = []
    counters = Counter()

    for index, vector in enumerate(vectors, start=1):
        produced_hex, missing, error = (
            encode_with_map(
                vector["translation"],
                mapping,
            )
        )
        expected_hex = vector["expected_hex"]

        if produced_hex == expected_hex:
            status = "exact"
        elif (
            produced_hex
            and expected_hex.startswith(
                produced_hex
            )
            and set(
                expected_hex[len(produced_hex):]
            ) <= {"0"}
        ):
            status = "expected_zero_padded"
        elif missing:
            status = "unresolved_missing_map"
        elif error:
            status = "encoding_error"
        else:
            status = "mismatch"

        counters[status] += 1

        rows.append(
            {
                "vector_index": index,
                "translation": vector["translation"],
                "expected_hex": expected_hex,
                "produced_hex": produced_hex,
                "status": status,
                "missing_characters": "|".join(
                    missing
                ),
                "encode_error": error,
                "evidence_file": vector[
                    "evidence_file"
                ],
                "evidence_row": vector[
                    "evidence_row"
                ],
            }
        )

    matched = (
        counters["exact"]
        + counters["expected_zero_padded"]
    )
    coverage = (
        matched / len(vectors)
        if vectors
        else 0.0
    )

    summary = {
        **dict(counters),
        "total": len(vectors),
        "matched": matched,
        "coverage": round(coverage, 6),
    }

    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        type=Path,
        default=PROJECT_DEFAULT,
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=ROOT_DEFAULT,
    )
    parser.add_argument(
        "--v711",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_11_structural_validation"
        ),
    )
    parser.add_argument(
        "--v7131",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_1_strict_map_recovery"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_2_full_vector_expansion"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    v711 = arguments.v711.expanduser().resolve()
    v7131 = arguments.v7131.expanduser().resolve()
    output = arguments.output.expanduser().resolve()

    structural_path = (
        v711 / "structural_validation.csv"
    )
    prior_reconstruction_path = (
        v7131 / "replacement_reconstruction.csv"
    )

    for required in (
        project,
        structural_path,
        prior_reconstruction_path,
    ):
        if not required.exists():
            raise FileNotFoundError(
                f"필수 입력이 없습니다: {required}"
            )

    output.mkdir(parents=True, exist_ok=True)

    print("[1/5] V7.13.1 후보 0개의 정확한 차단 사유 확인")

    structural_rows = read_csv(
        structural_path
    )
    prior_rows = read_csv(
        prior_reconstruction_path
    )
    prior_status_counts = Counter(
        row.get("status", "")
        for row in prior_rows
    )

    prior_blocker_rows = []

    for row in prior_rows:
        prior_blocker_rows.append(
            {
                "group_id": row.get(
                    "group_id",
                    "",
                ),
                "replacement_text": row.get(
                    "replacement_text",
                    "",
                ),
                "status": row.get(
                    "status",
                    "",
                ),
                "missing_characters": row.get(
                    "missing_characters",
                    "",
                ),
                "replacement_byte_length": row.get(
                    "replacement_byte_length",
                    "",
                ),
                "slot_capacity": row.get(
                    "slot_capacity",
                    "",
                ),
                "source_unique": row.get(
                    "source_unique",
                    "",
                ),
                "map_validated": row.get(
                    "map_validated",
                    "",
                ),
            }
        )

    write_csv(
        output / "v7131_blocker_audit.csv",
        prior_blocker_rows,
        [
            "group_id",
            "replacement_text",
            "status",
            "missing_characters",
            "replacement_byte_length",
            "slot_capacity",
            "source_unique",
            "map_validated",
        ],
    )

    print("[2/5] 60개 제한 없이 전체 과거 인코더 벡터 수집")

    vectors = collect_all_vectors(
        project,
        work_root,
        output,
    )

    write_csv(
        output / "all_known_vectors.csv",
        vectors,
        [
            "translation",
            "expected_hex",
            "evidence_file",
            "evidence_row",
        ],
    )

    print("[3/5] 전체 벡터에서 안정 한글 코드맵 확장·충돌 검사")

    parse_rows, observations = parse_vectors(
        vectors
    )
    mapping, support, conflicts = (
        build_stable_map(observations)
    )

    write_csv(
        output / "all_vector_parse.csv",
        parse_rows,
        [
            "vector_index",
            "translation",
            "expected_hex",
            "trimmed_hex",
            "trailing_zero_padding",
            "parse_status",
            "parse_reason",
            "evidence_file",
            "evidence_row",
        ],
    )

    map_rows = []

    for character, encoded_hex in sorted(
        mapping.items()
    ):
        map_rows.append(
            {
                "character": character,
                "hex": encoded_hex,
                "support": support.get(
                    character,
                    0,
                ),
                "conflict": False,
                "alternatives": "",
            }
        )

    for character, alternatives in sorted(
        conflicts.items()
    ):
        map_rows.append(
            {
                "character": character,
                "hex": "",
                "support": 0,
                "conflict": True,
                "alternatives": "|".join(
                    alternatives
                ),
            }
        )

    write_csv(
        output / "expanded_hangul_map.csv",
        map_rows,
        [
            "character",
            "hex",
            "support",
            "conflict",
            "alternatives",
        ],
    )

    print("[4/5] 확장 문자맵 왕복 검증 및 교체 바이트 재생성")

    validation_rows, validation = (
        validate_vectors(
            vectors,
            mapping,
        )
    )

    write_csv(
        output / "expanded_vector_roundtrip.csv",
        validation_rows,
        [
            "vector_index",
            "translation",
            "expected_hex",
            "produced_hex",
            "status",
            "missing_characters",
            "encode_error",
            "evidence_file",
            "evidence_row",
        ],
    )

    usable_vector_count = sum(
        row["parse_status"] == "usable"
        for row in parse_rows
    )
    required_matches = max(
        MIN_ACCEPTED_VECTORS,
        math.ceil(
            len(vectors)
            * MIN_ACCEPTED_COVERAGE
        ),
    )
    map_validated = (
        len(vectors) >= MIN_ACCEPTED_VECTORS
        and validation["matched"]
        >= required_matches
        and validation.get("mismatch", 0) == 0
        and validation.get(
            "encoding_error",
            0,
        ) == 0
    )

    reconstruction_rows = []
    ready_rows = []

    for row in structural_rows:
        replacement_text = row.get(
            "replacement_text",
            "",
        ).strip()

        if not replacement_text:
            continue

        replacement_hex, missing, error = (
            encode_with_map(
                replacement_text,
                mapping,
            )
        )
        replacement_length = (
            len(replacement_hex) // 2
            if replacement_hex
            else 0
        )
        slot_capacity = parse_integer(
            row.get(
                "slot_capacity_estimate",
                "",
            )
        )
        source_unique = (
            row.get(
                "source_validation_status",
                "",
            )
            == "verified_unique_source_location"
        )

        if missing:
            status = (
                "blocked_missing_hangul_after_expansion"
            )
        elif error:
            status = "blocked_encoding_error"
        elif not map_validated:
            status = "blocked_map_not_validated"
        elif not source_unique:
            status = "blocked_source_not_unique"
        elif (
            slot_capacity is not None
            and replacement_length > slot_capacity
        ):
            status = "blocked_slot_overflow"
        elif replacement_hex == clean_hex(
            row.get("source_hex", "")
        ):
            status = "blocked_no_actual_change"
        else:
            status = (
                "expanded_expected_write_candidate"
            )

        result = {
            "group_id": row.get(
                "group_id",
                "",
            ),
            "kind": row.get("kind", ""),
            "item_id": row.get(
                "item_id",
                "",
            ),
            "target": row.get(
                "resolved_target",
                "",
            ),
            "offset_hex": row.get(
                "offset_hex",
                "",
            ),
            "source_text": row.get(
                "source_text",
                "",
            ),
            "source_hex": row.get(
                "source_hex",
                "",
            ),
            "replacement_text": replacement_text,
            "replacement_hex": replacement_hex,
            "replacement_byte_length": (
                replacement_length
            ),
            "slot_capacity": (
                slot_capacity
                if slot_capacity is not None
                else ""
            ),
            "missing_characters": "|".join(
                missing
            ),
            "encode_error": error,
            "source_unique": source_unique,
            "map_validated": map_validated,
            "status": status,
            "expected_write_confirmed": "no",
        }
        reconstruction_rows.append(result)

        if status == (
            "expanded_expected_write_candidate"
        ):
            ready_rows.append(result)

    result_fields = [
        "group_id",
        "kind",
        "item_id",
        "target",
        "offset_hex",
        "source_text",
        "source_hex",
        "replacement_text",
        "replacement_hex",
        "replacement_byte_length",
        "slot_capacity",
        "missing_characters",
        "encode_error",
        "source_unique",
        "map_validated",
        "status",
        "expected_write_confirmed",
    ]

    write_csv(
        output / "replacement_reconstruction.csv",
        reconstruction_rows,
        result_fields,
    )
    write_csv(
        output / "expanded_expected_write_candidates.csv",
        ready_rows,
        result_fields,
    )

    print("[5/5] 전체 벡터 확장 보고서 저장")

    final_status_counts = Counter(
        row["status"]
        for row in reconstruction_rows
    )

    write_json(
        output / "expanded_encoder_profile.json",
        {
            "format": (
                "prinny1_expanded_encoder_profile_v1"
            ),
            "created_at": now(),
            "encoding_model": (
                "Hangul=custom_2_bytes;"
                "non-Hangul=CP932;"
                "trailing_zero=padding"
            ),
            "vector_count": len(vectors),
            "usable_vector_count": (
                usable_vector_count
            ),
            "required_matches": required_matches,
            "stable_hangul_characters": len(
                mapping
            ),
            "conflict_characters": conflicts,
            "roundtrip": validation,
            "validated": map_validated,
            "mapping": mapping,
        },
    )

    write_json(
        output / "all_report.json",
        {
            "format": (
                "prinny1_v7_13_2_full_vector_expansion_report_v1"
            ),
            "created_at": now(),
            "prior_blocker_counts": dict(
                prior_status_counts
            ),
            "all_vector_count": len(vectors),
            "usable_vector_count": (
                usable_vector_count
            ),
            "stable_hangul_characters": len(
                mapping
            ),
            "conflict_character_count": len(
                conflicts
            ),
            "roundtrip": validation,
            "required_matches": required_matches,
            "map_validated": map_validated,
            "replacement_rows": len(
                reconstruction_rows
            ),
            "expanded_expected_write_candidates": len(
                ready_rows
            ),
            "expected_write_confirmed": 0,
            "final_status_counts": dict(
                final_status_counts
            ),
            "patch_applied": False,
            "iso_created": False,
            "translation_wording_changed": False,
            "character_voice_changed": False,
            "status": "pass",
        },
    )

    print()
    print("완료")
    print(
        "V7.13.1 차단 상태       : "
        + ", ".join(
            f"{key}={value}"
            for key, value
            in sorted(
                prior_status_counts.items()
            )
        )
    )
    print(
        f"전체 수집 벡터          : {len(vectors)}"
    )
    print(
        f"사용 가능 벡터          : {usable_vector_count}"
    )
    print(
        f"안정 한글 문자          : {len(mapping)}"
    )
    print(
        f"충돌 한글 문자          : {len(conflicts)}"
    )
    print(
        f"왕복 exact/padded      : "
        f"{validation.get('exact', 0)}/"
        f"{validation.get('expected_zero_padded', 0)}"
    )
    print(
        f"왕복 불일치             : "
        f"{validation.get('mismatch', 0)}"
    )
    print(
        f"확장 문자맵 검증 통과   : {map_validated}"
    )
    print(
        f"확장 Expected Write 후보: {len(ready_rows)}"
    )
    print("확정 Expected Write    : 0")
    print(
        f"차단 감사 CSV           : "
        f"{output / 'v7131_blocker_audit.csv'}"
    )
    print(
        f"확장 문자맵 CSV         : "
        f"{output / 'expanded_hangul_map.csv'}"
    )
    print(
        f"교체 바이트 CSV         : "
        f"{output / 'replacement_reconstruction.csv'}"
    )
    print(
        f"확장 후보 CSV           : "
        f"{output / 'expanded_expected_write_candidates.csv'}"
    )
    print(
        f"보고서 JSON             : "
        f"{output / 'all_report.json'}"
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
