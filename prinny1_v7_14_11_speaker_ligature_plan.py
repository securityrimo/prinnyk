#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from build_font_canary import BYTES_PER_GLYPH, TXP_PIXEL_OFFSET, encode_4bpp
from core.start_runtime import StartRuntimeArchive


ROOT = Path(__file__).resolve().parent
SOURCE_START = (
    ROOT
    / "workspace/build/prinny1_v7_14_9_prologue_full_punctuation/start.dat"
)
OLD_PLAN = (
    ROOT
    / "workspace/reports/prinny1_v7_14_8_prologue_repair_plan"
    / "confirmed_patch_plan.csv"
)
ALLOCATION = ROOT / "workspace/font/audited_allocation_977/hangul_allocation.json"
CHARSET_PLAN = ROOT / "workspace/font/final_charset_plan/final_charset_plan.json"
FONT = Path.home() / ".local/share/fonts/Galmuri14.ttf"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_11_speaker_ligature_plan"

LIGATURE_TEXT = "대원"
LIGATURE_SJIS = bytes.fromhex("88A2")
LIGATURE_TABLE_INDEX = 0x0601
LIGATURE_GLYPH_INDEX = 0x01B4
EXPECTED_REPLACED_CHARACTER = "阿"
CURRENT_NAME = bytes.fromhex("C989F396B18F5094E790D5")
LIGATURE_NAME = bytes.fromhex("C989F396B18F5088A20000")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_ligature() -> tuple[bytes, Image.Image]:
    scale = 4
    width, height = 20, 14
    canvas = Image.new("L", (width * scale, height * scale), 0)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(FONT), 40)
    bbox = draw.textbbox((0, 0), LIGATURE_TEXT, font=font, spacing=0)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (canvas.width - text_width) // 2 - bbox[0]
    y = (canvas.height - text_height) // 2 - bbox[1]
    draw.text((x, y), LIGATURE_TEXT, font=font, fill=255, spacing=0)
    reduced = canvas.resize((width, height), Image.Resampling.LANCZOS)
    pixels = [
        [max(0, min(15, round(reduced.getpixel((x, y)) / 17))) for x in range(width)]
        for y in range(height)
    ]
    encoded = encode_4bpp(pixels)
    if len(encoded) != BYTES_PER_GLYPH:
        raise ValueError("결합 글리프 크기가 잘못됐습니다.")
    preview = reduced.resize((width * 16, height * 16), Image.Resampling.NEAREST)
    return encoded, preview


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    for required in (SOURCE_START, OLD_PLAN, ALLOCATION, CHARSET_PLAN, FONT):
        if not required.is_file():
            raise FileNotFoundError(required)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))
    charset = json.loads(CHARSET_PLAN.read_text(encoding="utf-8"))
    allocated_pairs = {
        (int(item["table_index"]), int(item["glyph_index"]))
        for item in allocation["allocations"]
    }
    matching_candidates = [
        item for item in charset["strict_candidates"]
        if int(item["table_index"]) == LIGATURE_TABLE_INDEX
        and int(item["glyph_index"]) == LIGATURE_GLYPH_INDEX
        and item["character"] == EXPECTED_REPLACED_CHARACTER
    ]
    if len(matching_candidates) != 1:
        raise ValueError("결합 글리프 후보를 유일하게 검증하지 못했습니다.")
    if (LIGATURE_TABLE_INDEX, LIGATURE_GLYPH_INDEX) in allocated_pairs:
        raise ValueError("결합 글리프 후보가 기존 977자와 충돌합니다.")
    if int(matching_candidates[0]["alias_count"]) != 1:
        raise ValueError("결합 글리프 후보가 다른 문자와 글리프를 공유합니다.")

    start = SOURCE_START.read_bytes()
    archive = StartRuntimeArchive.from_bytes(start, source=str(SOURCE_START))
    records = {str(record.output_name).casefold(): record for record in archive.records}
    fnt = records["font.fnt"]
    txp = records["font.txp"]
    demo = records["demo00.dat"]
    fnt_data = start[fnt.data_offset:fnt.end_offset]
    mapped_glyph = int.from_bytes(
        fnt_data[2 + LIGATURE_TABLE_INDEX * 2:4 + LIGATURE_TABLE_INDEX * 2],
        "little",
    )
    if mapped_glyph != LIGATURE_GLYPH_INDEX:
        raise ValueError("V7.14.9 font.fnt의 후보 매핑이 예상과 다릅니다.")

    encoded_glyph, preview = render_ligature()
    preview.save(REPORT_DIR / "dae_won_ligature_preview.png")
    glyph_offset = TXP_PIXEL_OFFSET + LIGATURE_GLYPH_INDEX * BYTES_PER_GLYPH
    glyph_before = start[
        txp.data_offset + glyph_offset:
        txp.data_offset + glyph_offset + BYTES_PER_GLYPH
    ]
    if len(glyph_before) != BYTES_PER_GLYPH or glyph_before == encoded_glyph:
        raise ValueError("결합 글리프 Expected Write를 만들 수 없습니다.")

    with OLD_PLAN.open("r", encoding="utf-8-sig", newline="") as handle:
        old_rows = list(csv.DictReader(handle))
    speaker_rows = [row for row in old_rows if row.get("group_id") == "G018"]
    if len(speaker_rows) != 27:
        raise ValueError(f"이름 슬롯 수가 27개가 아닙니다: {len(speaker_rows)}")

    writes: list[dict[str, object]] = [{
        "group_id": "G019",
        "logical_id": "FONT-LIGATURE-DAEWON",
        "occurrence_number": 1,
        "target": "font.txp",
        "offset_hex": f"0x{glyph_offset:X}",
        "slot_capacity": BYTES_PER_GLYPH,
        "expected_before_hex": glyph_before.hex().upper(),
        "write_after_hex": encoded_glyph.hex().upper(),
        "source_text": EXPECTED_REPLACED_CHARACTER,
        "current_text": EXPECTED_REPLACED_CHARACTER,
        "replacement_text": LIGATURE_TEXT,
        "change_kind": "dedicated_speaker_name_ligature_glyph",
        "user_wording_approval": "yes",
        "expected_write_confirmed": "yes",
    }]
    demo_data = start[demo.data_offset:demo.end_offset]
    offsets: list[int] = []
    for number, old in enumerate(speaker_rows, start=1):
        offset = int(old["offset_hex"], 0)
        offsets.append(offset)
        actual = demo_data[offset:offset + len(CURRENT_NAME)]
        if actual != CURRENT_NAME:
            raise ValueError(
                f"V7.14.9 이름 슬롯 {number} 불일치: {actual.hex().upper()}"
            )
        writes.append({
            "group_id": "G020",
            "logical_id": "TXT-D23CB67F0C43-LIGATURE",
            "occurrence_number": number,
            "target": "Demo00.dat",
            "offset_hex": f"0x{offset:X}",
            "slot_capacity": len(CURRENT_NAME),
            "expected_before_hex": CURRENT_NAME.hex().upper(),
            "write_after_hex": LIGATURE_NAME.hex().upper(),
            "source_text": "プリニー隊",
            "current_text": "프리니대원(5글자)",
            "replacement_text": "프리니+[대원 결합 글리프](4칸)",
            "change_kind": "speaker_name_layout_only_ligature",
            "user_wording_approval": "yes",
            "expected_write_confirmed": "yes",
        })
    if len(set(offsets)) != 27:
        raise ValueError("이름 슬롯 오프셋이 중복됩니다.")

    write_csv(REPORT_DIR / "confirmed_patch_plan.csv", writes)
    write_csv(REPORT_DIR / "expected_write_confirmed.csv", writes)
    report = {
        "format": "prinny1_v7_14_11_speaker_ligature_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base": str(SOURCE_START),
        "base_sha256": sha256(start),
        "ligature": {
            "visible_text": LIGATURE_TEXT,
            "sjis_hex": LIGATURE_SJIS.hex().upper(),
            "table_index_hex": f"0x{LIGATURE_TABLE_INDEX:04X}",
            "glyph_index_hex": f"0x{LIGATURE_GLYPH_INDEX:04X}",
            "replaces_unused_character": EXPECTED_REPLACED_CHARACTER,
            "strict_candidate": True,
            "alias_count": 1,
            "conflicts_with_977_allocations": False,
            "glyph_before_sha256": sha256(glyph_before),
            "glyph_after_sha256": sha256(encoded_glyph),
        },
        "speaker_occurrences": len(speaker_rows),
        "expected_write_count": len(writes),
        "changed_resources": ["font.txp", "Demo00.dat"],
        "global_renderer_changed": False,
        "character_voice_changed": False,
        "status": "expected_write_confirmed_preview_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Expected Writes: {len(writes)}")
    print(f"Preview: {REPORT_DIR / 'dae_won_ligature_preview.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
