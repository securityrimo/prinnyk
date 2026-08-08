#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.font_runtime import FontRuntime
from core.lzs import compress_buffer, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_21_scoped_decoder_plan import BASE_ISO
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_plan"
PLAN = PLAN_DIR / "all_report.json"
WRITES = PLAN_DIR / "expected_write_confirmed.csv"
CODEBOOK = PLAN_DIR / "coherent_f0_codebook.csv"
QA = ROOT / "workspace/reports/prinny_qa/qa_rows.csv"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_review"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def encode_independent(text: str, mapping: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        output.extend(mapping[character] if character in mapping else character.encode("cp932", errors="strict"))
    return bytes(output)


def main() -> int:
    for path in (BASE_ISO, PLAN, WRITES, CODEBOOK, QA):
        if not path.is_file():
            raise FileNotFoundError(path)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("final_verdict") != "PASS" or plan.get("status") != "expected_writes_confirmed_independent_review_required":
        raise ValueError("사전 계획 상태가 검토 가능 상태가 아닙니다.")
    if sha256_file(WRITES) != plan["artifacts"]["expected_writes_sha256"] or sha256_file(CODEBOOK) != plan["artifacts"]["codebook_sha256"]:
        raise ValueError("봉인 산출물 해시가 다릅니다.")

    system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    start_entry = font_builder.parse_nispack_start_entry(system)
    lzs_offset, old_lzs_size = int(start_entry["data_offset"]), int(start_entry["size"])
    old_lzs = system[lzs_offset:lzs_offset + old_lzs_size]
    start, _ = decompress_buffer(old_lzs)
    archive = StartRuntimeArchive.from_bytes(start, source=f"{BASE_ISO}!/start.dat")
    records = {record.output_name.casefold(): record for record in archive.records}
    patched_start, patched_boot = bytearray(start), bytearray(boot)
    declared_start: set[int] = set()
    declared_boot: set[int] = set()
    occupied_start: list[tuple[int, int, str]] = []
    occupied_boot: list[tuple[int, int, str]] = []
    rows = read_csv(WRITES)
    if len(rows) != int(plan["verified"]["expected_write_count"]):
        raise ValueError("Expected Write 수가 봉인값과 다릅니다.")
    for row in rows:
        before, after = bytes.fromhex(row["expected_before_hex"]), bytes.fromhex(row["write_after_hex"])
        if len(before) != len(after) or len(before) != int(row["write_span"]):
            raise ValueError(f"Expected Write 길이 오류: {row['logical_id']}")
        relative = int(row["offset_hex"], 0)
        if row["layer"].startswith("START.DAT/"):
            record = records.get(row["target"].casefold())
            if record is None:
                raise ValueError(f"START 대상 자원 누락: {row['target']}")
            absolute = int(record.data_offset) + relative
            if absolute + len(before) > int(record.end_offset):
                raise ValueError(f"START 경계 초과: {row['logical_id']}")
            if patched_start[absolute:absolute + len(before)] != before:
                raise ValueError(f"START before 불일치: {row['logical_id']}")
            for left, right, logical_id in occupied_start:
                if absolute < right and absolute + len(before) > left:
                    raise ValueError(f"START 쓰기 중첩: {logical_id}/{row['logical_id']}")
            occupied_start.append((absolute, absolute + len(before), row["logical_id"]))
            patched_start[absolute:absolute + len(after)] = after
            declared_start.update(absolute + i for i, (a, b) in enumerate(zip(before, after)) if a != b)
        elif row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN":
            absolute = relative
            if patched_boot[absolute:absolute + len(before)] != before:
                raise ValueError(f"BOOT before 불일치: {row['logical_id']}")
            for left, right, logical_id in occupied_boot:
                if absolute < right and absolute + len(before) > left:
                    raise ValueError(f"BOOT 쓰기 중첩: {logical_id}/{row['logical_id']}")
            occupied_boot.append((absolute, absolute + len(before), row["logical_id"]))
            patched_boot[absolute:absolute + len(after)] = after
            declared_boot.update(absolute + i for i, (a, b) in enumerate(zip(before, after)) if a != b)
        else:
            raise ValueError(f"허용되지 않은 layer: {row['layer']}")

    actual_start = {i for i, pair in enumerate(zip(start, patched_start)) if pair[0] != pair[1]}
    actual_boot = {i for i, pair in enumerate(zip(boot, patched_boot)) if pair[0] != pair[1]}
    if actual_start != declared_start or actual_boot != declared_boot:
        raise ValueError("실제 변경 집합과 Expected Write 합집합이 다릅니다.")
    if sha256_bytes(bytes(patched_start)) != plan["preflight"]["patched_start_sha256"] or sha256_bytes(bytes(patched_boot)) != plan["preflight"]["patched_boot_sha256"]:
        raise ValueError("독립 재계산 결과 해시가 사전 봉인값과 다릅니다.")

    codebook = read_csv(CODEBOOK)
    assigned = [row for row in codebook if row["hangul"]]
    reserved = [row for row in codebook if not row["hangul"]]
    mapping = {row["hangul"]: bytes.fromhex(row["f0_code"]) for row in assigned}
    if len(codebook) != 987 or len(mapping) != 980 or len(reserved) != 7 or len(set(mapping.values())) != 980:
        raise ValueError("독립 코드맵 수/일대일 검증 실패")
    fnt_record = records["font.fnt"]
    fnt_blob = bytes(patched_start[int(fnt_record.data_offset):int(fnt_record.end_offset)])
    table = FontRuntime._parse_fnt(fnt_blob)
    for row in assigned:
        table_index = FontRuntime.table_index_from_sjis(bytes.fromhex(row["f0_code"]))
        if table[table_index] != int(row["existing_glyph_index_hex"], 0):
            raise ValueError(f"F0→기존 글리프 연결 실패: {row['hangul']}")

    qa_rows = read_csv(QA)
    for qa in qa_rows:
        record = records[qa["resource"].casefold()]
        absolute, capacity = int(record.data_offset) + int(qa["offset"], 0), int(qa["capacity_bytes"])
        payload = encode_independent(qa["translation"], mapping)
        expected = payload + bytes(capacity - len(payload))
        if len(payload) != int(qa["encoded_bytes"]) or bytes(patched_start[absolute:absolute + capacity]) != expected:
            raise ValueError(f"사용자 QA 최종 슬롯 검증 실패: {qa['id']}")

    font_txp = records["font.txp"]
    if patched_start[int(font_txp.data_offset):int(font_txp.end_offset)] != start[int(font_txp.data_offset):int(font_txp.end_offset)]:
        raise ValueError("font.txp가 변경됐습니다.")
    excluded = ((0x957B4, 4), (0x95814, 4), (0x9599C, 8), (0x959B0, 12))
    if any(patched_boot[o:o + n] != boot[o:o + n] for o, n in excluded):
        raise ValueError("게임플레이 회귀 범위가 변경됐습니다.")
    new_lzs = compress_buffer(bytes(patched_start), old_lzs[:4])
    decoded, _ = decompress_buffer(new_lzs)
    if decoded != bytes(patched_start) or len(new_lzs) > old_lzs_size or sha256_bytes(new_lzs) != plan["preflight"]["new_lzs_sha256"]:
        raise ValueError("독립 LZS 왕복/용량/해시 검증 실패")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "prinny1_v7_14_22_coherent_f0_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verified": {
            "expected_write_count": len(rows), "assigned_f0_codes": len(mapping), "reserved_f0_codes": len(reserved),
            "qa_slot_count": len(qa_rows), "start_changed_bytes": len(actual_start), "boot_changed_bytes": len(actual_boot),
            "new_lzs_size": len(new_lzs), "lzs_slot_size": old_lzs_size,
        },
        "checks": {
            "fresh_base_reextracted": True, "all_before_bytes_match": True, "no_expected_write_overlap": True,
            "actual_changes_equal_declared": True, "preflight_hashes_match": True, "all_qa_slots_match_user_translation": True,
            "all_f0_aliases_resolve_existing_glyphs": True, "font_txp_byte_identical": True,
            "gameplay_regression_ranges_excluded": True, "candidate_wording_imported": False, "translation_wording_changed": False,
            "iso_created": False,
        },
        "status": "pass_resource_build_ready_automatic_test_iso_approval",
        "final_verdict": "PASS",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Expected Writes reviewed: {len(rows)}")
    print(f"QA final slots: {len(qa_rows)}/{len(qa_rows)}")
    print(f"F0 aliases: {len(mapping)}/980")
    print("font.txp changed: no")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
