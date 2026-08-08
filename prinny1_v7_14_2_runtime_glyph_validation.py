#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from prinny1_v7_14_1_base_compatibility import (
    DRIVE_DEFAULT,
    PROJECT_DEFAULT,
    ROOT_DEFAULT,
    clean_hex,
    find_iso_file,
    read_csv,
    read_iso_file,
    sha256_file,
    write_csv,
    write_json,
)

EXPECTED_CODEMAP_ENTRIES = 960
TARGET_TEXT = "도망치고싶어"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_record(archive: Any, name: str) -> Any:
    normalized = Path(name).name.casefold()
    matches = [
        record
        for record in archive.records
        if (
            str(record.name).casefold() == normalized
            or str(record.output_name).casefold() == normalized
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            f"START 자원을 하나로 확정하지 못했습니다: "
            f"{name} (matches={len(matches)})"
        )

    return matches[0]


def record_bytes(archive: Any, record: Any) -> bytes:
    return archive.data[
        int(record.data_offset):int(record.end_offset)
    ]


def render_glyphs(
    runtime: Any,
    rows: list[dict[str, Any]],
    output: Path,
    scale: int = 8,
) -> None:
    cell_width = 190
    glyph_width = int(runtime.txp["width"]) * scale
    glyph_height = int(runtime.txp["glyph_height"]) * scale
    cell_height = glyph_height + 48
    sheet = Image.new(
        "RGB",
        (cell_width * len(rows), cell_height),
        "black",
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for column, row in enumerate(rows):
        glyph = runtime.decode_glyph(int(row["actual_glyph_index"]))
        glyph = glyph.resize(
            (glyph_width, glyph_height),
            Image.Resampling.NEAREST,
        ).convert("RGB")
        left = column * cell_width
        sheet.paste(
            glyph,
            (left + (cell_width - glyph_width) // 2, 4),
        )
        labels = [
            f"U+{ord(str(row['character'])):04X}",
            f"CODE {row['encoded_hex']}",
            (
                f"T={int(row['table_index']):04X} "
                f"G={int(row['actual_glyph_index']):04X}"
            ),
        ]

        for index, label in enumerate(labels):
            draw.text(
                (left + 5, glyph_height + 6 + index * 11),
                label,
                fill="white",
                font=font,
            )

        draw.rectangle(
            (left, 0, left + cell_width - 1, cell_height - 1),
            outline="white",
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        type=Path,
        default=PROJECT_DEFAULT,
    )
    parser.add_argument(
        "--base-iso",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "build/prinny_stage1_hotfix_v6_2"
            / "prinny_korean_stage1_hotfix_v6_2_977.iso"
        ),
    )
    parser.add_argument(
        "--codemap",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_3_outlier_quarantine"
            / "accepted_encoder_profile.json"
        ),
    )
    parser.add_argument(
        "--patch-plan",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "reports/prinny1_v7_13_4_expected_write_confirmation"
            / "confirmed_patch_plan.csv"
        ),
    )
    parser.add_argument(
        "--font-manifest",
        type=Path,
        default=(
            ROOT_DEFAULT
            / "build/prinny_stage1_hotfix_v6_2"
            / "font_source/manifest.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_DEFAULT
            / "workspace/reports"
            / "prinny1_v7_14_2_runtime_glyph_validation"
        ),
    )
    arguments = parser.parse_args()

    project = arguments.project.expanduser().resolve()
    base_iso = arguments.base_iso.expanduser().resolve()
    codemap_path = arguments.codemap.expanduser().resolve()
    plan_path = arguments.patch_plan.expanduser().resolve()
    manifest_path = arguments.font_manifest.expanduser().resolve()
    output = arguments.output.expanduser().resolve()

    for required in (
        project,
        base_iso,
        codemap_path,
        plan_path,
        manifest_path,
    ):
        if not required.exists():
            raise FileNotFoundError(f"필수 입력이 없습니다: {required}")

    profile = json.loads(codemap_path.read_text(encoding="utf-8"))
    mapping = profile.get("mapping")

    if (
        not profile.get("validated")
        or profile.get("map_entries") != EXPECTED_CODEMAP_ENTRIES
        or not isinstance(mapping, dict)
        or len(mapping) != EXPECTED_CODEMAP_ENTRIES
    ):
        raise ValueError("검증된 960자 코드맵이 아닙니다.")

    plans = read_csv(plan_path)

    if len(plans) != 1:
        raise ValueError(f"V7.13.4 패치 계획 수가 1이 아닙니다: {len(plans)}")

    plan_text = plans[0].get("replacement_text", "")

    if not plan_text or TARGET_TEXT not in plan_text:
        raise ValueError(
            f"대상 문구가 V7.13.4 계획과 일치하지 않습니다: {plan_text!r}"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_glyphs = {
        item.get("hangul"): item
        for item in manifest.get("glyphs", [])
        if isinstance(item, dict) and item.get("hangul")
    }

    from core.font_runtime import FontRuntime
    from core.lzs import decompress_buffer
    import core.font_builder as builder
    from core.start_runtime import StartRuntimeArchive

    print("[1/4] V6.2 ISO에서 START.DAT와 런타임 폰트 직접 복원")
    system_entry = find_iso_file(
        base_iso,
        ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    )
    system_data = read_iso_file(base_iso, system_entry)
    start_entry = builder.parse_nispack_start_entry(system_data)
    lzs_offset = int(start_entry["data_offset"])
    lzs_size = int(start_entry["size"])
    start_data, _ = decompress_buffer(
        system_data[lzs_offset:lzs_offset + lzs_size]
    )
    archive = StartRuntimeArchive.from_bytes(
        start_data,
        source=f"{base_iso}!/start.dat",
    )
    fnt_data = record_bytes(archive, resolve_record(archive, "font.fnt"))
    txp_data = record_bytes(archive, resolve_record(archive, "font.txp"))
    runtime = FontRuntime(
        fnt_path=Path(f"{base_iso}!/font.fnt"),
        txp_path=Path(f"{base_iso}!/font.txp"),
        table=FontRuntime._parse_fnt(fnt_data),
        txp_data=txp_data,
        txp=FontRuntime._parse_txp(txp_data),
    )

    print("[2/4] 대상 글자의 960자 코드와 font.fnt 조회 결과 대조")
    unique_characters = list(dict.fromkeys(TARGET_TEXT))
    rows: list[dict[str, Any]] = []

    for character in unique_characters:
        encoded_hex = clean_hex(mapping.get(character, ""))

        if len(encoded_hex) != 4:
            raise ValueError(f"대상 글자 코드가 없습니다: {character}")

        encoded = bytes.fromhex(encoded_hex)
        table_index = FontRuntime.table_index_from_sjis(encoded)

        if table_index >= len(runtime.table):
            raise ValueError(
                f"font.fnt 범위 초과: {character} index=0x{table_index:X}"
            )

        actual_glyph_index = int(runtime.table[table_index])
        glyph_start = (
            int(runtime.txp["pixel_offset"])
            + actual_glyph_index * int(runtime.txp["bytes_per_glyph"])
        )
        glyph_end = glyph_start + int(runtime.txp["bytes_per_glyph"])

        if glyph_end > len(txp_data):
            raise ValueError(f"font.txp 글리프 범위 초과: {character}")

        actual_glyph_sha1 = sha1_bytes(txp_data[glyph_start:glyph_end])
        expected = manifest_glyphs.get(character)

        if not expected:
            raise ValueError(f"V6.2 폰트 매니페스트에 글자가 없습니다: {character}")

        row = {
            "character": character,
            "unicode": f"U+{ord(character):04X}",
            "encoded_hex": encoded_hex,
            "table_index": table_index,
            "table_index_hex": f"0x{table_index:X}",
            "actual_glyph_index": actual_glyph_index,
            "actual_glyph_index_hex": f"0x{actual_glyph_index:X}",
            "manifest_sjis": clean_hex(expected.get("sjis", "")),
            "manifest_table_index": expected.get("table_index"),
            "manifest_glyph_index": expected.get("glyph_index"),
            "actual_glyph_sha1": actual_glyph_sha1,
            "manifest_glyph_sha1": expected.get("glyph_sha1", ""),
            "code_matches_manifest": (
                encoded_hex == clean_hex(expected.get("sjis", ""))
            ),
            "table_index_matches_manifest": (
                table_index == expected.get("table_index")
            ),
            "glyph_index_matches_manifest": (
                actual_glyph_index == expected.get("glyph_index")
            ),
            "glyph_bytes_match_manifest": (
                actual_glyph_sha1 == expected.get("glyph_sha1")
            ),
        }
        row["ok"] = all(
            bool(row[key])
            for key in (
                "code_matches_manifest",
                "table_index_matches_manifest",
                "glyph_index_matches_manifest",
                "glyph_bytes_match_manifest",
            )
        )
        rows.append(row)

    print("[3/4] 내장 font.txp 계보와 대상 글리프 픽셀 검증")
    embedded_txp_sha1 = sha1_bytes(txp_data)
    embedded_txp_matches_manifest = (
        embedded_txp_sha1 == manifest.get("output_txp_sha1")
    )
    all_glyphs_match = all(bool(row["ok"]) for row in rows)
    preview_path = output / "target_glyphs.png"
    render_glyphs(runtime, rows, preview_path)

    conclusion = (
        "runtime_font_mapping_and_glyphs_valid"
        if embedded_txp_matches_manifest and all_glyphs_match
        else "runtime_font_or_mapping_mismatch"
    )
    next_action = (
        "텍스트 바이트와 런타임 글리프가 모두 정상입니다. "
        "다음에는 Demo00.dat의 대사 레이아웃 명령, 표시 폭, "
        "문자열 선택 흐름을 조사합니다."
        if conclusion == "runtime_font_mapping_and_glyphs_valid"
        else
        "폰트 매핑 또는 글리프 불일치를 먼저 복구해야 합니다."
    )

    print("[4/4] CSV·JSON·글리프 미리보기 저장")
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "target_glyph_validation.csv"
    json_path = output / "all_report.json"
    write_csv(csv_path, rows, list(rows[0].keys()))
    write_json(
        json_path,
        {
            "format": "prinny1_v7_14_2_runtime_glyph_validation_v1",
            "created_at": now(),
            "base_iso": str(base_iso),
            "base_iso_sha256": sha256_file(base_iso),
            "codemap": str(codemap_path),
            "codemap_sha256": sha256_file(codemap_path),
            "codemap_entries": len(mapping),
            "patch_plan": str(plan_path),
            "patch_plan_sha256": sha256_file(plan_path),
            "font_manifest": str(manifest_path),
            "font_manifest_sha256": sha256_file(manifest_path),
            "target_text": TARGET_TEXT,
            "candidate_text": plan_text,
            "embedded_font_fnt_sha256": sha256_bytes(fnt_data),
            "embedded_font_txp_sha256": sha256_bytes(txp_data),
            "embedded_font_txp_sha1": embedded_txp_sha1,
            "manifest_output_txp_sha1": manifest.get("output_txp_sha1"),
            "embedded_txp_matches_manifest": embedded_txp_matches_manifest,
            "font_table_entries": len(runtime.table),
            "font_glyph_count": runtime.txp["glyph_count"],
            "validated_unique_characters": len(rows),
            "all_glyphs_match": all_glyphs_match,
            "conclusion": conclusion,
            "next_action": next_action,
            "iso_created": False,
            "bytes_modified": 0,
            "outputs": {
                "csv": str(csv_path),
                "json": str(json_path),
                "preview": str(preview_path),
            },
            "glyphs": rows,
        },
    )

    print()
    print("완료")
    print(f"대상 문구              : {TARGET_TEXT}")
    print(f"검증 글자              : {len(rows)}")
    print(f"내장 TXP 계보 일치     : {embedded_txp_matches_manifest}")
    print(f"전체 글리프 일치       : {all_glyphs_match}")
    print(f"판정                   : {conclusion}")
    print(f"다음 처리              : {next_action}")
    print("ISO 생성               : 없음")

    return 0 if conclusion == "runtime_font_mapping_and_glyphs_valid" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
