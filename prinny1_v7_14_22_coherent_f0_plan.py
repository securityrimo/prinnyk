#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as font_builder
from core.font_runtime import FontRuntime
from core.lzs import compress_buffer, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_boot_translation_plan import (
    ELF_FILE_BASE,
    ELF_VIRTUAL_BASE,
    GROUPS,
    LABELS,
    align4,
    normalize_ascii,
    virtual_address,
)
from prinny1_v7_14_21_scoped_decoder_plan import (
    BASE_ISO,
    BASE_ISO_SHA256,
    CANDIDATE_BOOT,
    RANGES as DECODER_RANGES,
)
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_xdelta_codebook_recover import candidate_codes


ROOT = Path(__file__).resolve().parent
QA = ROOT / "workspace/reports/prinny_qa/qa_rows.csv"
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
UI_TRANSLATION = ROOT / "workspace/translations/ui_v7_14_15/title_difficulty_translation.csv"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_plan"
EXPECTED_ALLOCATION_COUNT = 980
EXPECTED_CODE_CAPACITY = 987


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def encode_text(text: str, mapping: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        encoded = mapping.get(character)
        if encoded is None:
            encoded = character.encode("cp932", errors="strict")
        output.extend(encoded)
    return bytes(output)


def decode_text(payload: bytes, reverse: dict[bytes, str]) -> str:
    output: list[str] = []
    offset = 0
    while offset < len(payload):
        pair = payload[offset:offset + 2]
        if pair in reverse:
            output.append(reverse[pair])
            offset += 2
            continue
        lead = payload[offset]
        if (0x81 <= lead <= 0x9F or 0xE0 <= lead <= 0xEF) and offset + 1 < len(payload):
            output.append(pair.decode("cp932"))
            offset += 2
        else:
            output.append(bytes((lead,)).decode("cp932"))
            offset += 1
    return "".join(output)


def expected_row(
    sequence: int,
    layer: str,
    logical_id: str,
    target: str,
    offset: int,
    before: bytes,
    after: bytes,
    change_kind: str,
) -> dict[str, Any]:
    if len(before) != len(after):
        raise ValueError(f"Expected Write 길이 불일치: {logical_id}")
    return {
        "sequence": sequence,
        "layer": layer,
        "logical_id": logical_id,
        "target": target,
        "offset_hex": f"0x{offset:X}",
        "write_span": len(before),
        "expected_before_hex": before.hex().upper(),
        "write_after_hex": after.hex().upper(),
        "change_kind": change_kind,
        "wording_changed": "no",
        "expected_write_confirmed": "yes",
    }


def main() -> int:
    for path in (BASE_ISO, CANDIDATE_BOOT, QA, ALLOCATION, UI_TRANSLATION):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(BASE_ISO) != BASE_ISO_SHA256:
        raise ValueError("V7.14.14 기준 ISO 해시가 다릅니다.")

    allocation_doc = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    allocations = allocation_doc["allocations"]
    codes = candidate_codes()
    if len(allocations) != EXPECTED_ALLOCATION_COUNT or len(codes) != EXPECTED_CODE_CAPACITY:
        raise ValueError("980자 배정 또는 987자 F0 코드 용량이 다릅니다.")
    mapping = {
        str(row["hangul"]): bytes.fromhex(code)
        for row, code in zip(allocations, codes)
    }
    reverse = {encoded: character for character, encoded in mapping.items()}
    if len(mapping) != EXPECTED_ALLOCATION_COUNT or len(reverse) != EXPECTED_ALLOCATION_COUNT:
        raise ValueError("새 F0 코드맵이 일대일이 아닙니다.")

    system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    candidate_boot = CANDIDATE_BOOT.read_bytes()
    start_entry = font_builder.parse_nispack_start_entry(system)
    lzs_offset = int(start_entry["data_offset"])
    old_lzs_size = int(start_entry["size"])
    old_lzs = system[lzs_offset:lzs_offset + old_lzs_size]
    start, _header = decompress_buffer(old_lzs)
    archive = StartRuntimeArchive.from_bytes(start, source=f"{BASE_ISO}!/start.dat")
    records = {record.output_name.casefold(): record for record in archive.records}
    font_record = records.get("font.fnt")
    if font_record is None:
        raise ValueError("START.DAT에 font.fnt가 없습니다.")

    patched_start = bytearray(start)
    patched_boot = bytearray(boot)
    rows: list[dict[str, Any]] = []
    codebook_rows: list[dict[str, Any]] = []
    sequence = 1

    # F0 코드 980개를 검증된 기존 Galmuri 글리프에 연결한다. font.txp는 쓰지 않는다.
    table_indices = [FontRuntime.table_index_from_sjis(bytes.fromhex(code)) for code in codes[:980]]
    alias_entries = list(zip(table_indices, allocations))
    alias_runs: list[list[tuple[int, dict[str, Any]]]] = []
    for table_index, allocation in alias_entries:
        if not alias_runs or table_index != alias_runs[-1][-1][0] + 1:
            alias_runs.append([])
        alias_runs[-1].append((table_index, allocation))
    if sum(map(len, alias_runs)) != 980:
        raise ValueError("F0 별칭 연속 구간 분할 수가 다릅니다.")
    for run_number, run in enumerate(alias_runs, 1):
        fnt_relative = 2 + run[0][0] * 2
        fnt_span = len(run) * 2
        fnt_absolute = int(font_record.data_offset) + fnt_relative
        fnt_before = start[fnt_absolute:fnt_absolute + fnt_span]
        fnt_after = b"".join(struct.pack("<H", int(row["glyph_index"])) for _, row in run)
        if len(fnt_before) != fnt_span or fnt_before == fnt_after:
            raise ValueError(f"font.fnt F0 별칭 입력이 잘못됐습니다: run {run_number}")
        patched_start[fnt_absolute:fnt_absolute + fnt_span] = fnt_after
        rows.append(expected_row(sequence, "START.DAT/font.fnt", f"P1-F0-ALIAS-980-RUN-{run_number:02d}", "font.fnt", fnt_relative, fnt_before, fnt_after, "coherent_f0_alias_to_existing_galmuri_glyphs"))
        sequence += 1
    for index, (allocation, code) in enumerate(zip(allocations, codes), 1):
        codebook_rows.append({
            "sequence": index,
            "hangul": allocation["hangul"],
            "unicode": allocation["unicode"],
            "f0_code": code,
            "table_index_hex": f"0x{FontRuntime.table_index_from_sjis(bytes.fromhex(code)):04X}",
            "existing_glyph_index_hex": f"0x{int(allocation['glyph_index']):04X}",
            "source": "current_audited_allocation_980",
            "candidate_wording_applied": "no",
        })
    for index, code in enumerate(codes[980:], 981):
        codebook_rows.append({
            "sequence": index,
            "hangul": "",
            "unicode": "",
            "f0_code": code,
            "table_index_hex": f"0x{FontRuntime.table_index_from_sjis(bytes.fromhex(code)):04X}",
            "existing_glyph_index_hex": "",
            "source": "reserved_unassigned",
            "candidate_wording_applied": "no",
        })

    qa_rows = read_csv(QA)
    if len(qa_rows) != 4110:
        raise ValueError(f"QA 슬롯 수가 4,110개가 아닙니다: {len(qa_rows)}")
    used_ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    roundtrip_count = 0
    qa_write_count = 0
    for qa in qa_rows:
        record = records.get(qa["resource"].casefold())
        if record is None:
            raise ValueError(f"START 자원 누락: {qa['resource']}")
        relative = int(qa["offset"], 0)
        capacity = int(qa["capacity_bytes"])
        encoded_bytes = int(qa["encoded_bytes"])
        translation = qa["translation"]
        payload = encode_text(translation, mapping)
        if len(payload) != encoded_bytes or len(payload) > capacity or decode_text(payload, reverse) != translation:
            raise ValueError(f"F0 인코딩 길이/왕복 실패: {qa['id']}")
        after_slot = payload + bytes(capacity - len(payload))
        absolute = int(record.data_offset) + relative
        if absolute + capacity > int(record.end_offset):
            raise ValueError(f"슬롯 경계 초과: {qa['id']}")
        for left, right in used_ranges[qa["resource"].casefold()]:
            if absolute < right and absolute + capacity > left:
                raise ValueError(f"QA 슬롯 중첩: {qa['id']}")
        used_ranges[qa["resource"].casefold()].append((absolute, absolute + capacity))
        before = start[absolute:absolute + capacity]
        if before != after_slot:
            patched_start[absolute:absolute + capacity] = after_slot
            rows.append(expected_row(sequence, f"START.DAT/{qa['resource']}", qa["id"], qa["resource"], relative, before, after_slot, "user_translation_coherent_f0_reencode"))
            sequence += 1
            qa_write_count += 1
        roundtrip_count += 1

    # 보스 진행 회귀를 일으킨 4개 전역 범위를 제외한 V21 디코더만 결합한다.
    for logical_id, offset, size, purpose in DECODER_RANGES:
        before = boot[offset:offset + size]
        after = candidate_boot[offset:offset + size]
        if patched_boot[offset:offset + size] != before or before == after:
            raise ValueError(f"디코더 before/after 오류: {logical_id}")
        patched_boot[offset:offset + size] = after
        rows.append(expected_row(sequence, "PSP_GAME/SYSDIR/BOOT.BIN", logical_id, "PSP_GAME/SYSDIR/BOOT.BIN", offset, before, after, purpose))
        sequence += 1

    translation_rows = {row["id"]: row for row in read_csv(UI_TRANSLATION)}
    for group in GROUPS:
        group_id = str(group["id"])
        translated_lines = tuple(group["translation_lines"])
        if " ".join(translated_lines) != translation_rows[group_id]["translation_korean"]:
            raise ValueError(f"사용자 BOOT 문구 불일치: {group_id}")
        block_start, block_end = int(group["block_start"]), int(group["block_end"])
        new_block = bytearray(block_end - block_start)
        new_offsets: list[int] = []
        cursor = block_start
        for line in translated_lines:
            normalized = normalize_ascii(line)
            payload = encode_text(normalized, mapping)
            if decode_text(payload, reverse) != normalized:
                raise ValueError(f"BOOT F0 왕복 실패: {group_id}")
            cursor = align4(cursor)
            relative = cursor - block_start
            if relative + len(payload) + 2 > len(new_block):
                raise ValueError(f"BOOT 블록 용량 초과: {group_id}")
            new_block[relative:relative + len(payload)] = payload
            new_offsets.append(cursor)
            cursor += len(payload) + 2
        before_block = boot[block_start:block_end]
        patched_boot[block_start:block_end] = new_block
        rows.append(expected_row(sequence, "PSP_GAME/SYSDIR/BOOT.BIN", f"{group_id}-F0-BLOCK", "PSP_GAME/SYSDIR/BOOT.BIN", block_start, before_block, bytes(new_block), "user_translation_coherent_f0_block"))
        sequence += 1
        for order, (pointer_offset, new_offset) in enumerate(zip(group["pointer_offsets"], new_offsets), 1):
            pointer_offset = int(pointer_offset)
            before = boot[pointer_offset:pointer_offset + 4]
            after = struct.pack("<I", virtual_address(new_offset))
            if before != after:
                patched_boot[pointer_offset:pointer_offset + 4] = after
                rows.append(expected_row(sequence, "PSP_GAME/SYSDIR/BOOT.BIN", f"{group_id}-PTR-{order}", "PSP_GAME/SYSDIR/BOOT.BIN", pointer_offset, before, after, "in_block_string_pointer_adjustment"))
                sequence += 1

    for group_id, offset, span, _source_text in LABELS:
        translation = translation_rows[group_id]["translation_korean"]
        normalized = normalize_ascii(translation)
        payload = encode_text(normalized, mapping)
        if decode_text(payload, reverse) != normalized or len(payload) + 2 > span:
            raise ValueError(f"BOOT 레이블 F0 왕복/용량 실패: {group_id}")
        before = boot[offset:offset + span]
        after = payload + bytes(span - len(payload))
        patched_boot[offset:offset + span] = after
        rows.append(expected_row(sequence, "PSP_GAME/SYSDIR/BOOT.BIN", f"{group_id}-F0-LABEL", "PSP_GAME/SYSDIR/BOOT.BIN", offset, before, after, "user_translation_coherent_f0_label"))
        sequence += 1

    # START 재압축 고정 슬롯과 모든 변경 집합을 쓰기 전에 확인한다.
    new_lzs = compress_buffer(bytes(patched_start), old_lzs[:4])
    decoded, _ = decompress_buffer(new_lzs)
    if decoded != bytes(patched_start) or len(new_lzs) > old_lzs_size:
        raise ValueError("START.LZS 왕복 또는 고정 슬롯 용량 실패")
    excluded = ((0x957B4, 4), (0x95814, 4), (0x9599C, 8), (0x959B0, 12))
    if any(patched_boot[o:o + n] != boot[o:o + n] for o, n in excluded):
        raise ValueError("V20 게임플레이 회귀 범위가 유입됐습니다.")
    if bytes(patched_start[int(records['font.txp'].data_offset):int(records['font.txp'].end_offset)]) != start[int(records['font.txp'].data_offset):int(records['font.txp'].end_offset)]:
        raise ValueError("font.txp가 변경됐습니다.")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    writes_path = OUTPUT / "expected_write_confirmed.csv"
    codebook_path = OUTPUT / "coherent_f0_codebook.csv"
    write_csv(writes_path, rows)
    write_csv(codebook_path, codebook_rows)
    report = {
        "format": "prinny1_v7_14_22_coherent_f0_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "base_iso": str(BASE_ISO), "base_iso_sha256": sha256_file(BASE_ISO),
            "qa": str(QA), "qa_sha256": sha256_file(QA),
            "allocation_980": str(ALLOCATION), "allocation_980_sha256": sha256_file(ALLOCATION),
            "ui_translation": str(UI_TRANSLATION), "ui_translation_sha256": sha256_file(UI_TRANSLATION),
            "candidate_boot_mechanism_sha256": sha256_file(CANDIDATE_BOOT),
        },
        "verified": {
            "f0_code_capacity": len(codes), "assigned_f0_code_count": len(mapping), "reserved_f0_code_count": len(codes) - len(mapping),
            "font_fnt_alias_run_count": len(alias_runs),
            "qa_slot_count": len(qa_rows), "qa_roundtrip_count": roundtrip_count, "qa_write_count": qa_write_count,
            "expected_write_count": len(rows), "new_lzs_size": len(new_lzs), "lzs_slot_size": old_lzs_size,
            "start_changed_bytes": sum(a != b for a, b in zip(start, patched_start)),
            "boot_changed_bytes": sum(a != b for a, b in zip(boot, patched_boot)),
        },
        "checks": {
            "all_user_text_preserved_verbatim": True,
            "all_user_text_encode_decode_roundtrip": True,
            "font_txp_byte_identical": True,
            "candidate_font_and_wording_imported": False,
            "scoped_decoder_only": True,
            "gameplay_regression_ranges_excluded": True,
            "start_lzs_roundtrip": True,
            "iso_created": False,
        },
        "preflight": {
            "patched_start_sha256": sha256_bytes(bytes(patched_start)),
            "patched_boot_sha256": sha256_bytes(bytes(patched_boot)),
            "new_lzs_sha256": sha256_bytes(new_lzs),
        },
        "artifacts": {
            "expected_writes": str(writes_path), "expected_writes_sha256": sha256_file(writes_path),
            "codebook": str(codebook_path), "codebook_sha256": sha256_file(codebook_path),
        },
        "status": "expected_writes_confirmed_independent_review_required",
        "final_verdict": "PASS",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"F0 aliases: {len(mapping)}/{len(codes)}")
    print(f"QA roundtrips: {roundtrip_count}/{len(qa_rows)}")
    print(f"Expected Writes: {len(rows)}")
    print(f"LZS capacity: {len(new_lzs)}/{old_lzs_size}")
    print("font.txp changed: no")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
