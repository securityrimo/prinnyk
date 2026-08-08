#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

PROJECT_DEFAULT = Path.home() / "PrinnyReverseToolkit"
DRIVE_DEFAULT = Path("/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd")
ROOT_DEFAULT = DRIVE_DEFAULT / "PSP_Localization_Work"
SECTOR_SIZE = 2048
EXPECTED_CODEMAP_ENTRIES = 960


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
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


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


def normalized_iso_name(name: str) -> str:
    return name.split(";", 1)[0].rstrip(".").casefold()


def parse_directory_record(record: bytes) -> dict[str, Any]:
    if len(record) < 34:
        raise ValueError("ISO 디렉터리 레코드가 너무 짧습니다.")

    record_length = record[0]

    if record_length != len(record):
        raise ValueError("ISO 디렉터리 레코드 길이가 맞지 않습니다.")

    extent_lba = int.from_bytes(record[2:6], "little")
    data_length = int.from_bytes(record[10:14], "little")
    flags = record[25]
    name_length = record[32]
    name_bytes = record[33:33 + name_length]

    if name_bytes == b"\x00":
        name = "."
    elif name_bytes == b"\x01":
        name = ".."
    else:
        name = name_bytes.decode("ascii", errors="replace")

    return {
        "name": name,
        "extent_lba": extent_lba,
        "data_length": data_length,
        "is_directory": bool(flags & 0x02),
        "is_multi_extent": bool(flags & 0x80),
    }


def read_primary_volume_descriptor(handle: BinaryIO) -> bytes:
    for sector in range(16, 65):
        handle.seek(sector * SECTOR_SIZE)
        descriptor = handle.read(SECTOR_SIZE)

        if len(descriptor) != SECTOR_SIZE:
            break

        if (
            descriptor[0] == 1
            and descriptor[1:6] == b"CD001"
            and descriptor[6] == 1
        ):
            return descriptor

        if descriptor[0] == 255:
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
        raise EOFError("ISO 디렉터리를 전부 읽지 못했습니다.")

    entries: list[dict[str, Any]] = []
    offset = 0

    while offset < len(data):
        record_length = data[offset]

        if record_length == 0:
            offset = ((offset // SECTOR_SIZE) + 1) * SECTOR_SIZE
            continue

        end = offset + record_length

        if end > len(data):
            raise ValueError(
                "ISO 디렉터리 레코드가 범위를 벗어났습니다."
            )

        entry = parse_directory_record(data[offset:end])

        if entry["name"] not in {".", ".."}:
            entries.append(entry)

        offset = end

    return entries


def find_iso_file(
    iso_path: Path,
    path_parts: list[str],
) -> dict[str, Any]:
    with iso_path.open("rb") as handle:
        descriptor = read_primary_volume_descriptor(handle)
        root_length = descriptor[156]

        if root_length == 0:
            raise ValueError("ISO 루트 레코드가 없습니다.")

        current = parse_directory_record(
            descriptor[156:156 + root_length]
        )

        for index, wanted in enumerate(path_parts):
            entries = read_directory_entries(
                handle,
                int(current["extent_lba"]),
                int(current["data_length"]),
            )
            normalized = normalized_iso_name(wanted)
            matches = [
                entry
                for entry in entries
                if normalized_iso_name(str(entry["name"]))
                == normalized
            ]

            if len(matches) != 1:
                raise ValueError(
                    "ISO 경로를 하나로 확정하지 못했습니다: "
                    + "/".join(path_parts[:index + 1])
                )

            current = matches[0]

            if current["is_multi_extent"]:
                raise ValueError(
                    "다중 extent 파일은 처리하지 않습니다."
                )

            if (
                index < len(path_parts) - 1
                and not current["is_directory"]
            ):
                raise ValueError(
                    f"중간 경로가 디렉터리가 아닙니다: {wanted}"
                )

        if current["is_directory"]:
            raise ValueError("요청 경로가 파일이 아닙니다.")

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
        raise EOFError("ISO 내부 파일을 전부 읽지 못했습니다.")

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

    candidates = [
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

    for path, label in candidates:
        if path.is_file():
            return path.resolve(), label

    raise FileNotFoundError(
        "검증된 V6.2/V5/V4 한글 기준 ISO를 찾지 못했습니다."
    )


def resolve_start_record(archive: Any, target_name: str) -> Any:
    normalized = Path(
        target_name.replace("\\", "/")
    ).name.casefold()

    matches = [
        record
        for record in archive.records
        if (
            str(record.name).casefold() == normalized
            or str(record.output_name).casefold() == normalized
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            f"START 자원을 하나로 확정하지 못했습니다: "
            f"{target_name} (matches={len(matches)})"
        )

    return matches[0]


def trim_slot(data: bytes) -> bytes:
    return data.split(b"\x00", 1)[0]


def decode_cp932(data: bytes) -> str:
    try:
        return trim_slot(data).decode("cp932")
    except UnicodeDecodeError:
        return "<CP932 해독 실패>"


def decode_custom(
    data: bytes,
    reverse_mapping: dict[bytes, str],
) -> tuple[str, list[str]]:
    source = trim_slot(data)
    output: list[str] = []
    unknown: list[str] = []
    index = 0

    while index < len(source):
        if index + 2 <= len(source):
            pair = source[index:index + 2]
            mapped = reverse_mapping.get(pair)

            if mapped is not None:
                output.append(mapped)
                index += 2
                continue

        byte = source[index]

        if 0x00 <= byte <= 0x7F:
            try:
                output.append(bytes([byte]).decode("cp932"))
            except UnicodeDecodeError:
                unknown.append(f"{byte:02X}")
                output.append("�")

            index += 1
            continue

        if (
            0x81 <= byte <= 0x9F
            or 0xE0 <= byte <= 0xFC
        ) and index + 1 < len(source):
            pair = source[index:index + 2]

            try:
                output.append(pair.decode("cp932"))
            except UnicodeDecodeError:
                unknown.append(pair.hex().upper())
                output.append("�")

            index += 2
            continue

        try:
            output.append(bytes([byte]).decode("cp932"))
        except UnicodeDecodeError:
            unknown.append(f"{byte:02X}")
            output.append("�")

        index += 1

    return "".join(output), unknown


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


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
        "--v7133",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_3_outlier_quarantine"
        ),
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
            / "reports/prinny1_v7_14_1_base_compatibility"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    work_root = arguments.work_root.expanduser().resolve()
    v7133 = arguments.v7133.expanduser().resolve()
    v7134 = arguments.v7134.expanduser().resolve()
    output = arguments.output.expanduser().resolve()

    plan_path = v7134 / "confirmed_patch_plan.csv"
    profile_path = v7133 / "accepted_encoder_profile.json"

    for required in (
        project,
        plan_path,
        profile_path,
    ):
        if not required.exists():
            raise FileNotFoundError(
                f"필수 입력이 없습니다: {required}"
            )

    output.mkdir(parents=True, exist_ok=True)

    print("[1/5] 확정 패치 계획과 V6.2 기준 ISO 확인")

    plans = read_csv(plan_path)

    if len(plans) != 1:
        raise ValueError(
            f"확정 패치 계획이 1개가 아닙니다: {len(plans)}"
        )

    plan = plans[0]
    profile = json.loads(
        profile_path.read_text(encoding="utf-8")
    )

    if not profile.get("validated"):
        raise ValueError("복구 문자맵이 검증되지 않았습니다.")

    mapping = profile.get("mapping", {})

    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("복구 문자맵이 비어 있습니다.")

    declared_map_entries = parse_integer(
        profile.get("map_entries")
    )

    if (
        declared_map_entries != EXPECTED_CODEMAP_ENTRIES
        or len(mapping) != EXPECTED_CODEMAP_ENTRIES
    ):
        raise ValueError(
            "복구 문자맵이 검증 대상 960자와 일치하지 않습니다: "
            f"declared={declared_map_entries}, actual={len(mapping)}"
        )

    reverse_mapping: dict[bytes, str] = {}

    for character, encoded_hex in mapping.items():
        cleaned = clean_hex(encoded_hex)

        if len(str(character)) != 1 or len(cleaned) != 4:
            raise ValueError(
                "960자 문자맵에 잘못된 항목이 있습니다: "
                f"{character!r}={encoded_hex!r}"
            )

        encoded = bytes.fromhex(cleaned)

        if encoded in reverse_mapping:
            raise ValueError(
                "역방향 문자맵에서 바이트 충돌이 발생했습니다: "
                f"{cleaned}"
            )

        reverse_mapping[encoded] = str(character)

    base_iso, base_label = choose_base_iso(
        arguments.base_iso,
        project,
        work_root,
    )
    base_iso_sha256 = sha256_file(base_iso)
    codemap_profile_sha256 = sha256_file(profile_path)
    patch_plan_sha256 = sha256_file(plan_path)

    print("[2/5] 기준 ISO에서 Demo00.dat 슬롯 직접 복원")

    from core.lzs import decompress_buffer
    import core.font_builder as builder
    from core.start_runtime import StartRuntimeArchive

    system_entry = find_iso_file(
        base_iso,
        ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    )
    system_data = read_iso_file(base_iso, system_entry)
    start_entry = builder.parse_nispack_start_entry(
        system_data
    )
    lzs_offset = int(start_entry["data_offset"])
    lzs_size = int(start_entry["size"])
    start_data, _header = decompress_buffer(
        system_data[
            lzs_offset:lzs_offset + lzs_size
        ]
    )

    archive = StartRuntimeArchive.from_bytes(
        start_data,
        source=f"{base_iso}!/start.dat",
    )
    record = resolve_start_record(
        archive,
        plan.get("target", ""),
    )

    resource_offset = parse_integer(
        plan.get("offset_hex", "")
    )
    expected_before_hex = clean_hex(
        plan.get("expected_before_hex", "")
    )
    write_after_hex = clean_hex(
        plan.get("write_after_hex", "")
    )

    if resource_offset is None:
        raise ValueError("확정 패치 오프셋이 잘못됐습니다.")

    if not expected_before_hex or not write_after_hex:
        raise ValueError("확정 전후 바이트가 없습니다.")

    expected_before = bytes.fromhex(expected_before_hex)
    write_after = bytes.fromhex(write_after_hex)
    slot_size = len(expected_before)

    if len(write_after) != slot_size:
        raise ValueError("확정 전후 슬롯 길이가 다릅니다.")

    absolute_offset = (
        int(record.data_offset) + resource_offset
    )
    absolute_end = absolute_offset + slot_size

    if absolute_end > int(record.end_offset):
        raise ValueError("대상 슬롯이 START 자원 경계를 벗어납니다.")

    actual_base = start_data[
        absolute_offset:absolute_end
    ]

    print("[3/5] 현재 한글 바이트·원본 일본어·목표 번역 해독")

    source_text = plan.get("source_text", "")
    replacement_text = plan.get("replacement_text", "")

    expected_cp932 = decode_cp932(expected_before)
    actual_cp932 = decode_cp932(actual_base)
    actual_custom, actual_unknown = decode_custom(
        actual_base,
        reverse_mapping,
    )
    write_custom, write_unknown = decode_custom(
        write_after,
        reverse_mapping,
    )

    print("[4/5] 이미 적용·동일 문구·잘못 연결 여부 판정")

    if actual_base == expected_before:
        compatibility_status = "original_slot_compatible"
        candidate_disposition = "applicable_to_base"
        next_action = (
            "V7.14 빌드를 진행할 수 있으나 현재 실행 결과와 다릅니다."
        )

    elif actual_base == write_after:
        compatibility_status = "already_applied_exact_bytes"
        candidate_disposition = "redundant_for_v6_2_base"
        next_action = (
            "V7.13.4 후보는 V6.2에 이미 정확히 적용되어 있습니다. "
            "새 ISO를 만들지 말고 런타임 문제의 다른 원인을 조사합니다."
        )

    elif (
        normalize_text(actual_custom)
        == normalize_text(replacement_text)
        and replacement_text.strip()
    ):
        compatibility_status = "already_applied_text_equivalent"
        candidate_disposition = "redundant_text_equivalent"
        next_action = (
            "바이트는 다르지만 현재 기준 ISO의 문구가 목표 번역과 같습니다. "
            "중복 패치를 만들지 않습니다."
        )

    else:
        compatibility_status = (
            "existing_translation_conflicts_with_candidate"
        )
        candidate_disposition = "blocked_for_v6_2_base"
        next_action = (
            "확정 후보가 V6.2 런타임 문제 위치와 호환되지 않습니다. "
            "해당 후보를 Expected Write에서 제외하고 다음 문맥 후보를 "
            "다시 찾아야 합니다."
        )

    print("[5/5] 기준 ISO 호환성 보고서 저장")

    result = {
        "created_at": now(),
        "base_iso": str(base_iso),
        "base_label": base_label,
        "base_iso_sha256": base_iso_sha256,
        "codemap_profile": str(profile_path),
        "codemap_profile_sha256": codemap_profile_sha256,
        "codemap_entries_declared": declared_map_entries,
        "codemap_entries_loaded": len(reverse_mapping),
        "codemap_validated": True,
        "v7134_patch_plan": str(plan_path),
        "v7134_patch_plan_sha256": patch_plan_sha256,
        "target": str(record.output_name),
        "resource_offset_hex": f"0x{resource_offset:X}",
        "slot_size": slot_size,
        "expected_original_hex": expected_before.hex().upper(),
        "actual_base_hex": actual_base.hex().upper(),
        "candidate_write_hex": write_after.hex().upper(),
        "source_text_from_plan": source_text,
        "expected_original_cp932": expected_cp932,
        "actual_base_cp932_view": actual_cp932,
        "actual_base_custom_decode": actual_custom,
        "candidate_replacement_text": replacement_text,
        "candidate_write_custom_decode": write_custom,
        "actual_unknown_bytes": "|".join(actual_unknown),
        "candidate_unknown_bytes": "|".join(write_unknown),
        "actual_equals_original": actual_base == expected_before,
        "actual_equals_candidate_bytes": actual_base == write_after,
        "actual_text_equals_candidate_text": (
            normalize_text(actual_custom)
            == normalize_text(replacement_text)
            and bool(replacement_text.strip())
        ),
        "compatibility_status": compatibility_status,
        "candidate_disposition": candidate_disposition,
        "next_action": next_action,
        "expected_write_still_valid_for_original_iso": True,
        "expected_write_valid_for_v6_2_base": (
            compatibility_status == "original_slot_compatible"
        ),
        "iso_created": False,
        "bytes_modified": 0,
    }

    write_csv(
        output / "base_slot_compatibility.csv",
        [result],
        list(result.keys()),
    )
    write_json(
        output / "all_report.json",
        {
            "format": (
                "prinny1_v7_14_1_base_compatibility_report_v1"
            ),
            **result,
        },
    )

    print()
    print("완료")
    print(f"기준 ISO                 : {base_iso}")
    print(f"기준 종류                : {base_label}")
    print(f"기준 ISO SHA-256         : {base_iso_sha256}")
    print(f"검증 코드맵              : {len(reverse_mapping)}자")
    print(f"대상                      : {record.output_name}")
    print(f"오프셋                    : 0x{resource_offset:X}")
    print(f"원본 일본어               : {expected_cp932}")
    print(f"기준 ISO 현재 문구        : {actual_custom}")
    print(f"후보 목표 문구            : {replacement_text}")
    print(f"후보 바이트 해독          : {write_custom}")
    print(f"호환성 판정               : {compatibility_status}")
    print(f"다음 처리                 : {next_action}")
    print("바이트 변경               : 0")
    print("ISO 생성                  : 없음")
    print(
        f"보고서 CSV                : "
        f"{output / 'base_slot_compatibility.csv'}"
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
