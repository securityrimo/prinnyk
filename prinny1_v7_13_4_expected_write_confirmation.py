#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_DEFAULT = Path.home() / "PrinnyReverseToolkit"
DRIVE_DEFAULT = Path("/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd")
ROOT_DEFAULT = DRIVE_DEFAULT / "PSP_Localization_Work"


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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_target(value: str) -> str:
    return (
        str(value or "")
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
                    "scope": "start_resource",
                }
            )

    for relative, scope in (
        (
            "PSP_GAME/SYSDIR/BOOT.BIN",
            "executable",
        ),
        (
            "PSP_GAME/SYSDIR/EBOOT.BIN",
            "executable",
        ),
        (
            "PSP_GAME/USRDIR/SCRIPT.DAT",
            "script_container",
        ),
        (
            "PSP_GAME/USRDIR/SYSTEM.DAT",
            "container",
        ),
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


def sanitize_relative(value: str) -> str:
    cleaned = (
        value.replace("\\", "/")
        .replace("../", "")
        .lstrip("/")
    )

    return re.sub(
        r"[^A-Za-z0-9._/\-]+",
        "_",
        cleaned,
    )


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
        "--v7133",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_3_outlier_quarantine"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_4_expected_write_confirmation"
        ),
    )
    parser.add_argument(
        "--run-directory",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "work/prinny1_v7_13_4_expected_write_confirmation"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    game_iso = arguments.game.expanduser().resolve()
    v7133 = arguments.v7133.expanduser().resolve()
    output = arguments.output.expanduser().resolve()
    run_directory = arguments.run_directory.expanduser().resolve()

    candidate_path = (
        v7133 / "final_payload_review_candidates.csv"
    )
    profile_path = (
        v7133 / "accepted_encoder_profile.json"
    )

    for required in (
        project,
        game_iso,
        candidate_path,
        profile_path,
    ):
        if not required.exists():
            raise FileNotFoundError(
                f"필수 입력이 없습니다: {required}"
            )

    output.mkdir(parents=True, exist_ok=True)
    run_directory.mkdir(parents=True, exist_ok=True)

    print("[1/5] 최종 페이로드 검토 후보와 인코더 프로필 확인")

    candidates = read_csv(candidate_path)
    encoder_profile = json.loads(
        profile_path.read_text(encoding="utf-8")
    )

    if not candidates:
        raise ValueError(
            "최종 페이로드 검토 후보가 없습니다."
        )

    if not encoder_profile.get("validated"):
        raise ValueError(
            "유효 문자맵이 검증되지 않았습니다."
        )

    print("[2/5] 원본 ISO를 새로 추출해 대상 자원 복원")

    targets = prepare_targets(
        game_iso,
        run_directory,
        output,
    )

    print("[3/5] 원본 슬롯·널 종료·패딩·교체 길이 최종 검증")

    dry_run_root = output / "dry_run_targets"
    shutil.rmtree(dry_run_root, ignore_errors=True)
    dry_run_root.mkdir(parents=True, exist_ok=True)

    result_rows: list[dict[str, Any]] = []
    confirmed_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        requested_target = candidate.get("target", "")
        target, resolution_method = resolve_target(
            requested_target,
            targets,
        )

        offset = parse_integer(
            candidate.get("offset_hex", "")
        )
        slot_capacity = parse_integer(
            candidate.get("slot_capacity", "")
        )
        source_hex = clean_hex(
            candidate.get("source_hex", "")
        )
        replacement_hex = clean_hex(
            candidate.get("replacement_hex", "")
        )
        terminator_hex = clean_hex(
            candidate.get("terminator_hex", "")
        )

        source_bytes = (
            bytes.fromhex(source_hex)
            if source_hex
            else b""
        )
        replacement_bytes = (
            bytes.fromhex(replacement_hex)
            if replacement_hex
            else b""
        )

        blockers: list[str] = []

        if target is None:
            blockers.append("target_resolution_failed")

        if offset is None:
            blockers.append("invalid_offset")

        if slot_capacity is None or slot_capacity <= 0:
            blockers.append("invalid_slot_capacity")

        if not source_bytes:
            blockers.append("missing_source_bytes")

        if not replacement_bytes:
            blockers.append("missing_replacement_bytes")

        if terminator_hex != "00":
            blockers.append("terminator_not_zero")

        if not as_bool(
            candidate.get("accepted_map_validated")
        ):
            blockers.append("encoder_profile_not_validated")

        if not as_bool(candidate.get("source_unique")):
            blockers.append("source_not_unique")

        if not as_bool(candidate.get("original_match")):
            blockers.append("prior_original_match_failed")

        if not as_bool(candidate.get("exact_boundary")):
            blockers.append("prior_boundary_check_failed")

        if blockers:
            result_rows.append(
                {
                    **candidate,
                    "resolved_target": (
                        target["logical"] if target else ""
                    ),
                    "resolution_method": resolution_method,
                    "expected_before_hex": "",
                    "actual_before_hex": "",
                    "write_after_hex": "",
                    "file_size_before": "",
                    "file_size_after": "",
                    "file_sha256_before": "",
                    "file_sha256_after": "",
                    "changed_byte_count": "",
                    "changed_outside_slot": "",
                    "dry_run_target": "",
                    "status": "blocked",
                    "block_reasons": "|".join(blockers),
                    "expected_write_confirmed": "no",
                }
            )
            continue

        assert target is not None
        assert offset is not None
        assert slot_capacity is not None

        original_data = target["path"].read_bytes()
        source_length = len(source_bytes)
        replacement_length = len(replacement_bytes)

        if offset < 0:
            blockers.append("negative_offset")

        if offset + slot_capacity > len(original_data):
            blockers.append("slot_out_of_range")

        if replacement_length + 1 > slot_capacity:
            blockers.append("replacement_plus_null_overflow")

        actual_source = original_data[
            offset:offset + source_length
        ]

        if actual_source != source_bytes:
            blockers.append("fresh_source_bytes_mismatch")

        slot_before = original_data[
            offset:offset + slot_capacity
        ]
        expected_before = (
            source_bytes
            + b"\x00" * (
                slot_capacity - source_length
            )
        )

        if slot_before != expected_before:
            blockers.append(
                "fresh_slot_not_source_plus_zero_padding"
            )

        if (
            offset + source_length >= len(original_data)
            or original_data[offset + source_length] != 0
        ):
            blockers.append("fresh_null_terminator_missing")

        write_after = (
            replacement_bytes
            + b"\x00"
            + b"\x00" * (
                slot_capacity
                - replacement_length
                - 1
            )
        )

        if len(write_after) != slot_capacity:
            blockers.append("write_payload_size_mismatch")

        if blockers:
            result_rows.append(
                {
                    **candidate,
                    "resolved_target": target["logical"],
                    "resolution_method": resolution_method,
                    "expected_before_hex": (
                        expected_before.hex().upper()
                    ),
                    "actual_before_hex": (
                        slot_before.hex().upper()
                    ),
                    "write_after_hex": (
                        write_after.hex().upper()
                        if len(write_after) == slot_capacity
                        else ""
                    ),
                    "file_size_before": len(original_data),
                    "file_size_after": "",
                    "file_sha256_before": sha256_bytes(
                        original_data
                    ),
                    "file_sha256_after": "",
                    "changed_byte_count": "",
                    "changed_outside_slot": "",
                    "dry_run_target": "",
                    "status": "blocked",
                    "block_reasons": "|".join(blockers),
                    "expected_write_confirmed": "no",
                }
            )
            continue

        patched_data = bytearray(original_data)
        patched_data[
            offset:offset + slot_capacity
        ] = write_after
        patched_bytes = bytes(patched_data)

        changed_positions = [
            index
            for index, (
                before_byte,
                after_byte,
            ) in enumerate(
                zip(original_data, patched_bytes)
            )
            if before_byte != after_byte
        ]

        changed_outside_slot = [
            index
            for index in changed_positions
            if not (
                offset
                <= index
                < offset + slot_capacity
            )
        ]

        if len(patched_bytes) != len(original_data):
            blockers.append("file_size_changed")

        if changed_outside_slot:
            blockers.append("change_outside_allowed_slot")

        if patched_bytes[
            offset:offset + slot_capacity
        ] != write_after:
            blockers.append("dry_run_write_verification_failed")

        relative_target = sanitize_relative(
            target["logical"]
        )
        dry_run_path = (
            dry_run_root
            / f"{relative_target}.patched.bin"
        )
        dry_run_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        dry_run_path.write_bytes(patched_bytes)

        status = (
            "expected_write_confirmed"
            if not blockers
            else "blocked"
        )

        result = {
            **candidate,
            "resolved_target": target["logical"],
            "resolution_method": resolution_method,
            "expected_before_hex": (
                expected_before.hex().upper()
            ),
            "actual_before_hex": (
                slot_before.hex().upper()
            ),
            "write_after_hex": (
                write_after.hex().upper()
            ),
            "file_size_before": len(original_data),
            "file_size_after": len(patched_bytes),
            "file_sha256_before": sha256_bytes(
                original_data
            ),
            "file_sha256_after": sha256_bytes(
                patched_bytes
            ),
            "changed_byte_count": len(
                changed_positions
            ),
            "changed_outside_slot": len(
                changed_outside_slot
            ),
            "dry_run_target": str(dry_run_path),
            "status": status,
            "block_reasons": "|".join(blockers),
            "expected_write_confirmed": (
                "yes"
                if status == "expected_write_confirmed"
                else "no"
            ),
        }
        result_rows.append(result)

        if status == "expected_write_confirmed":
            confirmed_rows.append(result)

    print("[4/5] 드라이런 대상 파일 생성·허용 범위 밖 변경 검사")

    fields = list(result_rows[0].keys())

    write_csv(
        output / "expected_write_final_validation.csv",
        result_rows,
        fields,
    )
    write_csv(
        output / "expected_write_confirmed.csv",
        confirmed_rows,
        fields,
    )

    patch_plan_rows: list[dict[str, Any]] = []

    for row in confirmed_rows:
        patch_plan_rows.append(
            {
                "group_id": row.get("group_id", ""),
                "target": row.get("resolved_target", ""),
                "offset_hex": row.get("offset_hex", ""),
                "slot_capacity": row.get(
                    "slot_capacity",
                    "",
                ),
                "expected_before_hex": row.get(
                    "expected_before_hex",
                    "",
                ),
                "write_after_hex": row.get(
                    "write_after_hex",
                    "",
                ),
                "source_text": row.get(
                    "source_text",
                    "",
                ),
                "replacement_text": row.get(
                    "replacement_text",
                    "",
                ),
                "file_sha256_before": row.get(
                    "file_sha256_before",
                    "",
                ),
                "dry_run_file_sha256": row.get(
                    "file_sha256_after",
                    "",
                ),
            }
        )

    write_csv(
        output / "confirmed_patch_plan.csv",
        patch_plan_rows,
        [
            "group_id",
            "target",
            "offset_hex",
            "slot_capacity",
            "expected_before_hex",
            "write_after_hex",
            "source_text",
            "replacement_text",
            "file_sha256_before",
            "dry_run_file_sha256",
        ],
    )

    print("[5/5] Expected Write 확정 보고서 저장")

    blocked_count = len(result_rows) - len(confirmed_rows)

    write_json(
        output / "all_report.json",
        {
            "format": (
                "prinny1_v7_13_4_expected_write_confirmation_report_v1"
            ),
            "created_at": now(),
            "input_candidates": len(candidates),
            "expected_write_confirmed": len(
                confirmed_rows
            ),
            "blocked_candidates": blocked_count,
            "dry_run_targets_created": len(
                confirmed_rows
            ),
            "fresh_iso_extraction": True,
            "fresh_original_byte_check": True,
            "slot_zero_padding_check": True,
            "null_termination_check": True,
            "file_size_invariance_check": True,
            "outside_slot_change_check": True,
            "patch_applied_to_iso": False,
            "iso_created": False,
            "translation_wording_changed": False,
            "character_voice_changed": False,
            "outputs": {
                "final_validation": str(
                    output
                    / "expected_write_final_validation.csv"
                ),
                "confirmed_writes": str(
                    output
                    / "expected_write_confirmed.csv"
                ),
                "patch_plan": str(
                    output / "confirmed_patch_plan.csv"
                ),
                "dry_run_targets": str(
                    dry_run_root
                ),
            },
            "status": (
                "pass"
                if confirmed_rows
                else "blocked"
            ),
        },
    )

    shutil.rmtree(
        run_directory,
        ignore_errors=True,
    )

    print()
    print("완료")
    print(
        f"입력 최종 검토 후보       : {len(candidates)}"
    )
    print(
        f"Expected Write 확정      : {len(confirmed_rows)}"
    )
    print(
        f"차단 후보                 : {blocked_count}"
    )
    print(
        f"드라이런 대상 파일        : {len(confirmed_rows)}"
    )

    if result_rows and blocked_count:
        reasons: dict[str, int] = {}

        for row in result_rows:
            for reason in str(
                row.get("block_reasons", "")
            ).split("|"):
                if reason:
                    reasons[reason] = (
                        reasons.get(reason, 0) + 1
                    )

        if reasons:
            print(
                "차단 사유                 : "
                + ", ".join(
                    f"{key}={value}"
                    for key, value
                    in sorted(reasons.items())
                )
            )

    print(
        f"최종 검증 CSV             : "
        f"{output / 'expected_write_final_validation.csv'}"
    )
    print(
        f"확정 Expected Write CSV  : "
        f"{output / 'expected_write_confirmed.csv'}"
    )
    print(
        f"확정 패치 계획 CSV        : "
        f"{output / 'confirmed_patch_plan.csv'}"
    )
    print(
        f"드라이런 대상 폴더        : "
        f"{dry_run_root}"
    )
    print(
        f"보고서 JSON               : "
        f"{output / 'all_report.json'}"
    )
    print("ISO 생성                  : 없음")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
