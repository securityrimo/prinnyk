#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
TRANSLATION_CSV = (
    ROOT / "workspace/translations/ui_v7_14_15/title_difficulty_translation.csv"
)
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
BOOT = ROOT / "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_boot_translation_plan"

TRANSLATION_SHA256 = "2099d8923f4854dc4bd46b8fd2c7e7a6188ed192eef4403746a61ecdf8198689"
BOOT_SHA256 = "3220c559596cc9e91db868284157622406110faa5e8c044c3824c8a138088415"
ELF_FILE_BASE = 0x54
ELF_VIRTUAL_BASE = 0x08804000

GROUPS = (
    {
        "id": "P1-UI-DIFFICULTY-004",
        "block_start": 0xEE3AC,
        "block_end": 0xEE3F0,
        "pointer_offsets": (0xDC904, 0xDC908, 0xDC90C),
        "source_lines": (
            "魔界公認のやみつき",
            "難易度。敵に１回でも",
            "接触するとアウト！　",
        ),
        "translation_lines": (
            "마계 공인 중독",
            "난이도! 한 번만",
            "스쳐도 아웃!",
        ),
    },
    {
        "id": "P1-UI-DIFFICULTY-005",
        "block_start": 0xEE3F0,
        "block_end": 0xEE42C,
        "pointer_offsets": (0xDC910, 0xDC914, 0xDC918),
        "source_lines": (
            "基本的な難易度。",
            "敵と接触しても、３回",
            "まではセーフ。",
        ),
        "translation_lines": (
            "기본 난이도.",
            "적과 닿아도",
            "3번까지는 세이프!",
        ),
    },
    {
        "id": "P1-UI-DIFFICULTY-006",
        "block_start": 0xEE42C,
        "block_end": 0xEE4B0,
        "pointer_offsets": (0xDC91C, 0xDC920),
        "source_lines": (
            "【解説】難易度によって、イベントやエンディングが変化することは",
            "　ありません。また、ゲームの途中で難易度を変更することもできます。",
        ),
        "translation_lines": (
            "【해설】 난이도에 따라 이벤트나 엔딩이 변하지는 않습니다.",
            "또한 게임 도중에도 난이도를 변경할 수 있습니다.",
        ),
    },
)

LABELS = (
    ("P1-UI-DIFFICULTY-003", 0xEEA94, 16, "魔界公式ルール"),
    ("P1-UI-DIFFICULTY-002", 0xEEAA4, 16, "スタンダード"),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalize_ascii(text: str) -> str:
    result = []
    for character in text:
        if character == " ":
            result.append("\u3000")
        elif 0x21 <= ord(character) <= 0x7E:
            result.append(chr(ord(character) + 0xFEE0))
        else:
            result.append(character)
    return "".join(result)


def load_mapping() -> tuple[dict[str, bytes], dict[bytes, str]]:
    document = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    mapping = {
        str(row["hangul"]): bytes.fromhex(str(row["sjis"]))
        for row in document["allocations"]
    }
    if len(mapping) != 980 or len(set(mapping.values())) != 980:
        raise ValueError("980자 확장 코드맵이 유일하지 않습니다.")
    return mapping, {encoded: character for character, encoded in mapping.items()}


def encode_text(text: str, mapping: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        if character in mapping:
            encoded = mapping[character]
        else:
            encoded = character.encode("cp932")
        if len(encoded) != 2:
            raise ValueError(f"2바이트가 아닌 적용 문자입니다: {character!r}")
        output.extend(encoded)
    return bytes(output)


def decode_text(payload: bytes, reverse: dict[bytes, str]) -> str:
    if len(payload) % 2:
        raise ValueError("홀수 바이트 문자열입니다.")
    output = []
    for offset in range(0, len(payload), 2):
        pair = payload[offset:offset + 2]
        output.append(reverse[pair] if pair in reverse else pair.decode("cp932"))
    return "".join(output)


def virtual_address(file_offset: int) -> int:
    return ELF_VIRTUAL_BASE + file_offset - ELF_FILE_BASE


def align4(value: int) -> int:
    return (value + 3) & ~3


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    for path in (TRANSLATION_CSV, ALLOCATION, BOOT):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(TRANSLATION_CSV) != TRANSLATION_SHA256:
        raise ValueError("사용자 번역 CSV가 봉인 해시와 다릅니다.")
    if sha256_file(BOOT) != BOOT_SHA256:
        raise ValueError("기준 BOOT.BIN이 봉인 해시와 다릅니다.")

    with TRANSLATION_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        translation_rows = {row["id"]: row for row in csv.DictReader(handle)}
    mapping, reverse = load_mapping()
    boot = BOOT.read_bytes()
    writes: list[dict[str, Any]] = []
    layout_rows: list[dict[str, Any]] = []

    for group in GROUPS:
        group_id = str(group["id"])
        source_lines = tuple(group["source_lines"])
        translated_lines = tuple(group["translation_lines"])
        user_translation = translation_rows[group_id]["translation_korean"]
        if " ".join(translated_lines) != user_translation:
            raise ValueError(f"줄 배치가 사용자 문구와 다릅니다: {group_id}")

        block_start = int(group["block_start"])
        block_end = int(group["block_end"])
        source_block = boot[block_start:block_end]
        for source_line, pointer_offset in zip(source_lines, group["pointer_offsets"]):
            pointer = struct.unpack_from("<I", boot, int(pointer_offset))[0]
            source_offset = ELF_FILE_BASE + pointer - ELF_VIRTUAL_BASE
            payload = source_line.encode("cp932")
            if boot[source_offset:source_offset + len(payload)] != payload:
                raise ValueError(f"원문 포인터 연결 실패: {group_id}")

        new_block = bytearray(block_end - block_start)
        new_offsets: list[int] = []
        cursor = block_start
        for order, line in enumerate(translated_lines, start=1):
            normalized = normalize_ascii(line)
            payload = encode_text(normalized, mapping)
            if decode_text(payload, reverse) != normalized:
                raise ValueError(f"인코딩 왕복 실패: {group_id}/{order}")
            cursor = align4(cursor)
            relative = cursor - block_start
            end = relative + len(payload) + 2
            if end > len(new_block):
                raise ValueError(f"연속 블록 용량 초과: {group_id}/{order}")
            new_block[relative:relative + len(payload)] = payload
            new_offsets.append(cursor)
            layout_rows.append(
                {
                    "group_id": group_id,
                    "line_order": order,
                    "translation_verbatim_line": line,
                    "mechanical_fullwidth_line": normalized,
                    "character_count": len(normalized),
                    "payload_bytes": len(payload),
                    "new_offset_hex": f"0x{cursor:X}",
                    "new_virtual_address_hex": f"0x{virtual_address(cursor):08X}",
                    "encode_decode_roundtrip": "yes",
                    "wording_changed": "no",
                    "spaces_replaced_by_line_break": "yes",
                }
            )
            cursor += len(payload) + 2

        after_block = bytes(new_block)
        if source_block == after_block:
            raise ValueError(f"블록 변경이 없습니다: {group_id}")
        writes.append(
            {
                "group_id": "G024",
                "logical_id": f"{group_id}-BLOCK",
                "target": "PSP_GAME/SYSDIR/BOOT.BIN",
                "offset_hex": f"0x{block_start:X}",
                "write_span": len(after_block),
                "expected_before_hex": source_block.hex().upper(),
                "write_after_hex": after_block.hex().upper(),
                "change_kind": "user_translation_contiguous_block_repack",
                "wording_changed": "no",
                "user_wording_approval": "yes_translation_csv",
                "expected_write_confirmed": "yes",
            }
        )
        for order, (pointer_offset, new_offset) in enumerate(
            zip(group["pointer_offsets"], new_offsets), start=1
        ):
            pointer_offset = int(pointer_offset)
            before = boot[pointer_offset:pointer_offset + 4]
            after = struct.pack("<I", virtual_address(new_offset))
            if before == after:
                continue
            writes.append(
                {
                    "group_id": "G024",
                    "logical_id": f"{group_id}-PTR-{order}",
                    "target": "PSP_GAME/SYSDIR/BOOT.BIN",
                    "offset_hex": f"0x{pointer_offset:X}",
                    "write_span": 4,
                    "expected_before_hex": before.hex().upper(),
                    "write_after_hex": after.hex().upper(),
                    "change_kind": "in_block_string_pointer_adjustment",
                    "wording_changed": "no",
                    "user_wording_approval": "yes_translation_csv",
                    "expected_write_confirmed": "yes",
                }
            )

    for group_id, offset, span, source_text in LABELS:
        translation = translation_rows[group_id]["translation_korean"]
        normalized = normalize_ascii(translation)
        payload = encode_text(normalized, mapping)
        if decode_text(payload, reverse) != normalized:
            raise ValueError(f"레이블 인코딩 왕복 실패: {group_id}")
        source_payload = source_text.encode("cp932")
        before = boot[offset:offset + span]
        if before[:len(source_payload)] != source_payload or any(before[len(source_payload):]):
            raise ValueError(f"레이블 원문/패딩 불일치: {group_id}")
        if len(payload) + 2 > span:
            raise ValueError(f"레이블 용량 초과: {group_id}")
        after = payload + bytes(span - len(payload))
        writes.append(
            {
                "group_id": "G024",
                "logical_id": f"{group_id}-LABEL",
                "target": "PSP_GAME/SYSDIR/BOOT.BIN",
                "offset_hex": f"0x{offset:X}",
                "write_span": span,
                "expected_before_hex": before.hex().upper(),
                "write_after_hex": after.hex().upper(),
                "change_kind": "user_translation_fixed_label",
                "wording_changed": "no",
                "user_wording_approval": "yes_translation_csv",
                "expected_write_confirmed": "yes",
            }
        )
        layout_rows.append(
            {
                "group_id": group_id,
                "line_order": 1,
                "translation_verbatim_line": translation,
                "mechanical_fullwidth_line": normalized,
                "character_count": len(normalized),
                "payload_bytes": len(payload),
                "new_offset_hex": f"0x{offset:X}",
                "new_virtual_address_hex": f"0x{virtual_address(offset):08X}",
                "encode_decode_roundtrip": "yes",
                "wording_changed": "no",
                "spaces_replaced_by_line_break": "no",
            }
        )

    ordered = sorted(writes, key=lambda row: int(row["offset_hex"], 0))
    for left, right in zip(ordered, ordered[1:]):
        if int(left["offset_hex"], 0) + int(left["write_span"]) > int(
            right["offset_hex"], 0
        ):
            raise ValueError(
                f"Expected Write 중첩: {left['logical_id']} / {right['logical_id']}"
            )
    simulated = bytearray(boot)
    declared: set[int] = set()
    for row in ordered:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(str(row["expected_before_hex"]))
        after = bytes.fromhex(str(row["write_after_hex"]))
        if simulated[offset:offset + len(before)] != before:
            raise ValueError(f"before 재검증 실패: {row['logical_id']}")
        simulated[offset:offset + len(after)] = after
        declared.update(
            offset + i for i, (old, new) in enumerate(zip(before, after)) if old != new
        )
    actual = {i for i, (old, new) in enumerate(zip(boot, simulated)) if old != new}
    if actual != declared or len(simulated) != len(boot):
        raise ValueError("BOOT 시뮬레이션 변경 범위가 선언과 다릅니다.")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(REPORT_DIR / "layout_validation.csv", layout_rows)
    write_csv(REPORT_DIR / "expected_write_confirmed.csv", ordered)
    report = {
        "format": "prinny1_v7_14_15_boot_translation_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "translation_csv": str(TRANSLATION_CSV),
            "translation_csv_sha256": sha256_file(TRANSLATION_CSV),
            "allocation": str(ALLOCATION),
            "allocation_sha256": sha256_file(ALLOCATION),
            "boot": str(BOOT),
            "boot_size": len(boot),
            "boot_sha256": sha256_bytes(boot),
        },
        "patch": {
            "translated_groups": [group["id"] for group in GROUPS],
            "translated_labels": [row[0] for row in LABELS],
            "expected_write_count": len(ordered),
            "changed_byte_count": len(actual),
            "output_boot_sha256": sha256_bytes(bytes(simulated)),
        },
        "checks": {
            "all_user_wording_exact_before_mechanical_layout": True,
            "ascii_only_mechanically_fullwidth": True,
            "all_strings_encode_decode_roundtrip": True,
            "all_characters_two_bytes": True,
            "all_repacked_strings_remain_in_original_blocks": True,
            "all_pointers_remain_in_original_blocks": True,
            "expected_writes_non_overlapping": True,
            "actual_changes_equal_declared_changes": True,
            "boot_size_preserved": True,
            "source_boot_unchanged": sha256_file(BOOT) == sha256_bytes(boot),
            "iso_created": False,
        },
        "runtime_pending": [
            "BOOT 레이블이 실제 난이도 선택 텍스처와 연결되는지 확인",
            "32자 첫 안내 줄과 10자 세 번째 일반 난이도 줄의 화면 폭 확인",
        ],
        "status": "boot_expected_writes_confirmed_runtime_validation_required",
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"번역 그룹: {len(GROUPS) + len(LABELS)}")
    print(f"Expected Writes: {len(ordered)}")
    print(f"변경 바이트: {len(actual)}")
    print("ISO 생성: 없음")
    print(f"보고서: {REPORT_DIR / 'all_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
