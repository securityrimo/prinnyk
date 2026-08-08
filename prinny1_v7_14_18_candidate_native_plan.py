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
    GROUPS, LABELS, TRANSLATION_CSV, TRANSLATION_SHA256, align4, normalize_ascii, virtual_address,
)


ROOT = Path(__file__).resolve().parent
BASE_START = ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/start.dat"
BASE_BOOT = ROOT / "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
FONT_WRITES = ROOT / "workspace/reports/prinny1_v7_14_15_font_extension_plan/expected_write_confirmed.csv"
CODE_WRITES = ROOT / "workspace/reports/prinny1_v7_14_17_boot_decoder_plan/expected_write_confirmed.csv"
OLD_ALIASES = ROOT / "workspace/reports/prinny1_v7_14_16_boot_alias_plan/alias_mapping.csv"
CANDIDATE_START = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start.dat"
RUNTIME = ROOT / "workspace/reports/prinny1_v7_14_17_runtime_test/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_18_candidate_native_plan"

# Code-to-character identity is recovered from the readable xdelta difficulty screenshot.
# Seven characters absent from that visible text were cross-checked against candidate glyph OCR
# and the candidate font's ascending Hangul ordering. No candidate wording is adopted.
NATIVE_HEX = {
    "마":"F1CA", "계":"F060", "공":"F067", "인":"F364", "중":"F39E", "독":"F14A",
    "난":"F0C0", "이":"F362", "도":"F149", "한":"F486", "번":"F24E", "만":"F1CC",
    "스":"F2AB", "쳐":"F3D1", "아":"F2C9", "웃":"F351", "기":"F087", "본":"F25C",
    "적":"F37A", "과":"F068", "닿":"F192", "까":"F09D", "지":"F3A8", "는":"F0EB",
    "세":"F290", "프":"F47D", "해":"F48B", "설":"F28C", "에":"F2E8", "따":"F16F",
    "라":"F186", "벤":"F4D1", "트":"F45F", "나":"F0BE", "엔":"F2EA", "딩":"F16D",
    "변":"F257", "하":"F484", "않":"F2CC", "습":"F2AF", "니":"F0EF", "다":"F0F4",
    "또":"F2CA", "게":"F056", "임":"F367", "를":"F1BF", "경":"F05F", "할":"F487",
    "수":"F29E", "있":"F36A", "식":"F2B3", "룰":"F4C7", "탠":"F554", "드":"F161",
}

OCR_RECOVERED = {"인", "독", "만", "쳐", "세", "프", "또", "하"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def encode_native(text: str, mapping: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        encoded = mapping.get(character)
        if encoded is None:
            encoded = character.encode("cp932")
        if len(encoded) != 2:
            raise ValueError(f"2바이트가 아닌 적용 문자: {character!r}")
        output.extend(encoded)
    return bytes(output)


def main() -> int:
    for path in (BASE_START, BASE_BOOT, ALLOCATION, FONT_WRITES, CODE_WRITES, OLD_ALIASES,
                 CANDIDATE_START, RUNTIME, TRANSLATION_CSV):
        if not path.is_file(): raise FileNotFoundError(path)
    if sha256_file(TRANSLATION_CSV) != TRANSLATION_SHA256:
        raise ValueError("사용자 번역 CSV 해시가 다릅니다.")
    if json.loads(RUNTIME.read_text(encoding="utf-8")).get("final_verdict") != "BLOCKER":
        raise ValueError("V7.14.17 런타임 BLOCKER가 봉인되지 않았습니다.")
    old_chars = [row["hangul"] for row in read_csv(OLD_ALIASES)]
    if len(old_chars) != 54 or set(old_chars) != set(NATIVE_HEX):
        raise ValueError("사용자 문구 54자와 복구 native 코드맵이 다릅니다.")
    mapping = {char: bytes.fromhex(value) for char, value in NATIVE_HEX.items()}
    if len(set(mapping.values())) != 54:
        raise ValueError("native 코드가 중복됩니다.")

    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    by_char = {row["hangul"]: row for row in allocation["allocations"]}
    base_archive = StartRuntimeArchive.load(BASE_START)
    records = {r.output_name.casefold(): r for r in base_archive.records}
    fnt_record, txp_record = records["font.fnt"], records["font.txp"]
    base_fnt = base_archive.data[fnt_record.data_offset:fnt_record.end_offset]
    base_table = FontRuntime._parse_fnt(base_fnt)
    candidate_archive = StartRuntimeArchive.load(CANDIDATE_START)
    candidate_records = {r.output_name.casefold(): r for r in candidate_archive.records}
    candidate_fnt = candidate_archive.data[candidate_records["font.fnt"].data_offset:candidate_records["font.fnt"].end_offset]
    candidate_table = FontRuntime._parse_fnt(candidate_fnt)

    mapping_rows = []
    target_table = list(base_table)
    for sequence, character in enumerate(old_chars, 1):
        code = mapping[character]
        table_index = FontRuntime.table_index_from_sjis(code)
        glyph_index = int(by_char[character]["glyph_index"])
        if candidate_table[table_index] == base_table[table_index]:
            raise ValueError(f"후보 native F0 항목이 변경되지 않았습니다: {character}")
        target_table[table_index] = glyph_index
        mapping_rows.append({
            "sequence": sequence, "hangul": character, "unicode": f"U+{ord(character):04X}",
            "native_code": code.hex(" ").upper(), "table_index_hex": f"0x{table_index:04X}",
            "current_glyph_index_hex": f"0x{glyph_index:04X}",
            "candidate_glyph_index_hex": f"0x{candidate_table[table_index]:04X}",
            "identity_evidence": "candidate_glyph_ocr_and_hangul_order" if character in OCR_RECOVERED else "readable_xdelta_difficulty_screen_alignment",
            "candidate_wording_imported": "no",
        })

    rows: list[dict[str, Any]] = []
    for source in read_csv(FONT_WRITES):
        rows.append({
            "sequence": 0, "layer": "START.DAT/font.txp", "logical_id": source["logical_id"],
            "target": "font.txp", "offset_hex": source["offset_hex"], "write_span": source["write_span"],
            "expected_before_hex": source["expected_before_hex"], "write_after_hex": source["write_after_hex"],
            "change_kind": source["change_kind"], "wording_changed": "no", "expected_write_confirmed": "yes",
        })
    changed_indices = [i for i, pair in enumerate(zip(base_table, target_table)) if pair[0] != pair[1]]
    groups: list[tuple[int, int]] = []
    start = previous = changed_indices[0]
    for index in changed_indices[1:]:
        if index != previous + 1:
            groups.append((start, previous + 1)); start = index
        previous = index
    groups.append((start, previous + 1))
    for number, (left, right) in enumerate(groups, 1):
        offset = 2 + left * 2
        before = base_fnt[offset:2 + right * 2]
        after = b"".join(struct.pack("<H", target_table[i]) for i in range(left, right))
        rows.append({
            "sequence": 0, "layer": "START.DAT/font.fnt", "logical_id": f"P1-NATIVE-FNT-{number:03d}",
            "target": "font.fnt", "offset_hex": f"0x{offset:X}", "write_span": len(after),
            "expected_before_hex": before.hex().upper(), "write_after_hex": after.hex().upper(),
            "change_kind": "candidate_native_code_to_current_glyph", "wording_changed": "no", "expected_write_confirmed": "yes",
        })

    translations = {row["id"]: row["translation_korean"] for row in read_csv(TRANSLATION_CSV)}
    boot = BASE_BOOT.read_bytes()
    for group in GROUPS:
        group_id = str(group["id"]); lines = tuple(group["translation_lines"])
        if " ".join(lines) != translations[group_id]: raise ValueError(f"사용자 문구 불일치: {group_id}")
        block_start, block_end = int(group["block_start"]), int(group["block_end"])
        new_block = bytearray(block_end - block_start); offsets=[]; cursor=block_start
        for line in lines:
            payload = encode_native(normalize_ascii(line), mapping); cursor=align4(cursor); rel=cursor-block_start
            if rel + len(payload) + 2 > len(new_block): raise ValueError(f"BOOT 용량 초과: {group_id}")
            new_block[rel:rel+len(payload)] = payload; offsets.append(cursor); cursor += len(payload)+2
        rows.append({"sequence":0,"layer":"PSP_GAME/SYSDIR/BOOT.BIN","logical_id":f"{group_id}-NATIVE-BLOCK",
                     "target":"PSP_GAME/SYSDIR/BOOT.BIN","offset_hex":f"0x{block_start:X}","write_span":len(new_block),
                     "expected_before_hex":boot[block_start:block_end].hex().upper(),"write_after_hex":bytes(new_block).hex().upper(),
                     "change_kind":"user_translation_candidate_native_encoding","wording_changed":"no","expected_write_confirmed":"yes"})
        for number,(pointer_offset,string_offset) in enumerate(zip(group["pointer_offsets"],offsets),1):
            pointer_offset=int(pointer_offset); before=boot[pointer_offset:pointer_offset+4]; after=struct.pack("<I",virtual_address(string_offset))
            if before != after:
                rows.append({"sequence":0,"layer":"PSP_GAME/SYSDIR/BOOT.BIN","logical_id":f"{group_id}-PTR-{number}",
                             "target":"PSP_GAME/SYSDIR/BOOT.BIN","offset_hex":f"0x{pointer_offset:X}","write_span":4,
                             "expected_before_hex":before.hex().upper(),"write_after_hex":after.hex().upper(),
                             "change_kind":"in_block_string_pointer_adjustment","wording_changed":"no","expected_write_confirmed":"yes"})
    for group_id, offset, span, _source in LABELS:
        payload=encode_native(normalize_ascii(translations[group_id]),mapping); after=payload+bytes(span-len(payload))
        rows.append({"sequence":0,"layer":"PSP_GAME/SYSDIR/BOOT.BIN","logical_id":f"{group_id}-NATIVE-LABEL",
                     "target":"PSP_GAME/SYSDIR/BOOT.BIN","offset_hex":f"0x{offset:X}","write_span":span,
                     "expected_before_hex":boot[offset:offset+span].hex().upper(),"write_after_hex":after.hex().upper(),
                     "change_kind":"user_translation_candidate_native_encoding","wording_changed":"no","expected_write_confirmed":"yes"})
    for source in read_csv(CODE_WRITES):
        rows.append({"sequence":0,"layer":source["layer"],"logical_id":source["logical_id"],"target":source["target"],
                     "offset_hex":source["offset_hex"],"write_span":source["write_span"],"expected_before_hex":source["expected_before_hex"],
                     "write_after_hex":source["write_after_hex"],"change_kind":source["change_kind"],"wording_changed":"no",
                     "expected_write_confirmed":"yes"})
    rows.sort(key=lambda r:(r["layer"],int(r["offset_hex"],0)))
    for sequence,row in enumerate(rows,1): row["sequence"]=sequence
    OUTPUT.mkdir(parents=True,exist_ok=True)
    mapping_path=OUTPUT/"native_mapping.csv"; writes_path=OUTPUT/"expected_write_confirmed.csv"
    write_csv(mapping_path,mapping_rows); write_csv(writes_path,rows)
    report={"format":"prinny1_v7_14_18_candidate_native_plan_v1","created_at":datetime.now().astimezone().isoformat(timespec="seconds"),
            "inputs":{"base_start_sha256":sha256_file(BASE_START),"base_boot_sha256":sha256_file(BASE_BOOT),
                      "translation_sha256":sha256_file(TRANSLATION_CSV),"candidate_start_sha256":sha256_file(CANDIDATE_START)},
            "verified":{"native_character_count":len(mapping_rows),"screenshot_aligned_count":46,"ocr_cross_checked_count":8,
                        "font_fnt_write_count":len(groups),"total_expected_write_count":len(rows)},
            "checks":{"all_54_user_characters_covered":True,"native_codes_unique":True,"candidate_font_entries_changed":True,
                      "candidate_wording_imported":False,"translation_wording_changed":False,"image_writes":0,"iso_created":False},
            "artifacts":{"mapping":str(mapping_path),"mapping_sha256":sha256_file(mapping_path),
                         "expected_writes":str(writes_path),"expected_writes_sha256":sha256_file(writes_path)},
            "status":"expected_writes_confirmed_independent_review_required","final_verdict":"PASS"}
    (OUTPUT/"all_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"native mapping: {len(mapping_rows)}")
    print(f"Expected Writes: {len(rows)}")
    print("candidate wording imported: 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__": raise SystemExit(main())
