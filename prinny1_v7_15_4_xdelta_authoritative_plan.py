#!/usr/bin/env python3
"""Seal the one user fallback permitted on the xdelta-authoritative baseline."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_3_xdelta_translation_select import load_codebook


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/analysis/prinny1_xdelta_20260729/forced_redecode_20260801.iso"
COMPARISON = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_translation_selection/translation_comparison.csv"
USER_QUEUE = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_user_only.csv"
FORCE_REPORT = ROOT / "workspace/reports/prinny1_xdelta_force_apply_20260801/all_report.json"
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_4_xdelta_authoritative_plan"
EXPECTED = {
    BASE_ISO: "8bc47f189a41309dcca5ef6c61bd5e1368909da8c9b0fc032e2498368d095b65",
    COMPARISON: "7b0a5d3622b8bb9cf204fe420abd5e2501b981c651d89905c8258a4b1e5edbbf",
    USER_QUEUE: "293efcb219632ce1a8f95143d0a629e28445c2d4eb83a663fded9ee100d4ca61",
    FORCE_REPORT: "fb391687fa9ada7677c0ffbfd0e7db7e6bdb932ec219fc3b6e50b8103c62192f",
}
FALLBACK_ID = "P1-V7.15.2-BOOT-0345"
FALLBACK_OFFSET = 0xF3A38
FALLBACK_SPAN = 24
FALLBACK_TEXT = "데이터 송신 완료"
EXPECTED_CODES = {
    "데": "F147", "이": "F362", "터": "F450", "송": "F29B",
    "신": "F2B4", "완": "F342", "료": "F1B7",
}
JAPANESE = re.compile(r"[ぁ-ゖァ-ヺヽヾ一-龯]")
HANGUL = re.compile(r"[가-힣]")


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, data: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.4 계획 입력 해시 불일치: {path}")
    comparison = rows(COMPARISON)
    user_rows = {row["id"]: row for row in rows(USER_QUEUE)}
    if len(comparison) != 542 or len(user_rows) != 542:
        raise ValueError("번역 비교 또는 사용자 큐 행 수 불일치")

    missing = [row for row in comparison if JAPANESE.search(row["xdelta_translation_korean"])]
    if [row["id"] for row in missing] != [FALLBACK_ID]:
        raise ValueError(f"xdelta 한국어 부재 집합 변경: {[row['id'] for row in missing]}")
    if user_rows[FALLBACK_ID]["user_translation_korean"] != FALLBACK_TEXT:
        raise ValueError("사용자 fallback 문구 불일치")
    if any(not HANGUL.search(row["xdelta_translation_korean"]) for row in comparison if row["id"] != FALLBACK_ID):
        raise ValueError("xdelta 유지 대상 중 한국어가 없는 행이 있습니다.")

    manifest = []
    for row in comparison:
        fallback = row["id"] == FALLBACK_ID
        manifest.append({
            "id": row["id"], "offset_hex": row["offset_hex"],
            "xdelta_translation_korean": row["xdelta_translation_korean"],
            "final_translation_korean": FALLBACK_TEXT if fallback else row["xdelta_translation_korean"],
            "decision": "user_fallback_xdelta_missing" if fallback else "xdelta_unchanged",
            "binary_write": "yes" if fallback else "no",
        })

    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    base_eboot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    if base_boot != base_eboot or sha256_bytes(base_boot) != "97cbc41bd5617d1076b6eacc5907fb4edc85babcd433d65992b5b9d881ab73e6":
        raise ValueError("xdelta BOOT/EBOOT 기준 불일치")
    before = base_boot[FALLBACK_OFFSET:FALLBACK_OFFSET + FALLBACK_SPAN]
    if before.hex().upper() != user_rows[FALLBACK_ID]["base_bytes_hex"].upper():
        raise ValueError("xdelta fallback 슬롯이 일본어 기준 바이트와 다릅니다.")
    if base_boot[FALLBACK_OFFSET + FALLBACK_SPAN] != 0:
        raise ValueError("xdelta fallback 슬롯 외부 NUL 경계 불일치")

    codebook, _ = load_codebook()
    reverse: dict[str, str] = {}
    for code, character in codebook.items():
        reverse.setdefault(character, code)
    for character, code in EXPECTED_CODES.items():
        if reverse.get(character) != code:
            raise ValueError(f"xdelta 코드북 고정값 불일치: {character}/{reverse.get(character)}/{code}")
    payload = bytearray()
    for character in FALLBACK_TEXT:
        payload.extend(b"\x20" if character == " " else bytes.fromhex(EXPECTED_CODES[character]))
    if len(payload) > FALLBACK_SPAN:
        raise ValueError("사용자 fallback이 xdelta 슬롯을 초과합니다.")
    after = bytes(payload) + bytes(FALLBACK_SPAN - len(payload))
    patched_boot = bytearray(base_boot)
    patched_boot[FALLBACK_OFFSET:FALLBACK_OFFSET + FALLBACK_SPAN] = after

    entry = font_builder.parse_nispack_start_entry(base_system)
    start, _ = decompress_buffer(base_system[int(entry["data_offset"]):int(entry["data_offset"]) + int(entry["size"])])
    archive = StartRuntimeArchive.from_bytes(start)
    records = {record.output_name.casefold(): record for record in archive.records}
    fnt_record, txp_record = records["font.fnt"], records["font.txp"]
    fnt = start[fnt_record.data_offset:fnt_record.end_offset]
    txp = start[txp_record.data_offset:txp_record.end_offset]
    glyphs = []
    for character, code in EXPECTED_CODES.items():
        sjis = bytes.fromhex(code)
        table_index = font_builder.table_index_from_sjis(*sjis)
        glyph_index = font_builder.read_u16(fnt, 2 + table_index * 2)
        glyph_offset = font_builder.TXP_PIXEL_OFFSET + glyph_index * font_builder.BYTES_PER_GLYPH
        glyph = txp[glyph_offset:glyph_offset + font_builder.BYTES_PER_GLYPH]
        if len(glyph) != font_builder.BYTES_PER_GLYPH or not any(glyph):
            raise ValueError(f"xdelta fallback 글리프 연결 실패: {character}")
        glyphs.append({"character": character, "code": code, "table_index": table_index, "glyph_index": glyph_index})

    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "BOOT.BIN").write_bytes(bytes(patched_boot))
    (OUTPUT / "EBOOT.BIN").write_bytes(bytes(patched_boot))
    manifest_path = REPORT_DIR / "xdelta_authoritative_selection.csv"
    writes_path = REPORT_DIR / "expected_write_confirmed.csv"
    write_csv(manifest_path, manifest)
    write_csv(writes_path, [{
        "logical_id": FALLBACK_ID, "target": "PSP_GAME/SYSDIR/BOOT.BIN",
        "offset_hex": f"0x{FALLBACK_OFFSET:X}", "write_span": FALLBACK_SPAN,
        "expected_before_hex": before.hex().upper(), "write_after_hex": after.hex().upper(),
        "text": FALLBACK_TEXT, "change_kind": "user_fallback_only_where_xdelta_untranslated",
    }])
    report = {
        "format": "prinny1_v7_15_4_xdelta_authoritative_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "directive": "xdelta_is_authoritative_use_user_translation_only_when_xdelta_has_no_korean_do_not_change_unused_data",
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "baseline": {
            "path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO),
            "role": "user_directed_xdelta_authoritative_for_test_build",
            "declared_official_source_hash_match": False,
        },
        "verified": {
            "compared_rows": len(comparison), "xdelta_rows_unchanged": 541,
            "user_fallback_rows": 1, "binary_expected_writes": 1,
            "fallback_payload_bytes": len(payload), "fallback_slot_bytes": FALLBACK_SPAN,
            "fallback_font_glyphs_rechecked": len(glyphs),
            "boot_changed_bytes": sum(a != b for a, b in zip(base_boot, patched_boot)),
        },
        "fallback": {"id": FALLBACK_ID, "text": FALLBACK_TEXT, "glyphs": glyphs},
        "preflight": {
            "base_boot_sha256": sha256_bytes(base_boot),
            "patched_boot_sha256": sha256_bytes(bytes(patched_boot)),
            "base_system_sha256": sha256_bytes(base_system),
        },
        "artifacts": {
            "resources": str(OUTPUT), "selection_manifest": str(manifest_path),
            "selection_manifest_sha256": sha256_file(manifest_path),
            "expected_writes": str(writes_path), "expected_writes_sha256": sha256_file(writes_path),
        },
        "checks": {
            "xdelta_korean_overrides_user_wording": True,
            "only_xdelta_untranslated_row_uses_user_text": True,
            "xdelta_system_font_images_and_other_data_unchanged": True,
            "fallback_fits_existing_slot": True, "external_nul_boundary_preserved": True,
            "base_iso_modified": False, "iso_created": False,
        },
        "status": "xdelta_authoritative_resources_sealed_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("xdelta unchanged: 541, user fallback: 1")
    print(f"Expected Writes: 1, BOOT changed bytes: {report['verified']['boot_changed_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
