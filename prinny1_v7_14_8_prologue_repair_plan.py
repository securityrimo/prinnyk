#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from prinny1_v7_14_1_base_compatibility import (
    PROJECT_DEFAULT,
    ROOT_DEFAULT,
    decode_custom,
    find_iso_file,
    read_iso_file,
    resolve_start_record,
    sha256_file,
    write_csv,
    write_json,
)


BASE_ISO_DEFAULT = (
    ROOT_DEFAULT
    / "build/prinny_stage1_hotfix_v6_2"
    / "prinny_korean_stage1_hotfix_v6_2_977.iso"
)
ORIGINAL_ISO_DEFAULT = PROJECT_DEFAULT / "game.iso"
PROFILE_DEFAULT = (
    ROOT_DEFAULT
    / "reports/prinny1_v7_13_3_outlier_quarantine"
    / "accepted_encoder_profile.json"
)
FIT_PLAN_DEFAULT = (
    PROJECT_DEFAULT
    / "workspace/translations/final_patch_plan_977/fit_patch_plan.json"
)
SPEAKER_ID = "TXT-D23CB67F0C43"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_start_resource(iso: Path, target: str) -> bytes:
    from core.lzs import decompress_buffer
    import core.font_builder as builder
    from core.start_runtime import StartRuntimeArchive

    system_entry = find_iso_file(
        iso,
        ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    )
    system = read_iso_file(iso, system_entry)
    start_entry = builder.parse_nispack_start_entry(system)
    lzs_offset = int(start_entry["data_offset"])
    lzs_size = int(start_entry["size"])
    start, _header = decompress_buffer(
        system[lzs_offset:lzs_offset + lzs_size]
    )
    archive = StartRuntimeArchive.from_bytes(
        start,
        source=f"{iso}!/start.dat",
    )
    record = resolve_start_record(archive, target)
    return start[int(record.data_offset):int(record.end_offset)]


def walk_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(walk_dicts(child))

    return found


def encode_text(text: str, mapping: dict[str, str]) -> bytes:
    output = bytearray()

    for character in text:
        encoded = mapping.get(character)
        if encoded is not None:
            output.extend(bytes.fromhex(encoded))
        else:
            output.extend(character.encode("cp932"))

    return bytes(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-iso", type=Path, default=BASE_ISO_DEFAULT)
    parser.add_argument(
        "--original-iso",
        type=Path,
        default=ORIGINAL_ISO_DEFAULT,
    )
    parser.add_argument("--profile", type=Path, default=PROFILE_DEFAULT)
    parser.add_argument("--fit-plan", type=Path, default=FIT_PLAN_DEFAULT)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports/prinny1_v7_14_8_prologue_repair_plan"
        ),
    )
    arguments = parser.parse_args()

    base_iso = arguments.base_iso.expanduser().resolve()
    original_iso = arguments.original_iso.expanduser().resolve()
    profile_path = arguments.profile.expanduser().resolve()
    fit_plan_path = arguments.fit_plan.expanduser().resolve()
    output = arguments.output.expanduser().resolve()

    for required in (
        base_iso,
        original_iso,
        profile_path,
        fit_plan_path,
    ):
        if not required.is_file():
            raise FileNotFoundError(f"필수 입력이 없습니다: {required}")

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    mapping = profile.get("mapping", {})

    if profile.get("validated") is not True or len(mapping) != 960:
        raise ValueError("검증된 960자 코드맵이 아닙니다.")

    reverse_mapping = {
        bytes.fromhex(encoded): character
        for character, encoded in mapping.items()
    }
    fit_plan = json.loads(fit_plan_path.read_text(encoding="utf-8"))
    speaker_records = [
        record
        for record in walk_dicts(fit_plan)
        if record.get("id") == SPEAKER_ID
    ]
    speaker_records.sort(key=lambda row: int(row["offset"]))

    if len(speaker_records) != 27:
        raise ValueError(
            "프리니대 화자명 발생 수가 27개가 아닙니다: "
            f"{len(speaker_records)}"
        )

    offsets = [int(record["offset"]) for record in speaker_records]
    if len(offsets) != len(set(offsets)):
        raise ValueError("프리니대 화자명 오프셋이 중복됐습니다.")

    original_resource = load_start_resource(original_iso, "Demo00.dat")
    base_resource = load_start_resource(base_iso, "Demo00.dat")

    writes: list[dict[str, Any]] = []

    line_offset = 0x9940
    line_span = 35
    original_line = bytes.fromhex(
        "82D082A682A582C181418B7D82AE83628358815B8149"
    ) + bytes(line_span - 22)
    current_line = bytes.fromhex(
        "95D294F68E7C2C8EFB90688CB093F790E28DF02D21"
    ) + bytes(line_span - 21)
    repaired_line = bytes.fromhex(
        "95D294F68E7C81438EFB90688CB093F790E28DF0817C8149"
    ) + bytes(line_span - 24)

    if original_resource[line_offset:line_offset + line_span] != original_line:
        raise ValueError("원본 ISO의 프롤로그 대사 슬롯이 예상과 다릅니다.")
    if base_resource[line_offset:line_offset + line_span] != current_line:
        raise ValueError("V6.2의 프롤로그 대사 슬롯이 예상과 다릅니다.")

    current_text, current_unknown = decode_custom(
        current_line,
        reverse_mapping,
    )
    repaired_text, repaired_unknown = decode_custom(
        repaired_line,
        reverse_mapping,
    )

    if current_unknown or repaired_unknown:
        raise ValueError("프롤로그 대사에 미해독 바이트가 있습니다.")
    if current_text != "히에엑,서둘러야함다-!":
        raise ValueError(f"현재 프롤로그 문구가 다릅니다: {current_text}")
    if repaired_text != "히에엑，서둘러야함다－！":
        raise ValueError(f"수정 프롤로그 문구가 다릅니다: {repaired_text}")

    writes.append(
        {
            "group_id": "G017",
            "logical_id": "TXT-9BC9EC88762A",
            "target": "Demo00.dat",
            "offset_hex": f"0x{line_offset:X}",
            "slot_capacity": line_span,
            "expected_before_hex": current_line.hex().upper(),
            "write_after_hex": repaired_line.hex().upper(),
            "original_iso_hex": original_line.hex().upper(),
            "source_text": "ひえぇっ、急ぐッスー！",
            "current_text": current_text,
            "replacement_text": repaired_text,
            "change_kind": (
                "ASCII_2C_2D_21_to_CP932_8143_817C_8149"
            ),
            "user_wording_approval": "not_required_mechanical_only",
            "expected_write_confirmed": "yes",
        }
    )

    current_name_text = "프리니 대"
    replacement_name_text = "프리니대원"
    current_name = encode_text(current_name_text, mapping)
    replacement_name = encode_text(replacement_name_text, mapping)
    prefix = bytes.fromhex("C9")
    original_name = bytes.fromhex("C98376838A836A815B91E0")
    expected_name = prefix + current_name + b"\x00"
    repaired_name = prefix + replacement_name

    if len(expected_name) != 11 or len(repaired_name) != 11:
        raise ValueError("화자명 전후 슬롯이 11바이트가 아닙니다.")

    for index, (offset, record) in enumerate(
        zip(offsets, speaker_records, strict=True),
        start=1,
    ):
        original_actual = original_resource[offset:offset + 11]
        base_actual = base_resource[offset:offset + 11]

        if original_actual != original_name:
            raise ValueError(
                f"원본 ISO 화자명 #{index} 바이트가 다릅니다: 0x{offset:X}"
            )
        if base_actual != expected_name:
            raise ValueError(
                f"V6.2 화자명 #{index} 바이트가 다릅니다: 0x{offset:X}"
            )
        if base_resource[offset + 11] != 0:
            raise ValueError(
                f"화자명 #{index} 종료 바이트가 0이 아닙니다: 0x{offset + 11:X}"
            )
        if int(record.get("patch_span_length", 0)) != 11:
            raise ValueError(f"화자명 #{index} 패치 길이가 다릅니다.")

        writes.append(
            {
                "group_id": "G018",
                "logical_id": SPEAKER_ID,
                "occurrence_number": index,
                "target": "Demo00.dat",
                "offset_hex": f"0x{offset:X}",
                "slot_capacity": 11,
                "expected_before_hex": expected_name.hex().upper(),
                "write_after_hex": repaired_name.hex().upper(),
                "original_iso_hex": original_name.hex().upper(),
                "source_text": "プリニー隊",
                "current_text": current_name_text,
                "replacement_text": replacement_name_text,
                "change_kind": "user_approved_speaker_name",
                "user_wording_approval": "yes",
                "expected_write_confirmed": "yes",
            }
        )

    ranges = []
    for row in writes:
        start = int(str(row["offset_hex"]), 16)
        end = start + int(row["slot_capacity"])
        ranges.append((start, end))

    for previous, current in zip(sorted(ranges), sorted(ranges)[1:]):
        if previous[1] > current[0]:
            raise ValueError("Expected Write 범위가 서로 겹칩니다.")

    output.mkdir(parents=True, exist_ok=True)
    fields = [
        "group_id",
        "logical_id",
        "occurrence_number",
        "target",
        "offset_hex",
        "slot_capacity",
        "expected_before_hex",
        "write_after_hex",
        "original_iso_hex",
        "source_text",
        "current_text",
        "replacement_text",
        "change_kind",
        "user_wording_approval",
        "expected_write_confirmed",
    ]
    csv_path = output / "confirmed_patch_plan.csv"
    confirmed_path = output / "expected_write_confirmed.csv"
    json_path = output / "all_report.json"
    write_csv(csv_path, writes, fields)
    write_csv(confirmed_path, writes, fields)
    write_json(
        json_path,
        {
            "format": "prinny1_v7_14_8_prologue_repair_plan_v1",
            "created_at": now(),
            "base_iso": str(base_iso),
            "base_iso_sha256": sha256_file(base_iso),
            "original_iso": str(original_iso),
            "original_iso_sha256": sha256_file(original_iso),
            "codemap_profile": str(profile_path),
            "codemap_profile_sha256": sha256_file(profile_path),
            "codemap_entries": len(mapping),
            "fit_plan": str(fit_plan_path),
            "fit_plan_sha256": sha256_file(fit_plan_path),
            "expected_write_count": len(writes),
            "prologue_line_write_count": 1,
            "speaker_name_write_count": len(speaker_records),
            "all_original_bytes_verified": True,
            "all_v6_2_expected_bytes_verified": True,
            "all_terminators_verified": True,
            "all_ranges_non_overlapping": True,
            "translation_wording": {
                "before": current_name_text,
                "after": replacement_name_text,
                "user_approved": True,
            },
            "writes": writes,
            "status": "ready_for_new_iso_build_approval",
            "iso_created": False,
            "bytes_modified": 0,
            "next_action": (
                "사용자 승인 후 V6.2 기준 새 ISO에 28개 Expected Write만 "
                "적용하고 재추출·PPSSPP 회귀 QA를 수행합니다."
            ),
            "outputs": {
                "csv": str(csv_path),
                "confirmed_csv": str(confirmed_path),
                "json": str(json_path),
            },
        },
    )

    print(f"프롤로그 대사 Expected Write : 1")
    print(f"프리니대원 Expected Write    : {len(speaker_records)}")
    print(f"전체 Expected Write          : {len(writes)}")
    print("원본/V6.2 바이트 검증        : PASS")
    print("종료 바이트/범위 검증        : PASS")
    print("상태                          : 새 ISO 생성 승인 대기")
    print(f"CSV                           : {csv_path}")
    print(f"확정 CSV                      : {confirmed_path}")
    print(f"JSON                          : {json_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
