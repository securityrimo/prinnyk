#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from core.font_runtime import FontRuntime
from core.start_runtime import StartRuntimeArchive


ROOT = Path(__file__).resolve().parent
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_14_16_boot_alias_plan"
PLAN_REPORT = PLAN_DIR / "all_report.json"
WRITES = PLAN_DIR / "expected_write_confirmed.csv"
ALIASES = PLAN_DIR / "alias_mapping.csv"
LAYOUT = PLAN_DIR / "layout_validation.csv"
START = ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/start.dat"
BOOT = ROOT / "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_16_boot_alias_review"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def changed(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("독립 검토 비교 크기가 다릅니다.")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def main() -> int:
    for path in (PLAN_REPORT, WRITES, ALIASES, LAYOUT, START, BOOT):
        if not path.is_file():
            raise FileNotFoundError(path)
    plan = json.loads(PLAN_REPORT.read_text(encoding="utf-8"))
    if plan.get("status") != "expected_writes_confirmed_independent_review_required":
        raise ValueError("별칭 계획 상태가 독립 검토 대기가 아닙니다.")
    for key, path in (
        ("source_start_sha256", START),
        ("source_boot_sha256", BOOT),
    ):
        if sha256_file(path) != plan["inputs"][key]:
            raise ValueError(f"독립 검토 입력 해시 불일치: {path}")

    archive = StartRuntimeArchive.load(START)
    records = {record.output_name.casefold(): record for record in archive.records}
    fnt_record = records["font.fnt"]
    source_fnt = archive.data[fnt_record.data_offset:fnt_record.end_offset]
    source_boot = BOOT.read_bytes()
    patched_fnt = bytearray(source_fnt)
    patched_boot = bytearray(source_boot)
    declared_fnt: set[int] = set()
    declared_boot: set[int] = set()
    rows = read_csv(WRITES)
    if len(rows) != 10:
        raise ValueError(f"Expected Write가 10개가 아닙니다: {len(rows)}")
    for row in rows:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if len(before) != len(after) or len(after) != int(row["write_span"]):
            raise ValueError(f"Expected Write 길이 오류: {row['logical_id']}")
        if row["layer"] == "START.DAT/font.fnt":
            target = patched_fnt
            declared = declared_fnt
        elif row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN":
            target = patched_boot
            declared = declared_boot
        else:
            raise ValueError(f"허용되지 않은 계층: {row['layer']}")
        if target[offset:offset + len(before)] != before:
            raise ValueError(f"독립 before 불일치: {row['logical_id']}")
        target[offset:offset + len(after)] = after
        declared.update(
            offset + index for index, (old, new) in enumerate(zip(before, after)) if old != new
        )
    if changed(source_fnt, bytes(patched_fnt)) != declared_fnt:
        raise ValueError("font.fnt 실제 변경이 선언과 다릅니다.")
    if changed(source_boot, bytes(patched_boot)) != declared_boot:
        raise ValueError("BOOT 실제 변경이 선언과 다릅니다.")

    source_table = FontRuntime._parse_fnt(source_fnt)
    patched_table = FontRuntime._parse_fnt(bytes(patched_fnt))
    alias_rows = read_csv(ALIASES)
    if len(alias_rows) != 54:
        raise ValueError("별칭 행이 54개가 아닙니다.")
    reverse: dict[bytes, str] = {}
    for row in alias_rows:
        alias = bytes.fromhex(row["alias_sjis"])
        source = bytes.fromhex(row["source_sjis"])
        alias_index = FontRuntime.table_index_from_sjis(alias)
        source_index = FontRuntime.table_index_from_sjis(source)
        expected_glyph = int(row["glyph_index_hex"], 0)
        if source_table[alias_index] != 0:
            raise ValueError(f"원본 F0 별칭 슬롯 비어 있지 않음: {row['hangul']}")
        if source_table[source_index] != expected_glyph:
            raise ValueError(f"원본 글리프 연결 불일치: {row['hangul']}")
        if patched_table[alias_index] != expected_glyph:
            raise ValueError(f"패치 별칭 글리프 연결 불일치: {row['hangul']}")
        if patched_table[source_index] != source_table[source_index]:
            raise ValueError(f"기존 매핑 변경 감지: {row['hangul']}")
        reverse[alias] = row["hangul"]

    layout_rows = read_csv(LAYOUT)
    if len(layout_rows) != 10:
        raise ValueError("레이아웃 검증 행이 10개가 아닙니다.")
    for row in layout_rows:
        offset = int(row["new_offset_hex"], 0)
        length = int(row["payload_bytes"])
        payload = bytes(patched_boot[offset:offset + length])
        decoded_parts: list[str] = []
        for index in range(0, len(payload), 2):
            pair = payload[index:index + 2]
            decoded_parts.append(reverse[pair] if pair in reverse else pair.decode("cp932"))
        if "".join(decoded_parts) != row["mechanical_fullwidth_line"]:
            raise ValueError(f"BOOT 별칭 문구 왕복 불일치: {row['group_id']}/{row['line_order']}")
        if row["wording_changed"] != "no":
            raise ValueError("문구 변경 플래그가 no가 아닙니다.")

    review = {
        "format": "prinny1_v7_14_16_boot_alias_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "plan_report": str(PLAN_REPORT),
            "plan_report_sha256": sha256_file(PLAN_REPORT),
            "writes_sha256": sha256_file(WRITES),
            "aliases_sha256": sha256_file(ALIASES),
            "layout_sha256": sha256_file(LAYOUT),
        },
        "verified": {
            "expected_write_count": len(rows),
            "alias_count": len(alias_rows),
            "layout_row_count": len(layout_rows),
            "font_fnt_changed_bytes": len(declared_fnt),
            "boot_changed_bytes": len(declared_boot),
            "patched_font_fnt_sha256": sha256_bytes(bytes(patched_fnt)),
            "patched_boot_sha256": sha256_bytes(bytes(patched_boot)),
        },
        "checks": {
            "fresh_sources_reopened": True,
            "all_before_bytes_match": True,
            "actual_changes_equal_declared": True,
            "all_54_alias_targets_originally_zero": True,
            "all_54_aliases_point_to_existing_glyphs": True,
            "existing_scattered_mappings_preserved": True,
            "all_10_layout_rows_roundtrip": True,
            "translation_wording_generated_or_changed_by_codex": False,
            "xdelta_wording_imported": False,
            "iso_created": False,
        },
        "status": "pass_resource_build_required",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT / "all_report.json"
    report_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"F0 aliases: {len(alias_rows)} PASS")
    print(f"Expected Writes: {len(rows)} PASS")
    print(f"layout roundtrip: {len(layout_rows)} PASS")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
