#!/usr/bin/env python3
"""Independent prebuild review of the sealed V7.15.3 resources."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui/prinny_korean_v7_15_1_full_text_internal_ui.iso"
SELECTED = ROOT / "workspace/translations/selected_v7_15_3/boot_executable_translation_selected_v7_15_3.csv"
ALLOCATION_980 = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
ALLOCATION_988 = ROOT / "workspace/font/audited_allocation_988/hangul_allocation.json"
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_selected_plan"
PLAN = PLAN_DIR / "all_report.json"
BOOT_WRITES = PLAN_DIR / "boot_expected_write_confirmed.csv"
FONT_WRITES = PLAN_DIR / "font_expected_write_confirmed.csv"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_3_xdelta_selected_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_selected_review"
EXPECTED = {
    BASE_ISO: "98411d6861c0cc9cc6b34672915786426fc2260ea005b7ba13ac0d75aac7e7d8",
    SELECTED: "5f70bd572d54d71b3a80fd94b814a9034feebf059262a64f2b9ef396cf46673a",
    ALLOCATION_980: "f35f9bdac9c07c867e40b72e71323b16928b8dfdeb34de99420db289a49291f3",
    ALLOCATION_988: "315ea9d4d1b0e6b911eda8014d9331958df035f872170350152f12e096817f38",
    PLAN: "a3006090dfbde4a868d96a47b1a7d6f9dd3a24b25d3086bd849cd38e67a461d1",
    BOOT_WRITES: "7c78f9d16f4af7b772487aa747a66de7d77b5474d7e63e1aac44777ed9a40b1f",
    FONT_WRITES: "ed33eb0446aa5a2ad7058b45141ad4c87204d6e8faf414f2b2a16e203011f50e",
    RESOURCE_DIR / "BOOT.BIN": "782bab27ce20d438ef7abc6568c367d17ac5f66d3ad2e64bf4fd9550fce6e6ad",
    RESOURCE_DIR / "EBOOT.BIN": "782bab27ce20d438ef7abc6568c367d17ac5f66d3ad2e64bf4fd9550fce6e6ad",
    RESOURCE_DIR / "start.dat": "c5222be3d41a2d24847d770e486334b54aa2315704abf303816734fad7b7ced5",
    RESOURCE_DIR / "start.lzs": "3e63cb2302b5b4bc285fe96163359c4c389bd152b4c3cc2eabc322971d47dbfe",
    RESOURCE_DIR / "SYSTEM.DAT": "dec58d4dfff22d8d1d53a7cd6e079785844ef93821da85b66c4720e97fd9f2fc",
}
COMPOSITE_IDS = {
    "P1-V7.15.2-BOOT-0387", "P1-V7.15.2-BOOT-0388",
    "P1-V7.15.2-BOOT-0390", "P1-V7.15.2-BOOT-0391",
}
MISSING = ("꿉", "냅", "돕", "랗", "쏩", "짧", "켠", "횟")
JAPANESE = re.compile(r"[ぁ-ゖァ-ヺヽヾ一-龯]")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def changed(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("고정 자원 크기 불일치")
    return {i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def decode_text(payload: bytes, reverse: dict[bytes, str]) -> str:
    output: list[str] = []
    cursor = 0
    while cursor < len(payload) and payload[cursor] != 0:
        pair = payload[cursor:cursor + 2]
        if pair in reverse:
            output.append(reverse[pair])
            cursor += 2
        elif payload[cursor] < 0x80:
            output.append(chr(payload[cursor]))
            cursor += 1
        elif 0x81 <= payload[cursor] <= 0x9F or 0xE0 <= payload[cursor] <= 0xEF:
            output.append(pair.decode("cp932"))
            cursor += 2
        else:
            output.append(bytes([payload[cursor]]).decode("cp932"))
            cursor += 1
    return "".join(output)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.3 독립 검토 입력 해시 불일치: {path}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    selected = rows(SELECTED)
    boot_rows, font_rows = rows(BOOT_WRITES), rows(FONT_WRITES)
    if len(selected) != 542 or len(boot_rows) != 540 or len(font_rows) != 8:
        raise ValueError("독립 검토 행 수 불일치")

    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_boot = (RESOURCE_DIR / "BOOT.BIN").read_bytes()
    rebuilt_boot = bytearray(base_boot)
    declared: set[int] = set()
    intervals: list[tuple[int, int]] = []
    for row in boot_rows:
        offset = int(row["offset_hex"], 0)
        before, after = bytes.fromhex(row["expected_before_hex"]), bytes.fromhex(row["write_after_hex"])
        if len(before) != int(row["write_span"]) or len(after) != len(before):
            raise ValueError(f"BOOT Expected Write 길이 불일치: {row['logical_id']}")
        if rebuilt_boot[offset:offset + len(before)] != before:
            raise ValueError(f"BOOT Expected Write before 불일치: {row['logical_id']}")
        rebuilt_boot[offset:offset + len(after)] = after
        intervals.append((offset, offset + len(after)))
        declared.update(offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    intervals.sort()
    if any(left_end > right_start for (_, left_end), (right_start, _) in zip(intervals, intervals[1:])):
        raise ValueError("BOOT Expected Write 겹침")
    if bytes(rebuilt_boot) != final_boot or declared != changed(base_boot, final_boot):
        raise ValueError("봉인 BOOT가 Expected Writes의 정확한 합이 아닙니다.")

    old_allocation = json.loads(ALLOCATION_980.read_text(encoding="utf-8"))
    new_allocation = json.loads(ALLOCATION_988.read_text(encoding="utf-8"))
    if new_allocation["allocations"][:980] != old_allocation["allocations"]:
        raise ValueError("기존 980자 배정이 변경됐습니다.")
    extension = new_allocation["allocations"][980:]
    if [row["hangul"] for row in extension] != list(MISSING):
        raise ValueError("8자 폰트 확장 순서 불일치")
    if any(int(row["audit"]["trusted_text_hits"]) != 0 for row in extension):
        raise ValueError("폰트 확장 슬롯에 신뢰 텍스트 사용 흔적이 있습니다.")
    mapping = {str(row["hangul"]): bytes.fromhex(str(row["sjis"])) for row in new_allocation["allocations"]}
    reverse = {value: key for key, value in mapping.items()}
    if len(mapping) != 988 or len(reverse) != 988:
        raise ValueError("988자 코드맵 중복")

    decoded_rows = 0
    for row in selected:
        if row["id"] in COMPOSITE_IDS:
            continue
        offset, span = int(row["offset_hex"], 0), int(row["byte_length"])
        actual = decode_text(final_boot[offset:offset + span + 1], reverse)
        if actual != row["user_translation_korean"] or JAPANESE.search(actual):
            raise ValueError(f"최종 BOOT 재디코딩 불일치: {row['id']}/{actual!r}")
        if final_boot[offset + span] != 0:
            raise ValueError(f"최종 BOOT 외부 NUL 경계 손상: {row['id']}")
        decoded_rows += 1
    by_suffix = {row["id"].rsplit("-", 1)[-1]: row["user_translation_korean"] for row in selected}
    expected_groups = (
        "%s %s\n" + by_suffix["0387"] + "\n" + by_suffix["0390"],
        "%s %s\n" + by_suffix["0388"] + "\n난이도: %s\n" + by_suffix["0391"],
    )
    for (offset, span), expected_text in zip(((0xF0AA4, 54), (0xF0C54, 64)), expected_groups):
        if decode_text(final_boot[offset:offset + span + 1], reverse) != expected_text:
            raise ValueError("최종 BOOT 복합 문자열 재디코딩 불일치")
        if final_boot[offset + span] != 0:
            raise ValueError("최종 BOOT 복합 문자열 외부 NUL 손상")

    base_entry = font_builder.parse_nispack_start_entry(base_system)
    base_start, _ = decompress_buffer(base_system[int(base_entry["data_offset"]):int(base_entry["data_offset"]) + int(base_entry["size"])])
    final_system = (RESOURCE_DIR / "SYSTEM.DAT").read_bytes()
    final_entry = font_builder.parse_nispack_start_entry(final_system)
    final_start, _ = decompress_buffer(final_system[int(final_entry["data_offset"]):int(final_entry["data_offset"]) + int(final_entry["size"])])
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or final_start == base_start:
        raise ValueError("최종 SYSTEM/START 봉인 또는 실제 변경 오류")
    base_archive = StartRuntimeArchive.from_bytes(base_start)
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    base_records = {record.output_name.casefold(): record for record in base_archive.records}
    final_records = {record.output_name.casefold(): record for record in final_archive.records}
    if [(r.output_name, r.data_offset, r.size) for r in base_archive.records] != [(r.output_name, r.data_offset, r.size) for r in final_archive.records]:
        raise ValueError("START.DAT 레코드 구조 변경")
    base_txp_record, final_txp_record = base_records["font.txp"], final_records["font.txp"]
    base_txp = base_start[base_txp_record.data_offset:base_txp_record.end_offset]
    final_txp = final_start[final_txp_record.data_offset:final_txp_record.end_offset]
    rebuilt_txp = bytearray(base_txp)
    font_declared: set[int] = set()
    for row in font_rows:
        offset = int(row["offset_hex"], 0)
        before, after = bytes.fromhex(row["expected_before_hex"]), bytes.fromhex(row["write_after_hex"])
        if rebuilt_txp[offset:offset + len(before)] != before:
            raise ValueError(f"font.txp Expected Write before 불일치: {row['logical_id']}")
        rebuilt_txp[offset:offset + len(after)] = after
        font_declared.update(offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if bytes(rebuilt_txp) != final_txp or font_declared != changed(base_txp, final_txp):
        raise ValueError("font.txp 변경 범위가 Expected Writes와 다릅니다.")
    for name, record in base_records.items():
        if name == "font.txp":
            continue
        final_record = final_records[name]
        if base_start[record.data_offset:record.end_offset] != final_start[final_record.data_offset:final_record.end_offset]:
            raise ValueError(f"START.DAT 비폰트 자원 변경: {name}")

    allowed_system = set(range(int(base_entry["data_offset"]), int(base_entry["data_offset"]) + max(int(base_entry["size"]), int(final_entry["size"]))))
    allowed_system.update(range(int(base_entry["entry_offset"]) + 0x24, int(base_entry["entry_offset"]) + 0x28))
    if not changed(base_system, final_system) <= allowed_system:
        raise ValueError("SYSTEM.DAT의 START.LZS/크기 필드 밖 변경")

    report = {
        "format": "prinny1_v7_15_3_xdelta_selected_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "boot_expected_writes": len(boot_rows), "boot_changed_bytes": len(declared),
            "nongrouped_texts_redecoded": decoded_rows, "composite_groups_redecoded": 2,
            "font_expected_writes": len(font_rows), "font_changed_bytes": len(font_declared),
            "font_aliases": len(mapping), "start_records_preserved": len(base_archive.records),
            "start_lzs_size": int(final_entry["size"]),
        },
        "checks": {
            "sealed_boot_is_exact_expected_write_sum": True, "boot_writes_nonoverlapping": True,
            "all_selected_texts_redecoded_exactly": True, "composite_placeholders_and_wording_exact": True,
            "external_nul_boundaries_preserved": True, "existing_980_font_entries_unchanged": True,
            "new_font_slots_audited_unused": True, "font_changes_exactly_declared": True,
            "nonfont_start_records_byte_identical": True, "system_changes_scoped_to_start_lzs": True,
            "lzs_roundtrip_and_sealed_resource_match": True, "iso_created": False,
        },
        "status": "pass_v7_15_3_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"BOOT 재디코딩: {decoded_rows}+2 groups, font aliases: {len(mapping)}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
