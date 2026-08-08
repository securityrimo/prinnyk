#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

from core.font_runtime import FontRuntime
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_boot_translation_plan import (
    BOOT,
    BOOT_SHA256,
    GROUPS,
    LABELS,
    TRANSLATION_CSV,
    TRANSLATION_SHA256,
    align4,
    normalize_ascii,
    virtual_address,
)


ROOT = Path(__file__).resolve().parent
SOURCE_START = (
    ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/start.dat"
)
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
RUNTIME_REPORT = ROOT / "workspace/reports/prinny1_v7_14_15_runtime_test/all_report.json"
XDELTA_AUDIT = ROOT / "workspace/reports/prinny1_v7_14_15_xdelta_import_audit/all_report.json"
QA_ROWS = ROOT / "workspace/reports/prinny_qa/qa_rows.csv"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_16_boot_alias_plan"
SOURCE_START_SHA256 = "04e434d982189bd2d37bd2d664f892ef7aef04fb7b86dc3b395ff36798a8134f"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"빈 CSV입니다: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def alias_codes(count: int) -> list[bytes]:
    codes: list[bytes] = []
    lead = 0xF0
    trail = 0x40
    while len(codes) < count:
        if trail == 0x7F:
            trail += 1
            continue
        if trail > 0xFC:
            lead += 1
            trail = 0x40
            continue
        if lead > 0xFC:
            raise ValueError("F0 계열 별칭 코드 용량이 부족합니다.")
        codes.append(bytes((lead, trail)))
        trail += 1
    return codes


def encode_alias(text: str, aliases: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        encoded = aliases.get(character)
        if encoded is None:
            encoded = character.encode("cp932")
        if len(encoded) != 2:
            raise ValueError(f"2바이트가 아닌 BOOT 적용 문자: {character!r}")
        output.extend(encoded)
    return bytes(output)


def main() -> int:
    for path in (
        SOURCE_START, ALLOCATION, RUNTIME_REPORT, XDELTA_AUDIT,
        QA_ROWS, TRANSLATION_CSV, BOOT,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(SOURCE_START) != SOURCE_START_SHA256:
        raise ValueError("V7.14.14 START 해시가 고정값과 다릅니다.")
    if sha256_file(TRANSLATION_CSV) != TRANSLATION_SHA256:
        raise ValueError("사용자 번역 CSV 봉인 해시가 다릅니다.")
    if sha256_file(BOOT) != BOOT_SHA256:
        raise ValueError("기준 BOOT 해시가 다릅니다.")
    runtime = json.loads(RUNTIME_REPORT.read_text(encoding="utf-8"))
    if runtime.get("final_verdict") != "BLOCKER":
        raise ValueError("V7.14.15 런타임 실패 근거가 봉인되지 않았습니다.")
    xdelta = json.loads(XDELTA_AUDIT.read_text(encoding="utf-8"))
    if not xdelta["font_coupling"]["candidate_uses_separate_f0_f5_code_range"]:
        raise ValueError("xdelta F0~F5 참고 근거가 없습니다.")

    with TRANSLATION_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        translations = {row["id"]: row["translation_korean"] for row in csv.DictReader(handle)}
    ordered_texts = [translations[str(group["id"])] for group in GROUPS]
    ordered_texts.extend(translations[group_id] for group_id, *_rest in LABELS)
    hangul_order: list[str] = []
    for text in ordered_texts:
        for character in text:
            if "가" <= character <= "힣" and character not in hangul_order:
                hangul_order.append(character)
    if len(hangul_order) != 54:
        raise ValueError(f"BOOT 사용자 문구 한글 수가 54자가 아닙니다: {len(hangul_order)}")

    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    allocation_by_char = {row["hangul"]: row for row in allocation["allocations"]}
    missing = [character for character in hangul_order if character not in allocation_by_char]
    if missing:
        raise ValueError(f"980자 배정표에 없는 BOOT 문자: {missing}")

    archive = StartRuntimeArchive.load(SOURCE_START)
    records = {record.output_name.casefold(): record for record in archive.records}
    fnt_record = records["font.fnt"]
    font_fnt = archive.data[fnt_record.data_offset:fnt_record.end_offset]
    table = FontRuntime._parse_fnt(font_fnt)
    codes = alias_codes(len(hangul_order))
    aliases = dict(zip(hangul_order, codes))
    alias_rows: list[dict[str, Any]] = []
    table_indices: list[int] = []
    glyph_indices: list[int] = []
    for character, code in zip(hangul_order, codes):
        allocation_row = allocation_by_char[character]
        source_code = bytes.fromhex(allocation_row["sjis"])
        source_index = FontRuntime.table_index_from_sjis(source_code)
        alias_index = FontRuntime.table_index_from_sjis(code)
        glyph_index = int(allocation_row["glyph_index"])
        if table[source_index] != glyph_index:
            raise ValueError(f"현재 글리프 연결 불일치: {character}")
        if table[alias_index] != 0:
            raise ValueError(
                f"F0 별칭 대상이 비어 있지 않습니다: {character}/{code.hex(' ').upper()}"
            )
        table_indices.append(alias_index)
        glyph_indices.append(glyph_index)
        alias_rows.append(
            {
                "sequence": len(alias_rows) + 1,
                "hangul": character,
                "unicode": f"U+{ord(character):04X}",
                "source_sjis": source_code.hex(" ").upper(),
                "alias_sjis": code.hex(" ").upper(),
                "alias_table_index_hex": f"0x{alias_index:04X}",
                "glyph_index_hex": f"0x{glyph_index:04X}",
                "source_mapping_preserved": "yes",
                "wording_changed": "no",
            }
        )
    if table_indices != list(range(table_indices[0], table_indices[0] + len(table_indices))):
        raise ValueError("54개 F0 별칭 테이블 인덱스가 연속되지 않습니다.")

    fnt_start = 2 + table_indices[0] * 2
    fnt_end = fnt_start + len(table_indices) * 2
    before_fnt = font_fnt[fnt_start:fnt_end]
    after_fnt = b"".join(struct.pack("<H", glyph) for glyph in glyph_indices)
    if before_fnt != bytes(len(before_fnt)):
        raise ValueError("F0 별칭 font.fnt 원본 범위가 0이 아닙니다.")

    with QA_ROWS.open("r", encoding="utf-8-sig", newline="") as handle:
        qa = list(csv.DictReader(handle))
    alias_set = set(codes)
    trusted_alias_hits = 0
    for row in qa:
        key = row["resource"].casefold()
        record = records.get(key)
        if record is None:
            continue
        offset = int(row["offset"], 0)
        capacity = int(row["capacity_bytes"])
        blob = archive.data[record.data_offset + offset:record.data_offset + offset + capacity]
        trusted_alias_hits += sum(
            blob[index:index + 2] in alias_set for index in range(0, len(blob) - 1, 2)
        )
    if trusted_alias_hits:
        raise ValueError(f"기존 QA 텍스트에 F0 별칭 코드가 존재합니다: {trusted_alias_hits}")

    boot = BOOT.read_bytes()
    writes: list[dict[str, Any]] = [
        {
            "group_id": "G025",
            "logical_id": "P1-BOOT-F0-ALIASES-54",
            "layer": "START.DAT/font.fnt",
            "target": "font.fnt",
            "offset_hex": f"0x{fnt_start:X}",
            "write_span": len(after_fnt),
            "expected_before_hex": before_fnt.hex().upper(),
            "write_after_hex": after_fnt.hex().upper(),
            "change_kind": "difficulty_ui_f0_alias_table",
            "wording_changed": "no",
            "user_wording_approval": "yes_translation_csv",
            "expected_write_confirmed": "yes",
        }
    ]
    layout_rows: list[dict[str, Any]] = []
    for group in GROUPS:
        group_id = str(group["id"])
        translated_lines = tuple(group["translation_lines"])
        if " ".join(translated_lines) != translations[group_id]:
            raise ValueError(f"줄 배치가 사용자 번역과 다릅니다: {group_id}")
        block_start = int(group["block_start"])
        block_end = int(group["block_end"])
        new_block = bytearray(block_end - block_start)
        new_offsets: list[int] = []
        cursor = block_start
        for order, line in enumerate(translated_lines, start=1):
            normalized = normalize_ascii(line)
            payload = encode_alias(normalized, aliases)
            cursor = align4(cursor)
            relative = cursor - block_start
            end = relative + len(payload) + 2
            if end > len(new_block):
                raise ValueError(f"BOOT 블록 용량 초과: {group_id}/{order}")
            new_block[relative:relative + len(payload)] = payload
            new_offsets.append(cursor)
            reverse_aliases = {value: key for key, value in aliases.items()}
            decoded_parts: list[str] = []
            for index in range(0, len(payload), 2):
                pair = payload[index:index + 2]
                decoded_parts.append(
                    reverse_aliases[pair] if pair in reverse_aliases else pair.decode("cp932")
                )
            decoded = "".join(decoded_parts)
            if decoded != normalized:
                raise ValueError(f"F0 별칭 왕복 실패: {group_id}/{order}")
            layout_rows.append(
                {
                    "group_id": group_id,
                    "line_order": order,
                    "translation_verbatim_line": line,
                    "mechanical_fullwidth_line": normalized,
                    "payload_bytes": len(payload),
                    "new_offset_hex": f"0x{cursor:X}",
                    "new_virtual_address_hex": f"0x{virtual_address(cursor):08X}",
                    "alias_roundtrip": "yes",
                    "wording_changed": "no",
                }
            )
            cursor += len(payload) + 2
        writes.append(
            {
                "group_id": "G025",
                "logical_id": f"{group_id}-F0-BLOCK",
                "layer": "PSP_GAME/SYSDIR/BOOT.BIN",
                "target": "PSP_GAME/SYSDIR/BOOT.BIN",
                "offset_hex": f"0x{block_start:X}",
                "write_span": len(new_block),
                "expected_before_hex": boot[block_start:block_end].hex().upper(),
                "write_after_hex": bytes(new_block).hex().upper(),
                "change_kind": "user_translation_f0_alias_block_repack",
                "wording_changed": "no",
                "user_wording_approval": "yes_translation_csv",
                "expected_write_confirmed": "yes",
            }
        )
        for order, (pointer_offset, new_offset) in enumerate(zip(group["pointer_offsets"], new_offsets), start=1):
            pointer_offset = int(pointer_offset)
            before = boot[pointer_offset:pointer_offset + 4]
            after = struct.pack("<I", virtual_address(new_offset))
            if before != after:
                writes.append(
                    {
                        "group_id": "G025",
                        "logical_id": f"{group_id}-PTR-{order}",
                        "layer": "PSP_GAME/SYSDIR/BOOT.BIN",
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
        normalized = normalize_ascii(translations[group_id])
        payload = encode_alias(normalized, aliases)
        reverse_aliases = {value: key for key, value in aliases.items()}
        decoded = "".join(
            reverse_aliases[payload[index:index + 2]]
            if payload[index:index + 2] in reverse_aliases
            else payload[index:index + 2].decode("cp932")
            for index in range(0, len(payload), 2)
        )
        if decoded != normalized:
            raise ValueError(f"BOOT 레이블 F0 별칭 왕복 실패: {group_id}")
        before = boot[offset:offset + span]
        source_payload = source_text.encode("cp932")
        if before[:len(source_payload)] != source_payload or any(before[len(source_payload):]):
            raise ValueError(f"BOOT 레이블 원문 불일치: {group_id}")
        if len(payload) + 2 > span:
            raise ValueError(f"BOOT 레이블 용량 초과: {group_id}")
        after = payload + bytes(span - len(payload))
        writes.append(
            {
                "group_id": "G025",
                "logical_id": f"{group_id}-F0-LABEL",
                "layer": "PSP_GAME/SYSDIR/BOOT.BIN",
                "target": "PSP_GAME/SYSDIR/BOOT.BIN",
                "offset_hex": f"0x{offset:X}",
                "write_span": span,
                "expected_before_hex": before.hex().upper(),
                "write_after_hex": after.hex().upper(),
                "change_kind": "user_translation_f0_alias_label",
                "wording_changed": "no",
                "user_wording_approval": "yes_translation_csv",
                "expected_write_confirmed": "yes",
            }
        )
        layout_rows.append(
            {
                "group_id": group_id,
                "line_order": 1,
                "translation_verbatim_line": translations[group_id],
                "mechanical_fullwidth_line": normalized,
                "payload_bytes": len(payload),
                "new_offset_hex": f"0x{offset:X}",
                "new_virtual_address_hex": f"0x{virtual_address(offset):08X}",
                "alias_roundtrip": "yes",
                "wording_changed": "no",
            }
        )

    boot_writes = sorted(
        (row for row in writes if row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN"),
        key=lambda row: int(row["offset_hex"], 0),
    )
    simulated_boot = bytearray(boot)
    declared_boot: set[int] = set()
    for row in boot_writes:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if simulated_boot[offset:offset + len(before)] != before:
            raise ValueError(f"BOOT before 재검증 실패: {row['logical_id']}")
        simulated_boot[offset:offset + len(after)] = after
        declared_boot.update(
            offset + index for index, (old, new) in enumerate(zip(before, after)) if old != new
        )
    actual_boot = {
        index for index, (old, new) in enumerate(zip(boot, simulated_boot)) if old != new
    }
    if actual_boot != declared_boot:
        raise ValueError("BOOT 실제 변경 범위가 선언과 다릅니다.")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(REPORT_DIR / "alias_mapping.csv", alias_rows)
    write_csv(REPORT_DIR / "layout_validation.csv", layout_rows)
    write_csv(
        REPORT_DIR / "expected_write_confirmed.csv",
        [writes[0], *boot_writes],
    )
    report = {
        "format": "prinny1_v7_14_16_boot_alias_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "translation_csv": str(TRANSLATION_CSV),
            "translation_csv_sha256": sha256_file(TRANSLATION_CSV),
            "allocation_980": str(ALLOCATION),
            "allocation_980_sha256": sha256_file(ALLOCATION),
            "source_start": str(SOURCE_START),
            "source_start_sha256": sha256_file(SOURCE_START),
            "source_boot": str(BOOT),
            "source_boot_sha256": sha256_file(BOOT),
            "runtime_blocker": str(RUNTIME_REPORT),
            "runtime_blocker_sha256": sha256_file(RUNTIME_REPORT),
            "xdelta_reference": str(XDELTA_AUDIT),
            "xdelta_reference_sha256": sha256_file(XDELTA_AUDIT),
        },
        "alias": {
            "character_count": len(alias_rows),
            "first_sjis": alias_rows[0]["alias_sjis"],
            "last_sjis": alias_rows[-1]["alias_sjis"],
            "font_fnt_offset_hex": f"0x{fnt_start:X}",
            "font_fnt_write_span": len(after_fnt),
            "trusted_qa_text_hits_before_write": trusted_alias_hits,
            "existing_scattered_mappings_preserved": True,
            "font_txp_extra_writes": 0,
        },
        "patch": {
            "expected_write_count": 1 + len(boot_writes),
            "font_fnt_write_count": 1,
            "boot_write_count": len(boot_writes),
            "boot_changed_bytes": len(actual_boot),
            "simulated_boot_sha256": sha256_bytes(bytes(simulated_boot)),
        },
        "checks": {
            "user_wording_preserved": True,
            "xdelta_wording_imported": False,
            "all_54_alias_codes_unique": len(set(codes)) == 54,
            "all_alias_targets_were_zero": before_fnt == bytes(len(before_fnt)),
            "all_aliases_point_to_existing_verified_glyphs": True,
            "existing_source_mappings_unchanged": True,
            "trusted_qa_alias_collisions": 0,
            "all_boot_strings_alias_roundtrip": True,
            "actual_boot_changes_equal_declared": True,
            "iso_created": False,
        },
        "status": "expected_writes_confirmed_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"F0 aliases: {len(alias_rows)} ({alias_rows[0]['alias_sjis']}..{alias_rows[-1]['alias_sjis']})")
    print(f"Expected Writes: {1 + len(boot_writes)} (font.fnt 1, BOOT {len(boot_writes)})")
    print(f"BOOT changed bytes: {len(actual_boot)}")
    print("user wording changed: no")
    print("ISO created: no")
    print(f"report: {REPORT_DIR / 'all_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
