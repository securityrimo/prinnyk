#!/usr/bin/env python3
"""Build and seal user-priority Demo00 dialogue resources on the V7.15.11 base.

The forced-xdelta Demo00 layout is authoritative.  Only dialogue fields in which
the forced-xdelta candidate actually uses its Korean F0-F5 encoding are eligible.
User wording is selected by default; real slot overflow and clearly malformed
Prinny speech endings fall back to the exact xdelta field bytes.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import struct
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as font_builder
from core.font_runtime import FontRuntime
from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_8_prologue_repair_plan import load_start_resource
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_3_xdelta_translation_select import load_codebook
from prinny1_v7_15_4_ui_image_export import system_records


ROOT = Path(__file__).resolve().parent
ORIGINAL_ISO = ROOT / "game.iso"
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
USER_FONT_ISO = ROOT / "workspace/build/prinny1_v7_14_22_coherent_f0/prinny_korean_v7_14_22_coherent_f0.iso"
PARALLEL = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/parallel_slots.csv"
PARTIAL_CODEBOOK = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/candidate_codebook_partial.csv"
CANDIDATE_DEMO = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start_resources/Demo00.dat"
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_15_user_dialogue_plan"
SELECTION_DIR = ROOT / "workspace/translations/selected_v7_15_15"

EXPECTED = {
    ORIGINAL_ISO: "af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03",
    BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    USER_FONT_ISO: "fd460bbc0057a738712b2fcf7adaee985c13a156529fff5179e7e6a54cc77510",
    PARALLEL: "89949915a81e712662bd49729b77af86cc20ee9a0a2b9a377e63c80420488944",
    PARTIAL_CODEBOOK: "f1ac6829d2c07450f6433b0daa95d413b85aaf1ed8b2ece22bcd5dcf2a5387a3",
    CANDIDATE_DEMO: "a924ecd354997275c6107e98cc8f5c6f077d7e550be0ffda5a5b748a56c09541",
    ALLOCATION: "f35f9bdac9c07c867e40b72e71323b16928b8dfdeb34de99420db289a49291f3",
}

RECORD_SIZE = 0x84
DIALOGUE_FIELDS = {0x1C, 0x3F}
PIXEL_OFFSET = font_builder.TXP_PIXEL_OFFSET
BYTES_PER_GLYPH = font_builder.BYTES_PER_GLYPH
BAD_PRINNY_ENDING = re.compile(r"거슴|슴네|깜까|슴가|슴네요")

# This source sentence says that the speaker will return the sweets.  Both the
# old user line ("돌려주는거슴") and the raw xdelta imperative reverse the or
# obscure the action direction, so use the shortest user-terminology correction.
CURATED = {
    (1306, 0x1C): ("궁극의 디저트 돌려드림다.", "speaker_action_direction_and_prinny_register"),
}

VOICE_PROFILES = {
    "prinny_family": {
        "source_markers": ["ッス", "っス"],
        "preferred_korean": ["슴다", "임다", "함다", "십쇼", "검까", "임까"],
        "rejected_machine_endings": ["거슴", "슴네", "깜까", "슴가", "슴네요"],
        "rule": "행동 주체와 문장 기능을 유지하며 프리니식 군대 존대를 사용",
    },
    "etna": {"rule": "거친 반말·명령형과 과장된 감정 표현을 유지"},
    "asagi": {"rule": "장면에 따른 존댓말·반말을 보존하고 프리니 어미로 바꾸지 않음"},
    "other_named_speakers": {"rule": "고유 말버릇과 원문의 문장 기능을 우선"},
}


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"빈 CSV 산출물: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def is_hangul(character: str) -> bool:
    return "가" <= character <= "힣"


def measure(text: str) -> int:
    return sum(2 if is_hangul(character) else len(character.encode("cp932")) for character in text)


def has_xdelta_korean(payload: bytes) -> bool:
    payload = payload.split(b"\0", 1)[0]
    return any(0xF0 <= value <= 0xF5 for value in payload)


def decode_japanese(payload: bytes) -> str:
    return payload.split(b"\0", 1)[0].decode("cp932", errors="replace")


def decode_candidate(payload: bytes, mapping: dict[str, str]) -> str:
    payload = payload.split(b"\0", 1)[0]
    output: list[str] = []
    cursor = 0
    while cursor < len(payload):
        lead = payload[cursor]
        pair_code = payload[cursor:cursor + 2].hex().upper() if cursor + 1 < len(payload) else ""
        if pair_code in mapping:
            output.append(mapping[pair_code])
            cursor += 2
        elif 0xF0 <= lead <= 0xF5 and cursor + 1 < len(payload):
            code = payload[cursor:cursor + 2].hex().upper()
            output.append(mapping.get(code, f"□{code}"))
            cursor += 2
        elif (0x81 <= lead <= 0x9F or 0xE0 <= lead <= 0xEF) and cursor + 1 < len(payload):
            output.append(payload[cursor:cursor + 2].decode("cp932", errors="replace"))
            cursor += 2
        elif lead < 0x80:
            output.append(chr(lead))
            cursor += 1
        elif 0xA1 <= lead <= 0xDF:
            output.append(bytes((lead,)).decode("cp932"))
            cursor += 1
        else:
            output.append(f"□{lead:02X}")
            cursor += 1
    return "".join(output)


def preferred_reverse(mapping: dict[str, str], candidate_demo: bytes) -> dict[str, str]:
    frequency: Counter[str] = Counter()
    cursor = 0
    while cursor + 1 < len(candidate_demo):
        if 0xF0 <= candidate_demo[cursor] <= 0xF5:
            frequency[candidate_demo[cursor:cursor + 2].hex().upper()] += 1
            cursor += 2
        else:
            cursor += 1
    candidates: dict[str, list[str]] = {}
    for code, character in mapping.items():
        candidates.setdefault(character, []).append(code)
    return {
        character: sorted(codes, key=lambda code: (-frequency[code], code))[0]
        for character, codes in candidates.items()
    }


def encode_text(text: str, reverse: dict[str, str], extension: dict[str, str]) -> bytes:
    output = bytearray()
    for character in text:
        if is_hangul(character):
            code = reverse.get(character) or extension.get(character)
            if code is None:
                raise ValueError(f"인코딩 코드가 없는 적용 문자: {character}")
            output.extend(bytes.fromhex(code))
        else:
            output.extend(character.encode("cp932"))
    return bytes(output)


def start_from_iso(iso: Path) -> tuple[bytes, bytes, list[dict[str, Any]], dict[str, Any]]:
    system = read_iso_file(iso, find_iso_file(iso, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    lzs = system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    start, header = decompress_buffer(lzs)
    return system, start, rows, header


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("고정 크기 데이터 길이가 달라졌습니다.")
    return {index for index, (left, right) in enumerate(zip(before, after)) if left != right}


def lzs_overlap_count(stream: bytes) -> int:
    _raw, header = decompress_buffer(stream)
    flag = int(header["flag"])
    cursor, end = 0x10, int(header["compressed_end"])
    count = 0
    while cursor < end:
        token = stream[cursor]
        cursor += 1
        if token != flag:
            continue
        second = stream[cursor]
        cursor += 1
        if second == flag:
            continue
        length = stream[cursor]
        cursor += 1
        distance = second if second < flag else second - 1
        count += int(length > distance)
    return count


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.15 입력 해시 불일치: {path}")

    mapping, _trusted = load_codebook()
    if len(mapping) != 777 or len(set(mapping.values())) != 770:
        raise ValueError("전체 xdelta 코드북 통계가 달라졌습니다.")
    candidate_demo = CANDIDATE_DEMO.read_bytes()
    reverse = preferred_reverse(mapping, candidate_demo)
    parallel_rows = [
        row for row in read_csv(PARALLEL)
        if row["resource"].casefold() == "demo00.dat"
        and int(row["offset"], 0) % RECORD_SIZE in DIALOGUE_FIELDS
    ]
    if len(parallel_rows) != 2561 or len({int(row["offset"], 0) for row in parallel_rows}) != 2561:
        raise ValueError("Demo00 대사 슬롯 범위가 달라졌습니다.")

    base_system, base_start, system_rows, old_header = start_from_iso(BASE_ISO)
    archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    records = {row.output_name.casefold(): row for row in archive.records}
    demo_record = records["demo00.dat"]
    fnt_record = records["font.fnt"]
    txp_record = records["font.txp"]
    base_demo = base_start[demo_record.data_offset:demo_record.end_offset]
    base_fnt = base_start[fnt_record.data_offset:fnt_record.end_offset]
    base_txp = base_start[txp_record.data_offset:txp_record.end_offset]
    original_demo = load_start_resource(ORIGINAL_ISO, "Demo00.dat")
    if len(base_demo) != len(candidate_demo) or len(base_demo) != len(original_demo) or len(base_demo) != 207520:
        raise ValueError("Demo00.dat 기준 크기가 달라졌습니다.")

    used_rows = [row for row in parallel_rows if has_xdelta_korean(bytes.fromhex(row["candidate_payload_hex"]))]
    held_rows = [row for row in parallel_rows if row not in used_rows]
    if len(used_rows) != 2556 or len(held_rows) != 5:
        raise ValueError("xdelta 실사용/보류 대사 슬롯 수가 달라졌습니다.")

    # Determine which user-selected characters need deterministic glyph slots.
    provisional: list[dict[str, Any]] = []
    needed_missing: set[str] = set()
    overflow_count = 0
    voice_fallback_count = 0
    curated_count = 0
    for row in parallel_rows:
        offset = int(row["offset"], 0)
        record_index, field_offset = divmod(offset, RECORD_SIZE)
        capacity = int(row["capacity_bytes"])
        candidate_payload = bytes.fromhex(row["candidate_payload_hex"])
        if len(candidate_payload) != capacity or candidate_demo[offset:offset + capacity] != candidate_payload:
            raise ValueError(f"xdelta 슬롯 근거 불일치: 0x{offset:X}")
        source_record = original_demo[record_index * RECORD_SIZE:(record_index + 1) * RECORD_SIZE]
        field_end = 0x3F if field_offset == 0x1C else RECORD_SIZE
        absolute_field_end = record_index * RECORD_SIZE + field_end
        candidate_nul = candidate_demo.find(b"\0", offset, absolute_field_end)
        base_nul = base_demo.find(b"\0", offset, absolute_field_end)
        if candidate_nul < 0 or base_nul < 0:
            raise ValueError(f"대사 필드 NUL 종료가 없습니다: 0x{offset:X}")
        # The old QA capacity can end in the middle of a longer forced-xdelta
        # string.  User text must fit that declared capacity, while the write
        # span safely clears through both actual current/xdelta terminators.
        span = max(capacity, candidate_nul - offset, base_nul - offset)
        if offset + span >= absolute_field_end:
            raise ValueError(f"대사 쓰기 범위가 필드 경계를 넘습니다: 0x{offset:X}")
        if candidate_demo[offset + span] != 0 or base_demo[offset + span] != 0:
            raise ValueError(f"실제 대사 NUL 경계 불일치: 0x{offset + span:X}")
        candidate_full = candidate_demo[offset:candidate_nul]
        source_text = decode_japanese(source_record[field_offset:field_end])
        speaker_jp = decode_japanese(source_record[0x0A:0x1C])
        user_text = row["user_translation"]
        user_size = measure(user_text)
        candidate_used = has_xdelta_korean(candidate_payload)
        if not candidate_used:
            decision, reason, selected_text = "hold_xdelta_unused", "xdelta_does_not_use_this_dialogue_slot", ""
        elif user_size > capacity:
            decision, reason, selected_text = "xdelta_overflow", "user_payload_exceeds_declared_slot", decode_candidate(candidate_full, mapping)
            overflow_count += 1
        elif (record_index, field_offset) in CURATED:
            selected_text, reason = CURATED[(record_index, field_offset)]
            decision = "curated_user_voice"
            curated_count += 1
        elif ("ッス" in source_text or "っス" in source_text) and BAD_PRINNY_ENDING.search(user_text):
            decision, reason, selected_text = "xdelta_voice_fallback", "malformed_prinny_machine_ending", decode_candidate(candidate_full, mapping)
            voice_fallback_count += 1
        else:
            decision, reason, selected_text = "user", "user_translation_primary", user_text
        if decision in {"user", "curated_user_voice"}:
            if measure(selected_text) > capacity:
                raise ValueError(f"선택 문구 슬롯 초과: 0x{offset:X}/{measure(selected_text)}/{capacity}")
            needed_missing.update(character for character in selected_text if is_hangul(character) and character not in reverse)
        provisional.append({
            "row": row,
            "offset": offset,
            "record_index": record_index,
            "field_offset": field_offset,
            "capacity": capacity,
            "span": span,
            "candidate_payload": candidate_payload,
            "candidate_full": candidate_full,
            "source_text": source_text,
            "speaker_jp": speaker_jp,
            "user_text": user_text,
            "user_size": user_size,
            "candidate_used": candidate_used,
            "decision": decision,
            "reason": reason,
            "selected_text": selected_text,
        })
    if overflow_count != 0:
        raise ValueError(f"재검증상 예상하지 않은 사용자 슬롯 초과: {overflow_count}")

    allocation_rows = json.loads(ALLOCATION.read_text(encoding="utf-8"))["allocations"]
    allocation_by_char = {row["hangul"]: row for row in allocation_rows}
    if not needed_missing <= set(allocation_by_char):
        raise ValueError(f"검증 사용자 폰트에 없는 문자: {''.join(sorted(needed_missing - set(allocation_by_char)))}")
    base_table = FontRuntime._parse_fnt(base_fnt)
    table_references = Counter(base_table)
    safe_slots = [
        row for row in allocation_rows
        if int(row["audit"]["trusted_text_hits"]) == 0
        and table_references[base_table[int(row["table_index"])]] == 1
    ]
    if len(safe_slots) != 535 or len(safe_slots) < len(needed_missing):
        raise ValueError(f"안전 글리프 슬롯 부족: {len(safe_slots)}/{len(needed_missing)}")

    _font_system, font_start, _font_system_rows, _font_header = start_from_iso(USER_FONT_ISO)
    font_archive = StartRuntimeArchive.from_bytes(font_start)
    font_records = {row.output_name.casefold(): row for row in font_archive.records}
    source_fnt = font_start[font_records["font.fnt"].data_offset:font_records["font.fnt"].end_offset]
    source_txp = font_start[font_records["font.txp"].data_offset:font_records["font.txp"].end_offset]
    source_table = FontRuntime._parse_fnt(source_fnt)
    final_txp = bytearray(base_txp)
    extension: dict[str, str] = {}
    glyph_rows: list[dict[str, Any]] = []
    for sequence, (character, slot) in enumerate(zip(sorted(needed_missing), safe_slots), 1):
        target_code = slot["sjis"].replace(" ", "").upper()
        target_table_index = int(slot["table_index"])
        target_glyph = base_table[target_table_index]
        source_allocation = allocation_by_char[character]
        source_table_index = int(source_allocation["table_index"])
        source_glyph = source_table[source_table_index]
        target_offset = PIXEL_OFFSET + target_glyph * BYTES_PER_GLYPH
        source_offset = PIXEL_OFFSET + source_glyph * BYTES_PER_GLYPH
        before = base_txp[target_offset:target_offset + BYTES_PER_GLYPH]
        after = source_txp[source_offset:source_offset + BYTES_PER_GLYPH]
        if len(before) != BYTES_PER_GLYPH or len(after) != BYTES_PER_GLYPH or not any(after) or before == after:
            raise ValueError(f"글리프 복사 근거 불일치: {character}")
        final_txp[target_offset:target_offset + BYTES_PER_GLYPH] = after
        extension[character] = target_code
        glyph_rows.append({
            "sequence": sequence,
            "character": character,
            "unicode": f"U+{ord(character):04X}",
            "encoded_code": target_code,
            "target_table_index_hex": f"0x{target_table_index:04X}",
            "target_glyph_index": target_glyph,
            "source_glyph_index": source_glyph,
            "replaced_original_character": slot["replaces"],
            "trusted_text_hits": slot["audit"]["trusted_text_hits"],
            "glyph_offset_hex": f"0x{target_offset:X}",
            "expected_before_hex": before.hex().upper(),
            "write_after_hex": after.hex().upper(),
        })

    patched_demo = bytearray(base_demo)
    audit_rows: list[dict[str, Any]] = []
    dialogue_writes: list[dict[str, Any]] = []
    decision_counts: Counter[str] = Counter()
    selected_extension_characters: set[str] = set()
    xdelta_unused_offsets: set[int] = set()
    for item in provisional:
        offset, capacity, span = item["offset"], item["capacity"], item["span"]
        before = base_demo[offset:offset + span]
        decision = item["decision"]
        if decision == "hold_xdelta_unused":
            after = before
            xdelta_unused_offsets.add(offset)
        elif decision in {"xdelta_overflow", "xdelta_voice_fallback"}:
            after = item["candidate_full"] + bytes(span - len(item["candidate_full"]))
        else:
            payload = encode_text(item["selected_text"], reverse, extension)
            if len(payload) > capacity:
                raise ValueError(f"최종 인코딩 슬롯 초과: 0x{offset:X}")
            after = payload + bytes(span - len(payload))
            if decode_candidate(after, mapping | {code: char for char, code in extension.items()}) != item["selected_text"]:
                raise ValueError(f"최종 인코딩 왕복 실패: 0x{offset:X}")
            selected_extension_characters.update(character for character in item["selected_text"] if character in extension)
        if len(after) != span or offset + span > len(patched_demo):
            raise ValueError(
                f"대사 고정 쓰기 범위 불일치: 0x{offset:X}/after={len(after)}/span={span}/end={offset + span}"
            )
        patched_demo[offset:offset + span] = after
        decision_counts[decision] += 1
        speaker_record = base_demo[item["record_index"] * RECORD_SIZE:(item["record_index"] + 1) * RECORD_SIZE]
        audit_rows.append({
            "record_index": item["record_index"],
            "field_offset_hex": f"0x{item['field_offset']:X}",
            "resource_offset_hex": f"0x{offset:X}",
            "speaker_japanese": item["speaker_jp"],
            "speaker_korean_partial_decode": decode_candidate(speaker_record[0x0A:0x1C], mapping),
            "source_japanese": item["source_text"],
            "xdelta_translation_partial_decode": decode_candidate(item["candidate_full"], mapping),
            "current_v7_15_11_partial_decode": decode_candidate(before, mapping),
            "user_translation": item["user_text"],
            "selected_translation_or_partial_decode": item["selected_text"],
            "decision": decision,
            "reason": item["reason"],
            "xdelta_uses_korean": "yes" if item["candidate_used"] else "no",
            "capacity_bytes": capacity,
            "expected_write_span": span,
            "user_payload_bytes": item["user_size"],
            "selected_payload_bytes": len(after.split(b"\0", 1)[0]),
            "remaining_bytes": capacity - len(after.split(b"\0", 1)[0]),
            "required_extension_characters": "".join(sorted({c for c in item["selected_text"] if c in extension})),
            "changed_from_v7_15_11": "yes" if after != before else "no",
        })
        if after != before:
            dialogue_writes.append({
                "logical_id": f"P1-V7.15.15-DIALOGUE-{len(dialogue_writes) + 1:04d}",
                "layer": "START.DAT/Demo00.dat",
                "target": "Demo00.dat",
                "offset_hex": f"0x{offset:X}",
                "write_span": span,
                "expected_before_hex": before.hex().upper(),
                "write_after_hex": after.hex().upper(),
                "change_kind": decision,
                "expected_write_confirmed": "yes",
            })

    held_items = [item for item in provisional if item["decision"] == "hold_xdelta_unused"]
    if any(
        bytes(patched_demo)[item["offset"]:item["offset"] + item["span"]]
        != base_demo[item["offset"]:item["offset"] + item["span"]]
        for item in held_items
    ):
        raise ValueError("xdelta 미사용 슬롯이 변경됐습니다.")
    if selected_extension_characters != needed_missing:
        raise ValueError("필요 글리프와 실제 선택 글리프 집합이 다릅니다.")
    if len(patched_demo) != len(base_demo):
        raise ValueError(f"Demo00.dat 길이 변경: {len(base_demo)}->{len(patched_demo)}")
    if len(final_txp) != len(base_txp):
        raise ValueError(f"font.txp 길이 변경: {len(base_txp)}->{len(final_txp)}")

    final_start = bytearray(base_start)
    final_start[demo_record.data_offset:demo_record.end_offset] = patched_demo
    final_start[txp_record.data_offset:txp_record.end_offset] = final_txp
    for record in archive.records:
        before_resource = base_start[record.data_offset:record.end_offset]
        after_resource = bytes(final_start[record.data_offset:record.end_offset])
        if record.output_name.casefold() not in {"demo00.dat", "font.txp"} and before_resource != after_resource:
            raise ValueError(f"비대상 START 자원 변경: {record.output_name}")
    if bytes(final_start[fnt_record.data_offset:fnt_record.end_offset]) != base_fnt:
        raise ValueError("font.fnt는 변경하지 않아야 합니다.")

    start_row = next(row for row in system_rows if row["name"].casefold() == "start.lzs")
    old_lzs = base_system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]]
    if lzs_overlap_count(old_lzs) != 0:
        raise ValueError("V7.15.11 부모 LZS에 겹침 역참조가 있습니다.")
    new_lzs = compress_buffer_runtime_safe(bytes(final_start), old_lzs[:4], int(old_header["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start) or lzs_overlap_count(new_lzs) != 0:
        raise ValueError("V7.15.15 런타임 안전 LZS 왕복 실패")
    next_offset = system_rows[start_row["index"] + 1]["data_offset"]
    capacity = next_offset - start_row["data_offset"]
    if len(new_lzs) > capacity:
        raise ValueError(f"V7.15.15 START.LZS 슬롯 초과: {len(new_lzs)}>{capacity}")
    final_system = bytearray(base_system)
    final_system[start_row["data_offset"]:next_offset] = bytes(capacity)
    final_system[start_row["data_offset"]:start_row["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))
    verified_system_rows = system_records(bytes(final_system))
    verified_start_row = next(row for row in verified_system_rows if row["name"].casefold() == "start.lzs")
    verified_start = decompress_buffer(bytes(final_system[verified_start_row["data_offset"]:verified_start_row["data_offset"] + verified_start_row["size"]]))[0]
    if verified_start != bytes(final_start):
        raise ValueError("최종 SYSTEM.DAT START 재추출 불일치")

    declared_demo = set()
    simulated_demo = bytearray(base_demo)
    for row in dialogue_writes:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if simulated_demo[offset:offset + len(before)] != before or len(before) != len(after):
            raise ValueError(f"대사 Expected Write before 불일치: {row['logical_id']}")
        simulated_demo[offset:offset + len(after)] = after
        declared_demo.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if bytes(simulated_demo) != bytes(patched_demo) or declared_demo != changed_offsets(base_demo, bytes(patched_demo)):
        raise ValueError("대사 Expected Write 재적용 불일치")
    declared_glyph = set()
    simulated_txp = bytearray(base_txp)
    for row in glyph_rows:
        offset = int(row["glyph_offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if simulated_txp[offset:offset + len(before)] != before:
            raise ValueError(f"글리프 Expected Write before 불일치: {row['character']}")
        simulated_txp[offset:offset + len(after)] = after
        declared_glyph.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if bytes(simulated_txp) != bytes(final_txp) or declared_glyph != changed_offsets(base_txp, bytes(final_txp)):
        raise ValueError("글리프 Expected Write 재적용 불일치")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SELECTION_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "SYSTEM.DAT": bytes(final_system),
        "start.dat": bytes(final_start),
        "start.lzs": new_lzs,
        "Demo00.dat": bytes(patched_demo),
        "font.txp": bytes(final_txp),
        "font.fnt": base_fnt,
    }
    for name, blob in artifacts.items():
        (OUTPUT / name).write_bytes(blob)
    selection_path = SELECTION_DIR / "demo00_user_priority_selection.csv"
    glyph_path = REPORT_DIR / "font_extension_slots.csv"
    dialogue_write_path = REPORT_DIR / "expected_dialogue_writes.csv"
    write_csv(selection_path, audit_rows)
    write_csv(glyph_path, glyph_rows)
    write_csv(dialogue_write_path, dialogue_writes)
    (REPORT_DIR / "voice_profiles.json").write_text(json.dumps(VOICE_PROFILES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "format": "prinny1_v7_15_15_user_dialogue_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_requested_xdelta_scope_and_data_authority_with_user_translation_priority_2026_08_01",
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "selection_policy": {
            "data_scope": "forced_xdelta_demo00_dialogue_fields_with_f0_f5_korean_only",
            "translation_priority": "user",
            "overflow_fallback": "exact_xdelta_field_bytes",
            "voice_fallback": "exact_xdelta_field_bytes_for_malformed_prinny_machine_endings",
            "curated_exceptions": len(CURATED),
            "xdelta_unused_fields": "held_byte_exact_from_v7_15_11",
        },
        "verified": {
            "dialogue_slot_count": len(parallel_rows),
            "xdelta_used_dialogue_slots": len(used_rows),
            "xdelta_unused_held_slots": len(held_rows),
            "decision_counts": dict(decision_counts),
            "user_slot_overflow_count": overflow_count,
            "voice_fallback_count": voice_fallback_count,
            "curated_count": curated_count,
            "dialogue_expected_write_count": len(dialogue_writes),
            "dialogue_changed_bytes": len(declared_demo),
            "full_codebook_codes": len(mapping),
            "full_codebook_characters": len(set(mapping.values())),
            "required_font_extension_characters": len(needed_missing),
            "safe_font_slot_pool": len(safe_slots),
            "font_changed_bytes": len(declared_glyph),
            "old_start_lzs_size": len(old_lzs),
            "new_start_lzs_size": len(new_lzs),
            "start_lzs_capacity": capacity,
            "start_lzs_margin": capacity - len(new_lzs),
            "lzs_overlaps": 0,
        },
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()} | {
            "selection_csv": sha256_file(selection_path),
            "font_extension_slots_csv": sha256_file(glyph_path),
            "expected_dialogue_writes_csv": sha256_file(dialogue_write_path),
            "voice_profiles_json": sha256_file(REPORT_DIR / "voice_profiles.json"),
        },
        "checks": {
            "all_xdelta_unused_dialogue_slots_held": True,
            "all_user_overflows_use_xdelta": True,
            "all_selected_user_text_encode_decode_roundtrip": True,
            "all_selected_text_fits_declared_slot": True,
            "font_fnt_unchanged": True,
            "extension_slots_have_zero_trusted_text_hits": True,
            "extension_target_glyphs_have_single_table_reference": True,
            "only_demo00_and_font_txp_changed_inside_start": True,
            "expected_writes_match_resource_diffs": True,
            "runtime_safe_lzs_non_overlap": True,
            "lzs_roundtrip": True,
            "base_iso_modified": False,
            "iso_created": False,
        },
        "caveat": "155자 이하의 추가 글리프는 검증 사용자 폰트 모양을 사용하므로 기존 xdelta 글꼴과 획 모양이 일부 다를 수 있음",
        "status": "user_dialogue_resources_sealed_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"dialogue slots: {len(parallel_rows)}, xdelta used: {len(used_rows)}, held: {len(held_rows)}")
    print(f"decisions: {dict(decision_counts)}")
    print(f"font extension: {len(needed_missing)} chars / safe pool {len(safe_slots)}")
    print(f"START.LZS: {len(old_lzs)} -> {len(new_lzs)} / {capacity}; overlaps 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
