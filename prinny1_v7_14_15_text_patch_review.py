#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import core.font_builder as builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_14_14_title_difficulty_repair"
    / "prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
)
SEALED = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_text_patch_manifest"
    / "sealed_expected_writes.csv"
)
MANIFEST = SEALED.parent / "all_report.json"
LAYOUT = (
    ROOT
    / "workspace/reports/prinny1_v7_14_15_boot_translation_plan"
    / "layout_validation.csv"
)
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_text_patch_review"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def decode(payload: bytes, reverse: dict[bytes, str]) -> str:
    if len(payload) % 2:
        raise ValueError("검토 문자열이 홀수 바이트입니다.")
    output = []
    for offset in range(0, len(payload), 2):
        pair = payload[offset:offset + 2]
        output.append(reverse[pair] if pair in reverse else pair.decode("cp932"))
    return "".join(output)


def main() -> int:
    for path in (BASE_ISO, SEALED, MANIFEST, LAYOUT, ALLOCATION):
        if not path.is_file():
            raise FileNotFoundError(path)
    rows = read_csv(SEALED)
    layout_rows = read_csv(LAYOUT)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    reverse = {
        bytes.fromhex(str(row["sjis"])): str(row["hangul"])
        for row in allocation["allocations"]
    }
    if len(rows) != 12 or len(reverse) != 980:
        raise ValueError("봉인 쓰기 또는 코드맵 수가 다릅니다.")

    boot = read_iso_file(
        BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    )
    system = read_iso_file(
        BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    )
    entry = builder.parse_nispack_start_entry(system)
    start, _ = decompress_buffer(
        system[int(entry["data_offset"]):int(entry["data_offset"]) + int(entry["size"])]
    )
    archive = StartRuntimeArchive.from_bytes(start, source="independent_review")
    records = {record.output_name.casefold(): record for record in archive.records}
    font_record = records["font.txp"]

    patched_boot = bytearray(boot)
    patched_start = bytearray(start)
    seen: set[tuple[str, int]] = set()
    ranges: dict[str, list[tuple[int, int]]] = {"boot": [], "font": []}
    for row in rows:
        layer = row["layer"]
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if not before or len(before) != len(after):
            raise ValueError(f"쓰기 길이 오류: {row['logical_id']}")
        key = (layer, offset)
        if key in seen:
            raise ValueError(f"중복 쓰기: {key}")
        seen.add(key)
        if layer == "PSP_GAME/SYSDIR/BOOT.BIN":
            target = patched_boot
            absolute = offset
            range_key = "boot"
        elif layer == "START.DAT/font.txp":
            target = patched_start
            absolute = int(font_record.data_offset) + offset
            if absolute + len(before) > int(font_record.end_offset):
                raise ValueError(f"font.txp 경계 초과: {row['logical_id']}")
            range_key = "font"
        else:
            raise ValueError(f"예상하지 못한 계층: {layer}")
        if target[absolute:absolute + len(before)] != before:
            raise ValueError(f"독립 before 검증 실패: {row['logical_id']}")
        ranges[range_key].append((absolute, absolute + len(before)))
        target[absolute:absolute + len(after)] = after

    for items in ranges.values():
        items.sort()
        if any(left[1] > right[0] for left, right in zip(items, items[1:])):
            raise ValueError("봉인 쓰기 범위가 중첩됩니다.")

    for layout in layout_rows:
        offset = int(layout["new_offset_hex"], 0)
        length = int(layout["payload_bytes"])
        actual = decode(bytes(patched_boot[offset:offset + length]), reverse)
        if actual != layout["mechanical_fullwidth_line"]:
            raise ValueError(
                f"BOOT 문구 왕복 불일치: {layout['group_id']}/{layout['line_order']}"
            )

    for character in ("탠", "닿", "벤"):
        item = next(row for row in allocation["allocations"] if row["hangul"] == character)
        glyph_offset = builder.TXP_PIXEL_OFFSET + int(item["glyph_index"]) * builder.BYTES_PER_GLYPH
        font_bytes = bytes(
            patched_start[
                int(font_record.data_offset) + glyph_offset:
                int(font_record.data_offset) + glyph_offset + builder.BYTES_PER_GLYPH
            ]
        )
        sealed_row = next(row for row in rows if row.get("target") == "font.txp" and bytes.fromhex(row["write_after_hex"]) == font_bytes)
        if sealed_row.get("expected_write_confirmed") != "yes":
            raise ValueError(f"확장 글리프 미확정: {character}")

    start_hash = sha256(bytes(patched_start))
    boot_hash = sha256(bytes(patched_boot))
    if start_hash != manifest["sealed"]["patched_start_sha256"]:
        raise ValueError("독립 START 결과 해시 불일치")
    if boot_hash != manifest["sealed"]["patched_boot_sha256"]:
        raise ValueError("독립 BOOT 결과 해시 불일치")
    if manifest["deferred_images"]["write_count"] != 0:
        raise ValueError("텍스트 우선 manifest에 이미지 쓰기가 포함됐습니다.")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "prinny1_v7_14_15_text_patch_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_path": "independent_fresh_iso_reextract",
        "sealed_write_count": len(rows),
        "font_write_count": sum(row["target"] == "font.txp" for row in rows),
        "boot_write_count": sum(row["target"].endswith("BOOT.BIN") for row in rows),
        "decoded_layout_rows": len(layout_rows),
        "patched_start_sha256": start_hash,
        "patched_boot_sha256": boot_hash,
        "checks": {
            "fresh_iso_reextract": True,
            "all_before_bytes_match": True,
            "all_ranges_non_overlapping": True,
            "all_boot_text_roundtrips": True,
            "three_extended_glyphs_match": True,
            "producer_hashes_reproduced": True,
            "image_writes_absent": True,
            "iso_created": False,
        },
        "status": "pass_iso_build_approval_required",
        "final_verdict": "PASS",
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"독립 검증 쓰기: {len(rows)}")
    print(f"BOOT 문구 왕복: {len(layout_rows)}")
    print("이미지 쓰기: 0")
    print("ISO 생성: 없음")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
