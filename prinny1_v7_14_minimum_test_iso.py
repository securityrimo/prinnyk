#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

PROJECT_DEFAULT = Path.home() / "PrinnyReverseToolkit"
DRIVE_DEFAULT = Path("/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd")
ROOT_DEFAULT = DRIVE_DEFAULT / "PSP_Localization_Work"
SECTOR_SIZE = 2048


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def hash_range(
    path: Path,
    start: int,
    end: int,
) -> str:
    if start < 0 or end < start:
        raise ValueError(
            f"잘못된 해시 범위: {start}..{end}"
        )

    digest = hashlib.sha256()
    remaining = end - start

    with path.open("rb") as handle:
        handle.seek(start)

        while remaining:
            block = handle.read(
                min(1024 * 1024, remaining)
            )

            if not block:
                raise EOFError(
                    "범위 해시 중 예상보다 일찍 EOF에 도달했습니다."
                )

            digest.update(block)
            remaining -= len(block)

    return digest.hexdigest()


def normalized_iso_name(name: str) -> str:
    return name.split(";", 1)[0].rstrip(".").casefold()


def parse_directory_record(record: bytes) -> dict[str, Any]:
    if len(record) < 34:
        raise ValueError("ISO 디렉터리 레코드가 너무 짧습니다.")

    record_length = record[0]

    if record_length != len(record):
        raise ValueError("ISO 디렉터리 레코드 길이가 맞지 않습니다.")

    extent_lba = int.from_bytes(
        record[2:6],
        "little",
    )
    data_length = int.from_bytes(
        record[10:14],
        "little",
    )
    flags = record[25]
    name_length = record[32]
    name_bytes = record[33:33 + name_length]

    if name_bytes == b"\x00":
        name = "."
    elif name_bytes == b"\x01":
        name = ".."
    else:
        name = name_bytes.decode(
            "ascii",
            errors="replace",
        )

    return {
        "name": name,
        "extent_lba": extent_lba,
        "data_length": data_length,
        "flags": flags,
        "is_directory": bool(flags & 0x02),
        "is_multi_extent": bool(flags & 0x80),
    }


def read_primary_volume_descriptor(
    handle: BinaryIO,
) -> bytes:
    for sector in range(16, 65):
        handle.seek(sector * SECTOR_SIZE)
        descriptor = handle.read(SECTOR_SIZE)

        if len(descriptor) != SECTOR_SIZE:
            break

        descriptor_type = descriptor[0]
        identifier = descriptor[1:6]
        version = descriptor[6]

        if (
            descriptor_type == 1
            and identifier == b"CD001"
            and version == 1
        ):
            return descriptor

        if descriptor_type == 255:
            break

    raise ValueError(
        "ISO9660 Primary Volume Descriptor를 찾지 못했습니다."
    )


def read_directory_entries(
    handle: BinaryIO,
    extent_lba: int,
    data_length: int,
) -> list[dict[str, Any]]:
    handle.seek(extent_lba * SECTOR_SIZE)
    data = handle.read(data_length)

    if len(data) != data_length:
        raise EOFError(
            "ISO 디렉터리 데이터를 전부 읽지 못했습니다."
        )

    entries: list[dict[str, Any]] = []
    offset = 0

    while offset < len(data):
        record_length = data[offset]

        if record_length == 0:
            offset = (
                ((offset // SECTOR_SIZE) + 1)
                * SECTOR_SIZE
            )
            continue

        end = offset + record_length

        if end > len(data):
            raise ValueError(
                "ISO 디렉터리 레코드가 데이터 범위를 벗어났습니다."
            )

        entry = parse_directory_record(
            data[offset:end]
        )

        if entry["name"] not in {".", ".."}:
            entries.append(entry)

        offset = end

    return entries


def find_iso_file(
    iso_path: Path,
    path_parts: list[str],
) -> dict[str, Any]:
    with iso_path.open("rb") as handle:
        descriptor = read_primary_volume_descriptor(
            handle
        )

        root_length = descriptor[156]

        if root_length == 0:
            raise ValueError(
                "ISO 루트 디렉터리 레코드가 없습니다."
            )

        root = parse_directory_record(
            descriptor[156:156 + root_length]
        )
        current = root

        for index, wanted in enumerate(path_parts):
            entries = read_directory_entries(
                handle,
                int(current["extent_lba"]),
                int(current["data_length"]),
            )
            wanted_normalized = normalized_iso_name(
                wanted
            )
            matches = [
                entry
                for entry in entries
                if normalized_iso_name(
                    str(entry["name"])
                ) == wanted_normalized
            ]

            if len(matches) != 1:
                raise ValueError(
                    f"ISO 경로를 하나로 확정하지 못했습니다: "
                    f"{'/'.join(path_parts[:index + 1])} "
                    f"(matches={len(matches)})"
                )

            current = matches[0]

            if current["is_multi_extent"]:
                raise ValueError(
                    "다중 extent ISO 파일은 자동 처리하지 않습니다."
                )

            if (
                index < len(path_parts) - 1
                and not current["is_directory"]
            ):
                raise ValueError(
                    f"ISO 경로 중간 항목이 디렉터리가 아닙니다: "
                    f"{wanted}"
                )

        if current["is_directory"]:
            raise ValueError(
                "요청한 ISO 경로가 파일이 아니라 디렉터리입니다."
            )

        return current


def read_iso_file(
    iso_path: Path,
    entry: dict[str, Any],
) -> bytes:
    offset = int(entry["extent_lba"]) * SECTOR_SIZE
    size = int(entry["data_length"])

    with iso_path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(size)

    if len(data) != size:
        raise EOFError(
            "ISO 내부 파일을 전부 읽지 못했습니다."
        )

    return data


def choose_base_iso(
    explicit: Path | None,
    project: Path,
    work_root: Path,
) -> tuple[Path, str]:
    if explicit is not None:
        path = explicit.expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(
                f"지정한 기준 ISO가 없습니다: {path}"
            )

        return path, "explicit"

    trusted = [
        (
            work_root
            / "build/prinny_stage1_hotfix_v6_2"
            / "prinny_korean_stage1_hotfix_v6_2_977.iso",
            "v6.2_user_tested",
        ),
        (
            project
            / "workspace/build"
            / "prinny_korean_galmuri14_v5_977.iso",
            "v5_korean_font_base",
        ),
        (
            project
            / "workspace/build"
            / "prinny_korean_v4_977.iso",
            "v4_translation_base",
        ),
    ]

    for path, label in trusted:
        if path.is_file():
            return path.resolve(), label

    found = []

    for root in (
        work_root / "build",
        project / "workspace/build",
    ):
        if not root.is_dir():
            continue

        for path in root.rglob("*.iso"):
            lowered = path.name.casefold()

            if "v6_4" in lowered or "v6_3" in lowered:
                continue

            if (
                "v6_2" in lowered
                or "galmuri14_v5" in lowered
                or "korean_v4" in lowered
            ):
                found.append(path)

    if len(found) == 1:
        return found[0].resolve(), "discovered_trusted_pattern"

    raise FileNotFoundError(
        "검증된 한글 기준 ISO를 찾지 못했습니다. "
        "V6.2, Galmuri14 V5 또는 V4 ISO가 필요합니다. "
        "원본 game.iso로는 자동 빌드하지 않습니다."
    )


def resolve_start_record(
    archive: Any,
    target_name: str,
) -> Any:
    normalized = Path(
        target_name.replace("\\", "/")
    ).name.casefold()
    matches = [
        record
        for record in archive.records
        if (
            str(record.name).casefold() == normalized
            or str(record.output_name).casefold()
            == normalized
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            f"START 자원을 하나로 확정하지 못했습니다: "
            f"{target_name} (matches={len(matches)})"
        )

    return matches[0]


def changed_ranges(
    before: bytes,
    after: bytes,
) -> list[tuple[int, int]]:
    if len(before) != len(after):
        raise ValueError(
            "변경 범위 계산에는 같은 길이의 데이터가 필요합니다."
        )

    ranges: list[tuple[int, int]] = []
    start: int | None = None

    for index, (old, new) in enumerate(
        zip(before, after)
    ):
        if old != new and start is None:
            start = index
        elif old == new and start is not None:
            ranges.append((start, index))
            start = None

    if start is not None:
        ranges.append((start, len(before)))

    return ranges


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
        "--base-iso",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--v7134",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_4_expected_write_confirmation"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "build/prinny1_v7_14_minimum_test"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_14_minimum_test"
        ),
    )
    parser.add_argument(
        "--output-name",
        default="prinny_korean_v7_14_minimum_expected_write_1.iso",
    )
    parser.add_argument(
        "--allow-iso-build",
        action="store_true",
        help=(
            "기준 슬롯이 원본 Expected Write와 일치할 때만 "
            "새 테스트 ISO 생성을 허용합니다."
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    v7134 = arguments.v7134.expanduser().resolve()
    output = arguments.output.expanduser().resolve()
    report_directory = arguments.report.expanduser().resolve()

    confirmed_path = (
        v7134 / "expected_write_confirmed.csv"
    )
    patch_plan_path = (
        v7134 / "confirmed_patch_plan.csv"
    )

    for required in (
        project,
        confirmed_path,
        patch_plan_path,
    ):
        if not required.exists():
            raise FileNotFoundError(
                f"필수 입력이 없습니다: {required}"
            )

    report_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("[1/6] 확정 Expected Write와 검증된 한글 기준 ISO 확인")

    confirmed = read_csv(confirmed_path)
    patch_plan = read_csv(patch_plan_path)

    if not confirmed or len(confirmed) != len(patch_plan):
        raise ValueError(
            "확정 Expected Write와 패치 계획 수가 맞지 않습니다: "
            f"confirmed={len(confirmed)}, "
            f"plan={len(patch_plan)}"
        )

    base_iso, base_label = choose_base_iso(
        arguments.base_iso,
        project,
        work_root,
    )
    if Path(arguments.output_name).name != arguments.output_name:
        raise ValueError("출력 ISO 이름에는 경로를 넣을 수 없습니다.")
    if not arguments.output_name.lower().endswith(".iso"):
        raise ValueError("출력 파일 확장자는 .iso여야 합니다.")
    output_iso = output / arguments.output_name

    if output_iso.resolve() == base_iso.resolve():
        raise ValueError(
            "출력 ISO가 기준 ISO와 같은 경로입니다."
        )

    print("[2/6] 기준 ISO에서 SYSTEM.DAT·START.DAT 직접 복원")

    from core.lzs import decompress_buffer
    import core.font_builder as builder
    from core.start_runtime import StartRuntimeArchive

    system_entry = find_iso_file(
        base_iso,
        [
            "PSP_GAME",
            "USRDIR",
            "SYSTEM.DAT",
        ],
    )
    system_offset = (
        int(system_entry["extent_lba"])
        * SECTOR_SIZE
    )
    original_system = read_iso_file(
        base_iso,
        system_entry,
    )

    start_entry = builder.parse_nispack_start_entry(
        original_system
    )
    entry_offset = int(
        start_entry["entry_offset"]
    )
    lzs_offset = int(
        start_entry["data_offset"]
    )
    old_lzs_size = int(
        start_entry["size"]
    )
    old_lzs = original_system[
        lzs_offset:lzs_offset + old_lzs_size
    ]
    original_start, old_lzs_header = (
        decompress_buffer(old_lzs)
    )

    archive = StartRuntimeArchive.from_bytes(
        original_start,
        source=f"{base_iso}!/start.dat",
    )

    print(
        "[3/6] 기준 ISO의 확정 슬롯을 다시 검사하고 "
        f"{len(patch_plan)}개 적용"
    )

    write_specs: list[dict[str, Any]] = []
    preflight_rows: list[dict[str, Any]] = []

    for plan in patch_plan:
        target_name = plan.get("target", "")
        resource_offset = parse_integer(plan.get("offset_hex", ""))
        expected_before_hex = clean_hex(
            plan.get("expected_before_hex", "")
        )
        write_after_hex = clean_hex(plan.get("write_after_hex", ""))

        if resource_offset is None:
            raise ValueError("패치 오프셋이 잘못됐습니다.")
        if not expected_before_hex or not write_after_hex:
            raise ValueError(
                "확정 패치 계획의 before/after 바이트가 없습니다."
            )

        expected_before = bytes.fromhex(expected_before_hex)
        write_after = bytes.fromhex(write_after_hex)
        if len(expected_before) != len(write_after):
            raise ValueError("확정 쓰기 전후 길이가 다릅니다.")

        record = resolve_start_record(archive, target_name)
        absolute_offset = int(record.data_offset) + resource_offset
        absolute_end = absolute_offset + len(expected_before)
        if absolute_end > int(record.end_offset):
            raise ValueError(
                "확정 쓰기 범위가 START 자원 경계를 벗어납니다."
            )

        actual_before = original_start[absolute_offset:absolute_end]
        if actual_before == write_after:
            row_status = "already_applied_exact_bytes"
        elif actual_before == expected_before:
            row_status = "original_slot_compatible"
        else:
            row_status = "existing_translation_conflicts_with_candidate"

        write_specs.append(
            {
                "target_name": target_name,
                "record": record,
                "resource_offset": resource_offset,
                "absolute_offset": absolute_offset,
                "absolute_end": absolute_end,
                "expected_before": expected_before,
                "write_after": write_after,
                "actual_before": actual_before,
                "status": row_status,
            }
        )
        preflight_rows.append(
            {
                "base_iso": str(base_iso),
                "base_label": base_label,
                "target_resource": str(record.output_name),
                "resource_offset_hex": f"0x{resource_offset:X}",
                "slot_size": len(expected_before),
                "expected_before_hex": expected_before.hex().upper(),
                "actual_before_hex": actual_before.hex().upper(),
                "write_after_hex": write_after.hex().upper(),
                "compatibility_status": row_status,
                "iso_build_authorized": bool(arguments.allow_iso_build),
                "iso_created": False,
            }
        )

    sorted_ranges = sorted(
        (spec["absolute_offset"], spec["absolute_end"])
        for spec in write_specs
    )
    for previous, current in zip(sorted_ranges, sorted_ranges[1:]):
        if previous[1] > current[0]:
            raise ValueError("확정 Expected Write 범위가 겹칩니다.")

    statuses = {spec["status"] for spec in write_specs}
    if statuses == {"already_applied_exact_bytes"}:
        compatibility_status = "already_applied_exact_bytes"
        next_action = "기준 ISO에 모든 목표 바이트가 이미 있습니다."
    elif statuses == {"original_slot_compatible"}:
        compatibility_status = "original_slot_compatible"
        next_action = (
            "모든 Expected Write가 적용 가능하며 새 ISO 생성에는 "
            "--allow-iso-build가 필요합니다."
        )
    else:
        compatibility_status = "existing_translation_conflicts_with_candidate"
        next_action = "하나 이상의 현재 슬롯이 확정 before 바이트와 다릅니다."

    preflight_row = {
        "base_iso": str(base_iso),
        "base_label": base_label,
        "expected_write_count": len(write_specs),
        "compatibility_status": compatibility_status,
        "iso_build_authorized": bool(arguments.allow_iso_build),
        "iso_created": False,
        "next_action": next_action,
    }

    write_csv(
        report_directory / "base_preflight.csv",
        preflight_rows,
        list(preflight_rows[0].keys()),
    )

    if compatibility_status != "original_slot_compatible":
        write_json(
            report_directory / "all_report.json",
            {
                "format": (
                    "prinny1_v7_14_minimum_test_preflight_v1"
                ),
                "created_at": now(),
                **preflight_row,
                "status": compatibility_status,
            },
        )
        print()
        print("기준 슬롯 사전판정 완료")
        print(f"호환성 판정             : {compatibility_status}")
        print(f"다음 처리               : {next_action}")
        print("ISO 생성                : 없음")
        return (
            0
            if compatibility_status
            == "already_applied_exact_bytes"
            else 2
        )

    if not arguments.allow_iso_build:
        write_json(
            report_directory / "all_report.json",
            {
                "format": (
                    "prinny1_v7_14_minimum_test_preflight_v1"
                ),
                "created_at": now(),
                **preflight_row,
                "status": (
                    "iso_build_approval_required"
                ),
            },
        )
        print()
        print("기준 슬롯 사전판정 완료")
        print(f"호환성 판정             : {compatibility_status}")
        print(f"다음 처리               : {next_action}")
        print("ISO 생성                : 승인 대기")
        return 0

    output.mkdir(parents=True, exist_ok=True)

    patched_start_data = bytearray(original_start)
    for spec in write_specs:
        patched_start_data[
            spec["absolute_offset"]:spec["absolute_end"]
        ] = spec["write_after"]
    patched_start = bytes(patched_start_data)

    if len(patched_start) != len(original_start):
        raise ValueError(
            "START.DAT 크기가 변경됐습니다."
        )

    start_change_ranges = changed_ranges(
        original_start,
        patched_start,
    )

    if not start_change_ranges:
        raise ValueError(
            "실제 변경 바이트가 없습니다."
        )

    for start, end in start_change_ranges:
        if not any(
            spec["absolute_offset"] <= start
            and end <= spec["absolute_end"]
            for spec in write_specs
        ):
            raise ValueError(
                "확정 슬롯 밖 START 변경이 감지됐습니다."
            )

    changed_resources = []

    for current_record in archive.records:
        before_blob = original_start[
            current_record.data_offset:
            current_record.end_offset
        ]
        after_blob = patched_start[
            current_record.data_offset:
            current_record.end_offset
        ]

        if before_blob != after_blob:
            changed_resources.append(
                str(current_record.output_name)
            )

    expected_changed_resources = sorted(
        {
            str(spec["record"].output_name)
            for spec in write_specs
        }
    )
    if sorted(changed_resources) != expected_changed_resources:
        raise ValueError(
            "대상 외 START 자원이 변경됐습니다: "
            + ", ".join(changed_resources)
        )

    patched_start_path = output / "start.dat"
    patched_start_path.write_bytes(
        patched_start
    )
    verified_archive = StartRuntimeArchive.load(
        patched_start_path
    )

    if len(verified_archive.records) != len(
        archive.records
    ):
        raise ValueError(
            "패치 후 START 자원 수가 변경됐습니다."
        )

    print("[4/6] START.LZS·SYSTEM.DAT 고정 크기 재패킹")

    extension = old_lzs[0:4]
    original_flag = int.from_bytes(
        old_lzs[0x0C:0x10],
        "little",
    ) & 0xFF
    flag_candidates = [original_flag] + sorted(
        (
            value
            for value in range(256)
            if value != original_flag
        ),
        key=lambda value: patched_start.count(value),
    )
    new_lzs = b""
    selected_flag = original_flag
    compression_mode = "literal"

    for candidate_flag in flag_candidates:
        candidate_lzs = builder.build_literal_lzs(
            patched_start,
            extension,
            candidate_flag,
        )
        if len(candidate_lzs) <= old_lzs_size:
            new_lzs = candidate_lzs
            selected_flag = candidate_flag
            break

    if not new_lzs:
        from core.lzs import compress_buffer, parse_header

        candidate_lzs = compress_buffer(patched_start, extension)
        candidate_header = parse_header(candidate_lzs)
        if len(candidate_lzs) <= old_lzs_size:
            new_lzs = candidate_lzs
            selected_flag = int(candidate_header["flag"])
            compression_mode = "greedy_backreference"

    if not new_lzs:
        raise ValueError(
            "literal 및 역참조 LZS가 모두 고정 영역을 초과합니다."
        )

    decoded_start, _decoded_header = (
        decompress_buffer(new_lzs)
    )

    if decoded_start != patched_start:
        raise ValueError(
            "새 START.LZS 왕복 검증에 실패했습니다."
        )

    patched_system_data = bytearray(
        original_system
    )
    patched_system_data[
        lzs_offset:lzs_offset + old_lzs_size
    ] = (
        new_lzs
        + b"\x00" * (
            old_lzs_size - len(new_lzs)
        )
    )
    struct.pack_into(
        "<I",
        patched_system_data,
        entry_offset + 0x24,
        len(new_lzs),
    )
    patched_system = bytes(
        patched_system_data
    )

    if len(patched_system) != len(
        original_system
    ):
        raise ValueError(
            "SYSTEM.DAT 크기가 변경됐습니다."
        )

    verified_start_entry = (
        builder.parse_nispack_start_entry(
            patched_system
        )
    )
    verified_lzs_offset = int(
        verified_start_entry["data_offset"]
    )
    verified_lzs_size = int(
        verified_start_entry["size"]
    )

    if verified_lzs_offset != lzs_offset:
        raise ValueError(
            "START.LZS 오프셋이 변경됐습니다."
        )

    verified_start, _ = decompress_buffer(
        patched_system[
            verified_lzs_offset:
            verified_lzs_offset + verified_lzs_size
        ]
    )

    if verified_start != patched_start:
        raise ValueError(
            "재패킹 SYSTEM.DAT 내부 START 검증에 실패했습니다."
        )

    allowed_system_ranges = [
        (
            entry_offset + 0x24,
            entry_offset + 0x28,
        ),
        (
            lzs_offset,
            lzs_offset + old_lzs_size,
        ),
    ]
    unexpected_system_changes = 0

    for index, (before, after) in enumerate(
        zip(original_system, patched_system)
    ):
        if before == after:
            continue

        if not any(
            start <= index < end
            for start, end
            in allowed_system_ranges
        ):
            unexpected_system_changes += 1

    if unexpected_system_changes:
        raise ValueError(
            "SYSTEM.DAT 보호 영역 변경이 감지됐습니다: "
            f"{unexpected_system_changes}"
        )

    (output / "start.lzs").write_bytes(
        new_lzs
    )
    (output / "SYSTEM.DAT").write_bytes(
        patched_system
    )

    print("[5/6] 기준 ISO 복사·SYSTEM.DAT 동일 영역 주입·무결성 검사")

    iso_size = base_iso.stat().st_size
    system_end = (
        system_offset + len(original_system)
    )

    if system_end > iso_size:
        raise ValueError(
            "ISO의 SYSTEM.DAT 영역이 파일 범위를 벗어납니다."
        )

    embedded_system = read_iso_file(
        base_iso,
        system_entry,
    )

    if embedded_system != original_system:
        raise ValueError(
            "기준 ISO 내부 SYSTEM.DAT 재검증에 실패했습니다."
        )

    temporary_output = output_iso.with_suffix(
        ".iso.tmp"
    )

    if temporary_output.exists():
        temporary_output.unlink()

    with base_iso.open("rb") as source:
        with temporary_output.open("wb") as target:
            shutil.copyfileobj(
                source,
                target,
                1024 * 1024,
            )

    with temporary_output.open("r+b") as target:
        target.seek(system_offset)
        target.write(patched_system)
        target.flush()
        os.fsync(target.fileno())

    if temporary_output.stat().st_size != iso_size:
        raise ValueError(
            "출력 ISO 크기가 변경됐습니다."
        )

    with temporary_output.open("rb") as handle:
        handle.seek(system_offset)
        verified_system = handle.read(
            len(patched_system)
        )

    if verified_system != patched_system:
        raise ValueError(
            "출력 ISO 내부 SYSTEM.DAT 검증에 실패했습니다."
        )

    if hash_range(
        base_iso,
        0,
        system_offset,
    ) != hash_range(
        temporary_output,
        0,
        system_offset,
    ):
        raise ValueError(
            "ISO의 SYSTEM.DAT 이전 영역이 변경됐습니다."
        )

    if hash_range(
        base_iso,
        system_end,
        iso_size,
    ) != hash_range(
        temporary_output,
        system_end,
        iso_size,
    ):
        raise ValueError(
            "ISO의 SYSTEM.DAT 이후 영역이 변경됐습니다."
        )

    archive_test = subprocess.run(
        [
            "7z",
            "t",
            str(temporary_output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if archive_test.returncode != 0:
        raise RuntimeError(
            "7z ISO 검사 실패:\n"
            + archive_test.stdout[-2000:]
            + archive_test.stderr[-2000:]
        )

    os.replace(
        temporary_output,
        output_iso,
    )

    print("[6/6] ISO 내부 패치 재추출 검증·테스트 보고서 저장")

    output_system_entry = find_iso_file(
        output_iso,
        [
            "PSP_GAME",
            "USRDIR",
            "SYSTEM.DAT",
        ],
    )
    output_embedded_system = read_iso_file(
        output_iso,
        output_system_entry,
    )

    if output_embedded_system != patched_system:
        raise ValueError(
            "완성 ISO에서 SYSTEM.DAT 재추출 검증에 실패했습니다."
        )

    output_start_entry = (
        builder.parse_nispack_start_entry(
            output_embedded_system
        )
    )
    output_lzs_offset = int(
        output_start_entry["data_offset"]
    )
    output_lzs_size = int(
        output_start_entry["size"]
    )
    output_start, _ = decompress_buffer(
        output_embedded_system[
            output_lzs_offset:
            output_lzs_offset + output_lzs_size
        ]
    )

    if output_start != patched_start:
        raise ValueError(
            "완성 ISO에서 START.DAT 재추출 검증에 실패했습니다."
        )

    for spec in write_specs:
        final_slot = output_start[
            spec["absolute_offset"]:spec["absolute_end"]
        ]
        if final_slot != spec["write_after"]:
            raise ValueError(
                "완성 ISO의 최종 패치 슬롯이 예상과 다릅니다: "
                f"{spec['target_name']}+0x{spec['resource_offset']:X}"
            )

    result_row = {
        "base_iso": str(base_iso),
        "base_label": base_label,
        "base_iso_sha256": sha256_file(base_iso),
        "output_iso": str(output_iso),
        "output_iso_sha256": sha256_file(
            output_iso
        ),
        "iso_size": iso_size,
        "system_lba": int(
            system_entry["extent_lba"]
        ),
        "system_offset_hex": (
            f"0x{system_offset:X}"
        ),
        "system_size": len(original_system),
        "target_resource": "|".join(expected_changed_resources),
        "resource_offset_hex": "|".join(
            f"0x{spec['resource_offset']:X}" for spec in write_specs
        ),
        "changed_start_ranges": "|".join(
            f"0x{start:X}-0x{end:X}"
            for start, end in start_change_ranges
        ),
        "changed_resources": "|".join(
            changed_resources
        ),
        "old_lzs_size": old_lzs_size,
        "new_lzs_size": len(new_lzs),
        "original_lzs_flag_hex": f"0x{original_flag:02X}",
        "selected_lzs_flag_hex": f"0x{selected_flag:02X}",
        "compression_mode": compression_mode,
        "remaining_lzs_capacity": (
            old_lzs_size - len(new_lzs)
        ),
        "unexpected_system_changes": (
            unexpected_system_changes
        ),
        "iso_prefix_unchanged": True,
        "iso_suffix_unchanged": True,
        "seven_zip_test": "pass",
        "expected_write_count": len(write_specs),
        "ppsspp_test_status": "not_run",
    }

    write_csv(
        report_directory / "build_result.csv",
        [result_row],
        list(result_row.keys()),
    )

    write_json(
        report_directory / "all_report.json",
        {
            "format": (
                "prinny1_v7_14_minimum_test_iso_report_v1"
            ),
            "created_at": now(),
            "base_iso": {
                "path": str(base_iso),
                "label": base_label,
                "sha256": result_row[
                    "base_iso_sha256"
                ],
            },
            "expected_write_count": len(write_specs),
            "changed_resource_count": len(changed_resources),
            "changed_resources": (
                changed_resources
            ),
            "system_dat_same_size": True,
            "iso_same_size": True,
            "iso_prefix_unchanged": True,
            "iso_suffix_unchanged": True,
            "seven_zip_test": "pass",
            "fresh_reextract_verification": "pass",
            "output_iso": {
                "path": str(output_iso),
                "size": iso_size,
                "sha256": result_row[
                    "output_iso_sha256"
                ],
            },
            "ppsspp_test_status": "not_run",
            "translation_wording_changed": any(
                plan.get("change_kind")
                == "user_approved_speaker_name"
                for plan in patch_plan
            ),
            "translation_wording_user_approved": all(
                plan.get("user_wording_approval")
                in {"yes", "not_required_mechanical_only"}
                for plan in patch_plan
            ),
            "character_voice_changed": False,
            "status": "build_pass_runtime_test_required",
        },
    )

    print()
    print("완료")
    print(
        f"기준 한글 ISO            : {base_iso}"
    )
    print(
        f"기준 종류                : {base_label}"
    )
    print(f"확정 Expected Write     : {len(write_specs)}")
    print(
        f"변경 START 자원         : "
        f"{'|'.join(changed_resources)}"
    )
    print(
        f"START 슬롯 밖 변경      : 0"
    )
    print(
        f"SYSTEM 보호영역 변경    : "
        f"{unexpected_system_changes}"
    )
    print("ISO 크기 불변           : True")
    print("ISO 앞·뒤 영역 불변     : True")
    print("7z ISO 검사             : PASS")
    print("ISO 내부 재추출 검증    : PASS")
    print(
        f"테스트 ISO              : {output_iso}"
    )
    print(
        f"SHA-256                 : "
        f"{result_row['output_iso_sha256']}"
    )
    print(
        f"보고서 JSON             : "
        f"{report_directory / 'all_report.json'}"
    )
    print("PPSSPP 테스트           : 아직 실행하지 않음")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
