#!/usr/bin/env python3
"""Independent structural post-review of the final V7.15.3 test ISO."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui/prinny_korean_v7_15_1_full_text_internal_ui.iso"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_3_xdelta_selected/prinny_korean_v7_15_3_xdelta_selected.iso"
BUILD_REPORT = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_selected_iso/all_report.json"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_3_xdelta_selected_resources"
SELECTED = ROOT / "workspace/translations/selected_v7_15_3/boot_executable_translation_selected_v7_15_3.csv"
ALLOCATION = ROOT / "workspace/font/audited_allocation_988/hangul_allocation.json"
FONT_WRITES = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_selected_plan/font_expected_write_confirmed.csv"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_selected_iso_review"
EXPECTED = {
    BASE_ISO: "98411d6861c0cc9cc6b34672915786426fc2260ea005b7ba13ac0d75aac7e7d8",
    OUTPUT_ISO: "00de856f5b3bf33fc6cb036e4ab11232866f97821aac4f3a1dbeea472cb8d7ca",
    BUILD_REPORT: "6e1d7e81bbd4905135728e4e1de610fa8032821a94228ab6915604decfa77bc4",
    SELECTED: "5f70bd572d54d71b3a80fd94b814a9034feebf059262a64f2b9ef396cf46673a",
    ALLOCATION: "315ea9d4d1b0e6b911eda8014d9331958df035f872170350152f12e096817f38",
}
COMPOSITE_IDS = {
    "P1-V7.15.2-BOOT-0387", "P1-V7.15.2-BOOT-0388",
    "P1-V7.15.2-BOOT-0390", "P1-V7.15.2-BOOT-0391",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def decode_text(payload: bytes, reverse: dict[bytes, str]) -> str:
    output: list[str] = []
    cursor = 0
    while cursor < len(payload) and payload[cursor] != 0:
        pair = payload[cursor:cursor + 2]
        if pair in reverse:
            output.append(reverse[pair]); cursor += 2
        elif payload[cursor] < 0x80:
            output.append(chr(payload[cursor])); cursor += 1
        elif 0x81 <= payload[cursor] <= 0x9F or 0xE0 <= payload[cursor] <= 0xEF:
            output.append(pair.decode("cp932")); cursor += 2
        else:
            output.append(bytes([payload[cursor]]).decode("cp932")); cursor += 1
    return "".join(output)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.3 ISO 사후 검토 입력 해시 불일치: {path}")
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if build.get("status") != "pass_v7_15_3_test_iso_built_independent_post_review_required":
        raise ValueError("V7.15.3 ISO 빌드 보고 상태 불일치")

    parts = {
        "boot": ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
        "eboot": ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
        "system": ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    }
    base_records = {key: find_iso_file(BASE_ISO, value) for key, value in parts.items()}
    final_records = {key: find_iso_file(OUTPUT_ISO, value) for key, value in parts.items()}
    intervals = sorted((int(record["extent_lba"]) * SECTOR_SIZE, int(record["extent_lba"]) * SECTOR_SIZE + int(record["data_length"])) for record in base_records.values())
    cursor = 0
    for left, right in intervals:
        if hash_range(BASE_ISO, cursor, left) != hash_range(OUTPUT_ISO, cursor, left):
            raise ValueError("허용 ISO 자원 앞 범위 독립 비교 실패")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(OUTPUT_ISO, cursor, OUTPUT_ISO.stat().st_size):
        raise ValueError("마지막 허용 ISO 자원 뒤 범위 독립 비교 실패")
    if any(int(base_records[key]["data_length"]) != int(final_records[key]["data_length"]) for key in parts):
        raise ValueError("최종 ISO 레코드 크기 변경")

    final = {key: read_iso_file(OUTPUT_ISO, record) for key, record in final_records.items()}
    sealed = {
        "boot": (RESOURCE_DIR / "BOOT.BIN").read_bytes(),
        "eboot": (RESOURCE_DIR / "EBOOT.BIN").read_bytes(),
        "system": (RESOURCE_DIR / "SYSTEM.DAT").read_bytes(),
    }
    if final != sealed or final["boot"] != final["eboot"]:
        raise ValueError("최종 ISO 자원이 봉인본과 다르거나 BOOT/EBOOT가 다릅니다.")

    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))["allocations"]
    mapping = {row["hangul"]: bytes.fromhex(row["sjis"]) for row in allocation}
    reverse = {value: key for key, value in mapping.items()}
    if len(mapping) != 988 or len(reverse) != 988:
        raise ValueError("최종 988자 코드맵 중복")
    selected = csv_rows(SELECTED)
    decoded = 0
    for row in selected:
        if row["id"] in COMPOSITE_IDS:
            continue
        offset, span = int(row["offset_hex"], 0), int(row["byte_length"])
        if decode_text(final["boot"][offset:offset + span + 1], reverse) != row["user_translation_korean"]:
            raise ValueError(f"최종 ISO BOOT 문구 불일치: {row['id']}")
        decoded += 1
    by_suffix = {row["id"].rsplit("-", 1)[-1]: row["user_translation_korean"] for row in selected}
    group_texts = (
        "%s %s\n" + by_suffix["0387"] + "\n" + by_suffix["0390"],
        "%s %s\n" + by_suffix["0388"] + "\n난이도: %s\n" + by_suffix["0391"],
    )
    for (offset, span), text in zip(((0xF0AA4, 54), (0xF0C54, 64)), group_texts):
        if decode_text(final["boot"][offset:offset + span + 1], reverse) != text:
            raise ValueError("최종 ISO 복합 문구 불일치")

    entry = font_builder.parse_nispack_start_entry(final["system"])
    start, _ = decompress_buffer(final["system"][int(entry["data_offset"]):int(entry["data_offset"]) + int(entry["size"])])
    if start != (RESOURCE_DIR / "start.dat").read_bytes():
        raise ValueError("최종 ISO START.DAT가 봉인본과 다릅니다.")
    archive = StartRuntimeArchive.from_bytes(start)
    records = {record.output_name.casefold(): record for record in archive.records}
    fnt_record, txp_record = records["font.fnt"], records["font.txp"]
    fnt = start[fnt_record.data_offset:fnt_record.end_offset]
    txp = start[txp_record.data_offset:txp_record.end_offset]
    font_rows = csv_rows(FONT_WRITES)
    for allocation_row, write in zip(allocation[980:], font_rows):
        table_index, glyph_index = int(allocation_row["table_index"]), int(allocation_row["glyph_index"])
        if font_builder.read_u16(fnt, 2 + table_index * 2) != glyph_index:
            raise ValueError(f"최종 ISO font.fnt 연결 불일치: {allocation_row['hangul']}")
        offset = int(write["offset_hex"], 0)
        after = bytes.fromhex(write["write_after_hex"])
        if txp[offset:offset + len(after)] != after:
            raise ValueError(f"최종 ISO 글리프 불일치: {allocation_row['hangul']}")

    test = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("최종 ISO 7z 독립 재검사 실패")
    report = {
        "format": "prinny1_v7_15_3_xdelta_selected_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {
            "selected_rows": len(selected), "nongrouped_rows_redecoded": decoded,
            "composite_groups_redecoded": 2, "font_aliases": len(mapping),
            "new_glyphs_rechecked": len(font_rows), "start_records": len(archive.records),
        },
        "checks": {
            "output_hash_recomputed": True, "iso_outside_three_resources_byte_identical": True,
            "sealed_resources_match_exactly": True, "boot_eboot_identical": True,
            "all_selected_texts_redecoded": True, "composite_groups_redecoded": True,
            "font_fnt_links_and_txp_glyphs_match": True, "start_reextracted_exactly": True,
            "seven_zip_structure_retested": True,
        },
        "known_runtime_regressions": ["prologue_boss_interaction_may_fail"],
        "status": "pass_v7_15_3_structural_runtime_test_required",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {report['output_iso']['sha256']}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
