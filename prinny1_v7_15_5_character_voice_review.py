#!/usr/bin/env python3
"""Independent prebuild review for V7.15.5 character-voice resources."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.font_runtime import FontRuntime
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
CODEBOOK = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/candidate_codebook_partial.csv"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_5_character_voice_resources"
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_plan"
SELECTION = ROOT / "workspace/translations/selected_v7_15_5/character_voice_revisions.csv"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_review"

EXPECTED = {
    BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    CODEBOOK: "f1ac6829d2c07450f6433b0daa95d413b85aaf1ed8b2ece22bcd5dcf2a5387a3",
    RESOURCE_DIR / "Demo00.dat": "a7e870ad1a1561f5c57e8273689bcd5bebd8d2069eb6038f22866419dab23f26",
    RESOURCE_DIR / "start.dat": "1a230abd89106a8847547fe7b91be3f21a2968fe0fc50168b65b368e127d68b2",
    RESOURCE_DIR / "start.lzs": "dae68b69a5297be4f3633925776df4e59bdb031995381bf2a12fec1bfdaa0374",
    RESOURCE_DIR / "SYSTEM.DAT": "618ad8fd09794f24dd24c829b93aa274b959202c7bd4c10d357a00f33cfb232f",
    PLAN_DIR / "all_report.json": "42fed876faa5058c440311a444c6af81b62b98c953f5071314ef0695cf537c0c",
    PLAN_DIR / "expected_write_confirmed.csv": "4c304013d28d2e5753ee7b125d8197d76fa4ff33c829898834dc5d6397346995",
    PLAN_DIR / "dialogue_audit.csv": "91af345629d59c6e628ce59cc40096945d22119bea2b5ead9ad47bfb84a2012c",
    PLAN_DIR / "voice_profiles.json": "476f1022fea84240213382f979618f655f5924308e0c6412b85444ce7bf66291",
    SELECTION: "5ae5ed1acf6d1198f86a2c7d0eb7bee06806abdc695e6691cbd1644fe03e8416",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def decode(payload: bytes, mapping: dict[str, str]) -> str:
    payload = payload.split(b"\0", 1)[0]
    output: list[str] = []
    cursor = 0
    while cursor < len(payload):
        lead = payload[cursor]
        if 0xF0 <= lead <= 0xF5:
            code = payload[cursor:cursor + 2].hex().upper()
            if code not in mapping:
                raise ValueError(f"적용 슬롯에 미확정 코드가 있습니다: {code}")
            output.append(mapping[code])
            cursor += 2
        elif (0x81 <= lead <= 0x9F or 0xE0 <= lead <= 0xEF):
            output.append(payload[cursor:cursor + 2].decode("cp932"))
            cursor += 2
        elif lead < 0x80:
            output.append(chr(lead))
            cursor += 1
        else:
            raise ValueError(f"적용 슬롯 디코드 실패: 0x{lead:02X}")
    return "".join(output)


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("독립 검토 고정 크기 불일치")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"독립 검토 입력 해시 불일치: {path}")
    plan = json.loads((PLAN_DIR / "all_report.json").read_text(encoding="utf-8"))
    if plan.get("status") != "character_voice_resources_sealed_independent_review_required":
        raise ValueError("계획 봉인 상태가 아닙니다.")
    writes = read_csv(PLAN_DIR / "expected_write_confirmed.csv")
    selection = read_csv(SELECTION)
    audit = read_csv(PLAN_DIR / "dialogue_audit.csv")
    if len(writes) != 11 or len(selection) != 11 or len(audit) != 1572:
        raise ValueError("봉인 행 수가 다릅니다.")
    if sum(row["has_korean"] == "yes" for row in audit) != 1510:
        raise ValueError("한국어 코드 포함 레코드 집계가 다릅니다.")

    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    base_entry = font_builder.parse_nispack_start_entry(base_system)
    final_entry = font_builder.parse_nispack_start_entry(final_system)
    base_offset, base_size = int(base_entry["data_offset"]), int(base_entry["size"])
    final_offset, final_size = int(final_entry["data_offset"]), int(final_entry["size"])
    if base_offset != final_offset or final_size != (RESOURCE_DIR / "start.lzs").stat().st_size:
        raise ValueError("SYSTEM.DAT START.LZS 엔트리 불일치")
    base_start, _ = decompress_buffer(base_system[base_offset:base_offset + base_size])
    final_start, _ = decompress_buffer(final_system[final_offset:final_offset + final_size])
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes():
        raise ValueError("최종 SYSTEM/START 왕복 불일치")
    base_archive = StartRuntimeArchive.from_bytes(base_start)
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    base_records = {record.output_name.casefold(): record for record in base_archive.records}
    final_records = {record.output_name.casefold(): record for record in final_archive.records}
    if [(r.output_name, r.data_offset, r.end_offset) for r in base_archive.records] != [
        (r.output_name, r.data_offset, r.end_offset) for r in final_archive.records
    ]:
        raise ValueError("START 자원 테이블 또는 경계가 바뀌었습니다.")
    base_demo_record = base_records["demo00.dat"]
    final_demo_record = final_records["demo00.dat"]
    base_demo = base_start[base_demo_record.data_offset:base_demo_record.end_offset]
    final_demo = final_start[final_demo_record.data_offset:final_demo_record.end_offset]
    if final_demo != (RESOURCE_DIR / "Demo00.dat").read_bytes():
        raise ValueError("최종 Demo00.dat 산출물 불일치")

    declared: set[int] = set()
    simulated = bytearray(base_demo)
    mapping = {
        row["candidate_code"]: row["unicode_character"]
        for row in read_csv(CODEBOOK)
        if row["unicode_character"]
    }
    reverse = {character: code for code, character in mapping.items()}
    if len(mapping) != 735 or len(reverse) != 735:
        raise ValueError("독립 코드맵 일대일 검사 실패")
    replacement_characters: set[str] = set()
    for row, selected in zip(writes, selection):
        if row["text"] != selected["replacement_korean"]:
            raise ValueError(f"선택/Expected Write 문구 불일치: {row['logical_id']}")
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if len(before) != int(row["write_span"]) or len(after) != len(before):
            raise ValueError(f"Expected Write 길이 불일치: {row['logical_id']}")
        if simulated[offset:offset + len(before)] != before:
            raise ValueError(f"Expected Write before 불일치: {row['logical_id']}")
        if decode(after, mapping) != row["text"]:
            raise ValueError(f"Expected Write 독립 디코드 불일치: {row['logical_id']}")
        if final_demo[offset + len(after)] != 0:
            raise ValueError(f"Expected Write 외부 NUL 손상: {row['logical_id']}")
        simulated[offset:offset + len(after)] = after
        declared.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
        replacement_characters.update(character for character in row["text"] if "가" <= character <= "힣")
    if bytes(simulated) != final_demo or declared != changed_offsets(base_demo, final_demo):
        raise ValueError("독립 Expected Write 재적용 결과가 다릅니다.")
    allowed_start = {base_demo_record.data_offset + offset for offset in declared}
    if changed_offsets(base_start, final_start) != allowed_start:
        raise ValueError("Demo00.dat 허용 변경 밖 START 차이")

    allowed_system = set(range(final_offset, final_offset + max(base_size, final_size)))
    size_field = int(final_entry["entry_offset"]) + 0x24
    allowed_system.update(range(size_field, size_field + 4))
    if not changed_offsets(base_system, final_system) <= allowed_system:
        raise ValueError("START.LZS/크기 필드 밖 SYSTEM.DAT 변경")

    fnt_record, txp_record = final_records["font.fnt"], final_records["font.txp"]
    fnt = final_start[fnt_record.data_offset:fnt_record.end_offset]
    txp = final_start[txp_record.data_offset:txp_record.end_offset]
    table = FontRuntime._parse_fnt(fnt)
    for character in replacement_characters:
        code = reverse[character]
        table_index = FontRuntime.table_index_from_sjis(bytes.fromhex(code))
        glyph_index = table[table_index]
        begin = font_builder.TXP_PIXEL_OFFSET + glyph_index * font_builder.BYTES_PER_GLYPH
        if glyph_index == 0 or not any(txp[begin:begin + font_builder.BYTES_PER_GLYPH]):
            raise ValueError(f"독립 글리프 연결 실패: {character}")

    report = {
        "format": "prinny1_v7_15_5_character_voice_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "audit_rows": len(audit),
            "korean_code_records": 1510,
            "changed_records": 9,
            "expected_writes": len(writes),
            "demo_changed_bytes": len(declared),
            "replacement_glyphs": len(replacement_characters),
            "base_lzs_size": base_size,
            "final_lzs_size": final_size,
        },
        "checks": {
            "plan_inputs_hash_locked": True,
            "all_dialogue_records_audited": True,
            "selection_matches_expected_writes": True,
            "all_replacements_decode_exactly": True,
            "all_external_nul_boundaries_preserved": True,
            "demo_diff_matches_expected_writes": True,
            "start_diff_only_inside_demo": True,
            "system_diff_only_start_lzs_and_size": True,
            "start_lzs_roundtrip": True,
            "all_replacement_glyphs_linked": True,
            "base_iso_modified": False,
            "iso_created": False,
        },
        "status": "pass_v7_15_5_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Expected Writes: {len(writes)}, Demo changed bytes: {len(declared)}")
    print(f"START.LZS: {base_size} -> {final_size}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
