#!/usr/bin/env python3
"""Seal conservative character-voice revisions on the V7.15.4 xdelta baseline."""
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as font_builder
from core.font_runtime import FontRuntime
from core.lzs import compress_buffer_best, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_8_prologue_repair_plan import load_start_resource
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
ORIGINAL_ISO = ROOT / "game.iso"
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
CODEBOOK = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/candidate_codebook_partial.csv"
PARALLEL = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/parallel_slots.csv"
CANDIDATE_DEMO = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start_resources/Demo00.dat"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_5_character_voice_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_plan"
SELECTION_DIR = ROOT / "workspace/translations/selected_v7_15_5"

EXPECTED = {
    ORIGINAL_ISO: "af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03",
    BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    CODEBOOK: "f1ac6829d2c07450f6433b0daa95d413b85aaf1ed8b2ece22bcd5dcf2a5387a3",
    PARALLEL: "89949915a81e712662bd49729b77af86cc20ee9a0a2b9a377e63c80420488944",
    CANDIDATE_DEMO: "a924ecd354997275c6107e98cc8f5c6f077d7e550be0ffda5a5b748a56c09541",
}

# Only lines with a clear speaker-direction or speech-register defect are changed.
# Lines whose current wording already fits the character are deliberately absent.
REVISIONS = (
    (291, 0x1C, "프리니", "우왓, 지각임다!!", "prinny_signature_ending_restored"),
    (326, 0x3F, "프리니 부대", "다녀오겠슴다~.", "first_person_prinny_ending_restored"),
    (329, 0x1C, "프리니", "부탁임다.", "prinny_request_register_restored"),
    (329, 0x3F, "프리니", "순서 좀 양보해 주십쇼.", "prinny_request_register_restored"),
    (479, 0x1C, "프리니", "알겠슴다!", "affirmative_prinny_ending_restored"),
    (479, 0x3F, "프리니", "더 부르겠슴다!", "speaker_action_direction_restored"),
    (501, 0x1C, "프리니", "……수고하셨슴다.", "acknowledgement_not_command"),
    (1306, 0x1C, "프리니", "궁극의 스위츠 돌려드림다.", "speaker_action_direction_restored"),
    # The 10-byte field cannot hold 돌려드림다.; the shortest voice-preserving form is used.
    (1314, 0x3F, "프리니", "돌려드림.", "capacity_shortened_speaker_action_restored"),
    (1500, 0x1C, "아사기", "그 죽은 생선 눈인가요!?", "asagi_polite_register_restored"),
    (1501, 0x3F, "아사기", "펭귄 모습 그대로인가요!?", "asagi_polite_register_restored"),
)

VOICE_PROFILES = {
    "프리니/프리니 부대": {
        "source_markers": ["ッス", "っス"],
        "korean_register": ["~슴다", "~임다", "~함다", "~십쇼"],
        "rule": "행동 주체를 뒤집지 않고 프리니식 군대 존대를 유지",
    },
    "에트나": {
        "korean_register": ["거친 반말", "명령형", "상황에 따른 과장된 존댓말"],
        "rule": "현재 90개 대사는 문맥상 말투가 맞아 유지",
    },
    "아사기": {
        "korean_register": ["기본 반말", "선배 장면의 존댓말", "의도된 사투리 인격"],
        "rule": "ですか를 프리니식 임까로 바꾸지 않으며 의도된 다중 인격은 유지",
    },
    "기타": {
        "examples": ["파프리카~냥", "구르메 오거~구먼", "별그림자~요", "모브 병사 말버릇"],
        "rule": "현재 특징적 어미가 유지돼 변경하지 않음",
    },
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
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def decode_japanese(field: bytes) -> str:
    payload = field.split(b"\0", 1)[0]
    if payload and 0xC0 <= payload[0] < 0xE0:
        payload = payload[1:]
    return payload.decode("cp932", errors="replace")


def decode_candidate(field: bytes, mapping: dict[str, str]) -> str:
    payload = field.split(b"\0", 1)[0]
    cursor = 1 if payload and 0xC0 <= payload[0] < 0xE0 else 0
    output: list[str] = []
    while cursor < len(payload):
        lead = payload[cursor]
        if 0xF0 <= lead <= 0xF5 and cursor + 1 < len(payload):
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


def encode_text(text: str, reverse: dict[str, str]) -> bytes:
    output = bytearray()
    for character in text:
        if "가" <= character <= "힣":
            if character not in reverse:
                raise ValueError(f"확정 xdelta 코드가 없는 적용 문자: {character!r}")
            output.extend(bytes.fromhex(reverse[character]))
        else:
            output.extend(character.encode("cp932"))
    return bytes(output)


def has_candidate_hangul(field: bytes) -> bool:
    payload = field.split(b"\0", 1)[0]
    return any(0xF0 <= value <= 0xF5 for value in payload)


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("고정 크기 데이터 길이가 달라졌습니다.")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.5 입력 해시 불일치: {path}")

    codebook_rows = read_csv(CODEBOOK)
    mapping = {row["candidate_code"]: row["unicode_character"] for row in codebook_rows if row["unicode_character"]}
    reverse = {character: code for code, character in mapping.items()}
    if len(mapping) != 735 or len(reverse) != len(mapping):
        raise ValueError("통계 확정 xdelta 735자 코드맵이 일대일이 아닙니다.")

    parallel = {
        int(row["offset"], 0): row
        for row in read_csv(PARALLEL)
        if row["resource"].casefold() == "demo00.dat"
    }
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    start_entry = font_builder.parse_nispack_start_entry(base_system)
    lzs_offset, old_lzs_size = int(start_entry["data_offset"]), int(start_entry["size"])
    old_lzs = base_system[lzs_offset:lzs_offset + old_lzs_size]
    base_start, old_header = decompress_buffer(old_lzs)
    archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    records = {record.output_name.casefold(): record for record in archive.records}
    demo_record = records["demo00.dat"]
    base_demo = base_start[demo_record.data_offset:demo_record.end_offset]
    if base_demo != CANDIDATE_DEMO.read_bytes():
        raise ValueError("V7.15.4의 Demo00.dat이 xdelta 후보 기준과 다릅니다.")
    original_demo = load_start_resource(ORIGINAL_ISO, "Demo00.dat")
    if len(original_demo) != len(base_demo) or len(base_demo) != 207520:
        raise ValueError("Demo00.dat 고정 크기가 다릅니다.")

    patched_demo = bytearray(base_demo)
    selection_rows: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []
    changed_records: set[int] = set()
    used_characters: set[str] = set()
    for sequence, (record_index, field_offset, speaker_ko, text, reason) in enumerate(REVISIONS, 1):
        offset = record_index * 0x84 + field_offset
        row = parallel.get(offset)
        if row is None:
            raise ValueError(f"QA 슬롯을 찾지 못했습니다: 0x{offset:X}")
        declared_capacity = int(row["capacity_bytes"])
        if base_demo[offset:offset + declared_capacity].hex().upper() != row["candidate_payload_hex"].upper():
            raise ValueError(f"xdelta 슬롯 근거 불일치: 0x{offset:X}")
        field_end = record_index * 0x84 + (0x3F if field_offset == 0x1C else 0x84)
        current_nul = base_demo.find(b"\0", offset, field_end)
        if current_nul < 0:
            raise ValueError(f"xdelta 필드 NUL 종료가 없습니다: 0x{offset:X}")
        # The forced-xdelta wording can be longer than the older QA capacity.
        # Clear through the current xdelta terminator while still requiring the
        # replacement itself to fit the original QA capacity.
        span = max(declared_capacity, current_nul - offset)
        before = base_demo[offset:offset + span]
        if base_demo[offset + span] != 0:
            raise ValueError(f"슬롯 외부 NUL 경계 불일치: 0x{offset + span:X}")
        source_record = original_demo[record_index * 0x84:(record_index + 1) * 0x84]
        candidate_record = base_demo[record_index * 0x84:(record_index + 1) * 0x84]
        speaker_jp = decode_japanese(source_record[0x0A:0x1C])
        actual_speaker_ko = decode_candidate(candidate_record[0x0A:0x1C], mapping)
        expected_speaker_jp = {"프리니": "プリニー", "프리니 부대": "プリニー隊", "아사기": "アサギ"}[speaker_ko]
        if speaker_jp != expected_speaker_jp:
            raise ValueError(f"화자 귀속 불일치: #{record_index}/{speaker_jp}/{expected_speaker_jp}")
        payload = encode_text(text, reverse)
        if len(payload) > declared_capacity:
            raise ValueError(f"번역 슬롯 초과: 0x{offset:X}/{len(payload)}/{declared_capacity}")
        if decode_candidate(payload + b"\0", mapping) != text:
            raise ValueError(f"인코딩 왕복 실패: 0x{offset:X}")
        after = payload + bytes(span - len(payload))
        if after == before:
            raise ValueError(f"실제 변경이 없는 번역 후보: 0x{offset:X}")
        patched_demo[offset:offset + span] = after
        changed_records.add(record_index)
        used_characters.update(character for character in text if "가" <= character <= "힣")
        source_field = source_record[field_offset:(0x3F if field_offset == 0x1C else 0x84)]
        current_text = decode_candidate(before, mapping)
        selection_rows.append({
            "sequence": sequence,
            "record_index": record_index,
            "speaker_japanese": speaker_jp,
            "speaker_korean": speaker_ko,
            "resource_offset_hex": f"0x{offset:X}",
            "capacity_bytes": declared_capacity,
            "expected_write_span": span,
            "source_japanese": decode_japanese(source_field),
            "current_xdelta_korean_partial_decode": current_text,
            "replacement_korean": text,
            "encoded_bytes": len(payload),
            "remaining_bytes": declared_capacity - len(payload),
            "reason": reason,
            "decision": "replace_character_voice",
        })
        writes.append({
            "logical_id": f"P1-V7.15.5-VOICE-{sequence:03d}",
            "target": "START.DAT/Demo00.dat",
            "offset_hex": f"0x{offset:X}",
            "write_span": span,
            "expected_before_hex": before.hex().upper(),
            "write_after_hex": after.hex().upper(),
            "text": text,
            "change_kind": reason,
            "expected_write_confirmed": "yes",
        })

    ranges = sorted((int(row["offset_hex"], 0), int(row["write_span"])) for row in writes)
    if any(left + size > right for (left, size), (right, _) in zip(ranges, ranges[1:])):
        raise ValueError("Demo00.dat Expected Write 범위가 겹칩니다.")
    simulated = bytearray(base_demo)
    declared_changes: set[int] = set()
    for row in writes:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if simulated[offset:offset + len(before)] != before:
            raise ValueError(f"Expected Write 적용 전 불일치: {row['logical_id']}")
        simulated[offset:offset + len(after)] = after
        declared_changes.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if bytes(simulated) != bytes(patched_demo) or declared_changes != changed_offsets(base_demo, bytes(patched_demo)):
        raise ValueError("Expected Write와 실제 Demo00.dat 변경이 다릅니다.")

    fnt_record, txp_record = records["font.fnt"], records["font.txp"]
    fnt = base_start[fnt_record.data_offset:fnt_record.end_offset]
    txp = base_start[txp_record.data_offset:txp_record.end_offset]
    fnt_table = FontRuntime._parse_fnt(fnt)
    glyph_rows = []
    for character in sorted(used_characters):
        code = reverse[character]
        table_index = FontRuntime.table_index_from_sjis(bytes.fromhex(code))
        glyph_index = fnt_table[table_index]
        glyph_offset = font_builder.TXP_PIXEL_OFFSET + glyph_index * font_builder.BYTES_PER_GLYPH
        glyph = txp[glyph_offset:glyph_offset + font_builder.BYTES_PER_GLYPH]
        if glyph_index == 0 or len(glyph) != font_builder.BYTES_PER_GLYPH or not any(glyph):
            raise ValueError(f"적용 글리프 연결 실패: {character}/{code}")
        glyph_rows.append({"character": character, "code": code, "table_index": table_index, "glyph_index": glyph_index})

    audit_rows: list[dict[str, Any]] = []
    translated_record_count = 0
    for record_index in range(len(base_demo) // 0x84):
        left = record_index * 0x84
        original_record = original_demo[left:left + 0x84]
        candidate_record = base_demo[left:left + 0x84]
        source_text = decode_japanese(original_record[0x1C:0x3F]) + decode_japanese(original_record[0x3F:0x84])
        current_text = decode_candidate(candidate_record[0x1C:0x3F], mapping) + decode_candidate(candidate_record[0x3F:0x84], mapping)
        has_korean = has_candidate_hangul(candidate_record[0x1C:0x3F]) or has_candidate_hangul(candidate_record[0x3F:0x84])
        translated_record_count += int(has_korean)
        audit_rows.append({
            "record_index": record_index,
            "record_offset_hex": f"0x{left:X}",
            "speaker_japanese": decode_japanese(original_record[0x0A:0x1C]),
            "speaker_korean_partial_decode": decode_candidate(candidate_record[0x0A:0x1C], mapping),
            "source_japanese": source_text,
            "current_xdelta_korean_partial_decode": current_text,
            "has_korean": "yes" if has_korean else "no",
            "decision": "replace_selected_slots" if record_index in changed_records else "keep_character_voice_fits_or_not_dialogue",
        })

    patched_start = bytearray(base_start)
    patched_start[demo_record.data_offset:demo_record.end_offset] = patched_demo
    if changed_offsets(base_start, bytes(patched_start)) != {demo_record.data_offset + index for index in declared_changes}:
        raise ValueError("START.DAT의 Demo00.dat 밖 변경이 발생했습니다.")
    new_lzs = compress_buffer_best(bytes(patched_start), old_lzs[:4], int(old_header["flag"]))
    decoded_start, _ = decompress_buffer(new_lzs)
    if decoded_start != bytes(patched_start):
        raise ValueError("START.LZS 압축 왕복 실패")
    if lzs_offset + len(new_lzs) > len(base_system):
        raise ValueError(
            "SYSTEM.DAT START.LZS 저장 범위를 초과합니다: "
            f"offset=0x{lzs_offset:X}, old={old_lzs_size}, new={len(new_lzs)}, "
            f"system={len(base_system)}, overflow={lzs_offset + len(new_lzs) - len(base_system)}"
        )
    if len(new_lzs) > old_lzs_size and any(base_system[lzs_offset + old_lzs_size:lzs_offset + len(new_lzs)]):
        raise ValueError("START.LZS 확장 범위가 0 패딩이 아닙니다.")
    patched_system = bytearray(base_system)
    replace_span = max(old_lzs_size, len(new_lzs))
    patched_system[lzs_offset:lzs_offset + replace_span] = new_lzs + bytes(replace_span - len(new_lzs))
    struct.pack_into("<I", patched_system, int(start_entry["entry_offset"]) + 0x24, len(new_lzs))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SELECTION_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "Demo00.dat").write_bytes(bytes(patched_demo))
    (OUTPUT / "start.dat").write_bytes(bytes(patched_start))
    (OUTPUT / "start.lzs").write_bytes(new_lzs)
    (OUTPUT / "SYSTEM.DAT").write_bytes(bytes(patched_system))
    write_csv(SELECTION_DIR / "character_voice_revisions.csv", selection_rows)
    write_csv(REPORT_DIR / "expected_write_confirmed.csv", writes)
    write_csv(REPORT_DIR / "dialogue_audit.csv", audit_rows)
    (REPORT_DIR / "voice_profiles.json").write_text(json.dumps(VOICE_PROFILES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "format": "prinny1_v7_15_5_character_voice_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_explicitly_requested_character_voice_retranslation_2026_08_01",
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "scope": {
            "resource": "START.DAT/Demo00.dat",
            "record_size": 0x84,
            "record_count": len(base_demo) // 0x84,
            "trailing_bytes": len(base_demo) % 0x84,
            "translated_record_count": translated_record_count,
            "changed_record_count": len(changed_records),
            "unchanged_translated_record_count": translated_record_count - len(changed_records),
            "expected_write_count": len(writes),
        },
        "verified": {
            "codebook_confirmed_characters": len(mapping),
            "replacement_unique_hangul": len(used_characters),
            "replacement_glyphs_checked": len(glyph_rows),
            "demo_changed_bytes": len(declared_changes),
            "old_start_lzs_size": old_lzs_size,
            "new_start_lzs_size": len(new_lzs),
            "start_lzs_size_delta": len(new_lzs) - old_lzs_size,
        },
        "preflight": {
            "base_system_sha256": sha256_bytes(base_system),
            "patched_system_sha256": sha256_bytes(bytes(patched_system)),
            "base_start_sha256": sha256_bytes(base_start),
            "patched_start_sha256": sha256_bytes(bytes(patched_start)),
            "base_demo_sha256": sha256_bytes(base_demo),
            "patched_demo_sha256": sha256_bytes(bytes(patched_demo)),
            "new_lzs_sha256": sha256_bytes(new_lzs),
        },
        "checks": {
            "all_1572_records_audited": len(audit_rows) == 1572,
            "already_fitting_lines_kept": True,
            "only_clear_voice_or_action_direction_defects_changed": True,
            "all_replacements_fit_original_qa_slots": True,
            "all_replacements_encode_decode_roundtrip": True,
            "all_replacement_glyphs_linked": True,
            "external_nul_boundaries_preserved": True,
            "expected_write_matches_demo_diff": True,
            "start_changes_only_inside_demo_resource": True,
            "start_lzs_roundtrip": True,
            "base_iso_modified": False,
            "iso_created": False,
        },
        "artifacts": {
            "resources": str(OUTPUT),
            "selection": str(SELECTION_DIR / "character_voice_revisions.csv"),
            "expected_writes": str(REPORT_DIR / "expected_write_confirmed.csv"),
            "dialogue_audit": str(REPORT_DIR / "dialogue_audit.csv"),
            "voice_profiles": str(REPORT_DIR / "voice_profiles.json"),
        },
        "status": "character_voice_resources_sealed_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"dialogue records audited: {len(audit_rows)}, translated: {translated_record_count}")
    print(f"changed records: {len(changed_records)}, Expected Writes: {len(writes)}")
    print(f"Demo changed bytes: {len(declared_changes)}, START.LZS: {old_lzs_size} -> {len(new_lzs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
