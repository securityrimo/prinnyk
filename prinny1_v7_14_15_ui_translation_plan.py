#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
TRANSLATION_CSV = (
    ROOT / "workspace/translations/ui_v7_14_15/title_difficulty_translation.csv"
)
BOOT = ROOT / "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
ALLOCATION = ROOT / "workspace/font/audited_allocation_977/hangul_allocation.json"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_ui_translation_plan"

EXPECTED_ROWS = {
    "P1-UI-TITLE-001": ("title", "はじめから", "texture", None),
    "P1-UI-TITLE-002": ("title", "つづきから", "texture", None),
    "P1-UI-TITLE-003": ("title", "設定", "texture", None),
    "P1-UI-TITLE-004": ("title", "データ交換", "texture", None),
    "P1-UI-DIFFICULTY-001": ("difficulty", "難しさ設定", "texture", None),
    "P1-UI-DIFFICULTY-002": (
        "difficulty", "スタンダード", "executable_or_texture", 12
    ),
    "P1-UI-DIFFICULTY-003": (
        "difficulty", "魔界公式ルール", "executable_or_texture", 14
    ),
    "P1-UI-DIFFICULTY-004": (
        "difficulty",
        "魔界公認のやみつき難易度。敵に１回でも接触するとアウト！",
        "executable_multislot",
        58,
    ),
    "P1-UI-DIFFICULTY-005": (
        "difficulty",
        "基本的な難易度。敵と接触しても、３回まではセーフ。",
        "executable_multislot",
        50,
    ),
    "P1-UI-DIFFICULTY-006": (
        "difficulty",
        "【解説】難易度によって、イベントやエンディングが変化することはありません。"
        "また、ゲームの途中で難易度を変更することもできます。",
        "executable_multislot",
        128,
    ),
}

# payload_capacity excludes each slot's terminating NUL bytes.
BOOT_SLOTS = (
    ("P1-UI-DIFFICULTY-004", 1, 0xEE3AC, 18, "魔界公認のやみつき"),
    ("P1-UI-DIFFICULTY-004", 2, 0xEE3C0, 20, "難易度。敵に１回でも"),
    ("P1-UI-DIFFICULTY-004", 3, 0xEE3D8, 20, "接触するとアウト！　"),
    ("P1-UI-DIFFICULTY-005", 1, 0xEE3F0, 16, "基本的な難易度。"),
    ("P1-UI-DIFFICULTY-005", 2, 0xEE404, 20, "敵と接触しても、３回"),
    ("P1-UI-DIFFICULTY-005", 3, 0xEE41C, 14, "まではセーフ。"),
    (
        "P1-UI-DIFFICULTY-006",
        1,
        0xEE42C,
        62,
        "【解説】難易度によって、イベントやエンディングが変化することは",
    ),
    (
        "P1-UI-DIFFICULTY-006",
        2,
        0xEE46C,
        66,
        "　ありません。また、ゲームの途中で難易度を変更することもできます。",
    ),
    ("P1-UI-DIFFICULTY-003", 1, 0xEEA94, 14, "魔界公式ルール"),
    ("P1-UI-DIFFICULTY-002", 1, 0xEEAA4, 12, "スタンダード"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"빈 CSV를 생성할 수 없습니다: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def normalize_ascii(text: str) -> str:
    output = []
    for character in text:
        if character == " ":
            output.append("\u3000")
        elif 0x21 <= ord(character) <= 0x7E:
            output.append(chr(ord(character) + 0xFEE0))
        else:
            output.append(character)
    return "".join(output)


def load_mapping() -> dict[str, bytes]:
    document = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    mapping = {
        str(row["hangul"]): bytes.fromhex(str(row["sjis"]))
        for row in document["allocations"]
    }
    if len(mapping) != 977 or len(set(mapping.values())) != 977:
        raise ValueError("977자 코드맵의 키 또는 값이 유일하지 않습니다.")
    return mapping


def encode_character(character: str, mapping: dict[str, bytes]) -> bytes | None:
    if character in mapping:
        return mapping[character]
    try:
        return character.encode("cp932")
    except UnicodeEncodeError:
        return None


def main() -> int:
    for path in (TRANSLATION_CSV, BOOT, ALLOCATION):
        if not path.is_file():
            raise FileNotFoundError(path)

    with TRANSLATION_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != len(EXPECTED_ROWS):
        raise ValueError("번역 CSV 행 수가 원본 템플릿과 다릅니다.")
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(EXPECTED_ROWS):
        raise ValueError("번역 CSV ID가 누락·중복·변경됐습니다.")

    mapping = load_mapping()
    validation_rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for row in rows:
        row_id = row["id"]
        screen, source, kind, maximum = EXPECTED_ROWS[row_id]
        if row["screen"] != screen or row["source_japanese"] != source:
            raise ValueError(f"보호 열이 변경됐습니다: {row_id}")
        if row["target_kind"] != kind:
            raise ValueError(f"target_kind가 변경됐습니다: {row_id}")
        csv_maximum = (
            None
            if not row["max_encoded_bytes"].strip()
            else int(float(row["max_encoded_bytes"]))
        )
        if csv_maximum != maximum:
            raise ValueError(f"max_encoded_bytes가 변경됐습니다: {row_id}")

        translation = row["translation_korean"]
        normalized = normalize_ascii(translation)
        encoded_parts = [encode_character(character, mapping) for character in normalized]
        missing = list(
            dict.fromkeys(
                character
                for character, encoded in zip(normalized, encoded_parts)
                if encoded is None
            )
        )
        encoded_bytes = sum(
            2 if part is None else len(part) for part in encoded_parts
        )
        encoding_ready = not missing
        two_byte = not missing and all(len(part) == 2 for part in encoded_parts if part)
        capacity_ok = maximum is None or encoded_bytes <= maximum
        location_status = (
            "unresolved_texture_location"
            if kind == "texture"
            else "boot_verified_texture_link_pending"
            if kind == "executable_or_texture"
            else "boot_slots_verified"
        )

        row_blockers: list[str] = []
        if not translation:
            row_blockers.append("translation_empty")
        if missing:
            row_blockers.append("missing_glyphs:" + "".join(missing))
        if not capacity_ok:
            row_blockers.append(f"slot_capacity_exceeded:{encoded_bytes}>{maximum}")
        if kind == "texture":
            row_blockers.append("texture_location_unresolved")
        elif kind == "executable_or_texture":
            row_blockers.append("runtime_texture_link_unverified")

        result = {
            "id": row_id,
            "source_japanese": source,
            "translation_korean_verbatim": translation,
            "mechanical_fullwidth_preview": normalized,
            "character_count": len(normalized),
            "encoded_bytes": encoded_bytes,
            "max_encoded_bytes": "" if maximum is None else maximum,
            "capacity_ok": "yes" if capacity_ok else "no",
            "missing_glyphs": "".join(missing),
            "encoding_ready": "yes" if encoding_ready else "no",
            "all_characters_two_bytes": "yes" if two_byte else "no",
            "location_status": location_status,
            "expected_write_confirmed": "no",
            "blockers": ";".join(row_blockers),
        }
        validation_rows.append(result)
        if row_blockers:
            blockers.append({"id": row_id, "reasons": row_blockers})

    boot = BOOT.read_bytes()
    slot_rows: list[dict[str, Any]] = []
    for group_id, order, offset, capacity, source in BOOT_SLOTS:
        expected = source.encode("cp932")
        if len(expected) != capacity:
            raise AssertionError(f"선언된 원문 길이가 다릅니다: {group_id}/{order}")
        actual = boot[offset : offset + capacity]
        terminator = boot[offset + capacity : offset + capacity + 2]
        match = actual == expected and terminator == b"\x00\x00"
        if not match:
            raise ValueError(f"BOOT 원문 또는 NUL 검증 실패: {group_id}/{order}")
        slot_rows.append(
            {
                "group_id": group_id,
                "slot_order": order,
                "target": "PSP_GAME/SYSDIR/BOOT.BIN",
                "offset_hex": f"0x{offset:X}",
                "payload_capacity": capacity,
                "source_japanese": source,
                "source_hex": expected.hex().upper(),
                "terminator_hex": terminator.hex().upper(),
                "source_bytes_match": "yes",
                "expected_write_confirmed": "no",
            }
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(REPORT_DIR / "translation_validation.csv", validation_rows)
    write_csv(REPORT_DIR / "boot_slot_validation.csv", slot_rows)
    report = {
        "format": "prinny1_v7_14_15_ui_translation_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "translation_csv": str(TRANSLATION_CSV),
            "translation_csv_sha256": sha256(TRANSLATION_CSV),
            "boot": str(BOOT),
            "boot_size": BOOT.stat().st_size,
            "boot_sha256": sha256(BOOT),
            "allocation": str(ALLOCATION),
            "allocation_sha256": sha256(ALLOCATION),
        },
        "checks": {
            "translation_rows": len(rows),
            "all_ids_unique_and_complete": True,
            "protected_source_columns_unchanged": True,
            "filled_translations": sum(bool(row["translation_korean"]) for row in rows),
            "boot_slots_source_and_terminators_match": True,
            "translation_wording_modified_by_codex": False,
            "expected_writes_created": False,
            "iso_created": False,
        },
        "blockers": blockers,
        "status": "blocked_before_expected_writes" if blockers else "ready_for_expected_writes",
        "next_action": (
            "사용자가 용량 초과 번역을 수정하고, 누락 글리프와 텍스처 위치를 해결한 뒤 "
            "Expected Write를 별도로 확정한다."
        ),
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"번역 행: {len(rows)} (작성 {report['checks']['filled_translations']})")
    print(f"차단 행: {len(blockers)}")
    for blocker in blockers:
        print(f"- {blocker['id']}: {', '.join(blocker['reasons'])}")
    print("Expected Writes: 0")
    print("ISO 생성: 없음")
    print(f"보고서: {REPORT_DIR / 'all_report.json'}")
    return 2 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
