#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as builder
from core.start_runtime import StartRuntimeArchive


ROOT = Path(__file__).resolve().parent
SOURCE_START = (
    ROOT
    / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/start.dat"
)
ALLOCATION_977 = (
    ROOT / "workspace/font/audited_allocation_977/hangul_allocation.json"
)
RESIDUAL_AUDIT = (
    ROOT / "workspace/font/audited_allocation_977/residual_audit.json"
)
GALMURI = Path("/home/hyuk/.local/share/fonts/Galmuri14.ttf")
OUTPUT_ALLOCATION_DIR = ROOT / "workspace/font/audited_allocation_980"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_font_extension_plan"

SOURCE_START_SHA256 = "04e434d982189bd2d37bd2d664f892ef7aef04fb7b86dc3b395ff36798a8134f"
MISSING_HANGUL = ("탠", "닿", "벤")
EXPECTED_SLOTS = {
    "탠": ("呑", "93 DB", 0x0E7A, 0x06FB),
    "닿": ("包", "95 EF", 0x100E, 0x07E3),
    "벤": ("案", "88 C4", 0x0623, 0x01C2),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"빈 CSV입니다: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    for path in (SOURCE_START, ALLOCATION_977, RESIDUAL_AUDIT, GALMURI):
        if not path.is_file():
            raise FileNotFoundError(path)
    source = SOURCE_START.read_bytes()
    if sha256_bytes(source) != SOURCE_START_SHA256:
        raise ValueError("V7.14.14 START 해시가 고정값과 다릅니다.")

    allocation = json.loads(ALLOCATION_977.read_text(encoding="utf-8"))
    audit = json.loads(RESIDUAL_AUDIT.read_text(encoding="utf-8"))
    existing = list(allocation["allocations"])
    if len(existing) != 977:
        raise ValueError("기존 배정표가 977자가 아닙니다.")
    existing_hangul = {str(row["hangul"]) for row in existing}
    existing_sjis = {str(row["sjis"]).replace(" ", "").upper() for row in existing}
    if existing_hangul & set(MISSING_HANGUL):
        raise ValueError("누락 글리프가 기존 배정표에 이미 존재합니다.")

    safe_by_sjis = {
        str(row["sjis"]).replace(" ", "").upper(): row
        for row in audit["safe_candidates"]
    }
    selected: list[tuple[str, dict[str, Any]]] = []
    for hangul in MISSING_HANGUL:
        replaced, sjis_text, table_index, glyph_index = EXPECTED_SLOTS[hangul]
        key = sjis_text.replace(" ", "")
        candidate = safe_by_sjis.get(key)
        if candidate is None or key in existing_sjis:
            raise ValueError(f"안전한 미사용 후보가 아닙니다: {hangul}/{sjis_text}")
        if (
            candidate["character"] != replaced
            or int(candidate["table_index"]) != table_index
            or int(candidate["glyph_index"]) != glyph_index
            or int(candidate["audit"]["trusted_text_hits"]) != 0
        ):
            raise ValueError(f"고정 후보의 감사 정보가 달라졌습니다: {hangul}")
        selected.append((hangul, candidate))

    archive = StartRuntimeArchive.from_bytes(source, source=str(SOURCE_START))
    records = {record.output_name.casefold(): record for record in archive.records}
    fnt_record = records.get("font.fnt")
    txp_record = records.get("font.txp")
    if fnt_record is None or txp_record is None:
        raise ValueError("START에서 font.fnt/font.txp를 찾지 못했습니다.")
    fnt = source[fnt_record.data_offset:fnt_record.end_offset]
    txp = source[txp_record.data_offset:txp_record.end_offset]
    table_count = builder.read_u16(fnt, 0)
    if builder.read_u16(txp, 0) != 20:
        raise ValueError("font.txp 너비가 20이 아닙니다.")

    writes: list[dict[str, Any]] = []
    extension_rows: list[dict[str, Any]] = []
    preview_items = []
    for index, (hangul, candidate) in enumerate(selected, start=978):
        sjis = bytes.fromhex(str(candidate["sjis"]))
        table_index = int(candidate["table_index"])
        glyph_index = int(candidate["glyph_index"])
        if builder.table_index_from_sjis(sjis[0], sjis[1]) != table_index:
            raise ValueError(f"SJIS 테이블 인덱스 불일치: {hangul}")
        if not 0 <= table_index < table_count:
            raise ValueError(f"font.fnt 테이블 범위 초과: {hangul}")
        actual_glyph = builder.read_u16(fnt, 2 + table_index * 2)
        if actual_glyph != glyph_index:
            raise ValueError(f"font.fnt 글리프 연결 불일치: {hangul}")

        glyph_offset = builder.TXP_PIXEL_OFFSET + glyph_index * builder.BYTES_PER_GLYPH
        glyph_end = glyph_offset + builder.BYTES_PER_GLYPH
        if glyph_end > len(txp):
            raise ValueError(f"font.txp 범위 초과: {hangul}")
        before = txp[glyph_offset:glyph_end]
        pixels, preview = builder.render_character(GALMURI, hangul)
        after = builder.encode_4bpp(pixels)
        if len(before) != builder.BYTES_PER_GLYPH or len(after) != len(before):
            raise ValueError(f"글리프 길이 오류: {hangul}")
        if before == after:
            raise ValueError(f"새 글리프가 기존 글리프와 같습니다: {hangul}")
        preview_items.append((hangul, preview))

        extension = {
            "index": index,
            "hangul": hangul,
            "unicode": f"U+{ord(hangul):04X}",
            "frequency": 1,
            "safety": "audited-strict-extension",
            "sjis": sjis.hex(" ").upper(),
            "sjis_value": int.from_bytes(sjis, "big"),
            "lead": sjis[0],
            "trail": sjis[1],
            "table_index": table_index,
            "table_index_hex": f"0x{table_index:04X}",
            "glyph_index": glyph_index,
            "glyph_index_hex": f"0x{glyph_index:04X}",
            "replaces": str(candidate["character"]),
            "replaces_unicode": f"U+{ord(str(candidate['character'])):04X}",
            "alias_count": int(candidate["alias_count"]),
            "audit": candidate["audit"],
        }
        extension_rows.append(extension)
        writes.append(
            {
                "group_id": "G023",
                "logical_id": f"P1-FONT-EXT-{index:03d}",
                "target": "font.txp",
                "offset_hex": f"0x{glyph_offset:X}",
                "write_span": len(after),
                "expected_before_hex": before.hex().upper(),
                "write_after_hex": after.hex().upper(),
                "hangul": hangul,
                "sjis": sjis.hex(" ").upper(),
                "replaces": str(candidate["character"]),
                "table_index_hex": f"0x{table_index:04X}",
                "glyph_index_hex": f"0x{glyph_index:04X}",
                "trusted_text_hits": int(candidate["audit"]["trusted_text_hits"]),
                "raw_hits": int(candidate["audit"]["raw_hits"]),
                "changed_bytes": sum(a != b for a, b in zip(before, after)),
                "change_kind": "audited_unused_glyph_extension",
                "wording_changed": "no",
                "user_wording_approval": "yes_translation_csv",
                "expected_write_confirmed": "yes",
            }
        )

    ranges = sorted(
        (int(row["offset_hex"], 0), int(row["write_span"])) for row in writes
    )
    if any(left + length > right for (left, length), (right, _) in zip(ranges, ranges[1:])):
        raise ValueError("글리프 Expected Write 범위가 겹칩니다.")

    expanded = dict(allocation)
    expanded["format"] = "prinny_hangul_allocation_audited_980_v1"
    expanded["required_count"] = 980
    expanded["selected_count"] = 980
    expanded["capacity_margin"] = int(allocation["capacity_margin"]) - 3
    expanded["source_extension"] = str(
        ROOT / "workspace/translations/ui_v7_14_15/title_difficulty_translation.csv"
    )
    expanded["hangul_order"] = str(allocation["hangul_order"]) + "".join(MISSING_HANGUL)
    expanded["allocations"] = existing + extension_rows
    expanded["mapping"] = {
        **dict(allocation["mapping"]),
        **{row["hangul"]: row["sjis"] for row in extension_rows},
    }

    OUTPUT_ALLOCATION_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    allocation_path = OUTPUT_ALLOCATION_DIR / "hangul_allocation.json"
    allocation_path.write_text(
        json.dumps(expanded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    builder.save_preview_sheet(preview_items, REPORT_DIR / "glyph_preview.png")
    write_csv(REPORT_DIR / "expected_write_confirmed.csv", writes)

    simulated = bytearray(txp)
    changed_offsets: set[int] = set()
    for row in writes:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(str(row["expected_before_hex"]))
        after = bytes.fromhex(str(row["write_after_hex"]))
        if simulated[offset:offset + len(before)] != before:
            raise ValueError(f"시뮬레이션 before 불일치: {row['logical_id']}")
        simulated[offset:offset + len(after)] = after
        changed_offsets.update(
            offset + i for i, (old, new) in enumerate(zip(before, after)) if old != new
        )
    actual_changed = {
        i for i, (old, new) in enumerate(zip(txp, simulated)) if old != new
    }
    if actual_changed != changed_offsets or len(simulated) != len(txp):
        raise ValueError("시뮬레이션 변경 범위가 선언과 다릅니다.")

    report = {
        "format": "prinny1_v7_14_15_font_extension_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "source_start": str(SOURCE_START),
            "source_start_sha256": sha256_bytes(source),
            "source_font_txp_sha256": sha256_bytes(txp),
            "allocation_977": str(ALLOCATION_977),
            "allocation_977_sha256": sha256_file(ALLOCATION_977),
            "residual_audit": str(RESIDUAL_AUDIT),
            "residual_audit_sha256": sha256_file(RESIDUAL_AUDIT),
            "galmuri": str(GALMURI),
            "galmuri_sha256": sha256_file(GALMURI),
        },
        "extension": {
            "characters": list(MISSING_HANGUL),
            "previous_count": 977,
            "expanded_count": 980,
            "remaining_safe_margin": expanded["capacity_margin"],
            "expected_write_count": len(writes),
            "changed_byte_count": len(actual_changed),
            "simulated_font_txp_sha256": sha256_bytes(bytes(simulated)),
        },
        "checks": {
            "existing_977_entries_unchanged": expanded["allocations"][:977] == existing,
            "new_sjis_slots_unique": len({row["sjis"] for row in extension_rows}) == 3,
            "trusted_text_hits_zero": all(row["trusted_text_hits"] == 0 for row in writes),
            "font_fnt_links_match": True,
            "glyph_writes_non_overlapping": True,
            "actual_changes_equal_declared_changes": True,
            "source_start_unchanged": sha256_file(SOURCE_START) == sha256_bytes(source),
            "iso_created": False,
        },
        "status": "font_expected_writes_confirmed_runtime_validation_required",
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"확장 글리프: {', '.join(MISSING_HANGUL)}")
    print(f"Expected Writes: {len(writes)}")
    print(f"변경 바이트: {len(actual_changed)}")
    print("ISO 생성: 없음")
    print(f"보고서: {REPORT_DIR / 'all_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
