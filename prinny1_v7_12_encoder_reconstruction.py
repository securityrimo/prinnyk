#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import subprocess
import sys
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_DEFAULT = Path.home() / "PrinnyReverseToolkit"
DRIVE_DEFAULT = Path("/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd")
ROOT_DEFAULT = DRIVE_DEFAULT / "PSP_Localization_Work"

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
FUNCTION_NAME_RE = re.compile(
    r"(encode.*(?:text|string|translation|korean)|"
    r"(?:text|string|translation|korean).*encode|"
    r"text_to_bytes|string_to_bytes)",
    re.IGNORECASE,
)
MAX_SOURCE_SIZE = 20 * 1024 * 1024
MAX_VECTOR_COUNT = 60
MAX_ENCODER_FILES = 80


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


def vector_matches(
    produced_hex: str,
    expected_hex: str,
) -> tuple[bool, str]:
    produced = clean_hex(produced_hex)
    expected = clean_hex(expected_hex)

    if not produced or not expected:
        return False, ""

    if produced == expected:
        return True, "exact"

    if expected.startswith(produced):
        remainder = expected[len(produced):]
        if remainder and set(remainder) <= {"0"}:
            return True, "expected_zero_padded"

    if produced.startswith(expected):
        remainder = produced[len(expected):]
        if remainder and set(remainder) <= {"0"}:
            return True, "produced_zero_padded"

    return False, ""


def walk_json_records(value: Any, callback) -> None:
    if isinstance(value, dict):
        callback(value)
        for child in value.values():
            walk_json_records(child, callback)
    elif isinstance(value, list):
        for child in value:
            walk_json_records(child, callback)


def discover_known_vectors(
    project: Path,
    work_root: Path,
    output: Path,
) -> list[dict[str, str]]:
    discovered: dict[
        tuple[str, str],
        dict[str, str],
    ] = {}

    for root in (
        project,
        work_root / "reports",
        work_root / "build",
    ):
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

            if not 0 < size <= MAX_SOURCE_SIZE:
                continue

            def add_record(record: dict[str, Any]) -> None:
                translation = first_value(
                    record,
                    TRANSLATION_KEYS,
                ).strip()
                expected_hex = clean_hex(
                    first_value(record, HEX_KEYS)
                )
                if not translation or not expected_hex:
                    return

                discovered.setdefault(
                    (translation, expected_hex),
                    {
                        "translation": translation,
                        "expected_hex": expected_hex,
                        "evidence_file": str(path),
                    },
                )

            try:
                if path.suffix.casefold() == ".csv":
                    for record in read_csv(path):
                        add_record(record)
                else:
                    value = json.loads(
                        path.read_text(encoding="utf-8-sig")
                    )
                    walk_json_records(value, add_record)
            except Exception:
                continue

            if len(discovered) >= MAX_VECTOR_COUNT:
                break

        if len(discovered) >= MAX_VECTOR_COUNT:
            break

    vectors = list(discovered.values())[:MAX_VECTOR_COUNT]
    write_csv(
        output / "known_encoder_vectors.csv",
        vectors,
        [
            "translation",
            "expected_hex",
            "evidence_file",
        ],
    )
    return vectors


def discover_encoder_files(
    project: Path,
    hint_rows: list[dict[str, str]],
) -> list[Path]:
    files: dict[str, Path] = {}

    for row in hint_rows:
        raw = row.get("path", "").strip()
        path = Path(raw).expanduser()
        if path.is_file() and path.suffix.casefold() == ".py":
            files[str(path.resolve())] = path

    for path in project.rglob("*.py"):
        lowered = str(path).casefold()
        if any(
            blocked in lowered
            for blocked in (
                "/.git/",
                "/__pycache__/",
                "/.prinny",
                "prinny2",
                "psp_localization_studio",
            )
        ):
            continue

        name = path.name.casefold()
        if any(
            token in name
            for token in (
                "encode",
                "codec",
                "text",
                "string",
                "patch",
                "font",
                "char",
                "korean",
            )
        ):
            files[str(path.resolve())] = path

        if len(files) >= MAX_ENCODER_FILES:
            break

    return sorted(files.values())


def inspect_python_file(
    path: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    functions: list[dict[str, Any]] = []
    maps: list[dict[str, Any]] = []

    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        tree = ast.parse(text, filename=str(path))
    except Exception:
        return functions, maps

    for node in tree.body:
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            if not FUNCTION_NAME_RE.search(node.name):
                continue

            positional = (
                list(node.args.posonlyargs)
                + list(node.args.args)
            )
            required = max(
                0,
                len(positional) - len(node.args.defaults),
            )

            if required != 1:
                continue
            if node.args.vararg is not None:
                continue

            functions.append(
                {
                    "file": str(path),
                    "function": node.name,
                }
            )

        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        value_node = node.value
        if not isinstance(value_node, ast.Dict):
            continue

        try:
            value = ast.literal_eval(value_node)
        except Exception:
            continue

        if not isinstance(value, dict) or len(value) < 20:
            continue

        valid_entries = 0
        for key, item in value.items():
            if not isinstance(key, str) or len(key) != 1:
                continue
            if isinstance(item, (int, bytes)):
                valid_entries += 1
            elif isinstance(item, str) and clean_hex(item):
                valid_entries += 1

        if valid_entries < 20:
            continue

        names: list[str] = []
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
        elif isinstance(node.target, ast.Name):
            names.append(node.target.id)

        for name in names:
            maps.append(
                {
                    "file": str(path),
                    "map_name": name,
                    "literal_value": value,
                }
            )

    return functions, maps


def run_module_functions(
    project: Path,
    path: Path,
    functions: list[str],
    texts: list[str],
) -> dict[str, dict[str, str]]:
    harness = r'''
import importlib.util
import json
import re
import sys
import traceback
from pathlib import Path

project = Path(sys.argv[1])
module_path = Path(sys.argv[2])
request = json.loads(sys.stdin.read())
sys.path.insert(0, str(project))

def normalize(value):
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, bytearray):
        return bytes(value).hex().upper()
    if isinstance(value, memoryview):
        return value.tobytes().hex().upper()
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, int) and 0 <= item <= 255 for item in value):
            return bytes(value).hex().upper()
    if isinstance(value, str):
        raw = re.sub(r"[^0-9A-Fa-f]", "", value)
        if raw and len(raw) % 2 == 0:
            return raw.upper()
    return ""

result = {}

try:
    spec = importlib.util.spec_from_file_location(
        "_prinny_encoder_probe",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("module spec failed")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for function_name in request["functions"]:
        function = getattr(module, function_name, None)
        function_results = {}

        if not callable(function):
            result[function_name] = function_results
            continue

        for text in request["texts"]:
            try:
                encoded = normalize(function(text))
                if encoded:
                    function_results[text] = encoded
            except Exception:
                continue

        result[function_name] = function_results

except Exception:
    result["_module_error"] = {
        "error": traceback.format_exc()[-4000:]
    }

print(json.dumps(result, ensure_ascii=False))
'''

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                harness,
                str(project),
                str(path),
            ],
            input=json.dumps(
                {
                    "functions": functions,
                    "texts": texts,
                },
                ensure_ascii=False,
            ),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {}

    if completed.returncode != 0:
        return {}

    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}

    return value if isinstance(value, dict) else {}


def encode_with_literal_map(
    text: str,
    mapping: dict[Any, Any],
) -> str:
    output = bytearray()

    for character in text:
        if character not in mapping:
            return ""

        value = mapping[character]

        if isinstance(value, int):
            if value < 0:
                return ""
            if value <= 0xFF:
                output.append(value)
            elif value <= 0xFFFF:
                output.extend(value.to_bytes(2, "big"))
            else:
                return ""

        elif isinstance(value, bytes):
            output.extend(value)

        elif isinstance(value, str):
            encoded = clean_hex(value)
            if not encoded:
                return ""
            output.extend(bytes.fromhex(encoded))

        else:
            return ""

    return output.hex().upper()


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
        "--output",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_12_encoder_reconstruction"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    v711 = arguments.v711.expanduser().resolve()
    output = arguments.output.expanduser().resolve()

    structural_path = v711 / "structural_validation.csv"
    hints_path = v711 / "korean_encoder_hints.csv"

    for required in (
        project,
        structural_path,
        hints_path,
    ):
        if not required.exists():
            raise FileNotFoundError(
                f"필수 입력이 없습니다: {required}"
            )

    output.mkdir(parents=True, exist_ok=True)

    print("[1/5] 구조 검증 6행과 교체 문구 상태 확인")

    structural_rows = read_csv(structural_path)
    hint_rows = read_csv(hints_path)

    print("[2/5] 과거 패치 보고서에서 인코더 검증 벡터 수집")

    known_vectors = discover_known_vectors(
        project,
        work_root,
        output,
    )

    print("[3/5] Python 함수·문자맵 인코더 후보 탐색")

    encoder_files = discover_encoder_files(
        project,
        hint_rows,
    )
    function_candidates: list[dict[str, Any]] = []
    map_candidates: list[dict[str, Any]] = []

    for path in encoder_files:
        functions, maps = inspect_python_file(path)
        function_candidates.extend(functions)
        map_candidates.extend(maps)

    requested_texts = {
        row.get("replacement_text", "").strip()
        for row in structural_rows
        if row.get("replacement_text", "").strip()
    }
    requested_texts.update(
        row["translation"]
        for row in known_vectors
        if row.get("translation", "").strip()
    )
    texts = sorted(requested_texts)

    produced: dict[
        str,
        dict[str, str],
    ] = defaultdict(dict)
    inventory_rows: list[dict[str, Any]] = []

    functions_by_file: dict[str, list[str]] = defaultdict(list)
    for candidate in function_candidates:
        functions_by_file[
            candidate["file"]
        ].append(candidate["function"])

    for file_name, function_names in functions_by_file.items():
        path = Path(file_name)
        module_results = run_module_functions(
            project,
            path,
            sorted(set(function_names)),
            texts,
        )

        for function_name in sorted(set(function_names)):
            encoder_id = f"function:{path}:{function_name}"
            results = module_results.get(function_name, {})

            if isinstance(results, dict):
                for text, encoded in results.items():
                    cleaned = clean_hex(encoded)
                    if cleaned:
                        produced[encoder_id][str(text)] = cleaned

            inventory_rows.append(
                {
                    "encoder_id": encoder_id,
                    "type": "python_function",
                    "file": str(path),
                    "symbol": function_name,
                    "result_count": len(produced[encoder_id]),
                }
            )

    for candidate in map_candidates:
        path = Path(candidate["file"])
        encoder_id = (
            f"literal_map:{path}:"
            f"{candidate['map_name']}"
        )
        mapping = candidate["literal_value"]

        for text in texts:
            encoded = encode_with_literal_map(text, mapping)
            if encoded:
                produced[encoder_id][text] = encoded

        inventory_rows.append(
            {
                "encoder_id": encoder_id,
                "type": "literal_character_map",
                "file": str(path),
                "symbol": candidate["map_name"],
                "result_count": len(produced[encoder_id]),
            }
        )

    write_csv(
        output / "encoder_inventory.csv",
        inventory_rows,
        [
            "encoder_id",
            "type",
            "file",
            "symbol",
            "result_count",
        ],
    )

    print("[4/5] 후보 인코더를 과거 교체 바이트와 대조")

    validation_rows: list[dict[str, Any]] = []
    validation_summary: dict[
        str,
        dict[str, int],
    ] = {}

    for encoder_id, results in produced.items():
        exact_matches = 0
        padded_matches = 0
        mismatches = 0
        attempted = 0

        for vector in known_vectors:
            text = vector["translation"]
            produced_hex = results.get(text, "")
            if not produced_hex:
                continue

            attempted += 1
            matched, method = vector_matches(
                produced_hex,
                vector["expected_hex"],
            )

            if matched:
                if method == "exact":
                    exact_matches += 1
                else:
                    padded_matches += 1
            else:
                mismatches += 1

            validation_rows.append(
                {
                    "encoder_id": encoder_id,
                    "translation": text,
                    "produced_hex": produced_hex,
                    "expected_hex": vector["expected_hex"],
                    "matched": matched,
                    "match_method": method,
                    "evidence_file": vector["evidence_file"],
                }
            )

        validation_summary[encoder_id] = {
            "attempted": attempted,
            "exact_matches": exact_matches,
            "padded_matches": padded_matches,
            "mismatches": mismatches,
        }

    write_csv(
        output / "encoder_vector_validation.csv",
        validation_rows,
        [
            "encoder_id",
            "translation",
            "produced_hex",
            "expected_hex",
            "matched",
            "match_method",
            "evidence_file",
        ],
    )

    validated_encoders: set[str] = set()
    for encoder_id, summary in validation_summary.items():
        matched_count = (
            summary["exact_matches"]
            + summary["padded_matches"]
        )
        if matched_count >= 2 and summary["mismatches"] == 0:
            validated_encoders.add(encoder_id)

    print("[5/5] 교체 바이트 재구성 및 Expected Write 승격 판정")

    replacement_rows: list[dict[str, Any]] = []
    ready_rows: list[dict[str, Any]] = []
    ui_translation_rows: list[dict[str, Any]] = []

    for row in structural_rows:
        replacement_text = row.get(
            "replacement_text",
            "",
        ).strip()
        source_status = row.get(
            "source_validation_status",
            "",
        )
        group_id = row.get("group_id", "")
        item_id = row.get("item_id", "")
        kind = row.get("kind", "")

        common = {
            "group_id": group_id,
            "kind": kind,
            "item_id": item_id,
            "target": row.get("resolved_target", ""),
            "offset_hex": row.get("offset_hex", ""),
            "source_text": row.get("source_text", ""),
            "source_hex": row.get("source_hex", ""),
            "replacement_text": replacement_text,
        }

        if not replacement_text:
            ui_translation_rows.append(
                {
                    "group_id": group_id,
                    "kind": kind,
                    "item_id": item_id,
                    "source_text": row.get(
                        "source_text",
                        "",
                    ),
                    "target": row.get(
                        "resolved_target",
                        row.get("target", ""),
                    ),
                    "offset_hex": row.get(
                        "offset_hex",
                        "",
                    ),
                    "status": "approved_korean_text_missing",
                    "next_action": (
                        "화면 문맥을 유지한 한국어 UI 문구 승인"
                    ),
                }
            )
            replacement_rows.append(
                {
                    **common,
                    "encoder_id": "",
                    "replacement_hex": "",
                    "replacement_byte_length": "",
                    "slot_capacity": row.get(
                        "slot_capacity_estimate",
                        "",
                    ),
                    "status": "blocked_missing_replacement_text",
                    "expected_write_confirmed": "no",
                }
            )
            continue

        validated_outputs: dict[
            str,
            list[str],
        ] = defaultdict(list)
        provisional_outputs: dict[
            str,
            list[str],
        ] = defaultdict(list)

        for encoder_id, results in produced.items():
            encoded = clean_hex(
                results.get(replacement_text, "")
            )
            if not encoded:
                continue

            if encoder_id in validated_encoders:
                validated_outputs[encoded].append(encoder_id)
            else:
                provisional_outputs[encoded].append(encoder_id)

        slot_capacity = None
        raw_capacity = row.get(
            "slot_capacity_estimate",
            "",
        )
        try:
            slot_capacity = int(str(raw_capacity))
        except ValueError:
            slot_capacity = None

        if len(validated_outputs) == 1:
            replacement_hex = next(iter(validated_outputs))
            encoder_ids = validated_outputs[replacement_hex]
            replacement_length = len(replacement_hex) // 2

            if source_status != "verified_unique_source_location":
                status = "blocked_source_not_unique"
            elif (
                slot_capacity is not None
                and replacement_length > slot_capacity
            ):
                status = "blocked_slot_overflow"
            elif replacement_hex == clean_hex(row.get("source_hex", "")):
                status = "blocked_no_actual_change"
            else:
                status = "expected_write_ready"

            result = {
                **common,
                "encoder_id": "|".join(sorted(encoder_ids)),
                "replacement_hex": replacement_hex,
                "replacement_byte_length": replacement_length,
                "slot_capacity": (
                    slot_capacity
                    if slot_capacity is not None
                    else ""
                ),
                "status": status,
                "expected_write_confirmed": (
                    "yes"
                    if status == "expected_write_ready"
                    else "no"
                ),
            }
            replacement_rows.append(result)

            if status == "expected_write_ready":
                ready_rows.append(result)

        elif len(validated_outputs) > 1:
            replacement_rows.append(
                {
                    **common,
                    "encoder_id": "|".join(
                        sorted(
                            encoder_id
                            for encoder_ids
                            in validated_outputs.values()
                            for encoder_id in encoder_ids
                        )
                    ),
                    "replacement_hex": "|".join(
                        sorted(validated_outputs)
                    ),
                    "replacement_byte_length": "",
                    "slot_capacity": (
                        slot_capacity
                        if slot_capacity is not None
                        else ""
                    ),
                    "status": "blocked_multiple_validated_byte_sequences",
                    "expected_write_confirmed": "no",
                }
            )

        elif len(provisional_outputs) == 1:
            replacement_hex = next(iter(provisional_outputs))
            replacement_rows.append(
                {
                    **common,
                    "encoder_id": "|".join(
                        sorted(
                            provisional_outputs[
                                replacement_hex
                            ]
                        )
                    ),
                    "replacement_hex": replacement_hex,
                    "replacement_byte_length": (
                        len(replacement_hex) // 2
                    ),
                    "slot_capacity": (
                        slot_capacity
                        if slot_capacity is not None
                        else ""
                    ),
                    "status": "provisional_encoder_not_vector_validated",
                    "expected_write_confirmed": "no",
                }
            )

        elif len(provisional_outputs) > 1:
            replacement_rows.append(
                {
                    **common,
                    "encoder_id": "",
                    "replacement_hex": "|".join(
                        sorted(provisional_outputs)
                    ),
                    "replacement_byte_length": "",
                    "slot_capacity": (
                        slot_capacity
                        if slot_capacity is not None
                        else ""
                    ),
                    "status": "blocked_multiple_unvalidated_byte_sequences",
                    "expected_write_confirmed": "no",
                }
            )

        else:
            replacement_rows.append(
                {
                    **common,
                    "encoder_id": "",
                    "replacement_hex": "",
                    "replacement_byte_length": "",
                    "slot_capacity": (
                        slot_capacity
                        if slot_capacity is not None
                        else ""
                    ),
                    "status": "blocked_no_encoder_output",
                    "expected_write_confirmed": "no",
                }
            )

    replacement_fields = [
        "group_id",
        "kind",
        "item_id",
        "target",
        "offset_hex",
        "source_text",
        "source_hex",
        "replacement_text",
        "encoder_id",
        "replacement_hex",
        "replacement_byte_length",
        "slot_capacity",
        "status",
        "expected_write_confirmed",
    ]

    write_csv(
        output / "replacement_byte_candidates.csv",
        replacement_rows,
        replacement_fields,
    )
    write_csv(
        output / "expected_write_ready.csv",
        ready_rows,
        replacement_fields,
    )
    write_csv(
        output / "ui_translation_required.csv",
        ui_translation_rows,
        [
            "group_id",
            "kind",
            "item_id",
            "source_text",
            "target",
            "offset_hex",
            "status",
            "next_action",
        ],
    )

    status_counts: dict[str, int] = defaultdict(int)
    for row in replacement_rows:
        status_counts[row["status"]] += 1

    write_json(
        output / "all_report.json",
        {
            "format": (
                "prinny1_v7_12_encoder_reconstruction_report_v1"
            ),
            "created_at": now(),
            "structural_rows": len(structural_rows),
            "known_vectors": len(known_vectors),
            "encoder_files": len(encoder_files),
            "function_candidates": len(function_candidates),
            "literal_map_candidates": len(map_candidates),
            "encoder_candidates_with_output": len(produced),
            "vector_validated_encoders": len(
                validated_encoders
            ),
            "replacement_rows": len(replacement_rows),
            "ui_translation_required": len(
                ui_translation_rows
            ),
            "expected_write_ready": len(ready_rows),
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
        f"과거 인코더 검증 벡터      : {len(known_vectors)}"
    )
    print(
        f"검사한 인코더 파일         : {len(encoder_files)}"
    )
    print(
        f"바이트 출력 인코더 후보    : {len(produced)}"
    )
    print(
        f"벡터 검증 통과 인코더      : {len(validated_encoders)}"
    )
    print(
        f"UI 한국어 문구 승인 필요   : {len(ui_translation_rows)}"
    )
    print(
        f"Expected Write 준비 완료  : {len(ready_rows)}"
    )
    print(
        f"교체 바이트 후보 CSV       : "
        f"{output / 'replacement_byte_candidates.csv'}"
    )
    print(
        f"Expected Write CSV        : "
        f"{output / 'expected_write_ready.csv'}"
    )
    print(
        f"UI 번역 필요 CSV          : "
        f"{output / 'ui_translation_required.csv'}"
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
