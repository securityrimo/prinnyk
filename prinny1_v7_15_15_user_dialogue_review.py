#!/usr/bin/env python3
"""Independent prebuild review for V7.15.15 user-priority dialogue resources."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.font_runtime import FontRuntime
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_3_xdelta_translation_select import load_codebook
from prinny1_v7_15_4_ui_image_export import system_records


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
USER_FONT_ISO = ROOT / "workspace/build/prinny1_v7_14_22_coherent_f0/prinny_korean_v7_14_22_coherent_f0.iso"
CANDIDATE_DEMO = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start_resources/Demo00.dat"
PARALLEL = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/parallel_slots.csv"
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources"
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_15_15_user_dialogue_plan"
SELECTION = ROOT / "workspace/translations/selected_v7_15_15/demo00_user_priority_selection.csv"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_15_user_dialogue_review"

EXPECTED = {
    BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    USER_FONT_ISO: "fd460bbc0057a738712b2fcf7adaee985c13a156529fff5179e7e6a54cc77510",
    CANDIDATE_DEMO: "a924ecd354997275c6107e98cc8f5c6f077d7e550be0ffda5a5b748a56c09541",
    PARALLEL: "89949915a81e712662bd49729b77af86cc20ee9a0a2b9a377e63c80420488944",
    ALLOCATION: "f35f9bdac9c07c867e40b72e71323b16928b8dfdeb34de99420db289a49291f3",
    RESOURCE_DIR / "SYSTEM.DAT": "5c8d8447e1a8282d011eec93220bf2b3c1a145adf231fc104edda2a0b651a66c",
    RESOURCE_DIR / "start.dat": "00de7fb145ab1097a35ad2d737456a1a7f505bd1fda2c85a4070dd23d30fe3ef",
    RESOURCE_DIR / "start.lzs": "204400f2e276066a53fa08ddad6151e1505f5ab934c77ba76ac00b5c874ad739",
    RESOURCE_DIR / "Demo00.dat": "030f7040956a040a79c4c6e271e2007f743d3413062e3159ec393be4e0fd0a3b",
    RESOURCE_DIR / "font.txp": "fa1d70dd0ef7ca9f99a9fcfacd108e2d5653b25e95675c170b3a0b02e4bc94be",
    RESOURCE_DIR / "font.fnt": "b6eaf35a7dd469983bc0544d70552558a631d0469cfe4f39338ab6520c841cea",
    PLAN_DIR / "all_report.json": "6b08377b30fe5ff44c59ce7944dc40e5d49fc81d7905af563fc324e4001816dd",
    PLAN_DIR / "expected_dialogue_writes.csv": "a4e7990ae84e20495ccb7a9cc182cf81aa170ad41ac1abd60bf61d29f7f0bf67",
    PLAN_DIR / "font_extension_slots.csv": "5fc93dc0779ab59dabe60b99229905ec9637fe3c33e499725d19b829ebf02d01",
    PLAN_DIR / "voice_profiles.json": "3765ef453f28c5b0ac143b0b4e94ac5a801c487f3c816dc292e39707602c7d68",
    SELECTION: "4a89a15e52bdb9f29051b9552d97c0b860c2af3224f108a018030eff1a49f038",
}

BAD_PRINNY_ENDING = re.compile(r"거슴|슴네|깜까|슴가|슴네요")
PIXEL_OFFSET = font_builder.TXP_PIXEL_OFFSET
BYTES_PER_GLYPH = font_builder.BYTES_PER_GLYPH


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("독립 검토 고정 크기 불일치")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def contains_xdelta_code(blob: bytes) -> bool:
    return any(0xF0 <= value <= 0xF5 for value in blob.split(b"\0", 1)[0])


def decode(blob: bytes, mapping: dict[str, str]) -> str:
    payload = blob.split(b"\0", 1)[0]
    output: list[str] = []
    cursor = 0
    while cursor < len(payload):
        lead = payload[cursor]
        code = payload[cursor:cursor + 2].hex().upper() if cursor + 1 < len(payload) else ""
        if code in mapping:
            output.append(mapping[code])
            cursor += 2
        elif 0xF0 <= lead <= 0xF5 and cursor + 1 < len(payload):
            raise ValueError(f"독립 검토 미복구 xdelta 코드: {code}")
        elif (0x81 <= lead <= 0x9F or 0xE0 <= lead <= 0xEF) and cursor + 1 < len(payload):
            output.append(payload[cursor:cursor + 2].decode("cp932"))
            cursor += 2
        elif lead < 0x80:
            output.append(chr(lead))
            cursor += 1
        elif 0xA1 <= lead <= 0xDF:
            output.append(bytes((lead,)).decode("cp932"))
            cursor += 1
        else:
            raise ValueError(f"독립 검토 디코드 실패: 0x{lead:02X}")
    return "".join(output)


def overlap_count(stream: bytes) -> int:
    _raw, header = decompress_buffer(stream)
    flag = int(header["flag"])
    cursor, end = 0x10, int(header["compressed_end"])
    overlaps = 0
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
        overlaps += int(length > distance)
    return overlaps


def extract_start(iso: Path) -> tuple[bytes, bytes, list[dict]]:
    system = read_iso_file(iso, find_iso_file(iso, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    start = decompress_buffer(system[start_row["data_offset"]:start_row["data_offset"] + start_row["size"]])[0]
    return system, start, rows


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.15 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads((PLAN_DIR / "all_report.json").read_text(encoding="utf-8"))
    if plan.get("status") != "user_dialogue_resources_sealed_independent_review_required":
        raise ValueError("V7.15.15 계획 봉인 상태가 아닙니다.")

    base_system, base_start, base_system_rows = extract_start(BASE_ISO)
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    final_system_rows = system_records(final_system)
    final_start_row = next(row for row in final_system_rows if row["name"].casefold() == "start.lzs")
    final_lzs = final_system[final_start_row["data_offset"]:final_start_row["data_offset"] + final_start_row["size"]]
    final_start = decompress_buffer(final_lzs)[0]
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or final_lzs != (RESOURCE_DIR / "start.lzs").read_bytes():
        raise ValueError("독립 SYSTEM/START/LZS 왕복 불일치")
    if overlap_count(final_lzs) != 0:
        raise ValueError("독립 검토에서 겹침 역참조 발견")

    base_archive = StartRuntimeArchive.from_bytes(base_start)
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    base_records = {row.output_name.casefold(): row for row in base_archive.records}
    final_records = {row.output_name.casefold(): row for row in final_archive.records}
    if [(row.output_name, row.data_offset, row.end_offset) for row in base_archive.records] != [
        (row.output_name, row.data_offset, row.end_offset) for row in final_archive.records
    ]:
        raise ValueError("START 자원 테이블/경계 변경")
    for name, base_record in base_records.items():
        final_record = final_records[name]
        before = base_start[base_record.data_offset:base_record.end_offset]
        after = final_start[final_record.data_offset:final_record.end_offset]
        if name not in {"demo00.dat", "font.txp"} and before != after:
            raise ValueError(f"독립 검토 비대상 START 자원 변경: {base_record.output_name}")

    base_demo_record, final_demo_record = base_records["demo00.dat"], final_records["demo00.dat"]
    base_demo = base_start[base_demo_record.data_offset:base_demo_record.end_offset]
    final_demo = final_start[final_demo_record.data_offset:final_demo_record.end_offset]
    if final_demo != (RESOURCE_DIR / "Demo00.dat").read_bytes():
        raise ValueError("독립 Demo00 산출물 불일치")
    base_fnt_record, final_fnt_record = base_records["font.fnt"], final_records["font.fnt"]
    base_fnt = base_start[base_fnt_record.data_offset:base_fnt_record.end_offset]
    final_fnt = final_start[final_fnt_record.data_offset:final_fnt_record.end_offset]
    if base_fnt != final_fnt or final_fnt != (RESOURCE_DIR / "font.fnt").read_bytes():
        raise ValueError("font.fnt 변경 또는 산출물 불일치")
    base_txp_record, final_txp_record = base_records["font.txp"], final_records["font.txp"]
    base_txp = base_start[base_txp_record.data_offset:base_txp_record.end_offset]
    final_txp = final_start[final_txp_record.data_offset:final_txp_record.end_offset]
    if final_txp != (RESOURCE_DIR / "font.txp").read_bytes():
        raise ValueError("독립 font.txp 산출물 불일치")

    writes = read_csv(PLAN_DIR / "expected_dialogue_writes.csv")
    selection = read_csv(SELECTION)
    glyphs = read_csv(PLAN_DIR / "font_extension_slots.csv")
    if len(selection) != 2561 or len(writes) != 2049 or len(glyphs) != 152:
        raise ValueError("봉인 선택/Expected Write/글리프 행 수 불일치")
    decisions = Counter(row["decision"] for row in selection)
    if decisions != Counter({"user": 2379, "xdelta_voice_fallback": 176, "hold_xdelta_unused": 5, "curated_user_voice": 1}):
        raise ValueError(f"독립 선택 집계 불일치: {dict(decisions)}")

    parallel = {
        int(row["offset"], 0): row for row in read_csv(PARALLEL)
        if row["resource"].casefold() == "demo00.dat" and int(row["offset"], 0) % 0x84 in {0x1C, 0x3F}
    }
    candidate_demo = CANDIDATE_DEMO.read_bytes()
    if len(parallel) != 2561:
        raise ValueError("독립 xdelta 대사 범위 불일치")
    mapping, _trusted = load_codebook()
    extension = {row["encoded_code"]: row["character"] for row in glyphs}
    full_mapping = mapping | extension
    held_count = user_count = fallback_count = curated_count = 0
    used_extension: set[str] = set()
    for selected in selection:
        offset = int(selected["resource_offset_hex"], 0)
        capacity = int(selected["capacity_bytes"])
        span = int(selected["expected_write_span"])
        row = parallel[offset]
        candidate_slice = bytes.fromhex(row["candidate_payload_hex"])
        if candidate_demo[offset:offset + capacity] != candidate_slice:
            raise ValueError(f"독립 xdelta 슬롯 근거 불일치: 0x{offset:X}")
        current = final_demo[offset:offset + span]
        decision = selected["decision"]
        if decision == "hold_xdelta_unused":
            held_count += 1
            if contains_xdelta_code(candidate_slice) or current != base_demo[offset:offset + span]:
                raise ValueError(f"독립 xdelta 미사용 보류 실패: 0x{offset:X}")
        elif decision == "xdelta_voice_fallback":
            fallback_count += 1
            field_end = (offset // 0x84) * 0x84 + (0x3F if offset % 0x84 == 0x1C else 0x84)
            nul = candidate_demo.find(b"\0", offset, field_end)
            expected = candidate_demo[offset:nul] + bytes(span - (nul - offset))
            if current != expected or not BAD_PRINNY_ENDING.search(selected["user_translation"]):
                raise ValueError(f"독립 말투 xdelta 폴백 실패: 0x{offset:X}")
        else:
            selected_text = selected["selected_translation_or_partial_decode"]
            if decode(current, full_mapping) != selected_text:
                raise ValueError(f"독립 사용자 문구 디코드 불일치: 0x{offset:X}")
            if len(current.split(b"\0", 1)[0]) > capacity:
                raise ValueError(f"독립 사용자 문구 슬롯 초과: 0x{offset:X}")
            used_extension.update(character for character in selected_text if character in set(extension.values()))
            if decision == "user":
                user_count += 1
                if selected_text != selected["user_translation"]:
                    raise ValueError(f"독립 사용자 우선 문구 불일치: 0x{offset:X}")
            elif decision == "curated_user_voice":
                curated_count += 1
            else:
                raise ValueError(f"알 수 없는 선택 결정: {decision}")
    if (held_count, user_count, fallback_count, curated_count) != (5, 2379, 176, 1):
        raise ValueError("독립 선택 분기 재집계 불일치")

    simulated_demo = bytearray(base_demo)
    declared_demo: set[int] = set()
    for row in writes:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if simulated_demo[offset:offset + len(before)] != before or len(before) != len(after):
            raise ValueError(f"독립 대사 Expected Write 실패: {row['logical_id']}")
        simulated_demo[offset:offset + len(after)] = after
        declared_demo.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if bytes(simulated_demo) != final_demo or declared_demo != changed_offsets(base_demo, final_demo):
        raise ValueError("독립 대사 Expected Write/실제 diff 불일치")

    _source_system, source_start, _source_rows = extract_start(USER_FONT_ISO)
    source_archive = StartRuntimeArchive.from_bytes(source_start)
    source_records = {row.output_name.casefold(): row for row in source_archive.records}
    source_fnt = source_start[source_records["font.fnt"].data_offset:source_records["font.fnt"].end_offset]
    source_txp = source_start[source_records["font.txp"].data_offset:source_records["font.txp"].end_offset]
    source_table = FontRuntime._parse_fnt(source_fnt)
    base_table = FontRuntime._parse_fnt(base_fnt)
    references = Counter(base_table)
    allocation = {row["hangul"]: row for row in json.loads(ALLOCATION.read_text(encoding="utf-8"))["allocations"]}
    simulated_txp = bytearray(base_txp)
    declared_txp: set[int] = set()
    for row in glyphs:
        character = row["character"]
        code = bytes.fromhex(row["encoded_code"])
        table_index = FontRuntime.table_index_from_sjis(code)
        target_glyph = base_table[table_index]
        if table_index != int(row["target_table_index_hex"], 0) or references[target_glyph] != 1 or int(row["trusted_text_hits"]) != 0:
            raise ValueError(f"독립 안전 글리프 슬롯 실패: {character}")
        offset = PIXEL_OFFSET + target_glyph * BYTES_PER_GLYPH
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        source_index = int(allocation[character]["table_index"])
        source_glyph = source_table[source_index]
        source_offset = PIXEL_OFFSET + source_glyph * BYTES_PER_GLYPH
        if after != source_txp[source_offset:source_offset + BYTES_PER_GLYPH]:
            raise ValueError(f"독립 사용자 글리프 원본 불일치: {character}")
        if simulated_txp[offset:offset + BYTES_PER_GLYPH] != before:
            raise ValueError(f"독립 글리프 before 불일치: {character}")
        simulated_txp[offset:offset + BYTES_PER_GLYPH] = after
        declared_txp.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if bytes(simulated_txp) != final_txp or declared_txp != changed_offsets(base_txp, final_txp):
        raise ValueError("독립 font.txp Expected Write/diff 불일치")
    if used_extension != set(extension.values()):
        raise ValueError("독립 추가 글리프 사용 집합 불일치")

    base_start_row = next(row for row in base_system_rows if row["name"].casefold() == "start.lzs")
    allowed_system = set(range(base_start_row["data_offset"], base_system_rows[base_start_row["index"] + 1]["data_offset"]))
    size_field = 0x10 + base_start_row["index"] * 0x2C + 0x24
    allowed_system.update(range(size_field, size_field + 4))
    if not changed_offsets(base_system, final_system) <= allowed_system:
        raise ValueError("독립 START.LZS/크기 필드 밖 SYSTEM 변경")

    report = {
        "format": "prinny1_v7_15_15_user_dialogue_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "selection_rows": len(selection),
            "decision_counts": dict(decisions),
            "dialogue_expected_writes": len(writes),
            "dialogue_changed_bytes": len(declared_demo),
            "font_extension_characters": len(glyphs),
            "font_changed_bytes": len(declared_txp),
            "base_lzs_size": base_start_row["size"],
            "final_lzs_size": final_start_row["size"],
            "final_lzs_capacity": base_system_rows[base_start_row["index"] + 1]["data_offset"] - base_start_row["data_offset"],
            "final_lzs_overlaps": 0,
        },
        "checks": {
            "all_inputs_hash_locked": True,
            "xdelta_scope_recomputed": True,
            "five_xdelta_unused_slots_held_byte_exact": True,
            "user_wording_primary_redecoded": True,
            "malformed_prinny_endings_use_exact_xdelta_bytes": True,
            "no_user_slot_overflow": True,
            "dialogue_expected_writes_reapplied": True,
            "font_extension_uses_audited_zero_hit_single_reference_slots": True,
            "font_glyphs_match_verified_user_font": True,
            "font_fnt_unchanged": True,
            "only_demo00_and_font_txp_changed_inside_start": True,
            "system_diff_only_start_lzs_and_size": True,
            "runtime_safe_lzs_roundtrip": True,
            "base_iso_modified": False,
            "iso_created": False,
        },
        "status": "pass_v7_15_15_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"selection: {dict(decisions)}")
    print(f"Demo diff: {len(declared_demo)} bytes; font diff: {len(declared_txp)} bytes")
    print(f"START.LZS: {base_start_row['size']} -> {final_start_row['size']}; overlaps 0")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
