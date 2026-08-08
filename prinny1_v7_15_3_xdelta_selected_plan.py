#!/usr/bin/env python3
"""Build sealed V7.15.3 BOOT and font resources from the reviewed selection."""
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as font_builder
from core.lzs import compress_buffer, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_3_xdelta_translation_select import decode_candidate, load_codebook


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui/prinny_korean_v7_15_1_full_text_internal_ui.iso"
SELECTED = ROOT / "workspace/translations/selected_v7_15_3/boot_executable_translation_selected_v7_15_3.csv"
SELECTION_REVIEW = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_translation_review/all_report.json"
ALLOCATION_980 = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
RESIDUAL_AUDIT = ROOT / "workspace/font/audited_allocation_977/residual_audit.json"
CANDIDATE_BOOT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/BOOT.BIN"
GALMURI = Path("/home/hyuk/.local/share/fonts/Galmuri14.ttf")
OUTPUT = ROOT / "workspace/build/prinny1_v7_15_3_xdelta_selected_resources"
OUTPUT_ALLOCATION = ROOT / "workspace/font/audited_allocation_988/hangul_allocation.json"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_selected_plan"

EXPECTED = {
    BASE_ISO: "98411d6861c0cc9cc6b34672915786426fc2260ea005b7ba13ac0d75aac7e7d8",
    SELECTED: "5f70bd572d54d71b3a80fd94b814a9034feebf059262a64f2b9ef396cf46673a",
    SELECTION_REVIEW: "960ea73a073164f5688a614546c7b55ba1aa9ca5bad0309e1de26826e6a9adb7",
    ALLOCATION_980: "f35f9bdac9c07c867e40b72e71323b16928b8dfdeb34de99420db289a49291f3",
    RESIDUAL_AUDIT: "ae3a33ca38ad93e319a890018126021c987c738c1423ca89f9a5781e5b2421d4",
    CANDIDATE_BOOT: "97cbc41bd5617d1076b6eacc5907fb4edc85babcd433d65992b5b9d881ab73e6",
    GALMURI: "d3818c0f2898a3b2d79ccd04ec1e4de5e8940aa26abee261f73e315a44ce8df9",
}
MISSING = ("꿉", "냅", "돕", "랗", "쏩", "짧", "켠", "횟")
COMPOSITE_IDS = {
    "P1-V7.15.2-BOOT-0387", "P1-V7.15.2-BOOT-0388",
    "P1-V7.15.2-BOOT-0390", "P1-V7.15.2-BOOT-0391",
}
GROUPS = ((0xF0AA4, 54, "0387", "0390"), (0xF0C54, 64, "0388", "0391"))


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


def encode_text(text: str, mapping: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        output.extend(mapping[character] if character in mapping else character.encode("cp932"))
    return bytes(output)


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("고정 크기 자원의 길이가 달라졌습니다.")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.3 계획 입력 해시 불일치: {path}")
    review = json.loads(SELECTION_REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS":
        raise ValueError("번역 선택 독립 검토가 PASS가 아닙니다.")

    selected = read_csv(SELECTED)
    if len(selected) != 542 or len({row["id"] for row in selected}) != 542:
        raise ValueError("선택 번역 행 수 또는 ID가 다릅니다.")
    by_suffix = {row["id"].rsplit("-", 1)[-1]: row for row in selected}

    allocation = json.loads(ALLOCATION_980.read_text(encoding="utf-8"))
    existing = list(allocation["allocations"])
    if len(existing) != 980:
        raise ValueError("기준 폰트 배정이 980자가 아닙니다.")
    used_sjis = {str(row["sjis"]).replace(" ", "").upper() for row in existing}
    audit = json.loads(RESIDUAL_AUDIT.read_text(encoding="utf-8"))
    safe = [
        row for row in audit["safe_candidates"]
        if str(row["sjis"]).replace(" ", "").upper() not in used_sjis
        and int(row["audit"]["trusted_text_hits"]) == 0
    ]
    if len(safe) < len(MISSING):
        raise ValueError("감사 완료 미사용 글리프 슬롯이 부족합니다.")
    chosen = safe[:len(MISSING)]

    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    base_eboot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    if base_boot != base_eboot:
        raise ValueError("V7.15.1 BOOT/EBOOT가 동일하지 않습니다.")

    start_entry = font_builder.parse_nispack_start_entry(base_system)
    lzs_offset, old_lzs_size = int(start_entry["data_offset"]), int(start_entry["size"])
    old_lzs = base_system[lzs_offset:lzs_offset + old_lzs_size]
    base_start, old_header = decompress_buffer(old_lzs)
    archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    records = {record.output_name.casefold(): record for record in archive.records}
    fnt_record, txp_record = records.get("font.fnt"), records.get("font.txp")
    if fnt_record is None or txp_record is None:
        raise ValueError("START.DAT에서 font.fnt/font.txp를 찾지 못했습니다.")
    fnt = base_start[fnt_record.data_offset:fnt_record.end_offset]
    txp = base_start[txp_record.data_offset:txp_record.end_offset]
    table_count = font_builder.read_u16(fnt, 0)

    font_writes: list[dict[str, Any]] = []
    extension_rows: list[dict[str, Any]] = []
    preview_items = []
    patched_txp = bytearray(txp)
    for index, (hangul, candidate) in enumerate(zip(MISSING, chosen), start=981):
        sjis = bytes.fromhex(str(candidate["sjis"]))
        table_index, glyph_index = int(candidate["table_index"]), int(candidate["glyph_index"])
        if font_builder.table_index_from_sjis(*sjis) != table_index or not 0 <= table_index < table_count:
            raise ValueError(f"안전 슬롯 SJIS 테이블 불일치: {hangul}")
        if font_builder.read_u16(fnt, 2 + table_index * 2) != glyph_index:
            raise ValueError(f"안전 슬롯 font.fnt 연결 불일치: {hangul}")
        offset = font_builder.TXP_PIXEL_OFFSET + glyph_index * font_builder.BYTES_PER_GLYPH
        before = txp[offset:offset + font_builder.BYTES_PER_GLYPH]
        pixels, preview = font_builder.render_character(GALMURI, hangul)
        after = font_builder.encode_4bpp(pixels)
        if len(before) != len(after) or before == after:
            raise ValueError(f"글리프 Expected Write 오류: {hangul}")
        patched_txp[offset:offset + len(after)] = after
        preview_items.append((hangul, preview))
        extension = {
            "index": index, "hangul": hangul, "unicode": f"U+{ord(hangul):04X}",
            "frequency": 1, "safety": "audited-strict-v7.15.3-extension",
            "sjis": sjis.hex(" ").upper(), "sjis_value": int.from_bytes(sjis, "big"),
            "lead": sjis[0], "trail": sjis[1], "table_index": table_index,
            "table_index_hex": f"0x{table_index:04X}", "glyph_index": glyph_index,
            "glyph_index_hex": f"0x{glyph_index:04X}", "replaces": str(candidate["character"]),
            "replaces_unicode": f"U+{ord(str(candidate['character'])):04X}",
            "alias_count": int(candidate["alias_count"]), "audit": candidate["audit"],
        }
        extension_rows.append(extension)
        font_writes.append({
            "logical_id": f"P1-V7.15.3-FONT-{index:03d}", "target": "START.DAT/font.txp",
            "offset_hex": f"0x{offset:X}", "write_span": len(after),
            "expected_before_hex": before.hex().upper(), "write_after_hex": after.hex().upper(),
            "text": hangul, "change_kind": "audited_unused_glyph_extension",
        })

    expanded = dict(allocation)
    expanded.update({
        "format": "prinny_hangul_allocation_audited_988_v1", "required_count": 988,
        "selected_count": 988, "capacity_margin": int(allocation["capacity_margin"]) - 8,
        "source_extension": str(SELECTED),
        "hangul_order": str(allocation["hangul_order"]) + "".join(MISSING),
        "allocations": existing + extension_rows,
        "mapping": {**dict(allocation["mapping"]), **{row["hangul"]: row["sjis"] for row in extension_rows}},
    })
    mapping = {str(row["hangul"]): bytes.fromhex(str(row["sjis"])) for row in expanded["allocations"]}
    if len(mapping) != 988 or len(set(mapping.values())) != 988:
        raise ValueError("988자 확장 코드맵이 유일하지 않습니다.")

    patched_boot = bytearray(base_boot)
    boot_writes: list[dict[str, Any]] = []
    for row in selected:
        if row["id"] in COMPOSITE_IDS:
            continue
        offset, span = int(row["offset_hex"], 0), int(row["byte_length"])
        declared = bytes.fromhex(row["current_bytes_hex"])
        if len(declared) != span or base_boot[offset:offset + span] != declared:
            raise ValueError(f"BOOT 적용 전 바이트 불일치: {row['id']}")
        if base_boot[offset + span] != 0:
            raise ValueError(f"BOOT 슬롯 외부 NUL 경계 불일치: {row['id']}")
        payload = encode_text(row["user_translation_korean"], mapping)
        if len(payload) > span:
            raise ValueError(f"BOOT 슬롯 초과: {row['id']}/{len(payload)}/{span}")
        after = payload + bytes(span - len(payload))
        patched_boot[offset:offset + span] = after
        boot_writes.append({
            "logical_id": row["id"], "target": "PSP_GAME/SYSDIR/BOOT.BIN",
            "offset_hex": f"0x{offset:X}", "write_span": span,
            "expected_before_hex": declared.hex().upper(), "write_after_hex": after.hex().upper(),
            "text": row["user_translation_korean"], "change_kind": f"selected_{row['selection_source']}",
        })

    candidate = CANDIDATE_BOOT.read_bytes()
    codebook, _ = load_codebook()
    for index, (offset, span, count_id, time_id) in enumerate(GROUPS, 1):
        text = "%s %s\n" + by_suffix[count_id]["user_translation_korean"] + "\n"
        if index == 2:
            text += "난이도: %s\n"
        text += by_suffix[time_id]["user_translation_korean"]
        candidate_text, _ = decode_candidate(candidate, offset, codebook)
        if candidate_text != text:
            raise ValueError(f"xdelta 복합 문자열 의미 대조 실패: 그룹 {index}/{candidate_text!r}/{text!r}")
        before = base_boot[offset:offset + span]
        if base_boot[offset + span] != 0:
            raise ValueError(f"복합 문자열 외부 NUL 경계 불일치: 그룹 {index}")
        payload = encode_text(text, mapping)
        if len(payload) > span:
            raise ValueError(f"복합 문자열 슬롯 초과: 그룹 {index}/{len(payload)}/{span}")
        after = payload + bytes(span - len(payload))
        patched_boot[offset:offset + span] = after
        boot_writes.append({
            "logical_id": f"P1-V7.15.3-BOOT-COMPOSITE-{index:02d}",
            "target": "PSP_GAME/SYSDIR/BOOT.BIN", "offset_hex": f"0x{offset:X}",
            "write_span": span, "expected_before_hex": before.hex().upper(),
            "write_after_hex": after.hex().upper(), "text": text,
            "change_kind": "xdelta_semantic_composite_format_group",
        })

    ranges = sorted((int(row["offset_hex"], 0), int(row["write_span"]), row["logical_id"]) for row in boot_writes)
    if any(left + size > right for (left, size, _), (right, _, _) in zip(ranges, ranges[1:])):
        raise ValueError("BOOT Expected Write 범위가 겹칩니다.")
    simulated = bytearray(base_boot)
    declared_changes: set[int] = set()
    for row in boot_writes:
        offset = int(row["offset_hex"], 0)
        before, after = bytes.fromhex(row["expected_before_hex"]), bytes.fromhex(row["write_after_hex"])
        if simulated[offset:offset + len(before)] != before:
            raise ValueError(f"BOOT Expected Write 적용 전 불일치: {row['logical_id']}")
        simulated[offset:offset + len(after)] = after
        declared_changes.update(offset + i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if bytes(simulated) != bytes(patched_boot) or declared_changes != changed_offsets(base_boot, bytes(patched_boot)):
        raise ValueError("BOOT 선언 변경과 실제 변경이 다릅니다.")

    patched_start = bytearray(base_start)
    patched_start[txp_record.data_offset:txp_record.end_offset] = patched_txp
    new_lzs = compress_buffer(bytes(patched_start), old_lzs[:4], int(old_header["flag"]))
    decoded_start, _ = decompress_buffer(new_lzs)
    if decoded_start != bytes(patched_start):
        raise ValueError("START.LZS 압축 왕복 실패")
    if lzs_offset + len(new_lzs) > len(base_system):
        raise ValueError("SYSTEM.DAT의 START.LZS 후단 용량 초과")
    if len(new_lzs) > old_lzs_size and any(base_system[lzs_offset + old_lzs_size:lzs_offset + len(new_lzs)]):
        raise ValueError("START.LZS 확장 범위가 0 패딩이 아닙니다.")
    patched_system = bytearray(base_system)
    replace_span = max(old_lzs_size, len(new_lzs))
    patched_system[lzs_offset:lzs_offset + replace_span] = new_lzs + bytes(replace_span - len(new_lzs))
    struct.pack_into("<I", patched_system, int(start_entry["entry_offset"]) + 0x24, len(new_lzs))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_ALLOCATION.parent.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "BOOT.BIN").write_bytes(bytes(patched_boot))
    (OUTPUT / "EBOOT.BIN").write_bytes(bytes(patched_boot))
    (OUTPUT / "start.dat").write_bytes(bytes(patched_start))
    (OUTPUT / "start.lzs").write_bytes(new_lzs)
    (OUTPUT / "SYSTEM.DAT").write_bytes(bytes(patched_system))
    OUTPUT_ALLOCATION.write_text(json.dumps(expanded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(REPORT_DIR / "boot_expected_write_confirmed.csv", boot_writes)
    write_csv(REPORT_DIR / "font_expected_write_confirmed.csv", font_writes)
    font_builder.save_preview_sheet(preview_items, REPORT_DIR / "glyph_preview.png")

    report = {
        "format": "prinny1_v7_15_3_xdelta_selected_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "font_extension": {
            "characters": list(MISSING), "previous_count": 980, "expanded_count": 988,
            "remaining_safe_margin": expanded["capacity_margin"],
            "slots": [{"hangul": h, "replaces": c["character"], "sjis": c["sjis"], "glyph_index": c["glyph_index"]} for h, c in zip(MISSING, chosen)],
        },
        "verified": {
            "selected_rows": len(selected), "nongrouped_rows": len(selected) - len(COMPOSITE_IDS),
            "composite_source_rows": len(COMPOSITE_IDS), "composite_expected_writes": len(GROUPS),
            "structural_xdelta_lines_added": 1, "boot_expected_writes": len(boot_writes),
            "font_expected_writes": len(font_writes), "boot_changed_bytes": len(declared_changes),
            "font_txp_changed_bytes": len(changed_offsets(txp, bytes(patched_txp))),
            "old_start_lzs_size": old_lzs_size, "new_start_lzs_size": len(new_lzs),
            "start_lzs_size_delta": len(new_lzs) - old_lzs_size,
        },
        "preflight": {
            "base_boot_sha256": sha256_bytes(base_boot), "patched_boot_sha256": sha256_bytes(bytes(patched_boot)),
            "base_start_sha256": sha256_bytes(base_start), "patched_start_sha256": sha256_bytes(bytes(patched_start)),
            "base_system_sha256": sha256_bytes(base_system), "patched_system_sha256": sha256_bytes(bytes(patched_system)),
            "new_lzs_sha256": sha256_bytes(new_lzs), "allocation_988_sha256": sha256_file(OUTPUT_ALLOCATION),
        },
        "artifacts": {
            "resources": str(OUTPUT), "allocation_988": str(OUTPUT_ALLOCATION),
            "boot_expected_writes": str(REPORT_DIR / "boot_expected_write_confirmed.csv"),
            "font_expected_writes": str(REPORT_DIR / "font_expected_write_confirmed.csv"),
        },
        "checks": {
            "selection_review_pass": True, "all_nongrouped_slots_fit": True,
            "composite_groups_match_xdelta_semantics": True, "external_nul_boundaries_preserved": True,
            "font_slots_trusted_text_hits_zero": True, "font_fnt_links_unchanged": True,
            "start_lzs_roundtrip": True, "base_iso_modified": False, "iso_created": False,
        },
        "status": "resources_sealed_independent_prebuild_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"BOOT Expected Writes: {len(boot_writes)}, changed bytes: {len(declared_changes)}")
    print(f"font: 980 -> 988, START.LZS: {old_lzs_size} -> {len(new_lzs)}")
    print(f"resources: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
