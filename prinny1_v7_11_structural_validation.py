#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import struct
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_DEFAULT = Path.home() / "PrinnyReverseToolkit"
DRIVE_DEFAULT = Path("/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd")
ROOT_DEFAULT = DRIVE_DEFAULT / "PSP_Localization_Work"

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
KR_RE = re.compile(r"[가-힣]")


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


def parse_integer(value: Any) -> int | None:
    match = re.search(r"0x[0-9A-Fa-f]+|\d+", str(value or ""))
    if not match:
        return None
    try:
        return int(match.group(0), 0)
    except ValueError:
        return None


def normalize_target(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "/")
        .casefold()
        .removeprefix("./")
    )


def locate_file(root: Path, relative: str) -> Path:
    direct = root / relative
    if direct.is_file():
        return direct

    basename = Path(relative).name.casefold()
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name.casefold() == basename
    ]

    if len(matches) == 1:
        return matches[0]

    raise FileNotFoundError(
        f"파일을 하나로 확정하지 못했습니다: {relative}"
    )


def prepare_targets(
    game_iso: Path,
    run_directory: Path,
    output: Path,
) -> list[dict[str, Any]]:
    from psp_localization.iso import prepare_disc
    from core.system_unpack import unpack_system
    from core.start_runtime import StartRuntimeArchive

    disc_directory = run_directory / "disc"
    system_directory = run_directory / "system"
    start_directory = run_directory / "start"

    for directory in (
        disc_directory,
        system_directory,
        start_directory,
    ):
        shutil.rmtree(directory, ignore_errors=True)

    try:
        disc_root, extract_manifest = prepare_disc(
            game_iso,
            disc_directory,
            force=True,
            extraction_mode="minimal",
        )
    except TypeError:
        disc_root, extract_manifest = prepare_disc(
            game_iso,
            disc_directory,
            force=True,
        )

    write_json(
        output / "extract_manifest.json",
        extract_manifest,
    )

    system_dat = locate_file(
        disc_root,
        "PSP_GAME/USRDIR/SYSTEM.DAT",
    )
    unpack_system(
        system_dat,
        system_directory,
        output / "system_unpack.json",
        force=True,
    )

    start_dat = system_directory / "start.dat"
    if not start_dat.is_file():
        matches = [
            path
            for path in system_directory.rglob("*")
            if path.is_file()
            and path.name.casefold() == "start.dat"
        ]
        if len(matches) != 1:
            raise FileNotFoundError(
                "새 추출물에서 start.dat을 확정하지 못했습니다."
            )
        start_dat = matches[0]

    archive = StartRuntimeArchive.load(start_dat)
    archive.extract(start_directory)

    targets: list[dict[str, Any]] = []

    for path in sorted(start_directory.rglob("*")):
        if path.is_file():
            targets.append(
                {
                    "logical": path.relative_to(
                        start_directory
                    ).as_posix(),
                    "path": path,
                    "kind": "dialogue",
                    "scope": "start_resource",
                }
            )

    for relative, kind, scope in (
        (
            "PSP_GAME/SYSDIR/BOOT.BIN",
            "ui",
            "executable",
        ),
        (
            "PSP_GAME/SYSDIR/EBOOT.BIN",
            "ui",
            "executable",
        ),
        (
            "PSP_GAME/USRDIR/SCRIPT.DAT",
            "dialogue",
            "script_container",
        ),
        (
            "PSP_GAME/USRDIR/SYSTEM.DAT",
            "container",
            "container",
        ),
    ):
        try:
            targets.append(
                {
                    "logical": relative,
                    "path": locate_file(disc_root, relative),
                    "kind": kind,
                    "scope": scope,
                }
            )
        except FileNotFoundError:
            pass

    return targets


def resolve_target(
    requested: str,
    targets: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    normalized = normalize_target(requested)

    exact = [
        target
        for target in targets
        if normalize_target(target["logical"]) == normalized
    ]
    if len(exact) == 1:
        return exact[0], "exact"

    basename = Path(normalized).name
    by_basename = [
        target
        for target in targets
        if Path(
            normalize_target(target["logical"])
        ).name == basename
    ]
    if len(by_basename) == 1:
        return by_basename[0], "unique_basename"
    if len(by_basename) > 1:
        return None, "ambiguous_basename"

    return None, "not_found"


def encode_cp932(text: str) -> tuple[bytes, str]:
    try:
        return text.encode("cp932"), "cp932"
    except UnicodeEncodeError:
        return b"", "cp932_unencodable"


def valid_shift_jis_pair(first_byte: int, second_byte: int) -> bool:
    lead = (
        0x81 <= first_byte <= 0x9F
        or 0xE0 <= first_byte <= 0xFC
    )
    trail = (
        0x40 <= second_byte <= 0xFC
        and second_byte != 0x7F
    )
    return lead and trail


def scan_strings(data: bytes) -> list[dict[str, Any]]:
    results: dict[tuple[int, str], dict[str, Any]] = {}
    index = 0

    while index < len(data):
        start = index
        encoded = bytearray()
        character_count = 0
        has_two_byte = False

        while index < len(data):
            current = data[index]

            if 0x20 <= current <= 0x7E:
                encoded.append(current)
                index += 1
                character_count += 1
                continue

            if (
                index + 1 < len(data)
                and valid_shift_jis_pair(
                    current,
                    data[index + 1],
                )
            ):
                encoded.extend(data[index:index + 2])
                index += 2
                character_count += 1
                has_two_byte = True
                continue

            break

        if character_count >= 2 and encoded:
            try:
                text = bytes(encoded).decode("cp932")
            except UnicodeDecodeError:
                text = ""

            if (
                text
                and (
                    has_two_byte
                    or len(text.strip()) >= 4
                )
            ):
                results[(start, text)] = {
                    "offset": start,
                    "offset_hex": f"0x{start:X}",
                    "text": text,
                    "byte_length": len(encoded),
                    "end_offset": start + len(encoded),
                }

        if index == start:
            index += 1

    return sorted(
        results.values(),
        key=lambda row: int(row["offset"]),
    )


def count_zero_padding(
    data: bytes,
    start: int,
    limit: int = 64,
) -> int:
    count = 0

    while (
        start + count < len(data)
        and count < limit
        and data[start + count] == 0
    ):
        count += 1

    return count


def pointer_reference_counts(
    data: bytes,
    offset: int,
) -> dict[str, int]:
    patterns: dict[str, bytes] = {}

    if 0 <= offset <= 0xFFFFFFFF:
        patterns["u32le"] = struct.pack("<I", offset)
        patterns["u32be"] = struct.pack(">I", offset)

    if 0 <= offset <= 0xFFFF:
        patterns["u16le"] = struct.pack("<H", offset)
        patterns["u16be"] = struct.pack(">H", offset)

    counts: dict[str, int] = {}

    for name, pattern in patterns.items():
        count = 0
        position = 0

        while True:
            found = data.find(pattern, position)
            if found < 0:
                break

            if found != offset:
                count += 1

            position = found + 1

        counts[name] = count

    return counts


def discover_encoder_hints(project: Path) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    patterns = (
        "encode_text",
        "encode_translation",
        "korean_encoder",
        "char_map",
        "code_map",
        "glyph_map",
        "hancharacter",
    )

    for path in project.rglob("*.py"):
        lowered_path = str(path).casefold()

        if any(
            blocked in lowered_path
            for blocked in (
                "/.git/",
                "/__pycache__/",
                "/.prinny",
            )
        ):
            continue

        try:
            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        lowered_text = text.casefold()
        found_patterns = [
            pattern
            for pattern in patterns
            if pattern in lowered_text
        ]

        if found_patterns:
            hints.append(
                {
                    "path": str(path),
                    "matched_terms": "|".join(found_patterns),
                }
            )

    return hints


def unique_best_ui_hits(
    strong_group_ids: set[str],
    ui_hits: list[dict[str, str]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    grouped: dict[
        tuple[str, str],
        list[dict[str, str]],
    ] = defaultdict(list)

    for row in ui_hits:
        group_id = row.get("group_id", "")

        if group_id not in strong_group_ids:
            continue

        token = row.get("token", "")
        grouped[(group_id, token)].append(row)

    selected: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []

    for (group_id, token), rows in sorted(grouped.items()):
        sorted_rows = sorted(
            rows,
            key=lambda row: (
                -int(row.get("match_score", "0") or 0),
                row.get("target", ""),
                parse_integer(row.get("offset_hex", ""))
                or 0,
            ),
        )

        best_score = int(
            sorted_rows[0].get("match_score", "0") or 0
        )
        best_rows = [
            row
            for row in sorted_rows
            if int(row.get("match_score", "0") or 0)
            == best_score
        ]

        unique_locations = {
            (
                row.get("target", ""),
                row.get("offset_hex", ""),
                row.get("source_text", ""),
            )
            for row in best_rows
        }

        if len(unique_locations) == 1:
            best = best_rows[0]
            selected.append(
                {
                    "group_id": group_id,
                    "kind": "ui",
                    "item_id": token,
                    "target": best.get("target", ""),
                    "offset_hex": best.get("offset_hex", ""),
                    "source_text": best.get("source_text", ""),
                    "replacement_text": "",
                    "selection_status": "unique_top_ui_token",
                    "selection_score": best_score,
                }
            )
        else:
            ambiguous.append(
                {
                    "group_id": group_id,
                    "token": token,
                    "best_score": best_score,
                    "top_location_count": len(unique_locations),
                    "locations": "|".join(
                        f"{target}@{offset}:{source}"
                        for target, offset, source
                        in sorted(unique_locations)
                    ),
                    "status": "ui_top_tie",
                }
            )

    return selected, ambiguous


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
        "--game",
        type=Path,
        default=ROOT_DEFAULT / "inputs/game.iso",
    )
    parser.add_argument(
        "--v710",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_10_global_source_search"
        ),
    )
    parser.add_argument(
        "--translation-pairs",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_9_translation_context"
            / "translation_pair_inventory.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_11_structural_validation"
        ),
    )
    parser.add_argument(
        "--run-directory",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "work/prinny1_v7_11_structural_validation"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    game_iso = arguments.game.expanduser().resolve()
    v710_directory = arguments.v710.expanduser().resolve()
    translation_pairs_path = (
        arguments.translation_pairs.expanduser().resolve()
    )
    output = arguments.output.expanduser().resolve()
    run_directory = arguments.run_directory.expanduser().resolve()

    required_files = (
        game_iso,
        v710_directory / "all_report.json",
        v710_directory / "ui_group_resolution.csv",
        v710_directory / "ui_token_hits.csv",
        v710_directory / "dialogue_assignment.csv",
        v710_directory / "next_structural_validation_queue.csv",
        translation_pairs_path,
    )

    for required in required_files:
        if not required.is_file():
            raise FileNotFoundError(
                f"필수 입력이 없습니다: {required}"
            )

    output.mkdir(parents=True, exist_ok=True)
    run_directory.mkdir(parents=True, exist_ok=True)

    print("[1/5] V7.10의 강한 UI·대사 후보 3개 복원")

    report = json.loads(
        (v710_directory / "all_report.json").read_text(
            encoding="utf-8"
        )
    )
    queue_rows = read_csv(
        v710_directory
        / "next_structural_validation_queue.csv"
    )
    ui_resolution = read_csv(
        v710_directory / "ui_group_resolution.csv"
    )
    ui_hits = read_csv(
        v710_directory / "ui_token_hits.csv"
    )
    dialogue_assignment = read_csv(
        v710_directory / "dialogue_assignment.csv"
    )
    translation_pairs = read_csv(translation_pairs_path)

    strong_ui_groups = {
        row["group_id"]
        for row in ui_resolution
        if row.get("status") == "strong_ui_source_set"
    }
    strong_dialogue_groups = {
        row["group_id"]
        for row in dialogue_assignment
        if row.get("status") == "strong_dialogue_source"
    }

    selected_ui, ambiguous_ui = unique_best_ui_hits(
        strong_ui_groups,
        ui_hits,
    )

    translation_by_source: dict[
        str,
        list[str],
    ] = defaultdict(list)

    for row in translation_pairs:
        source = row.get("source_text", "")
        translation = row.get("translation", "")

        if (
            source
            and translation
            and translation not in translation_by_source[source]
        ):
            translation_by_source[source].append(translation)

    selected_dialogue: list[dict[str, Any]] = []

    for row in dialogue_assignment:
        if row.get("group_id") not in strong_dialogue_groups:
            continue

        source_text = row.get("selected_source_text", "")
        replacement = row.get("matched_translation", "")

        if not replacement:
            translations = translation_by_source.get(
                source_text,
                [],
            )
            if len(translations) == 1:
                replacement = translations[0]

        selected_dialogue.append(
            {
                "group_id": row.get("group_id", ""),
                "kind": "dialogue",
                "item_id": row.get("group_id", ""),
                "target": row.get("selected_target", ""),
                "offset_hex": row.get(
                    "selected_offset_hex",
                    "",
                ),
                "source_text": source_text,
                "replacement_text": replacement,
                "selection_status": "strong_dialogue_source",
                "selection_score": row.get(
                    "final_score",
                    "",
                ),
            }
        )

    candidates = selected_ui + selected_dialogue

    write_csv(
        output / "reconstructed_validation_candidates.csv",
        candidates,
        [
            "group_id",
            "kind",
            "item_id",
            "target",
            "offset_hex",
            "source_text",
            "replacement_text",
            "selection_status",
            "selection_score",
        ],
    )
    write_csv(
        output / "ambiguous_ui_token_ties.csv",
        ambiguous_ui,
        [
            "group_id",
            "token",
            "best_score",
            "top_location_count",
            "locations",
            "status",
        ],
    )

    print("[2/5] 원본 ISO 재추출 및 대상 자원 재생성")

    targets = prepare_targets(
        game_iso,
        run_directory,
        output,
    )
    byte_cache: dict[str, bytes] = {}
    string_cache: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    print("[3/5] 원본 바이트·문자열 경계·종료·패딩 검사")

    raw_results: list[dict[str, Any]] = []

    for candidate in candidates:
        requested_target = candidate["target"]
        target, resolution = resolve_target(
            requested_target,
            targets,
        )
        offset = parse_integer(candidate["offset_hex"])
        source_text = candidate["source_text"]
        source_bytes, encoding_status = encode_cp932(
            source_text
        )

        result: dict[str, Any] = {
            **candidate,
            "resolved_target": "",
            "resolution_method": resolution,
            "target_size": "",
            "source_encoding": encoding_status,
            "source_byte_length": len(source_bytes),
            "source_hex": source_bytes.hex().upper(),
            "actual_hex": "",
            "range_ok": False,
            "expected_match": False,
            "exact_string_boundary": False,
            "scanned_string_text": "",
            "scanned_string_byte_length": "",
            "prefix_hex_16": "",
            "suffix_hex_16": "",
            "zero_padding_after_string": 0,
            "terminator_first_byte_hex": "",
            "pointer_u16le": 0,
            "pointer_u16be": 0,
            "pointer_u32le": 0,
            "pointer_u32be": 0,
            "replacement_source": "",
            "replacement_text": candidate.get(
                "replacement_text",
                "",
            ),
            "replacement_encoding_status": "",
            "replacement_byte_length": "",
            "slot_capacity_estimate": "",
            "capacity_status": "unknown",
            "candidate_range_start": "",
            "candidate_range_end": "",
            "structure_status": "",
        }

        if target is None:
            result["structure_status"] = (
                "target_resolution_failed"
            )
            raw_results.append(result)
            continue

        if offset is None:
            result["structure_status"] = "invalid_offset"
            raw_results.append(result)
            continue

        resolved_path = target["path"].resolve()
        cache_key = str(resolved_path)

        if cache_key not in byte_cache:
            byte_cache[cache_key] = resolved_path.read_bytes()
            string_cache[cache_key] = scan_strings(
                byte_cache[cache_key]
            )

        data = byte_cache[cache_key]
        scanned_strings = string_cache[cache_key]

        result["resolved_target"] = target["logical"]
        result["target_size"] = len(data)
        result["candidate_range_start"] = f"0x{offset:X}"
        result["candidate_range_end"] = (
            f"0x{offset + len(source_bytes):X}"
            if source_bytes
            else ""
        )

        range_ok = bool(
            source_bytes
            and 0 <= offset
            and offset + len(source_bytes) <= len(data)
        )
        result["range_ok"] = range_ok

        if range_ok:
            actual = data[
                offset:offset + len(source_bytes)
            ]
            result["actual_hex"] = actual.hex().upper()
            result["expected_match"] = (
                actual == source_bytes
            )

            prefix_start = max(0, offset - 16)
            suffix_start = offset + len(source_bytes)

            result["prefix_hex_16"] = data[
                prefix_start:offset
            ].hex().upper()
            result["suffix_hex_16"] = data[
                suffix_start:suffix_start + 16
            ].hex().upper()

        scanned = next(
            (
                row
                for row in scanned_strings
                if int(row["offset"]) == offset
            ),
            None,
        )

        if scanned is not None:
            result["scanned_string_text"] = scanned["text"]
            result["scanned_string_byte_length"] = (
                scanned["byte_length"]
            )
            result["exact_string_boundary"] = (
                scanned["text"] == source_text
            )

            string_end = int(scanned["end_offset"])
            padding = count_zero_padding(
                data,
                string_end,
            )
            result["zero_padding_after_string"] = padding
            result["slot_capacity_estimate"] = (
                int(scanned["byte_length"]) + padding
            )

            if string_end < len(data):
                result["terminator_first_byte_hex"] = (
                    f"{data[string_end]:02X}"
                )

        pointer_counts = pointer_reference_counts(
            data,
            offset,
        )
        result["pointer_u16le"] = pointer_counts.get(
            "u16le",
            0,
        )
        result["pointer_u16be"] = pointer_counts.get(
            "u16be",
            0,
        )
        result["pointer_u32le"] = pointer_counts.get(
            "u32le",
            0,
        )
        result["pointer_u32be"] = pointer_counts.get(
            "u32be",
            0,
        )

        replacement_text = str(
            result.get("replacement_text", "")
        )

        if replacement_text:
            try:
                replacement_cp932 = replacement_text.encode(
                    "cp932"
                )
                result[
                    "replacement_encoding_status"
                ] = "cp932_encodable"
                result["replacement_byte_length"] = len(
                    replacement_cp932
                )
                result["replacement_source"] = (
                    "translation_pair"
                )
            except UnicodeEncodeError:
                result[
                    "replacement_encoding_status"
                ] = "custom_korean_encoder_required"
                result["replacement_source"] = (
                    "translation_pair"
                )
        else:
            result[
                "replacement_encoding_status"
            ] = "replacement_text_missing"

        slot_capacity = result.get(
            "slot_capacity_estimate",
            "",
        )
        replacement_length = result.get(
            "replacement_byte_length",
            "",
        )

        if (
            isinstance(slot_capacity, int)
            and isinstance(replacement_length, int)
        ):
            result["capacity_status"] = (
                "fits_estimated_slot"
                if replacement_length <= slot_capacity
                else "exceeds_estimated_slot"
            )
        elif replacement_text:
            result["capacity_status"] = (
                "unknown_until_custom_encoder"
            )

        if not result["range_ok"]:
            result["structure_status"] = "out_of_range"
        elif not result["expected_match"]:
            result["structure_status"] = (
                "source_bytes_mismatch"
            )
        elif not result["exact_string_boundary"]:
            result["structure_status"] = (
                "source_verified_but_boundary_not_exact"
            )
        else:
            result["structure_status"] = (
                "source_verified_exact_boundary"
            )

        raw_results.append(result)

    print("[4/5] 후보 중복·범위 겹침·포인터 참조 검사")

    duplicate_counts: Counter[
        tuple[str, str, str]
    ] = Counter()
    overlap_counts: Counter[int] = Counter()

    for result in raw_results:
        key = (
            str(result.get("resolved_target", "")),
            str(result.get("offset_hex", "")),
            str(result.get("source_hex", "")),
        )
        duplicate_counts[key] += 1

    for left_index, left in enumerate(raw_results):
        left_target = str(
            left.get("resolved_target", "")
        )
        left_start = parse_integer(
            left.get("candidate_range_start", "")
        )
        left_end = parse_integer(
            left.get("candidate_range_end", "")
        )

        if (
            not left_target
            or left_start is None
            or left_end is None
        ):
            continue

        for right_index in range(
            left_index + 1,
            len(raw_results),
        ):
            right = raw_results[right_index]

            if str(
                right.get("resolved_target", "")
            ) != left_target:
                continue

            right_start = parse_integer(
                right.get("candidate_range_start", "")
            )
            right_end = parse_integer(
                right.get("candidate_range_end", "")
            )

            if right_start is None or right_end is None:
                continue

            overlaps = (
                left_start < right_end
                and right_start < left_end
            )

            if overlaps:
                overlap_counts[left_index] += 1
                overlap_counts[right_index] += 1

    for index, result in enumerate(raw_results):
        duplicate_key = (
            str(result.get("resolved_target", "")),
            str(result.get("offset_hex", "")),
            str(result.get("source_hex", "")),
        )
        result["duplicate_candidate_count"] = (
            duplicate_counts[duplicate_key]
        )
        result["overlap_candidate_count"] = (
            overlap_counts[index]
        )

        if (
            result["structure_status"]
            == "source_verified_exact_boundary"
            and result["duplicate_candidate_count"] == 1
            and result["overlap_candidate_count"] == 0
        ):
            result["source_validation_status"] = (
                "verified_unique_source_location"
            )
        elif result["structure_status"].startswith(
            "source_verified"
        ):
            result["source_validation_status"] = (
                "verified_but_duplicate_or_overlap"
            )
        else:
            result["source_validation_status"] = (
                "source_validation_failed"
            )

        result["expected_write_confirmed"] = "no"
        result["expected_write_block_reason"] = (
            "replacement_bytes_not_confirmed"
            if result["source_validation_status"]
            == "verified_unique_source_location"
            else "source_structure_not_unique"
        )

    print("[5/5] 한글 인코더 후보 조사 및 구조 검증 보고서 저장")

    encoder_hints = discover_encoder_hints(project)
    write_csv(
        output / "korean_encoder_hints.csv",
        encoder_hints,
        [
            "path",
            "matched_terms",
        ],
    )

    result_fields = [
        "group_id",
        "kind",
        "item_id",
        "selection_status",
        "selection_score",
        "target",
        "resolved_target",
        "resolution_method",
        "offset_hex",
        "source_text",
        "source_encoding",
        "source_byte_length",
        "source_hex",
        "actual_hex",
        "target_size",
        "range_ok",
        "expected_match",
        "exact_string_boundary",
        "scanned_string_text",
        "scanned_string_byte_length",
        "prefix_hex_16",
        "suffix_hex_16",
        "terminator_first_byte_hex",
        "zero_padding_after_string",
        "slot_capacity_estimate",
        "pointer_u16le",
        "pointer_u16be",
        "pointer_u32le",
        "pointer_u32be",
        "replacement_text",
        "replacement_source",
        "replacement_encoding_status",
        "replacement_byte_length",
        "capacity_status",
        "candidate_range_start",
        "candidate_range_end",
        "duplicate_candidate_count",
        "overlap_candidate_count",
        "structure_status",
        "source_validation_status",
        "expected_write_confirmed",
        "expected_write_block_reason",
    ]

    write_csv(
        output / "structural_validation.csv",
        raw_results,
        result_fields,
    )

    verified_unique = sum(
        row.get("source_validation_status")
        == "verified_unique_source_location"
        for row in raw_results
    )
    verified_nonunique = sum(
        row.get("source_validation_status")
        == "verified_but_duplicate_or_overlap"
        for row in raw_results
    )
    failed = sum(
        row.get("source_validation_status")
        == "source_validation_failed"
        for row in raw_results
    )
    custom_encoder_required = sum(
        row.get("replacement_encoding_status")
        == "custom_korean_encoder_required"
        for row in raw_results
    )

    write_json(
        output / "all_report.json",
        {
            "format": (
                "prinny1_v7_11_structural_validation_report_v1"
            ),
            "created_at": now(),
            "v710_report": report,
            "v710_queue_rows": len(queue_rows),
            "strong_ui_groups": len(strong_ui_groups),
            "strong_dialogue_groups": len(
                strong_dialogue_groups
            ),
            "reconstructed_candidate_rows": len(
                candidates
            ),
            "ambiguous_ui_token_ties": len(ambiguous_ui),
            "source_verified_unique": verified_unique,
            "source_verified_nonunique": verified_nonunique,
            "source_validation_failed": failed,
            "custom_korean_encoder_required": (
                custom_encoder_required
            ),
            "encoder_hint_files": len(encoder_hints),
            "expected_write_candidates_confirmed": 0,
            "patch_applied": False,
            "iso_created": False,
            "translation_wording_changed": False,
            "character_voice_changed": False,
            "next_action": (
                "검증된 고유 원본 위치의 실제 한글 교체 바이트를 "
                "프로젝트 인코더 또는 기존 패치 자원에서 재구성"
            ),
            "outputs": {
                "candidates": str(
                    output
                    / "reconstructed_validation_candidates.csv"
                ),
                "structural_validation": str(
                    output / "structural_validation.csv"
                ),
                "ui_ties": str(
                    output / "ambiguous_ui_token_ties.csv"
                ),
                "encoder_hints": str(
                    output / "korean_encoder_hints.csv"
                ),
            },
            "status": "pass",
        },
    )

    shutil.rmtree(run_directory, ignore_errors=True)

    print()
    print("완료")
    print(
        f"복원된 구조 검증 행       : {len(candidates)}"
    )
    print(
        f"고유 원본 위치 검증       : {verified_unique}"
    )
    print(
        f"중복·겹침 원본 위치       : {verified_nonunique}"
    )
    print(
        f"원본 구조 검증 실패       : {failed}"
    )
    print(
        f"한글 전용 인코더 필요     : "
        f"{custom_encoder_required}"
    )
    print(
        f"인코더 후보 소스 파일     : {len(encoder_hints)}"
    )
    print("확정 Expected Write      : 0")
    print(
        f"구조 검증 CSV            : "
        f"{output / 'structural_validation.csv'}"
    )
    print(
        f"인코더 후보 CSV          : "
        f"{output / 'korean_encoder_hints.csv'}"
    )
    print(
        f"보고서 JSON              : "
        f"{output / 'all_report.json'}"
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
