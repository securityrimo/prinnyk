#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import shutil
import sys
import traceback
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_DEFAULT = Path.home() / "PrinnyReverseToolkit"
DRIVE_DEFAULT = Path("/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd")
ROOT_DEFAULT = DRIVE_DEFAULT / "PSP_Localization_Work"

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
KR_RE = re.compile(r"[가-힣]")
TOKEN_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fffA-Za-z0-9○]+")
IMPOSSIBLE_SCORE = -100000


def timestamp() -> str:
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


def normalize_korean(text: str) -> str:
    return "".join(KR_RE.findall(text or ""))


def normalize_japanese(text: str) -> str:
    return "".join(
        character
        for character in text or ""
        if JP_RE.match(character)
    )


def similarity(left: str, right: str, language: str) -> float:
    if language == "ko":
        normalized_left = normalize_korean(left)
        normalized_right = normalize_korean(right)
    else:
        normalized_left = normalize_japanese(left)
        normalized_right = normalize_japanese(right)

    if not normalized_left or not normalized_right:
        return 0.0

    return difflib.SequenceMatcher(
        None,
        normalized_left,
        normalized_right,
    ).ratio()


def parse_integer(value: Any) -> int | None:
    match = re.search(r"0x[0-9A-Fa-f]+|\d+", str(value or ""))
    if not match:
        return None
    try:
        return int(match.group(0), 0)
    except ValueError:
        return None


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

    for relative in (
        "PSP_GAME/SYSDIR/BOOT.BIN",
        "PSP_GAME/SYSDIR/EBOOT.BIN",
    ):
        try:
            targets.append(
                {
                    "logical": relative,
                    "path": locate_file(disc_root, relative),
                    "kind": "ui",
                    "scope": "executable",
                }
            )
        except FileNotFoundError:
            pass

    try:
        targets.append(
            {
                "logical": "PSP_GAME/USRDIR/SCRIPT.DAT",
                "path": locate_file(
                    disc_root,
                    "PSP_GAME/USRDIR/SCRIPT.DAT",
                ),
                "kind": "dialogue",
                "scope": "script_container",
            }
        )
    except FileNotFoundError:
        pass

    return targets


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


def scan_strings(
    data: bytes,
    minimum_characters: int = 2,
) -> list[dict[str, Any]]:
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

        if character_count >= minimum_characters and encoded:
            try:
                decoded = bytes(encoded).decode("cp932")
            except UnicodeDecodeError:
                decoded = ""

            if (
                decoded
                and (
                    has_two_byte
                    or len(decoded.strip()) >= 4
                )
            ):
                results[(start, decoded)] = {
                    "offset": start,
                    "offset_hex": f"0x{start:X}",
                    "text": decoded,
                }

        if index == start:
            index += 1

    return sorted(
        results.values(),
        key=lambda row: int(row["offset"]),
    )


def build_string_index(
    targets: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    all_rows: list[dict[str, Any]] = []
    exact_index: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for target in targets:
        data = target["path"].read_bytes()

        for string_row in scan_strings(data):
            row = {
                "target": target["logical"],
                "target_kind": target["kind"],
                "scope": target["scope"],
                "offset": int(string_row["offset"]),
                "offset_hex": string_row["offset_hex"],
                "text": string_row["text"],
            }
            all_rows.append(row)
            exact_index[row["text"]].append(row)

    return all_rows, exact_index


def extract_ui_tokens(text: str) -> list[str]:
    tokens = [
        token
        for token in TOKEN_RE.findall(text or "")
        if len(token) >= 2
    ]

    unique: list[str] = []
    seen: set[str] = set()

    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)

    return unique


def ui_match_score(token: str, candidate_text: str) -> tuple[int, str]:
    if candidate_text == token:
        return 120, "exact"

    if token in candidate_text:
        return 105, "token_in_string"

    if candidate_text in token and len(candidate_text) >= 3:
        return 95, "string_in_token"

    ratio = similarity(token, candidate_text, "ja")
    if ratio >= 0.85:
        return round(ratio * 90), "fuzzy_high"
    if ratio >= 0.65:
        return round(ratio * 70), "fuzzy"

    return 0, ""


def rank_dialogue_translation_pairs(
    visible_korean: str,
    translation_pairs: list[dict[str, str]],
    limit: int = 80,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []

    for pair in translation_pairs:
        ratio = similarity(
            visible_korean,
            pair.get("translation", ""),
            "ko",
        )
        if ratio < 0.25:
            continue

        ranked.append(
            {
                **pair,
                "korean_similarity": ratio,
            }
        )

    ranked.sort(
        key=lambda row: -float(row["korean_similarity"])
    )
    return ranked[:limit]


def mapping_key(row: dict[str, Any]) -> str:
    return (
        f"{row['target']}|{row['offset_hex']}|"
        f"{row.get('source_text', '')}"
    )


def hungarian_max(
    weights: list[list[int]],
) -> tuple[int, list[int]]:
    row_count = len(weights)
    if row_count == 0:
        return 0, []

    column_count = len(weights[0])
    if column_count < row_count:
        raise ValueError(
            "전역 배정의 후보 열이 이슈 행보다 적습니다."
        )

    maximum_weight = max(
        max(row)
        for row in weights
    )
    costs = [
        [
            maximum_weight - value
            for value in row
        ]
        for row in weights
    ]

    u = [0] * (row_count + 1)
    v = [0] * (column_count + 1)
    p = [0] * (column_count + 1)
    way = [0] * (column_count + 1)

    for row_index in range(1, row_count + 1):
        p[0] = row_index
        column_zero = 0
        minimum_values = [10**18] * (column_count + 1)
        used = [False] * (column_count + 1)

        while True:
            used[column_zero] = True
            current_row = p[column_zero]
            delta = 10**18
            next_column = 0

            for column_index in range(1, column_count + 1):
                if used[column_index]:
                    continue

                current = (
                    costs[current_row - 1][column_index - 1]
                    - u[current_row]
                    - v[column_index]
                )

                if current < minimum_values[column_index]:
                    minimum_values[column_index] = current
                    way[column_index] = column_zero

                if minimum_values[column_index] < delta:
                    delta = minimum_values[column_index]
                    next_column = column_index

            for column_index in range(column_count + 1):
                if used[column_index]:
                    u[p[column_index]] += delta
                    v[column_index] -= delta
                else:
                    minimum_values[column_index] -= delta

            column_zero = next_column

            if p[column_zero] == 0:
                break

        while True:
            previous_column = way[column_zero]
            p[column_zero] = p[previous_column]
            column_zero = previous_column

            if column_zero == 0:
                break

    assignment = [-1] * row_count

    for column_index in range(1, column_count + 1):
        if p[column_index]:
            assignment[p[column_index] - 1] = column_index - 1

    total = sum(
        weights[row_index][assignment[row_index]]
        for row_index in range(row_count)
        if assignment[row_index] >= 0
    )

    return total, assignment


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
        "--screen-groups",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_9_translation_context"
            / "screen_issue_groups.csv"
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
            / "reports/prinny1_v7_10_global_source_search"
        ),
    )
    parser.add_argument(
        "--run-directory",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "work/prinny1_v7_10_global_source_search"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    game_iso = arguments.game.expanduser().resolve()
    screen_groups_path = arguments.screen_groups.expanduser().resolve()
    translation_pairs_path = (
        arguments.translation_pairs.expanduser().resolve()
    )
    output = arguments.output.expanduser().resolve()
    run_directory = arguments.run_directory.expanduser().resolve()

    for required in (
        project,
        game_iso,
        screen_groups_path,
        translation_pairs_path,
    ):
        if not required.exists():
            raise FileNotFoundError(
                f"필수 입력이 없습니다: {required}"
            )

    output.mkdir(parents=True, exist_ok=True)
    run_directory.mkdir(parents=True, exist_ok=True)

    print("[1/4] 원본 ISO 재추출 및 전체 일본어 문자열 인덱스 생성")

    targets = prepare_targets(
        game_iso,
        run_directory,
        output,
    )
    string_rows, exact_index = build_string_index(targets)

    write_csv(
        output / "source_string_index.csv",
        string_rows,
        [
            "target",
            "target_kind",
            "scope",
            "offset",
            "offset_hex",
            "text",
        ],
    )

    print("[2/4] UI 6개 그룹의 일본어 문구 직접 검색")

    screen_groups = read_csv(screen_groups_path)
    ui_groups = [
        row
        for row in screen_groups
        if row.get("kind") == "ui"
    ]
    dialogue_groups = [
        row
        for row in screen_groups
        if row.get("kind") == "dialogue"
    ]

    ui_string_rows = [
        row
        for row in string_rows
        if row["target_kind"] == "ui"
    ]

    ui_hit_rows: list[dict[str, Any]] = []
    ui_resolution_rows: list[dict[str, Any]] = []

    for group in ui_groups:
        tokens = extract_ui_tokens(
            group.get("visible_japanese", "")
        )
        resolved_tokens = 0
        exact_tokens = 0

        for token in tokens:
            matches: list[dict[str, Any]] = []

            for indexed in ui_string_rows:
                score, method = ui_match_score(
                    token,
                    indexed["text"],
                )
                if score <= 0:
                    continue

                matches.append(
                    {
                        "group_id": group["group_id"],
                        "issue_ids": group["issue_ids"],
                        "scene": group["scene"],
                        "token": token,
                        "target": indexed["target"],
                        "offset_hex": indexed["offset_hex"],
                        "source_text": indexed["text"],
                        "match_score": score,
                        "match_method": method,
                    }
                )

            matches.sort(
                key=lambda row: -int(row["match_score"])
            )
            top_matches = matches[:10]
            ui_hit_rows.extend(top_matches)

            if top_matches:
                resolved_tokens += 1
                if top_matches[0]["match_method"] in {
                    "exact",
                    "token_in_string",
                }:
                    exact_tokens += 1

        token_count = len(tokens)
        coverage = (
            resolved_tokens / token_count
            if token_count
            else 0.0
        )

        if (
            token_count
            and resolved_tokens == token_count
            and exact_tokens >= max(1, token_count // 2)
        ):
            status = "strong_ui_source_set"
        elif coverage >= 0.5:
            status = "provisional_ui_source_set"
        else:
            status = "ambiguous_ui_source_set"

        ui_resolution_rows.append(
            {
                "group_id": group["group_id"],
                "issue_ids": group["issue_ids"],
                "scene": group["scene"],
                "token_count": token_count,
                "resolved_tokens": resolved_tokens,
                "exact_tokens": exact_tokens,
                "coverage": round(coverage, 4),
                "status": status,
                "expected_write_confirmed": "no",
                "next_action": (
                    "각 UI 문자열의 슬롯·참조·교체 길이 검증"
                    if status == "strong_ui_source_set"
                    else "BOOT/EBOOT 외 텍스처·별도 UI 자원 탐색"
                ),
            }
        )

    write_csv(
        output / "ui_token_hits.csv",
        ui_hit_rows,
        [
            "group_id",
            "issue_ids",
            "scene",
            "token",
            "target",
            "offset_hex",
            "source_text",
            "match_score",
            "match_method",
        ],
    )
    write_csv(
        output / "ui_group_resolution.csv",
        ui_resolution_rows,
        [
            "group_id",
            "issue_ids",
            "scene",
            "token_count",
            "resolved_tokens",
            "exact_tokens",
            "coverage",
            "status",
            "expected_write_confirmed",
            "next_action",
        ],
    )

    print("[3/4] 대사 10개 그룹을 번역 5,434쌍 전체에서 재탐색")

    translation_pairs = read_csv(translation_pairs_path)
    dialogue_candidate_rows: list[dict[str, Any]] = []
    candidates_by_group: dict[
        str,
        dict[str, dict[str, Any]],
    ] = defaultdict(dict)

    for group in dialogue_groups:
        ranked_pairs = rank_dialogue_translation_pairs(
            group.get("visible_korean", ""),
            translation_pairs,
            limit=100,
        )

        for pair_rank, pair in enumerate(
            ranked_pairs,
            start=1,
        ):
            source_text = pair.get("source_text", "")
            occurrences = [
                occurrence
                for occurrence in exact_index.get(
                    source_text,
                    [],
                )
                if occurrence["target_kind"] == "dialogue"
            ]

            for occurrence in occurrences:
                korean_ratio = float(
                    pair["korean_similarity"]
                )
                base_score = round(korean_ratio * 160)
                rank_penalty = min(pair_rank, 30)
                score = (
                    base_score
                    + 120
                    - rank_penalty
                )

                row = {
                    "group_id": group["group_id"],
                    "issue_ids": group["issue_ids"],
                    "scene": group["scene"],
                    "sequence": group["sequence"],
                    "speaker": group["speaker"],
                    "visible_korean": group["visible_korean"],
                    "source_text": source_text,
                    "matched_translation": pair.get(
                        "translation",
                        "",
                    ),
                    "korean_similarity": round(
                        korean_ratio,
                        4,
                    ),
                    "translation_rank": pair_rank,
                    "target": occurrence["target"],
                    "offset": occurrence["offset"],
                    "offset_hex": occurrence["offset_hex"],
                    "scope": occurrence["scope"],
                    "base_score": score,
                    "sequence_bonus": 0,
                    "final_score": score,
                }

                key = mapping_key(row)
                current = candidates_by_group[
                    group["group_id"]
                ].get(key)

                if (
                    current is None
                    or int(row["base_score"])
                    > int(current["base_score"])
                ):
                    candidates_by_group[
                        group["group_id"]
                    ][key] = row

    scene_groups: dict[
        str,
        list[dict[str, str]],
    ] = defaultdict(list)

    for group in dialogue_groups:
        scene_groups[group["scene"]].append(group)

    sequence_rows: list[dict[str, Any]] = []

    for scene, groups in scene_groups.items():
        ordered_groups = sorted(
            groups,
            key=lambda row: int(row["sequence"]),
        )
        targets_in_scene = {
            candidate["target"]
            for group in ordered_groups
            for candidate in candidates_by_group.get(
                group["group_id"],
                {},
            ).values()
        }

        for target in sorted(targets_in_scene):
            chosen: list[dict[str, Any]] = []

            for group in ordered_groups:
                choices = [
                    candidate
                    for candidate in candidates_by_group.get(
                        group["group_id"],
                        {},
                    ).values()
                    if candidate["target"] == target
                ]
                if choices:
                    chosen.append(
                        max(
                            choices,
                            key=lambda row: int(
                                row["base_score"]
                            ),
                        )
                    )

            offsets = [
                int(row["offset"])
                for row in chosen
            ]
            monotonic = all(
                first < second
                for first, second in zip(
                    offsets,
                    offsets[1:],
                )
            )
            coverage = len(chosen)
            required = len(ordered_groups)

            if coverage == required and monotonic:
                bonus = 35
            elif coverage >= 2 and monotonic:
                bonus = 15
            else:
                bonus = 0

            sequence_rows.append(
                {
                    "scene": scene,
                    "target": target,
                    "required_groups": required,
                    "covered_groups": coverage,
                    "monotonic_offsets": monotonic,
                    "sequence_bonus": bonus,
                    "group_ids": "|".join(
                        str(row["group_id"])
                        for row in chosen
                    ),
                    "offsets": "|".join(
                        str(row["offset_hex"])
                        for row in chosen
                    ),
                }
            )

            if bonus:
                for group in ordered_groups:
                    for candidate in candidates_by_group.get(
                        group["group_id"],
                        {},
                    ).values():
                        if candidate["target"] == target:
                            candidate["sequence_bonus"] = bonus
                            candidate["final_score"] = (
                                int(candidate["base_score"])
                                + bonus
                            )

    for group_candidates in candidates_by_group.values():
        dialogue_candidate_rows.extend(
            group_candidates.values()
        )

    write_csv(
        output / "dialogue_global_candidates.csv",
        dialogue_candidate_rows,
        [
            "group_id",
            "issue_ids",
            "scene",
            "sequence",
            "speaker",
            "visible_korean",
            "source_text",
            "matched_translation",
            "korean_similarity",
            "translation_rank",
            "target",
            "offset",
            "offset_hex",
            "scope",
            "base_score",
            "sequence_bonus",
            "final_score",
        ],
    )
    write_csv(
        output / "dialogue_scene_sequence.csv",
        sequence_rows,
        [
            "scene",
            "target",
            "required_groups",
            "covered_groups",
            "monotonic_offsets",
            "sequence_bonus",
            "group_ids",
            "offsets",
        ],
    )

    print("[4/4] 전역 중복 없는 대사 배정 및 다음 검증 대상 저장")

    dialogue_group_ids = [
        group["group_id"]
        for group in dialogue_groups
    ]
    all_mapping_keys = sorted(
        {
            key
            for group_id in dialogue_group_ids
            for key in candidates_by_group.get(
                group_id,
                {},
            )
        }
    )

    dummy_keys = [
        f"__DUMMY_{index:03d}"
        for index in range(len(dialogue_group_ids))
    ]
    columns = all_mapping_keys + dummy_keys
    weights: list[list[int]] = []
    edge_info: dict[
        tuple[int, int],
        dict[str, Any],
    ] = {}

    for group_index, group_id in enumerate(
        dialogue_group_ids
    ):
        row_weights: list[int] = []

        for column_index, key in enumerate(columns):
            if key.startswith("__DUMMY_"):
                row_weights.append(
                    0
                    if key == dummy_keys[group_index]
                    else IMPOSSIBLE_SCORE
                )
                continue

            candidate = candidates_by_group.get(
                group_id,
                {},
            ).get(key)

            if candidate is None:
                row_weights.append(IMPOSSIBLE_SCORE)
                continue

            score = int(candidate["final_score"])
            row_weights.append(score)
            edge_info[(group_index, column_index)] = candidate

        weights.append(row_weights)

    assignment_rows: list[dict[str, Any]] = []

    if all_mapping_keys:
        total_score, assignment = hungarian_max(weights)
    else:
        total_score = 0
        assignment = [-1] * len(dialogue_group_ids)

    for group_index, group_id in enumerate(
        dialogue_group_ids
    ):
        group = next(
            row
            for row in dialogue_groups
            if row["group_id"] == group_id
        )
        assigned_column = assignment[group_index]
        assigned = edge_info.get(
            (group_index, assigned_column)
        )

        ranked_local = sorted(
            candidates_by_group.get(
                group_id,
                {},
            ).values(),
            key=lambda row: -int(row["final_score"]),
        )

        second_score = (
            int(ranked_local[1]["final_score"])
            if len(ranked_local) > 1
            else 0
        )
        assigned_score = (
            int(assigned["final_score"])
            if assigned
            else 0
        )
        local_margin = assigned_score - second_score

        if assigned:
            alternate_weights = [
                row[:]
                for row in weights
            ]
            alternate_weights[
                group_index
            ][assigned_column] = IMPOSSIBLE_SCORE
            alternate_total, _alternate_assignment = (
                hungarian_max(alternate_weights)
            )
            global_margin = total_score - alternate_total
        else:
            global_margin = 0

        korean_similarity = (
            float(assigned["korean_similarity"])
            if assigned
            else 0.0
        )

        if (
            assigned
            and korean_similarity >= 0.78
            and local_margin >= 15
            and global_margin >= 10
        ):
            status = "strong_dialogue_source"
        elif (
            assigned
            and korean_similarity >= 0.55
            and global_margin > 0
        ):
            status = "provisional_dialogue_source"
        else:
            status = "ambiguous_dialogue_source"

        assignment_rows.append(
            {
                "group_id": group_id,
                "issue_ids": group["issue_ids"],
                "scene": group["scene"],
                "sequence": group["sequence"],
                "visible_korean": group["visible_korean"],
                "selected_target": (
                    assigned["target"] if assigned else ""
                ),
                "selected_offset_hex": (
                    assigned["offset_hex"] if assigned else ""
                ),
                "selected_source_text": (
                    assigned["source_text"] if assigned else ""
                ),
                "matched_translation": (
                    assigned["matched_translation"]
                    if assigned
                    else ""
                ),
                "korean_similarity": korean_similarity,
                "final_score": assigned_score,
                "local_margin": local_margin,
                "global_margin": global_margin,
                "status": status,
                "expected_write_confirmed": "no",
                "next_action": (
                    "문자열 경계·포인터·슬롯·제어코드 검증"
                    if status == "strong_dialogue_source"
                    else "후보 번역과 화면 문구 수동 대조"
                ),
            }
        )

    write_csv(
        output / "dialogue_assignment.csv",
        assignment_rows,
        [
            "group_id",
            "issue_ids",
            "scene",
            "sequence",
            "visible_korean",
            "selected_target",
            "selected_offset_hex",
            "selected_source_text",
            "matched_translation",
            "korean_similarity",
            "final_score",
            "local_margin",
            "global_margin",
            "status",
            "expected_write_confirmed",
            "next_action",
        ],
    )

    strong_ui = sum(
        row["status"] == "strong_ui_source_set"
        for row in ui_resolution_rows
    )
    provisional_ui = sum(
        row["status"] == "provisional_ui_source_set"
        for row in ui_resolution_rows
    )
    ambiguous_ui = sum(
        row["status"] == "ambiguous_ui_source_set"
        for row in ui_resolution_rows
    )
    strong_dialogue = sum(
        row["status"] == "strong_dialogue_source"
        for row in assignment_rows
    )
    provisional_dialogue = sum(
        row["status"] == "provisional_dialogue_source"
        for row in assignment_rows
    )
    ambiguous_dialogue = sum(
        row["status"] == "ambiguous_dialogue_source"
        for row in assignment_rows
    )

    next_validation_rows: list[dict[str, Any]] = []

    for row in ui_resolution_rows:
        if row["status"] == "strong_ui_source_set":
            next_validation_rows.append(
                {
                    "group_id": row["group_id"],
                    "kind": "ui",
                    "status": row["status"],
                    "target": "",
                    "offset_hex": "",
                    "source_text": "",
                    "validation_required": (
                        "UI 토큰별 슬롯·참조·교체 길이"
                    ),
                }
            )

    for row in assignment_rows:
        if row["status"] == "strong_dialogue_source":
            next_validation_rows.append(
                {
                    "group_id": row["group_id"],
                    "kind": "dialogue",
                    "status": row["status"],
                    "target": row["selected_target"],
                    "offset_hex": row["selected_offset_hex"],
                    "source_text": row["selected_source_text"],
                    "validation_required": (
                        "경계·포인터·슬롯·제어코드"
                    ),
                }
            )

    write_csv(
        output / "next_structural_validation_queue.csv",
        next_validation_rows,
        [
            "group_id",
            "kind",
            "status",
            "target",
            "offset_hex",
            "source_text",
            "validation_required",
        ],
    )

    write_json(
        output / "all_report.json",
        {
            "format": (
                "prinny1_v7_10_global_source_search_report_v1"
            ),
            "created_at": timestamp(),
            "source_string_count": len(string_rows),
            "translation_pair_count": len(translation_pairs),
            "ui_group_count": len(ui_groups),
            "dialogue_group_count": len(dialogue_groups),
            "strong_ui": strong_ui,
            "provisional_ui": provisional_ui,
            "ambiguous_ui": ambiguous_ui,
            "strong_dialogue": strong_dialogue,
            "provisional_dialogue": provisional_dialogue,
            "ambiguous_dialogue": ambiguous_dialogue,
            "next_structural_validation_count": len(
                next_validation_rows
            ),
            "expected_write_candidates_confirmed": 0,
            "patch_applied": False,
            "iso_created": False,
            "translation_wording_changed": False,
            "character_voice_changed": False,
            "outputs": {
                "ui_hits": str(output / "ui_token_hits.csv"),
                "ui_resolution": str(
                    output / "ui_group_resolution.csv"
                ),
                "dialogue_candidates": str(
                    output / "dialogue_global_candidates.csv"
                ),
                "dialogue_assignment": str(
                    output / "dialogue_assignment.csv"
                ),
                "next_validation": str(
                    output
                    / "next_structural_validation_queue.csv"
                ),
            },
            "status": "pass",
        },
    )

    shutil.rmtree(run_directory, ignore_errors=True)

    print()
    print("완료")
    print(
        f"UI 강함/임시/모호       : "
        f"{strong_ui}/{provisional_ui}/{ambiguous_ui}"
    )
    print(
        f"대사 강함/임시/모호     : "
        f"{strong_dialogue}/"
        f"{provisional_dialogue}/"
        f"{ambiguous_dialogue}"
    )
    print(
        f"다음 구조 검증 대상      : "
        f"{len(next_validation_rows)}"
    )
    print("확정 Expected Write     : 0")
    print(
        f"UI 결과                 : "
        f"{output / 'ui_group_resolution.csv'}"
    )
    print(
        f"대사 결과               : "
        f"{output / 'dialogue_assignment.csv'}"
    )
    print(
        f"다음 검증 큐            : "
        f"{output / 'next_structural_validation_queue.csv'}"
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
