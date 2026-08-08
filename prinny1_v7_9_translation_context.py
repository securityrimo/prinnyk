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
from typing import Any, Iterable

PROJECT_DEFAULT = Path.home() / "PrinnyReverseToolkit"
DRIVE_DEFAULT = Path("/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd")
ROOT_DEFAULT = DRIVE_DEFAULT / "PSP_Localization_Work"

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
KR_RE = re.compile(r"[가-힣]")
SOURCE_KEYS = (
    "source",
    "source_text",
    "original",
    "japanese",
    "original_text",
)
TRANSLATION_KEYS = (
    "translation",
    "translated",
    "korean",
    "target_text",
    "ko",
    "translated_text",
)
MAX_FILE_SIZE = 20 * 1024 * 1024

SCREEN_GROUPS: list[dict[str, Any]] = [
    {
        "group_id": "G001",
        "issue_ids": "SHOT-001",
        "kind": "ui",
        "scene": "difficulty_settings",
        "speaker": "prinny",
        "sequence": 1,
        "visible_korean": "즐길 거리 만점인 악마용 난이도임다",
        "visible_japanese": (
            "難しさ設定 魔界公式ルール "
            "難易度によってイベントやエンディングが変化することはありません "
            "ゲームの途中で難易度を変更することもできます"
        ),
        "symptom": "mixed_language_ui",
        "note": "난이도 화면 제목·설명·규칙 카드 일본어 잔존",
    },
    {
        "group_id": "G002",
        "issue_ids": "SHOT-002",
        "kind": "dialogue",
        "scene": "field_dialogue",
        "speaker": "prinny",
        "sequence": 1,
        "visible_korean": "허예엑 러야함다",
        "visible_japanese": "",
        "symptom": "missing_or_ascii_glyph",
        "note": "문장 가운데 한글 대신 공백 또는 ASCII형 글리프",
    },
    {
        "group_id": "G003",
        "issue_ids": "SHOT-003",
        "kind": "ui",
        "scene": "stage_hud",
        "speaker": "system",
        "sequence": 1,
        "visible_korean": "훈룽",
        "visible_japanese": "タイトルへ チュートリアル",
        "symptom": "residual_japanese_ui",
        "note": "HUD 안내판과 튜토리얼 표지 일본어 잔존",
    },
    {
        "group_id": "G004",
        "issue_ids": "SHOT-004|SHOT-009",
        "kind": "dialogue",
        "scene": "throne_room",
        "speaker": "etna",
        "sequence": 1,
        "visible_korean": "내 스위츠 누 다 처먹었어어어",
        "visible_japanese": "",
        "symptom": "wrong_glyph|missing_character",
        "note": "동일 대사의 중복 캡처 두 장",
    },
    {
        "group_id": "G005",
        "issue_ids": "SHOT-005|SHOT-010",
        "kind": "dialogue",
        "scene": "throne_room",
        "speaker": "etna",
        "sequence": 2,
        "visible_korean": "좋아 아침까지 항간의 화제 궁극의 스위츠를 가져와",
        "visible_japanese": "",
        "symptom": "black_square|ascii_glyph",
        "note": "동일 대사의 중복 캡처 두 장",
    },
    {
        "group_id": "G006",
        "issue_ids": "SHOT-006",
        "kind": "ui",
        "scene": "tutorial_popup",
        "speaker": "system",
        "sequence": 1,
        "visible_korean": "",
        "visible_japanese": (
            "チュートリアル つかまり "
            "崖に向かって方向キーを押しっぱなしにすると崖につかまる とじる"
        ),
        "symptom": "untranslated_japanese",
        "note": "튜토리얼 팝업 전체 일본어",
    },
    {
        "group_id": "G007",
        "issue_ids": "SHOT-007",
        "kind": "ui",
        "scene": "stage_result",
        "speaker": "system",
        "sequence": 1,
        "visible_korean": "프리니수",
        "visible_japanese": (
            "STAGE RESULT クリアタイム ベストタイム "
            "ステージ ボス クリアランク"
        ),
        "symptom": "mixed_language_ui",
        "note": "결과 화면 대부분 일본어 또는 영어",
    },
    {
        "group_id": "G008",
        "issue_ids": "SHOT-008",
        "kind": "dialogue",
        "scene": "village_dialogue",
        "speaker": "prinny",
        "sequence": 1,
        "visible_korean": "무 이 일어난걸까",
        "visible_japanese": "",
        "symptom": "missing_character|ascii_glyph",
        "note": "문장 중간 누락과 ASCII형 글리프",
    },
    {
        "group_id": "G011",
        "issue_ids": "SHOT-011",
        "kind": "dialogue",
        "scene": "throne_room",
        "speaker": "etna",
        "sequence": 3,
        "visible_korean": "라고 생각하죠 후훗 그럼 좀 알고",
        "visible_japanese": "",
        "symptom": "wrong_glyph|possible_truncation",
        "note": "중간 쓰레기 글리프와 문장 끝 손상",
    },
    {
        "group_id": "G012",
        "issue_ids": "SHOT-012",
        "kind": "dialogue",
        "scene": "throne_room",
        "speaker": "etna",
        "sequence": 4,
        "visible_korean": "알았지 아침",
        "visible_japanese": "",
        "symptom": "black_square|ascii_glyph|truncation",
        "note": "짧은 문장이 중간부터 깨지고 잘림",
    },
    {
        "group_id": "G013",
        "issue_ids": "SHOT-013",
        "kind": "dialogue",
        "scene": "village_dialogue",
        "speaker": "prinny",
        "sequence": 2,
        "visible_korean": "우리들도 구천에서 응원하고 있습니다",
        "visible_japanese": "",
        "symptom": "trailing_wrong_hanja",
        "note": "정상 문장 뒤에 잘못된 글리프",
    },
    {
        "group_id": "G014",
        "issue_ids": "SHOT-014",
        "kind": "ui",
        "scene": "village_hud",
        "speaker": "system",
        "sequence": 1,
        "visible_korean": "",
        "visible_japanese": "魔王城へ Talk はなしかける 残り10序時間",
        "symptom": "untranslated_japanese_ui",
        "note": "마을 HUD와 조작 안내 일본어 잔존",
    },
    {
        "group_id": "G015",
        "issue_ids": "SHOT-015",
        "kind": "dialogue",
        "scene": "village_dialogue",
        "speaker": "prinny",
        "sequence": 3,
        "visible_korean": (
            "마계 6곳에서는 흉악한 악마에게 재료를 손에 넣을 필요가 있습니다"
        ),
        "visible_japanese": "",
        "symptom": "wrong_glyph|ascii_glyph",
        "note": "문장 중간 영문형 쓰레기 글리프",
    },
    {
        "group_id": "G016",
        "issue_ids": "SHOT-016",
        "kind": "dialogue",
        "scene": "village_dialogue",
        "speaker": "unknown_soul",
        "sequence": 4,
        "visible_korean": "이젠 실패 도망치고 싶어 도망치고 싶",
        "visible_japanese": "",
        "symptom": "wrong_glyph|truncation",
        "note": "쓰레기 글리프와 문장 끝 손상",
    },
    {
        "group_id": "G017",
        "issue_ids": "SHOT-017",
        "kind": "dialogue",
        "scene": "village_dialogue",
        "speaker": "unknown_soul",
        "sequence": 5,
        "visible_korean": "시공의 새바람 기분 좋은 법입니다",
        "visible_japanese": "",
        "symptom": "possible_wrong_character",
        "note": "대부분 정상으로 보이나 특정 글리프 확인 필요",
    },
    {
        "group_id": "G018",
        "issue_ids": "SHOT-018",
        "kind": "ui",
        "scene": "tutorial_house_menu",
        "speaker": "system",
        "sequence": 1,
        "visible_korean": "",
        "visible_japanese": (
            "チュートリアル屋 チュートリアル閲覧の説明 "
            "チュートリアルステージ1 チュートリアルステージ2 "
            "TIPS 難しさ変更"
        ),
        "symptom": "untranslated_japanese_ui",
        "note": "튜토리얼 집 메뉴 전체 일본어",
    },
]


def current_time() -> str:
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


def first_value(record: dict[str, Any], keys: Iterable[str]) -> str:
    lowered = {str(key).casefold(): value for key, value in record.items()}
    for key in keys:
        value = lowered.get(key.casefold())
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def normalize_text(text: str, language: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text or "")
    if language == "ko":
        return "".join(KR_RE.findall(cleaned))
    if language == "ja":
        return "".join(
            character
            for character in cleaned
            if JP_RE.match(character)
        )
    return re.sub(r"\s+", "", cleaned).casefold()


def text_similarity(left: str, right: str, language: str) -> float:
    normalized_left = normalize_text(left, language)
    normalized_right = normalize_text(right, language)
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


def discover_translation_pairs(
    project: Path,
    work_root: Path,
    output: Path,
) -> list[dict[str, str]]:
    candidate_files: list[Path] = []

    for root in (project, work_root / "reports"):
        if not root.exists():
            continue

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.casefold() not in {".csv", ".json"}:
                continue

            lowered = str(path).casefold()
            if "prinny2" in lowered:
                continue
            if "psp_localization_studio" in lowered:
                continue
            if output in path.parents:
                continue
            if any(
                part.casefold() in {".git", "__pycache__", "node_modules"}
                or part.startswith(".prinny")
                for part in path.parts
            ):
                continue

            try:
                size = path.stat().st_size
            except OSError:
                continue

            if 0 < size <= MAX_FILE_SIZE:
                candidate_files.append(path)

    pairs: dict[tuple[str, str], dict[str, str]] = {}

    def add_record(
        record: dict[str, Any],
        path: Path,
        row_number: int,
    ) -> None:
        source = first_value(record, SOURCE_KEYS).strip()
        translation = first_value(record, TRANSLATION_KEYS).strip()

        if not source or not translation:
            return
        if not JP_RE.search(source):
            return
        if not KR_RE.search(translation):
            return

        key = (source, translation)
        pairs.setdefault(
            key,
            {
                "source_text": source,
                "translation": translation,
                "evidence_file": str(path),
                "evidence_row": str(row_number),
            },
        )

    def walk_json(
        value: Any,
        path: Path,
        counter: list[int],
    ) -> None:
        if isinstance(value, dict):
            add_record(value, path, counter[0])
            counter[0] += 1
            for child in value.values():
                walk_json(child, path, counter)
        elif isinstance(value, list):
            for child in value:
                walk_json(child, path, counter)

    for path in candidate_files:
        try:
            if path.suffix.casefold() == ".csv":
                for row_number, row in enumerate(read_csv(path), start=1):
                    add_record(row, path, row_number)
            else:
                value = json.loads(
                    path.read_text(encoding="utf-8-sig")
                )
                walk_json(value, path, [1])
        except Exception:
            continue

    result = list(pairs.values())
    write_csv(
        output / "translation_pair_inventory.csv",
        result,
        [
            "source_text",
            "translation",
            "evidence_file",
            "evidence_row",
        ],
    )
    return result


def locate_file(root: Path, relative: str) -> Path:
    direct = root / relative
    if direct.is_file():
        return direct

    target_name = Path(relative).name.casefold()
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name.casefold() == target_name
    ]

    if len(matches) == 1:
        return matches[0]

    raise FileNotFoundError(
        f"파일을 하나로 확정하지 못했습니다: {relative}"
    )


def prepare_binary_targets(
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

    for path in (
        disc_directory,
        system_directory,
        start_directory,
    ):
        shutil.rmtree(path, ignore_errors=True)

    try:
        disc_root, manifest = prepare_disc(
            game_iso,
            disc_directory,
            force=True,
            extraction_mode="minimal",
        )
    except TypeError:
        disc_root, manifest = prepare_disc(
            game_iso,
            disc_directory,
            force=True,
        )

    write_json(output / "extract_manifest.json", manifest)

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
                    "scope": "start_resource",
                }
            )

    for relative, scope in (
        ("PSP_GAME/SYSDIR/BOOT.BIN", "executable"),
        ("PSP_GAME/SYSDIR/EBOOT.BIN", "executable"),
        ("PSP_GAME/USRDIR/SYSTEM.DAT", "container"),
        ("PSP_GAME/USRDIR/SCRIPT.DAT", "container"),
    ):
        try:
            targets.append(
                {
                    "logical": relative,
                    "path": locate_file(disc_root, relative),
                    "scope": scope,
                }
            )
        except FileNotFoundError:
            pass

    return targets


def valid_shift_jis_pair(first_byte: int, second_byte: int) -> bool:
    is_lead = (
        0x81 <= first_byte <= 0x9F
        or 0xE0 <= first_byte <= 0xFC
    )
    is_trail = (
        0x40 <= second_byte <= 0xFC
        and second_byte != 0x7F
    )
    return is_lead and is_trail


def scan_shift_jis_strings(
    data: bytes,
    minimum_characters: int = 2,
) -> list[dict[str, Any]]:
    results: dict[tuple[int, str], dict[str, Any]] = {}
    index = 0

    while index < len(data):
        start = index
        encoded = bytearray()
        characters = 0
        contains_two_byte_character = False

        while index < len(data):
            current = data[index]

            if 0x20 <= current <= 0x7E:
                encoded.append(current)
                index += 1
                characters += 1
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
                characters += 1
                contains_two_byte_character = True
                continue

            break

        if characters >= minimum_characters and encoded:
            try:
                text = bytes(encoded).decode("cp932")
            except UnicodeDecodeError:
                text = ""

            if (
                text
                and (
                    contains_two_byte_character
                    or len(text.strip()) >= 4
                )
            ):
                results[(start, text)] = {
                    "offset": start,
                    "offset_hex": f"0x{start:X}",
                    "text": text,
                }

        if index == start:
            index += 1

    return sorted(
        results.values(),
        key=lambda row: int(row["offset"]),
    )


def normalize_target_name(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "/")
        .casefold()
        .removeprefix("./")
    )


def resolve_target(
    requested: str,
    targets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized = normalize_target_name(requested)

    exact = [
        target
        for target in targets
        if normalize_target_name(target["logical"]) == normalized
    ]
    if len(exact) == 1:
        return exact[0]

    basename = Path(normalized).name
    same_basename = [
        target
        for target in targets
        if Path(
            normalize_target_name(target["logical"])
        ).name == basename
    ]
    if len(same_basename) == 1:
        return same_basename[0]

    return None


def target_kind(target_name: str) -> str:
    basename = Path(
        normalize_target_name(target_name)
    ).name

    if basename in {"boot.bin", "eboot.bin"}:
        return "ui"

    return "dialogue"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "프리니 1 화면 16개 그룹과 V7.7 원본 일치 후보를 "
            "기존 번역·주변 문자열·장면 순서로 연결합니다."
        )
    )
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
        "--candidates",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_7_duplicate_audit"
            / "all_top_candidates_fresh_verified.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_9_translation_context"
        ),
    )
    parser.add_argument(
        "--run-directory",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "work/prinny1_v7_9_translation_context"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    game_iso = arguments.game.expanduser().resolve()
    candidates_path = arguments.candidates.expanduser().resolve()
    output = arguments.output.expanduser().resolve()
    run_directory = arguments.run_directory.expanduser().resolve()

    if not project.is_dir():
        raise FileNotFoundError(f"프로젝트 폴더 없음: {project}")
    if not game_iso.is_file():
        raise FileNotFoundError(f"프리니 1 ISO 없음: {game_iso}")
    if not candidates_path.is_file():
        raise FileNotFoundError(
            f"V7.7 후보 CSV 없음: {candidates_path}"
        )

    output.mkdir(parents=True, exist_ok=True)
    run_directory.mkdir(parents=True, exist_ok=True)

    print("[1/4] 화면 18장 → 고유 화면 그룹 16개 정규화")

    group_rows = []
    issue_to_group: dict[str, dict[str, Any]] = {}

    for group in SCREEN_GROUPS:
        group_rows.append(group)
        for issue_id in str(group["issue_ids"]).split("|"):
            issue_to_group[issue_id] = group

    write_csv(
        output / "screen_issue_groups.csv",
        group_rows,
        [
            "group_id",
            "issue_ids",
            "kind",
            "scene",
            "speaker",
            "sequence",
            "visible_korean",
            "visible_japanese",
            "symptom",
            "note",
        ],
    )

    print("[2/4] 기존 일본어 원문↔한국어 번역 쌍 수집")

    translation_pairs = discover_translation_pairs(
        project,
        work_root,
        output,
    )
    pairs_by_source: dict[str, list[dict[str, str]]] = defaultdict(list)

    for pair in translation_pairs:
        pairs_by_source[pair["source_text"]].append(pair)

    print("[3/4] 원본 ISO 재추출 및 후보 주변 문자열 분석")

    targets = prepare_binary_targets(
        game_iso,
        run_directory,
        output,
    )
    candidate_rows = [
        row
        for row in read_csv(candidates_path)
        if row.get("verification_status") == "verified"
    ]

    cache: dict[
        str,
        tuple[bytes, list[dict[str, Any]]],
    ] = {}

    context_rows: list[dict[str, Any]] = []

    for candidate in candidate_rows:
        issue_id = candidate.get("issue_id", "")
        group = issue_to_group.get(issue_id)
        if group is None:
            continue

        requested_target = (
            candidate.get("resolved_target")
            or candidate.get("target")
            or ""
        )
        target = resolve_target(requested_target, targets)
        offset = parse_integer(
            candidate.get("normalized_offset_hex")
            or candidate.get("offset_hex")
        )

        if target is None or offset is None:
            continue

        cache_key = str(target["path"].resolve())
        if cache_key not in cache:
            data = target["path"].read_bytes()
            strings = scan_shift_jis_strings(data)
            cache[cache_key] = (data, strings)

        _data, strings = cache[cache_key]
        offsets = [int(row["offset"]) for row in strings]
        insertion_index = bisect_left(offsets, offset)

        lower = max(0, insertion_index - 4)
        upper = min(len(strings), insertion_index + 5)
        neighborhood = strings[lower:upper]

        nearest = min(
            neighborhood,
            key=lambda row: abs(int(row["offset"]) - offset),
            default=None,
        )

        source_text = candidate.get("source_text", "")
        best_translation = ""
        best_korean_similarity = 0.0

        for pair in pairs_by_source.get(source_text, []):
            ratio = text_similarity(
                str(group["visible_korean"]),
                pair["translation"],
                "ko",
            )
            if ratio > best_korean_similarity:
                best_korean_similarity = ratio
                best_translation = pair["translation"]

        japanese_similarity = text_similarity(
            str(group["visible_japanese"]),
            source_text,
            "ja",
        )

        candidate_target_kind = target_kind(
            str(target["logical"])
        )
        kind_bonus = (
            30
            if candidate_target_kind == group["kind"]
            else -60
        )
        semantic_bonus = round(
            best_korean_similarity * 100
        ) + round(japanese_similarity * 100)

        try:
            base_score = int(
                float(
                    candidate.get("adjusted_score")
                    or candidate.get("base_score")
                    or 0
                )
            )
        except ValueError:
            base_score = 0

        context_rows.append(
            {
                "group_id": group["group_id"],
                "issue_id": issue_id,
                "kind": group["kind"],
                "scene": group["scene"],
                "sequence": group["sequence"],
                "visible_korean": group["visible_korean"],
                "visible_japanese": group["visible_japanese"],
                "target": target["logical"],
                "offset_hex": f"0x{offset:X}",
                "source_text": source_text,
                "matched_translation": best_translation,
                "korean_similarity": round(
                    best_korean_similarity,
                    4,
                ),
                "japanese_similarity": round(
                    japanese_similarity,
                    4,
                ),
                "base_score": base_score,
                "kind_bonus": kind_bonus,
                "semantic_bonus": semantic_bonus,
                "score_before_sequence": (
                    base_score
                    + kind_bonus
                    + semantic_bonus
                ),
                "nearest_string_offset": (
                    nearest["offset_hex"]
                    if nearest
                    else ""
                ),
                "nearest_string": (
                    nearest["text"]
                    if nearest
                    else ""
                ),
                "previous_strings": " || ".join(
                    row["text"]
                    for row in neighborhood
                    if int(row["offset"]) < offset
                ),
                "next_strings": " || ".join(
                    row["text"]
                    for row in neighborhood
                    if int(row["offset"]) > offset
                ),
                "mapping_key": candidate.get(
                    "mapping_key",
                    "",
                ),
            }
        )

    deduplicated: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    for row in context_rows:
        candidate_key = (
            row["mapping_key"]
            or f"{row['target']}|{row['offset_hex']}"
        )
        key = (str(row["group_id"]), str(candidate_key))
        current = deduplicated.get(key)

        if (
            current is None
            or int(row["score_before_sequence"])
            > int(current["score_before_sequence"])
        ):
            deduplicated[key] = row

    context_rows = list(deduplicated.values())

    ranked_by_group: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in context_rows:
        ranked_by_group[str(row["group_id"])].append(row)

    dialogue_scenes: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for group in SCREEN_GROUPS:
        if group["kind"] == "dialogue":
            dialogue_scenes[str(group["scene"])].append(group)

    sequence_bonus: dict[tuple[str, str], int] = {}
    sequence_rows: list[dict[str, Any]] = []

    for scene, groups in dialogue_scenes.items():
        ordered_groups = sorted(
            groups,
            key=lambda row: int(row["sequence"]),
        )

        possible_targets = {
            str(candidate["target"])
            for group in ordered_groups
            for candidate in ranked_by_group.get(
                str(group["group_id"]),
                [],
            )
        }

        for target_name in sorted(possible_targets):
            selected: list[dict[str, Any]] = []

            for group in ordered_groups:
                choices = [
                    candidate
                    for candidate in ranked_by_group.get(
                        str(group["group_id"]),
                        [],
                    )
                    if candidate["target"] == target_name
                ]
                if choices:
                    selected.append(
                        max(
                            choices,
                            key=lambda row: int(
                                row["score_before_sequence"]
                            ),
                        )
                    )

            selected_offsets = [
                parse_integer(row["offset_hex"]) or 0
                for row in selected
            ]
            monotonic = all(
                first < second
                for first, second in zip(
                    selected_offsets,
                    selected_offsets[1:],
                )
            )

            coverage = len(selected)
            required = len(ordered_groups)

            if coverage == required and monotonic:
                bonus = 25
            elif coverage >= 2 and monotonic:
                bonus = 10
            else:
                bonus = 0

            sequence_bonus[(scene, target_name)] = bonus
            sequence_rows.append(
                {
                    "scene": scene,
                    "target": target_name,
                    "group_count": required,
                    "coverage": coverage,
                    "monotonic_offsets": monotonic,
                    "sequence_bonus": bonus,
                    "groups": "|".join(
                        str(row["group_id"])
                        for row in selected
                    ),
                    "offsets": "|".join(
                        str(row["offset_hex"])
                        for row in selected
                    ),
                }
            )

    for row in context_rows:
        bonus = sequence_bonus.get(
            (str(row["scene"]), str(row["target"])),
            0,
        )
        row["sequence_bonus"] = bonus
        row["final_score"] = (
            int(row["score_before_sequence"]) + bonus
        )

    for candidates in ranked_by_group.values():
        candidates.sort(
            key=lambda row: -int(row.get("final_score", 0))
        )

    print("[4/4] 화면 그룹별 후보 판정 및 보고서 저장")

    final_rows: list[dict[str, Any]] = []

    for group in SCREEN_GROUPS:
        ranked = ranked_by_group.get(
            str(group["group_id"]),
            [],
        )
        best = ranked[0] if ranked else None
        second_score = (
            int(ranked[1]["final_score"])
            if len(ranked) > 1
            else 0
        )
        margin = (
            int(best["final_score"]) - second_score
            if best
            else 0
        )
        semantic_strength = (
            max(
                float(best["korean_similarity"]),
                float(best["japanese_similarity"]),
            )
            if best
            else 0.0
        )

        if (
            best
            and semantic_strength >= 0.75
            and margin >= 20
        ):
            confidence = "strong_context"
        elif (
            best
            and semantic_strength >= 0.45
            and margin > 0
        ):
            confidence = "provisional_context"
        else:
            confidence = "ambiguous"

        final_rows.append(
            {
                "group_id": group["group_id"],
                "issue_ids": group["issue_ids"],
                "kind": group["kind"],
                "scene": group["scene"],
                "sequence": group["sequence"],
                "visible_korean": group["visible_korean"],
                "visible_japanese": group["visible_japanese"],
                "selected_target": (
                    best["target"] if best else ""
                ),
                "selected_offset_hex": (
                    best["offset_hex"] if best else ""
                ),
                "selected_source_text": (
                    best["source_text"] if best else ""
                ),
                "matched_translation": (
                    best["matched_translation"] if best else ""
                ),
                "korean_similarity": (
                    best["korean_similarity"] if best else 0
                ),
                "japanese_similarity": (
                    best["japanese_similarity"] if best else 0
                ),
                "final_score": (
                    best["final_score"] if best else 0
                ),
                "score_margin": margin,
                "confidence": confidence,
                "expected_write_confirmed": "no",
                "next_action": (
                    "포인터·슬롯·제어코드 검증"
                    if confidence == "strong_context"
                    else "앞뒤 대사와 이벤트 순서 추가 대조"
                ),
            }
        )

    write_csv(
        output / "candidate_context_windows.csv",
        context_rows,
        [
            "group_id",
            "issue_id",
            "kind",
            "scene",
            "sequence",
            "visible_korean",
            "visible_japanese",
            "target",
            "offset_hex",
            "source_text",
            "matched_translation",
            "korean_similarity",
            "japanese_similarity",
            "base_score",
            "kind_bonus",
            "semantic_bonus",
            "score_before_sequence",
            "sequence_bonus",
            "final_score",
            "nearest_string_offset",
            "nearest_string",
            "previous_strings",
            "next_strings",
            "mapping_key",
        ],
    )

    write_csv(
        output / "scene_sequence_clusters.csv",
        sequence_rows,
        [
            "scene",
            "target",
            "group_count",
            "coverage",
            "monotonic_offsets",
            "sequence_bonus",
            "groups",
            "offsets",
        ],
    )

    write_csv(
        output / "screen_group_link_results.csv",
        final_rows,
        [
            "group_id",
            "issue_ids",
            "kind",
            "scene",
            "sequence",
            "visible_korean",
            "visible_japanese",
            "selected_target",
            "selected_offset_hex",
            "selected_source_text",
            "matched_translation",
            "korean_similarity",
            "japanese_similarity",
            "final_score",
            "score_margin",
            "confidence",
            "expected_write_confirmed",
            "next_action",
        ],
    )

    strong_count = sum(
        row["confidence"] == "strong_context"
        for row in final_rows
    )
    provisional_count = sum(
        row["confidence"] == "provisional_context"
        for row in final_rows
    )
    ambiguous_count = sum(
        row["confidence"] == "ambiguous"
        for row in final_rows
    )

    write_json(
        output / "all_report.json",
        {
            "format": (
                "prinny1_v7_9_translation_context_report_v1"
            ),
            "created_at": current_time(),
            "screenshot_count": 18,
            "unique_screen_groups": 16,
            "duplicate_pairs": [
                ["SHOT-004", "SHOT-009"],
                ["SHOT-005", "SHOT-010"],
            ],
            "translation_pairs": len(translation_pairs),
            "verified_candidate_rows_input": len(
                candidate_rows
            ),
            "candidate_context_rows": len(context_rows),
            "strong_context": strong_count,
            "provisional_context": provisional_count,
            "ambiguous": ambiguous_count,
            "expected_write_candidates_confirmed": 0,
            "patch_applied": False,
            "iso_created": False,
            "translation_wording_changed": False,
            "character_voice_changed": False,
            "outputs": {
                "screen_groups": str(
                    output / "screen_issue_groups.csv"
                ),
                "translation_pairs": str(
                    output / "translation_pair_inventory.csv"
                ),
                "context_windows": str(
                    output / "candidate_context_windows.csv"
                ),
                "sequence_clusters": str(
                    output / "scene_sequence_clusters.csv"
                ),
                "results": str(
                    output / "screen_group_link_results.csv"
                ),
            },
            "status": "pass",
        },
    )

    shutil.rmtree(run_directory, ignore_errors=True)

    print()
    print("완료")
    print(f"고유 화면 그룹 : 16")
    print(f"번역 쌍        : {len(translation_pairs)}")
    print(f"강한 문맥      : {strong_count}")
    print(f"임시 문맥      : {provisional_count}")
    print(f"모호           : {ambiguous_count}")
    print("Expected Write : 0")
    print(f"결과 CSV       : {output / 'screen_group_link_results.csv'}")
    print(f"상세 CSV       : {output / 'candidate_context_windows.csv'}")
    print(f"보고서 JSON    : {output / 'all_report.json'}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
