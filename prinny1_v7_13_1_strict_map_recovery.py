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
MIN_VECTOR_COUNT = 20
MIN_VECTOR_COVERAGE = 0.80


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


def parse_integer(value: Any) -> int | None:
    match = re.search(r"0x[0-9A-Fa-f]+|\d+", str(value or ""))

    if not match:
        return None

    try:
        return int(match.group(0), 0)
    except ValueError:
        return None


def strip_trailing_zero_padding(
    data: bytes,
    maximum: int = 256,
) -> tuple[bytes, int]:
    removed = 0

    while (
        data.endswith(b"\x00")
        and removed < maximum
    ):
        data = data[:-1]
        removed += 1

    return data, removed


def cp932_bytes(character: str) -> bytes | None:
    try:
        return character.encode("cp932")
    except UnicodeEncodeError:
        return None


def split_vector_strict(
    text: str,
    encoded: bytes,
) -> tuple[
    list[tuple[str, bytes]] | None,
    str,
]:
    result: list[tuple[str, bytes]] = []
    position = 0

    for character in text:
        if HANGUL_RE.fullmatch(character):
            width = 2

            if position + width > len(encoded):
                return None, "hangul_byte_shortage"

            value = encoded[position:position + width]
            result.append((character, value))
            position += width
            continue

        expected = cp932_bytes(character)

        if expected is None:
            return None, "non_hangul_cp932_unencodable"

        width = len(expected)

        if position + width > len(encoded):
            return None, "cp932_byte_shortage"

        actual = encoded[position:position + width]

        if actual != expected:
            return None, (
                "non_hangul_cp932_mismatch:"
                f"{character}:"
                f"{actual.hex().upper()}!="
                f"{expected.hex().upper()}"
            )

        result.append((character, actual))
        position += width

    if position != len(encoded):
        return None, (
            f"unconsumed_bytes:{len(encoded) - position}"
        )

    return result, ""


def derive_hangul_map(
    vectors: list[dict[str, str]],
) -> tuple[
    dict[str, str],
    dict[str, int],
    dict[str, list[str]],
    list[dict[str, Any]],
]:
    observations: dict[
        str,
        Counter[str],
    ] = defaultdict(Counter)
    vector_rows: list[dict[str, Any]] = []

    for index, vector in enumerate(vectors, start=1):
        text = vector.get("translation", "")
        expected_hex = clean_hex(
            vector.get("expected_hex", "")
        )

        row: dict[str, Any] = {
            "vector_index": index,
            "translation": text,
            "expected_hex": expected_hex,
            "trimmed_hex": "",
            "trailing_zero_padding": 0,
            "parse_status": "",
            "parse_reason": "",
            "hangul_character_count": 0,
        }

        if not text or not expected_hex:
            row["parse_status"] = "rejected"
            row["parse_reason"] = "missing_text_or_hex"
            vector_rows.append(row)
            continue

        raw = bytes.fromhex(expected_hex)
        trimmed, removed = strip_trailing_zero_padding(raw)

        row["trimmed_hex"] = trimmed.hex().upper()
        row["trailing_zero_padding"] = removed

        parts, reason = split_vector_strict(
            text,
            trimmed,
        )

        if parts is None:
            row["parse_status"] = "rejected"
            row["parse_reason"] = reason
            vector_rows.append(row)
            continue

        hangul_count = 0

        for character, value in parts:
            if not HANGUL_RE.fullmatch(character):
                continue

            observations[character][
                value.hex().upper()
            ] += 1
            hangul_count += 1

        row["parse_status"] = "usable"
        row["hangul_character_count"] = hangul_count
        vector_rows.append(row)

    mapping: dict[str, str] = {}
    support: dict[str, int] = {}
    conflicts: dict[str, list[str]] = {}

    for character, counts in observations.items():
        if len(counts) == 1:
            encoded_hex, count = next(iter(counts.items()))
            mapping[character] = encoded_hex
            support[character] = int(count)
        else:
            conflicts[character] = [
                f"{encoded_hex}:{count}"
                for encoded_hex, count in counts.most_common()
            ]

    return mapping, support, conflicts, vector_rows


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

            output.extend(bytes.fromhex(encoded_hex))
            continue

        encoded = cp932_bytes(character)

        if encoded is None:
            return "", sorted(set(missing)), (
                f"cp932_unencodable:{character}"
            )

        output.extend(encoded)

    if missing:
        return "", sorted(set(missing)), "missing_hangul_map"

    return output.hex().upper(), [], ""


def compare_vector(
    produced_hex: str,
    expected_hex: str,
) -> tuple[bool, str]:
    produced = clean_hex(produced_hex)
    expected = clean_hex(expected_hex)

    if not produced or not expected:
        return False, "missing_hex"

    if produced == expected:
        return True, "exact"

    if expected.startswith(produced):
        remainder = expected[len(produced):]

        if remainder and set(remainder) <= {"0"}:
            return True, "expected_zero_padded"

    return False, "mismatch"


def validate_roundtrip(
    vectors: list[dict[str, str]],
    mapping: dict[str, str],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
]:
    rows: list[dict[str, Any]] = []
    exact = 0
    padded = 0
    mismatch = 0
    missing_map = 0
    cp932_error = 0

    for index, vector in enumerate(vectors, start=1):
        text = vector.get("translation", "")
        expected_hex = clean_hex(
            vector.get("expected_hex", "")
        )
        produced_hex, missing, error = encode_with_map(
            text,
            mapping,
        )

        matched, method = compare_vector(
            produced_hex,
            expected_hex,
        )

        if method == "exact":
            exact += 1
        elif method == "expected_zero_padded":
            padded += 1
        elif error == "missing_hangul_map":
            missing_map += 1
        elif error.startswith("cp932_unencodable"):
            cp932_error += 1
        else:
            mismatch += 1

        rows.append(
            {
                "vector_index": index,
                "translation": text,
                "expected_hex": expected_hex,
                "produced_hex": produced_hex,
                "matched": matched,
                "match_method": method,
                "missing_characters": "|".join(missing),
                "encode_error": error,
                "evidence_file": vector.get(
                    "evidence_file",
                    "",
                ),
            }
        )

    total = len(vectors)
    matched_count = exact + padded
    coverage = (
        matched_count / total
        if total
        else 0.0
    )

    summary = {
        "total_vectors": total,
        "exact_matches": exact,
        "padded_matches": padded,
        "matched_vectors": matched_count,
        "mismatches": mismatch,
        "missing_map_vectors": missing_map,
        "cp932_error_vectors": cp932_error,
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
        "--v712",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_12_encoder_reconstruction"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_1_strict_map_recovery"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    v711 = arguments.v711.expanduser().resolve()
    v712 = arguments.v712.expanduser().resolve()
    output = arguments.output.expanduser().resolve()

    structural_path = v711 / "structural_validation.csv"
    vectors_path = v712 / "known_encoder_vectors.csv"

    for required in (
        project,
        structural_path,
        vectors_path,
    ):
        if not required.exists():
            raise FileNotFoundError(
                f"필수 입력이 없습니다: {required}"
            )

    output.mkdir(parents=True, exist_ok=True)

    print("[1/5] 60개 인코더 벡터의 CP932·한글 2바이트 구조 검사")

    structural_rows = read_csv(structural_path)
    vectors = read_csv(vectors_path)

    (
        hangul_map,
        support,
        conflicts,
        vector_parse_rows,
    ) = derive_hangul_map(vectors)

    write_csv(
        output / "vector_parse_validation.csv",
        vector_parse_rows,
        [
            "vector_index",
            "translation",
            "expected_hex",
            "trimmed_hex",
            "trailing_zero_padding",
            "parse_status",
            "parse_reason",
            "hangul_character_count",
        ],
    )

    usable_vectors = sum(
        row["parse_status"] == "usable"
        for row in vector_parse_rows
    )
    rejected_vectors = len(vectors) - usable_vectors

    print("[2/5] 같은 한글의 2바이트 매핑 충돌 검사")

    map_rows: list[dict[str, Any]] = []

    for character, encoded_hex in sorted(
        hangul_map.items()
    ):
        map_rows.append(
            {
                "character": character,
                "hex": encoded_hex,
                "support": support.get(character, 0),
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
                "alternatives": "|".join(alternatives),
            }
        )

    write_csv(
        output / "recovered_hangul_map.csv",
        map_rows,
        [
            "character",
            "hex",
            "support",
            "conflict",
            "alternatives",
        ],
    )

    print("[3/5] 복구 문자맵으로 전체 벡터 왕복 검증")

    roundtrip_rows, roundtrip = validate_roundtrip(
        vectors,
        hangul_map,
    )

    write_csv(
        output / "vector_roundtrip_validation.csv",
        roundtrip_rows,
        [
            "vector_index",
            "translation",
            "expected_hex",
            "produced_hex",
            "matched",
            "match_method",
            "missing_characters",
            "encode_error",
            "evidence_file",
        ],
    )

    required_matches = max(
        MIN_VECTOR_COUNT,
        math.ceil(
            len(vectors) * MIN_VECTOR_COVERAGE
        ),
    )

    map_validated = (
        len(vectors) >= MIN_VECTOR_COUNT
        and usable_vectors >= required_matches
        and roundtrip["matched_vectors"] >= required_matches
        and roundtrip["mismatches"] == 0
        and roundtrip["cp932_error_vectors"] == 0
        and len(conflicts) == 0
    )

    print("[4/5] 검증된 원본 위치의 한국어 교체 바이트 재구성")

    reconstruction_rows: list[dict[str, Any]] = []
    ready_rows: list[dict[str, Any]] = []

    for row in structural_rows:
        replacement_text = row.get(
            "replacement_text",
            "",
        ).strip()

        if not replacement_text:
            continue

        replacement_hex, missing, encode_error = (
            encode_with_map(
                replacement_text,
                hangul_map,
            )
        )
        replacement_length = (
            len(replacement_hex) // 2
            if replacement_hex
            else 0
        )
        slot_capacity = parse_integer(
            row.get("slot_capacity_estimate", "")
        )
        source_unique = (
            row.get("source_validation_status")
            == "verified_unique_source_location"
        )

        if not map_validated:
            status = "blocked_map_not_strictly_validated"
        elif missing:
            status = "blocked_missing_hangul_characters"
        elif encode_error:
            status = "blocked_encoding_error"
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
            status = "strict_expected_write_candidate"

        result = {
            "group_id": row.get("group_id", ""),
            "kind": row.get("kind", ""),
            "item_id": row.get("item_id", ""),
            "target": row.get("resolved_target", ""),
            "offset_hex": row.get("offset_hex", ""),
            "source_text": row.get("source_text", ""),
            "source_hex": row.get("source_hex", ""),
            "replacement_text": replacement_text,
            "replacement_hex": replacement_hex,
            "replacement_byte_length": replacement_length,
            "slot_capacity": (
                slot_capacity
                if slot_capacity is not None
                else ""
            ),
            "missing_characters": "|".join(missing),
            "encode_error": encode_error,
            "source_unique": source_unique,
            "map_validated": map_validated,
            "status": status,
            "expected_write_confirmed": "no",
        }
        reconstruction_rows.append(result)

        if status == "strict_expected_write_candidate":
            ready_rows.append(result)

    fields = [
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
        fields,
    )
    write_csv(
        output / "strict_expected_write_candidates.csv",
        ready_rows,
        fields,
    )

    print("[5/5] 엄격 검증 보고서 저장")

    status_counts = Counter(
        row["status"]
        for row in reconstruction_rows
    )

    write_json(
        output / "recovered_encoder_profile.json",
        {
            "format": (
                "prinny1_recovered_encoder_profile_strict_v1"
            ),
            "created_at": now(),
            "encoding_model": (
                "Hangul=custom_2_bytes;"
                "non-Hangul=CP932;"
                "trailing_zero=slot_padding"
            ),
            "vector_count": len(vectors),
            "usable_vectors": usable_vectors,
            "rejected_vectors": rejected_vectors,
            "required_matches": required_matches,
            "hangul_map_entries": len(hangul_map),
            "hangul_conflicts": conflicts,
            "roundtrip": roundtrip,
            "strictly_validated": map_validated,
            "mapping": hangul_map,
        },
    )

    write_json(
        output / "all_report.json",
        {
            "format": (
                "prinny1_v7_13_1_strict_map_recovery_report_v1"
            ),
            "created_at": now(),
            "vector_count": len(vectors),
            "usable_vectors": usable_vectors,
            "rejected_vectors": rejected_vectors,
            "required_matches": required_matches,
            "hangul_map_entries": len(hangul_map),
            "hangul_conflict_count": len(conflicts),
            "roundtrip_exact": roundtrip[
                "exact_matches"
            ],
            "roundtrip_padded": roundtrip[
                "padded_matches"
            ],
            "roundtrip_matched": roundtrip[
                "matched_vectors"
            ],
            "roundtrip_mismatches": roundtrip[
                "mismatches"
            ],
            "roundtrip_missing_map": roundtrip[
                "missing_map_vectors"
            ],
            "roundtrip_coverage": roundtrip[
                "coverage"
            ],
            "map_strictly_validated": map_validated,
            "replacement_rows": len(
                reconstruction_rows
            ),
            "strict_expected_write_candidates": len(
                ready_rows
            ),
            "expected_write_confirmed": 0,
            "status_counts": dict(status_counts),
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
        f"벡터 사용 가능/거절       : "
        f"{usable_vectors}/{rejected_vectors}"
    )
    print(
        f"복구한 한글 문자          : {len(hangul_map)}"
    )
    print(
        f"한글 매핑 충돌            : {len(conflicts)}"
    )
    print(
        f"왕복 일치 exact/padded   : "
        f"{roundtrip['exact_matches']}/"
        f"{roundtrip['padded_matches']}"
    )
    print(
        f"왕복 불일치               : "
        f"{roundtrip['mismatches']}"
    )
    print(
        f"왕복 검증률               : "
        f"{roundtrip['coverage'] * 100:.2f}%"
    )
    print(
        f"엄격 문자맵 검증 통과     : {map_validated}"
    )
    print(
        f"엄격 Expected Write 후보 : {len(ready_rows)}"
    )
    print("확정 Expected Write      : 0")
    print(
        f"한글 문자맵 CSV           : "
        f"{output / 'recovered_hangul_map.csv'}"
    )
    print(
        f"왕복 검증 CSV             : "
        f"{output / 'vector_roundtrip_validation.csv'}"
    )
    print(
        f"교체 바이트 CSV           : "
        f"{output / 'replacement_reconstruction.csv'}"
    )
    print(
        f"엄격 후보 CSV             : "
        f"{output / 'strict_expected_write_candidates.csv'}"
    )
    print(
        f"인코더 프로필 JSON        : "
        f"{output / 'recovered_encoder_profile.json'}"
    )
    print(
        f"보고서 JSON               : "
        f"{output / 'all_report.json'}"
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
