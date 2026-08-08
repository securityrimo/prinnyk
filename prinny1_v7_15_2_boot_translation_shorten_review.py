#!/usr/bin/env python3
"""Independently review the applied V7.15.2 BOOT shortening queue."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_user_only.csv"
BACKUP = QUEUE.with_name("boot_executable_translation_queue_v7_15_2_user_only.before_shortening_75970acf.csv")
CANONICAL = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_corrected.csv"
CHANGES = ROOT / "workspace/reports/prinny1_v7_15_2_boot_translation_shortening/approved_shortening_changes.csv"
BUILD_REPORT = ROOT / "workspace/reports/prinny1_v7_15_2_boot_translation_shortening/all_report.json"
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
BASE_ISO = ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
CURRENT_ISO = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui/prinny_korean_v7_15_1_full_text_internal_ui.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_2_boot_translation_shortening_review"
EXPECTED_QUEUE_SHA256 = "293efcb219632ce1a8f95143d0a629e28445c2d4eb83a663fded9ee100d4ca61"
EXPECTED_BACKUP_SHA256 = "75970acf7f3eb14e0f8067c8ab89f93941f0f1077048e922302548e41b8c130b"
EXPECTED_CANONICAL_SHA256 = "f0987986cf4e2ceb1c6760374a5378237e15e3b6e35417e079ef4b12d1dd47b5"
EXPECTED_CHANGES_SHA256 = "6b6e21aeac105c0938bce9c9ea7f9acde314bb432d7e1fa5a07eb96ea354e859"
EXPECTED_BASE_ISO_SHA256 = "bd5168a461adfd4a41b8daf9dfe6037d7a9838ab2fc8ee0affd1e0f5521bd5b5"
EXPECTED_CURRENT_ISO_SHA256 = "98411d6861c0cc9cc6b34672915786426fc2260ea005b7ba13ac0d75aac7e7d8"
PLACEHOLDER = re.compile(r"%(?:\d+\$)?(?:0\d+)?[sd]")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def encode(text: str, mapping: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        output.extend(mapping[character] if character in mapping else character.encode("cp932"))
    return bytes(output)


def decode(payload: bytes, reverse: dict[bytes, str]) -> str:
    output: list[str] = []
    cursor = 0
    while cursor < len(payload):
        pair = payload[cursor:cursor + 2]
        if pair in reverse:
            output.append(reverse[pair])
            cursor += 2
            continue
        first = payload[cursor]
        size = 2 if 0x81 <= first <= 0x9F or 0xE0 <= first <= 0xFC else 1
        output.append(payload[cursor:cursor + size].decode("cp932"))
        cursor += size
    return "".join(output)


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    expected_hashes = {
        QUEUE: EXPECTED_QUEUE_SHA256,
        BACKUP: EXPECTED_BACKUP_SHA256,
        CANONICAL: EXPECTED_CANONICAL_SHA256,
        CHANGES: EXPECTED_CHANGES_SHA256,
        BASE_ISO: EXPECTED_BASE_ISO_SHA256,
        CURRENT_ISO: EXPECTED_CURRENT_ISO_SHA256,
    }
    for path, expected in expected_hashes.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"독립 검토 입력 해시 불일치: {path}")

    queue_fields, queue_rows = read_rows(QUEUE)
    _, backup_rows = read_rows(BACKUP)
    canonical_fields, all_canonical_rows = read_rows(CANONICAL)
    _, change_rows = read_rows(CHANGES)
    canonical_rows = [row for row in all_canonical_rows if row["status"] == "needs_user_translation"]
    if queue_fields != canonical_fields:
        raise ValueError("최종 큐 스키마가 기준 스키마와 다릅니다.")
    if len(queue_rows) != 542 or len(backup_rows) != 542 or len(canonical_rows) != 542 or len(change_rows) != 56:
        raise ValueError("독립 검토 행 수가 봉인 범위와 다릅니다.")

    queue_by_id = {row["id"]: row for row in queue_rows}
    backup_by_id = {row["id"]: row for row in backup_rows}
    canonical_by_id = {row["id"]: row for row in canonical_rows}
    changes_by_id = {row["id"]: row for row in change_rows}
    for table in (queue_by_id, backup_by_id, canonical_by_id, changes_by_id):
        if len(table) not in (56, 542):
            raise ValueError("독립 검토 ID 중복이 발견됐습니다.")
    if set(queue_by_id) != set(backup_by_id) or set(queue_by_id) != set(canonical_by_id):
        raise ValueError("최종·백업·기준 ID 집합이 다릅니다.")

    document = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    mapping = {str(row["hangul"]): bytes.fromhex(str(row["sjis"])) for row in document["allocations"]}
    reverse = {value: key for key, value in mapping.items()}
    if len(mapping) != 980 or len(reverse) != 980:
        raise ValueError("980자 코드맵이 유일하지 않습니다.")

    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    current_boot = read_iso_file(CURRENT_ISO, find_iso_file(CURRENT_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    translation_changes: set[str] = set()
    old_overflow: set[str] = set()
    total_saved = 0
    ranges: list[tuple[int, int, str]] = []
    nul_boundaries = 0
    newline_substrings: set[str] = set()
    metadata_fields = [field for field in canonical_fields if field != "user_translation_korean"]

    for identifier, final in queue_by_id.items():
        before = backup_by_id[identifier]
        canonical = canonical_by_id[identifier]
        for field in metadata_fields:
            if final[field] != canonical[field]:
                raise ValueError(f"기준 메타데이터 불일치: {identifier}/{field}")
        old_text = before["user_translation_korean"]
        new_text = final["user_translation_korean"]
        old_payload = encode(old_text, mapping)
        new_payload = encode(new_text, mapping)
        slot = int(canonical["byte_length"])
        if len(old_payload) + 2 > slot:
            old_overflow.add(identifier)
        if len(new_payload) + 2 > slot:
            raise ValueError(f"최종 슬롯 용량 초과: {identifier}")
        if decode(new_payload, reverse) != new_text:
            raise ValueError(f"최종 인코딩 왕복 실패: {identifier}")
        if PLACEHOLDER.findall(canonical["source_japanese"]) != PLACEHOLDER.findall(new_text):
            raise ValueError(f"최종 플레이스홀더 불일치: {identifier}")
        if old_text != new_text:
            translation_changes.add(identifier)
            total_saved += len(old_payload) - len(new_payload)
            declared = changes_by_id.get(identifier)
            if declared is None or declared["before"] != old_text or declared["after"] != new_text:
                raise ValueError(f"축약 변경 명세 불일치: {identifier}")

        offset = int(canonical["offset_hex"], 0)
        source = bytes.fromhex(canonical["base_bytes_hex"])
        if len(source) != slot or base_boot[offset:offset + slot] != source:
            raise ValueError(f"기준 BOOT 원문 바이트 불일치: {identifier}")
        if source.decode("shift_jis") != canonical["source_japanese"]:
            raise ValueError(f"기준 BOOT 원문 디코드 불일치: {identifier}")
        if current_boot[offset:offset + slot].hex() != canonical["current_bytes_hex"]:
            raise ValueError(f"현재 BOOT 바이트 불일치: {identifier}")
        boundary = base_boot[offset + slot]
        if boundary == 0:
            nul_boundaries += 1
        elif boundary == 0x0A:
            newline_substrings.add(identifier)
        else:
            raise ValueError(f"기준 BOOT 문자열 경계 불일치: {identifier}")
        ranges.append((offset, offset + slot, identifier))

    if old_overflow != translation_changes or translation_changes != set(changes_by_id):
        raise ValueError("기존 초과·실제 번역 변경·변경 명세 집합이 다릅니다.")
    for previous, current in zip(sorted(ranges), sorted(ranges)[1:]):
        if current[0] < previous[1]:
            raise ValueError(f"문자열 범위 겹침: {previous[2]}/{current[2]}")
    if newline_substrings != {"P1-V7.15.2-BOOT-0387", "P1-V7.15.2-BOOT-0388"}:
        raise ValueError("복합 포맷 문자열의 줄바꿈 부분 문자열 집합이 다릅니다.")

    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if build["artifacts"]["queue_sha256"] != sha256_file(QUEUE) or build["verified"]["overflow_after"] != 0:
        raise ValueError("축약 적용 보고서와 최종 큐가 다릅니다.")

    report = {
        "format": "prinny1_v7_15_2_boot_translation_shortening_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in expected_hashes},
        "verified": {
            "queue_rows": len(queue_rows),
            "translation_changes": len(translation_changes),
            "unchanged_translations": len(queue_rows) - len(translation_changes),
            "overflow_before": len(old_overflow),
            "overflow_after": 0,
            "total_payload_bytes_saved": total_saved,
            "source_slots_reextracted": len(queue_rows),
            "nul_terminated_source_slots": nul_boundaries,
            "newline_delimited_composite_substrings": len(newline_substrings),
            "encoding_roundtrips": len(queue_rows),
            "placeholder_mismatches": 0,
            "range_overlaps": 0,
            "metadata_mismatches": 0,
        },
        "checks": {
            "independent_input_hashes": True,
            "only_previous_overflows_changed": True,
            "all_final_strings_fit_with_two_nul_bytes": True,
            "canonical_metadata_fully_restored": True,
            "base_and_current_boot_reextracted": True,
            "build_report_matches_output": True,
            "composite_format_substrings_not_granted_direct_write_authority": True,
            "iso_modified": False,
        },
        "patch_planning_requirements": [
            {
                "ids": sorted(newline_substrings),
                "requirement": "Preserve and repack each complete newline-delimited format string; do not emit independent NUL-terminated writes for these substrings."
            }
        ],
        "status": "pass_shortening_queue_ready_composite_format_rows_must_be_grouped",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"translation changes: {len(translation_changes)}")
    print(f"payload bytes saved: {total_saved}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
