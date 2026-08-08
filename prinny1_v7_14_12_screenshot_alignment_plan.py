#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.start_runtime import StartRuntimeArchive


ROOT = Path(__file__).resolve().parent
SOURCE_START = (
    ROOT
    / "workspace/build/prinny1_v7_14_9_prologue_full_punctuation/start.dat"
)
QA_ROWS = ROOT / "workspace/reports/prinny_qa/qa_rows.csv"
ALLOCATION = ROOT / "workspace/font/audited_allocation_977/hangul_allocation.json"
SCREENSHOT_DIR = Path("/home/hyuk/사진")
REPORT_DIR = (
    ROOT / "workspace/reports/prinny1_v7_14_12_screenshot_alignment_plan"
)

STAGE_OFFSET_START = 0x178
STAGE_OFFSET_END = 0x9AE
DEMO_IDS = {"TXT-0E197FE562DD", "TXT-D84A56346D70"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"CSV 행이 없습니다: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_mapping() -> dict[str, bytes]:
    value = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    allocations = value.get("allocations", [])
    mapping = {
        str(row["hangul"]): bytes.fromhex(str(row["sjis"]))
        for row in allocations
    }
    if len(mapping) != 977 or len(set(mapping.values())) != 977:
        raise ValueError("검증 대상 977자 코드맵이 유일하지 않습니다.")
    return mapping


def fullwidth_ascii(character: str) -> str:
    if character == " ":
        return "\u3000"
    code = ord(character)
    if 0x21 <= code <= 0x7E:
        return chr(code + 0xFEE0)
    return character


def normalize_ascii(text: str) -> str:
    return "".join(fullwidth_ascii(character) for character in text)


def encode_text(text: str, mapping: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        encoded = mapping.get(character)
        if encoded is not None:
            output.extend(encoded)
        else:
            output.extend(character.encode("cp932"))
    return bytes(output)


def all_characters_two_bytes(text: str, mapping: dict[str, bytes]) -> bool:
    for character in text:
        encoded = mapping.get(character)
        if encoded is None:
            encoded = character.encode("cp932")
        if len(encoded) != 2:
            return False
    return True


def screenshot_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    paths = [SCREENSHOT_DIR / "테스트.png"] + [
        SCREENSHOT_DIR / f"테스트{number}.png" for number in range(1, 25)
    ]
    for index, path in enumerate(paths):
        if not path.is_file():
            raise FileNotFoundError(path)
        if index <= 17:
            classification = "existing_v7_8_issue"
            issue_ids = f"SHOT-{index + 1:03d}"
            resource = "existing_manifest"
            disposition = "retain_until_individual_runtime_pass"
        elif index == 18:
            classification = "newly_linked_alignment_defect"
            issue_ids = "SHOT-019"
            resource = "Demo00.dat"
            disposition = "expected_write_candidate"
        else:
            classification = "new_stageinfo_alignment_defect"
            issue_ids = f"SHOT-{index + 1:03d}"
            resource = "StageInfo00.dat"
            disposition = "expected_write_candidate"
        rows.append({
            "screenshot_id": issue_ids,
            "path": str(path),
            "sha256": sha256_file(path),
            "classification": classification,
            "resource": resource,
            "disposition": disposition,
        })
    return rows


def main() -> int:
    for required in (SOURCE_START, QA_ROWS, ALLOCATION, SCREENSHOT_DIR):
        if not required.exists():
            raise FileNotFoundError(required)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    mapping = load_mapping()
    source = SOURCE_START.read_bytes()
    source_hash_before = sha256_bytes(source)
    archive = StartRuntimeArchive.from_bytes(source, source=str(SOURCE_START))
    records = {str(row.output_name).casefold(): row for row in archive.records}

    with QA_ROWS.open("r", encoding="utf-8-sig", newline="") as handle:
        catalogue = list(csv.DictReader(handle))

    selected: list[dict[str, str]] = []
    for row in catalogue:
        resource = str(row.get("resource", ""))
        offset_text = str(row.get("offset", ""))
        if not offset_text:
            continue
        offset = int(offset_text, 0)
        if (
            resource.casefold() == "stageinfo00.dat"
            and STAGE_OFFSET_START <= offset <= STAGE_OFFSET_END
        ) or str(row.get("id", "")) in DEMO_IDS:
            selected.append(row)

    writes: list[dict[str, Any]] = []
    unchanged_rows = 0
    for row in selected:
        resource_name = str(row["resource"])
        record = records.get(resource_name.casefold())
        if record is None:
            raise ValueError(f"START 레코드가 없습니다: {resource_name}")
        offset = int(str(row["offset"]), 0)
        current_text = str(row["translation"])
        normalized_text = normalize_ascii(current_text)
        if current_text == normalized_text:
            unchanged_rows += 1
            continue

        expected_payload = encode_text(current_text, mapping)
        replacement_payload = encode_text(normalized_text, mapping)
        if not all_characters_two_bytes(normalized_text, mapping):
            raise ValueError(
                f"전각화 뒤 1바이트 문자가 남았습니다: {row['id']}"
            )
        if len(replacement_payload) % 2:
            raise ValueError(f"전각화 뒤 홀수 바이트입니다: {row['id']}")

        resource_data = source[record.data_offset:record.end_offset]
        actual_payload = resource_data[offset:offset + len(expected_payload)]
        if actual_payload != expected_payload:
            raise ValueError(
                f"현재 바이트가 번역 카탈로그와 다릅니다: {row['id']} "
                f"expected={expected_payload.hex().upper()} "
                f"actual={actual_payload.hex().upper()}"
            )

        required_span = len(replacement_payload) + 1
        before = resource_data[offset:offset + required_span]
        if len(before) != required_span:
            raise ValueError(f"레코드 범위를 벗어납니다: {row['id']}")
        if before[len(expected_payload):] != bytes(
            required_span - len(expected_payload)
        ):
            raise ValueError(f"필요 패딩이 0이 아닙니다: {row['id']}")
        after = replacement_payload + b"\x00"
        if len(after) != len(before):
            raise AssertionError("Expected Write 길이가 다릅니다.")

        ascii_characters = "".join(
            character for character in current_text if ord(character) < 0x80
        )
        writes.append({
            "group_id": "G021" if resource_name == "Demo00.dat" else "G022",
            "logical_id": str(row["id"]),
            "target": resource_name,
            "offset_hex": f"0x{offset:X}",
            "write_span": len(after),
            "expected_before_hex": before.hex().upper(),
            "write_after_hex": after.hex().upper(),
            "source_text": str(row["source"]),
            "current_text": current_text,
            "replacement_text": normalized_text,
            "ascii_characters_replaced": ascii_characters,
            "current_payload_bytes": len(expected_payload),
            "replacement_payload_bytes": len(replacement_payload),
            "replacement_even_aligned": "yes",
            "wording_changed": "no",
            "user_wording_approval": "not_required_mechanical_only",
            "change_kind": "ascii_to_cp932_fullwidth_alignment",
            "expected_write_confirmed": "yes",
        })

    if len({(row["target"], row["offset_hex"]) for row in writes}) != len(writes):
        raise ValueError("Expected Write 대상이 중복됩니다.")
    ordered = sorted(writes, key=lambda row: (row["target"], int(row["offset_hex"], 0)))
    for left, right in zip(ordered, ordered[1:]):
        if left["target"] != right["target"]:
            continue
        left_end = int(left["offset_hex"], 0) + int(left["write_span"])
        if left_end > int(right["offset_hex"], 0):
            raise ValueError(
                f"Expected Write 범위가 겹칩니다: {left['logical_id']} / "
                f"{right['logical_id']}"
            )

    screenshots = screenshot_rows()
    write_csv(REPORT_DIR / "screenshot_classification.csv", screenshots)
    write_csv(REPORT_DIR / "confirmed_patch_plan.csv", writes)
    write_csv(REPORT_DIR / "expected_write_confirmed.csv", writes)

    report = {
        "format": "prinny1_v7_14_12_screenshot_alignment_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "policy": "docs/PRINNY1_PRIORITY_RULES_V2.md",
        "source_start": str(SOURCE_START),
        "source_start_sha256": source_hash_before,
        "source_start_unchanged": sha256_file(SOURCE_START) == source_hash_before,
        "screenshots": {
            "directory": str(SCREENSHOT_DIR),
            "count": len(screenshots),
            "existing_issue_count": 18,
            "new_issue_count": 7,
        },
        "selection": {
            "catalogue_rows": len(selected),
            "unchanged_no_ascii_rows": unchanged_rows,
            "expected_write_count": len(writes),
            "resource_counts": {
                name: sum(1 for row in writes if row["target"] == name)
                for name in sorted({str(row["target"]) for row in writes})
            },
        },
        "checks": {
            "all_before_bytes_match_v7_14_9": True,
            "all_replacements_even_aligned": True,
            "all_replacement_characters_two_bytes": True,
            "all_required_padding_zero": True,
            "expected_writes_non_overlapping": True,
            "translation_wording_changed": False,
            "iso_created": False,
            "source_bytes_modified": 0,
        },
        "deferred": [
            "BOOT/EBOOT/UI 일본어 문자열은 승인 번역과 포인터/용량 확정 필요",
            "V7.14.11 결합 글리프 미리보기 및 통합 순서 검토 필요",
        ],
        "status": "expected_writes_confirmed_iso_build_approval_required",
        "next_action": (
            "V7.14.11 결합 글리프 계획과 이 계획을 하나의 봉인 manifest로 합친 뒤 "
            "독립 검토하고, 사용자 승인 후에만 새 ISO를 생성합니다."
        ),
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"사진 분류: {len(screenshots)}")
    print(f"선택 카탈로그 행: {len(selected)}")
    print(f"변경 없는 행: {unchanged_rows}")
    print(f"Expected Writes: {len(writes)}")
    print("번역 문구 변경: 없음")
    print("ISO 생성: 없음")
    print(f"보고서: {REPORT_DIR / 'all_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
