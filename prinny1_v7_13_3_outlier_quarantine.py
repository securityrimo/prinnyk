#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_DEFAULT = Path.home() / "PrinnyReverseToolkit"
DRIVE_DEFAULT = Path("/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd")
ROOT_DEFAULT = DRIVE_DEFAULT / "PSP_Localization_Work"

HANGUL_RE = re.compile(r"[가-힣]")
MATCH_STATUSES = {"exact", "expected_zero_padded"}
MIN_ACCEPTED_VECTORS = 20


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


def as_bool(value: Any) -> bool:
    return str(value or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "y",
        "pass",
    }


def cp932_bytes(character: str) -> bytes | None:
    try:
        return character.encode("cp932")
    except UnicodeEncodeError:
        return None


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
        "--v7132",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_2_full_vector_expansion"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_3_outlier_quarantine"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    v711 = arguments.v711.expanduser().resolve()
    v7132 = arguments.v7132.expanduser().resolve()
    output = arguments.output.expanduser().resolve()

    structural_path = v711 / "structural_validation.csv"
    parse_path = v7132 / "all_vector_parse.csv"
    roundtrip_path = v7132 / "expanded_vector_roundtrip.csv"
    map_path = v7132 / "expanded_hangul_map.csv"

    for required in (
        project,
        structural_path,
        parse_path,
        roundtrip_path,
        map_path,
    ):
        if not required.exists():
            raise FileNotFoundError(
                f"필수 입력이 없습니다: {required}"
            )

    output.mkdir(parents=True, exist_ok=True)

    print("[1/5] 거절 벡터 14개와 왕복 불일치 14개 대조")

    parse_rows = read_csv(parse_path)
    roundtrip_rows = read_csv(roundtrip_path)

    parse_by_index = {
        row["vector_index"]: row
        for row in parse_rows
    }
    roundtrip_by_index = {
        row["vector_index"]: row
        for row in roundtrip_rows
    }

    accepted_indices = {
        row["vector_index"]
        for row in parse_rows
        if row.get("parse_status") == "usable"
    }
    rejected_indices = {
        row["vector_index"]
        for row in parse_rows
        if row.get("parse_status") != "usable"
    }
    matched_indices = {
        row["vector_index"]
        for row in roundtrip_rows
        if row.get("status") in MATCH_STATUSES
    }
    mismatch_indices = {
        row["vector_index"]
        for row in roundtrip_rows
        if row.get("status") not in MATCH_STATUSES
    }

    mismatch_equals_rejected = (
        mismatch_indices == rejected_indices
    )
    accepted_mismatch_indices = (
        mismatch_indices & accepted_indices
    )
    rejected_match_indices = (
        matched_indices & rejected_indices
    )

    audit_rows: list[dict[str, Any]] = []

    for vector_index in sorted(
        set(parse_by_index) | set(roundtrip_by_index),
        key=lambda value: int(value),
    ):
        parse_row = parse_by_index.get(vector_index, {})
        roundtrip_row = roundtrip_by_index.get(
            vector_index,
            {},
        )

        audit_rows.append(
            {
                "vector_index": vector_index,
                "translation": (
                    parse_row.get("translation")
                    or roundtrip_row.get("translation")
                    or ""
                ),
                "parse_status": parse_row.get(
                    "parse_status",
                    "",
                ),
                "parse_reason": parse_row.get(
                    "parse_reason",
                    "",
                ),
                "roundtrip_status": roundtrip_row.get(
                    "status",
                    "",
                ),
                "expected_hex": roundtrip_row.get(
                    "expected_hex",
                    "",
                ),
                "produced_hex": roundtrip_row.get(
                    "produced_hex",
                    "",
                ),
                "missing_characters": roundtrip_row.get(
                    "missing_characters",
                    "",
                ),
                "encode_error": roundtrip_row.get(
                    "encode_error",
                    "",
                ),
                "evidence_file": (
                    parse_row.get("evidence_file")
                    or roundtrip_row.get("evidence_file")
                    or ""
                ),
                "evidence_row": (
                    parse_row.get("evidence_row")
                    or roundtrip_row.get("evidence_row")
                    or ""
                ),
                "quarantine": (
                    vector_index in rejected_indices
                ),
            }
        )

    write_csv(
        output / "vector_outlier_audit.csv",
        audit_rows,
        [
            "vector_index",
            "translation",
            "parse_status",
            "parse_reason",
            "roundtrip_status",
            "expected_hex",
            "produced_hex",
            "missing_characters",
            "encode_error",
            "evidence_file",
            "evidence_row",
            "quarantine",
        ],
    )

    quarantined_rows = [
        row
        for row in audit_rows
        if row["quarantine"]
    ]

    write_csv(
        output / "quarantined_vectors.csv",
        quarantined_rows,
        [
            "vector_index",
            "translation",
            "parse_status",
            "parse_reason",
            "roundtrip_status",
            "expected_hex",
            "produced_hex",
            "missing_characters",
            "encode_error",
            "evidence_file",
            "evidence_row",
            "quarantine",
        ],
    )

    print("[2/5] 유효 벡터만 대상으로 문자맵 재검증")

    accepted_roundtrip = [
        row
        for row in roundtrip_rows
        if row["vector_index"] in accepted_indices
    ]
    accepted_status_counts = Counter(
        row.get("status", "")
        for row in accepted_roundtrip
    )
    accepted_matched = sum(
        accepted_status_counts[status]
        for status in MATCH_STATUSES
    )
    accepted_mismatches = (
        len(accepted_roundtrip) - accepted_matched
    )

    map_rows = read_csv(map_path)
    mapping: dict[str, str] = {}
    conflict_rows: list[dict[str, str]] = []

    for row in map_rows:
        if as_bool(row.get("conflict")):
            conflict_rows.append(row)
            continue

        character = row.get("character", "")
        encoded_hex = clean_hex(row.get("hex", ""))

        if (
            len(character) == 1
            and HANGUL_RE.fullmatch(character)
            and encoded_hex
        ):
            mapping[character] = encoded_hex

    accepted_map_validated = (
        len(accepted_roundtrip) >= MIN_ACCEPTED_VECTORS
        and accepted_mismatches == 0
        and len(conflict_rows) == 0
        and mismatch_equals_rejected
        and not accepted_mismatch_indices
        and not rejected_match_indices
    )

    validation_summary_rows = [
        {
            "metric": "all_vectors",
            "value": len(parse_rows),
        },
        {
            "metric": "accepted_vectors",
            "value": len(accepted_indices),
        },
        {
            "metric": "rejected_vectors",
            "value": len(rejected_indices),
        },
        {
            "metric": "accepted_exact",
            "value": accepted_status_counts["exact"],
        },
        {
            "metric": "accepted_zero_padded",
            "value": accepted_status_counts[
                "expected_zero_padded"
            ],
        },
        {
            "metric": "accepted_mismatches",
            "value": accepted_mismatches,
        },
        {
            "metric": "mismatch_equals_rejected",
            "value": mismatch_equals_rejected,
        },
        {
            "metric": "map_entries",
            "value": len(mapping),
        },
        {
            "metric": "map_conflicts",
            "value": len(conflict_rows),
        },
        {
            "metric": "accepted_map_validated",
            "value": accepted_map_validated,
        },
    ]

    write_csv(
        output / "accepted_corpus_validation.csv",
        validation_summary_rows,
        [
            "metric",
            "value",
        ],
    )

    print("[3/5] 검증된 원본 위치의 교체 문구 재인코딩")

    structural_rows = read_csv(structural_path)
    reconstruction_rows: list[dict[str, Any]] = []

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
                mapping,
            )
        )
        replacement_length = (
            len(replacement_hex) // 2
            if replacement_hex
            else 0
        )
        source_length = parse_integer(
            row.get("source_byte_length", "")
        )
        slot_capacity = parse_integer(
            row.get("slot_capacity_estimate", "")
        )
        zero_padding = parse_integer(
            row.get(
                "zero_padding_after_string",
                "",
            )
        )
        terminator_hex = clean_hex(
            row.get("terminator_first_byte_hex", "")
        )
        source_unique = (
            row.get("source_validation_status")
            == "verified_unique_source_location"
        )
        original_match = as_bool(
            row.get("expected_match")
        )
        exact_boundary = as_bool(
            row.get("exact_string_boundary")
        )
        duplicate_count = parse_integer(
            row.get("duplicate_candidate_count", "")
        )
        overlap_count = parse_integer(
            row.get("overlap_candidate_count", "")
        )

        if slot_capacity is None and source_length is not None:
            slot_capacity = (
                source_length + (zero_padding or 0)
            )

        terminator_required = terminator_hex == "00"
        required_capacity = (
            replacement_length + 1
            if terminator_required
            else replacement_length
        )

        blocker: list[str] = []

        if not accepted_map_validated:
            blocker.append("accepted_map_not_validated")
        if missing:
            blocker.append("missing_hangul_characters")
        if encode_error:
            blocker.append("encoding_error")
        if not source_unique:
            blocker.append("source_not_unique")
        if not original_match:
            blocker.append("original_bytes_mismatch")
        if not exact_boundary:
            blocker.append("string_boundary_not_exact")
        if duplicate_count not in (None, 1):
            blocker.append("duplicate_candidate")
        if overlap_count not in (None, 0):
            blocker.append("overlap_candidate")
        if slot_capacity is None:
            blocker.append("slot_capacity_unknown")
        elif required_capacity > slot_capacity:
            blocker.append("slot_overflow")
        if not terminator_required:
            blocker.append("terminator_not_zero")

        status = (
            "final_payload_review_candidate"
            if not blocker
            else "blocked"
        )

        reconstruction_rows.append(
            {
                "group_id": row.get("group_id", ""),
                "kind": row.get("kind", ""),
                "item_id": row.get("item_id", ""),
                "target": row.get("resolved_target", ""),
                "offset_hex": row.get("offset_hex", ""),
                "source_text": row.get("source_text", ""),
                "source_hex": row.get("source_hex", ""),
                "source_byte_length": (
                    source_length
                    if source_length is not None
                    else ""
                ),
                "replacement_text": replacement_text,
                "replacement_hex": replacement_hex,
                "replacement_byte_length": (
                    replacement_length
                ),
                "terminator_hex": terminator_hex,
                "terminator_required": terminator_required,
                "required_capacity": required_capacity,
                "slot_capacity": (
                    slot_capacity
                    if slot_capacity is not None
                    else ""
                ),
                "zero_padding_after_string": (
                    zero_padding
                    if zero_padding is not None
                    else ""
                ),
                "missing_characters": "|".join(missing),
                "encode_error": encode_error,
                "accepted_map_validated": (
                    accepted_map_validated
                ),
                "source_unique": source_unique,
                "original_match": original_match,
                "exact_boundary": exact_boundary,
                "duplicate_candidate_count": (
                    duplicate_count
                    if duplicate_count is not None
                    else ""
                ),
                "overlap_candidate_count": (
                    overlap_count
                    if overlap_count is not None
                    else ""
                ),
                "status": status,
                "block_reasons": "|".join(blocker),
                "expected_write_confirmed": "no",
            }
        )

    reconstruction_fields = [
        "group_id",
        "kind",
        "item_id",
        "target",
        "offset_hex",
        "source_text",
        "source_hex",
        "source_byte_length",
        "replacement_text",
        "replacement_hex",
        "replacement_byte_length",
        "terminator_hex",
        "terminator_required",
        "required_capacity",
        "slot_capacity",
        "zero_padding_after_string",
        "missing_characters",
        "encode_error",
        "accepted_map_validated",
        "source_unique",
        "original_match",
        "exact_boundary",
        "duplicate_candidate_count",
        "overlap_candidate_count",
        "status",
        "block_reasons",
        "expected_write_confirmed",
    ]

    write_csv(
        output / "replacement_payload_review.csv",
        reconstruction_rows,
        reconstruction_fields,
    )

    print("[4/5] 최종 페이로드 검토 후보 생성")

    review_candidates = [
        row
        for row in reconstruction_rows
        if row["status"]
        == "final_payload_review_candidate"
    ]

    write_csv(
        output / "final_payload_review_candidates.csv",
        review_candidates,
        reconstruction_fields,
    )

    blocker_counts = Counter()

    for row in reconstruction_rows:
        for reason in str(
            row.get("block_reasons", "")
        ).split("|"):
            if reason:
                blocker_counts[reason] += 1

    print("[5/5] 격리·재검증 보고서 저장")

    write_json(
        output / "accepted_encoder_profile.json",
        {
            "format": (
                "prinny1_accepted_encoder_profile_v1"
            ),
            "created_at": now(),
            "encoding_model": (
                "Hangul=custom_2_bytes;"
                "non-Hangul=CP932;"
                "rejected_vectors=quarantined"
            ),
            "all_vectors": len(parse_rows),
            "accepted_vectors": len(accepted_indices),
            "rejected_vectors": len(rejected_indices),
            "accepted_status_counts": dict(
                accepted_status_counts
            ),
            "accepted_mismatches": accepted_mismatches,
            "mismatch_equals_rejected": (
                mismatch_equals_rejected
            ),
            "map_entries": len(mapping),
            "map_conflicts": len(conflict_rows),
            "validated": accepted_map_validated,
            "mapping": mapping,
        },
    )

    write_json(
        output / "all_report.json",
        {
            "format": (
                "prinny1_v7_13_3_outlier_quarantine_report_v1"
            ),
            "created_at": now(),
            "all_vectors": len(parse_rows),
            "accepted_vectors": len(accepted_indices),
            "rejected_vectors": len(rejected_indices),
            "mismatch_vectors": len(mismatch_indices),
            "mismatch_equals_rejected": (
                mismatch_equals_rejected
            ),
            "accepted_mismatches": accepted_mismatches,
            "rejected_vectors_that_matched": len(
                rejected_match_indices
            ),
            "map_entries": len(mapping),
            "map_conflicts": len(conflict_rows),
            "accepted_map_validated": (
                accepted_map_validated
            ),
            "replacement_rows": len(
                reconstruction_rows
            ),
            "final_payload_review_candidates": len(
                review_candidates
            ),
            "blocker_counts": dict(blocker_counts),
            "expected_write_confirmed": 0,
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
        f"전체/유효/격리 벡터       : "
        f"{len(parse_rows)}/"
        f"{len(accepted_indices)}/"
        f"{len(rejected_indices)}"
    )
    print(
        f"불일치와 격리 집합 동일   : "
        f"{mismatch_equals_rejected}"
    )
    print(
        f"유효 벡터 exact/padded  : "
        f"{accepted_status_counts['exact']}/"
        f"{accepted_status_counts['expected_zero_padded']}"
    )
    print(
        f"유효 벡터 불일치          : "
        f"{accepted_mismatches}"
    )
    print(
        f"한글 문자맵/충돌          : "
        f"{len(mapping)}/{len(conflict_rows)}"
    )
    print(
        f"유효 문자맵 검증 통과     : "
        f"{accepted_map_validated}"
    )
    print(
        f"최종 페이로드 검토 후보   : "
        f"{len(review_candidates)}"
    )
    print("확정 Expected Write      : 0")

    if blocker_counts:
        print(
            "남은 차단 사유            : "
            + ", ".join(
                f"{key}={value}"
                for key, value
                in sorted(blocker_counts.items())
            )
        )

    print(
        f"격리 벡터 CSV             : "
        f"{output / 'quarantined_vectors.csv'}"
    )
    print(
        f"유효 코퍼스 검증 CSV      : "
        f"{output / 'accepted_corpus_validation.csv'}"
    )
    print(
        f"교체 페이로드 CSV         : "
        f"{output / 'replacement_payload_review.csv'}"
    )
    print(
        f"최종 검토 후보 CSV        : "
        f"{output / 'final_payload_review_candidates.csv'}"
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
