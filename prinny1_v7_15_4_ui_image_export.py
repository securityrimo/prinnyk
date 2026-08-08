#!/usr/bin/env python3
"""Export xdelta-authoritative Prinny 1 image/UI assets for human translation."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import struct
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from scripts.prinny_anime_preview import decode_texture, find_texture_groups, parse_objects
from scripts.prinny_txp_preview import decode_txp


ROOT = Path(__file__).resolve().parent
ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
CANDIDATE = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate"
ANIME_ROOT = CANDIDATE / "anime_resources"
BG_ROOT = CANDIDATE / "bg_resources"
START_ROOT = CANDIDATE / "start_resources"
OUTPUT = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_4_ui_image_export"
EXPECTED_ISO_SHA256 = "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7"
EXPECTED_RESOURCES = {
    "SYSTEM.DAT": "665b373d513de94058dbd5dbd7dd0c3e410a088dd67b3e0e01c6ac24584d1616",
    "ANIME.DAT": "292d75ec404c7c9d40f8f214a10a58776e6025bb3d49c150aca227a6a304cef0",
    "BG.DAT": "1e7cce5da883155f0ed68949839d0618ebd1e8a9e052ceee8045e526c1194562",
    "start.dat": "ee92515c9b014c95072abf5404cc20f3330080b636393421d72ba3f2a8978cba",
}


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"빈 CSV입니다: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def relative(path: Path) -> str:
    return str(path.relative_to(OUTPUT))


def save_png(image: Image.Image, target: Path) -> tuple[int, int, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    with Image.open(target) as verified:
        verified.load()
        width, height = verified.size
    return width, height, sha256_file(target)


def system_records(system: bytes) -> list[dict[str, Any]]:
    if system[:7] != b"NISPACK":
        raise ValueError("SYSTEM.DAT NISPACK 서명 불일치")
    count = struct.unpack_from("<I", system, 0x0C)[0]
    records = []
    for index in range(count):
        offset = 0x10 + index * 0x2C
        name = system[offset:offset + 0x20].split(b"\0", 1)[0].decode("ascii")
        data_offset, size = struct.unpack_from("<II", system, offset + 0x20)
        if data_offset + size > len(system):
            raise ValueError(f"SYSTEM.DAT 레코드 범위 오류: {name}")
        records.append({"index": index, "name": name, "data_offset": data_offset, "size": size})
    return records


def contact_sheet(items: list[tuple[str, Path]], target: Path) -> list[dict[str, Any]]:
    columns, cell_w, cell_h = 5, 200, 130
    rows = math.ceil(len(items) / columns)
    canvas = Image.new("RGB", (columns * cell_w, rows * cell_h), (38, 38, 38))
    draw = ImageDraw.Draw(canvas)
    index_rows = []
    for cell, (asset_id, source) in enumerate(items):
        x, y = (cell % columns) * cell_w, (cell // columns) * cell_h
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
        image.thumbnail((cell_w - 12, cell_h - 28), Image.Resampling.NEAREST)
        checker = Image.new("RGBA", image.size, (220, 220, 220, 255))
        checker.alpha_composite(image)
        px = x + (cell_w - image.width) // 2
        py = y + 2
        canvas.paste(checker.convert("RGB"), (px, py))
        draw.text((x + 5, y + cell_h - 20), asset_id, fill=(255, 255, 255))
        index_rows.append({"asset_id": asset_id, "sheet": relative(target), "cell": cell, "column": cell % columns, "row": cell // columns})
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)
    return index_rows


def main() -> int:
    if OUTPUT.exists():
        raise ValueError("V7.15.4 이미지 번역 작업 폴더가 이미 있습니다. 덮어쓰지 않습니다.")
    if not ISO.is_file() or sha256_file(ISO) != EXPECTED_ISO_SHA256:
        raise ValueError("V7.15.4 xdelta 기준 ISO 해시 불일치")
    if len(list(ANIME_ROOT.glob("anime*.dat"))) != 28 or len(list(BG_ROOT.glob("*.txp"))) != 155:
        raise ValueError("xdelta 이미지 하위 자원 수 불일치")

    blobs = {}
    for name in ("SYSTEM.DAT", "ANIME.DAT", "BG.DAT"):
        blobs[name] = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "USRDIR", name]))
        if sha256_bytes(blobs[name]) != EXPECTED_RESOURCES[name]:
            raise ValueError(f"V7.15.4 이미지 기준 자원 해시 불일치: {name}")
    entry = font_builder.parse_nispack_start_entry(blobs["SYSTEM.DAT"])
    start, _ = decompress_buffer(blobs["SYSTEM.DAT"][int(entry["data_offset"]):int(entry["data_offset"]) + int(entry["size"])])
    if sha256_bytes(start) != EXPECTED_RESOURCES["start.dat"]:
        raise ValueError("V7.15.4 start.dat 해시 불일치")
    archive = StartRuntimeArchive.from_bytes(start)
    start_records = {record.output_name.casefold(): record for record in archive.records}
    for name in ("anime00.dat", "number.txp", "font.txp"):
        record = start_records[name]
        blob = start[record.data_offset:record.end_offset]
        if not (START_ROOT / name).is_file() or sha256_file(START_ROOT / name) != sha256_bytes(blob):
            raise ValueError(f"xdelta START 추출 자원 불일치: {name}")

    OUTPUT.mkdir(parents=True)
    (OUTPUT / "translated").mkdir()
    inventory: list[dict[str, Any]] = []
    sheet_groups: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    sequence = 0

    def add_asset(category: str, container: str, raw_source: str, raw_sha: str, png: Path,
                  width: int, height: int, priority: str, relevance: str,
                  object_index: str = "", group_index: str = "", page_index: str = "") -> None:
        nonlocal sequence
        sequence += 1
        asset_id = f"P1-IMG-V7.15.4-{sequence:04d}"
        group_key = container.replace(".", "_")
        inventory.append({
            "asset_id": asset_id, "category": category, "container": container,
            "raw_source": raw_source, "raw_source_sha256": raw_sha,
            "png_source": relative(png), "png_sha256": sha256_file(png),
            "width": width, "height": height, "object_index": object_index,
            "group_index": group_index, "page_index": page_index,
            "review_priority": priority, "translation_relevance": relevance,
            "translation_status": "pending_visual_review" if relevance != "reference_only" else "reference_only",
            "source_text_japanese": "", "translation_korean": "", "notes": "",
            "contact_sheet": "", "contact_cell": "",
        })
        sheet_groups[group_key].append((asset_id, png))

    for index, name in enumerate(("ICON0.PNG", "PIC0.PNG", "PIC1.PNG"), 1):
        blob = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", name]))
        target = OUTPUT / "source_png/direct_iso" / name
        width, height, _ = save_png(Image.open(io.BytesIO(blob)).convert("RGBA"), target)
        add_asset("direct_iso_png", "ISO_DIRECT", f"{ISO}!/PSP_GAME/{name}", sha256_bytes(blob), target, width, height, "medium", "branding_or_boot_image")

    for record in system_records(blobs["SYSTEM.DAT"]):
        if not record["name"].upper().endswith(".PNG"):
            continue
        blob = blobs["SYSTEM.DAT"][record["data_offset"]:record["data_offset"] + record["size"]]
        target = OUTPUT / "source_png/system_pack" / record["name"]
        width, height, _ = save_png(Image.open(io.BytesIO(blob)).convert("RGBA"), target)
        add_asset("system_pack_png", "SYSTEM.DAT", f"{ISO}!/SYSTEM.DAT/{record['name']}", sha256_bytes(blob), target, width, height, "medium", "branding_or_system_image")

    for source in sorted(BG_ROOT.glob("*.txp")):
        target = OUTPUT / "source_png/bg" / source.with_suffix(".png").name
        image = decode_txp(source)
        width, height, _ = save_png(image, target)
        add_asset("txp", "BG.DAT", str(source), sha256_file(source), target, width, height, "low", "background_review")

    for name, relevance, priority in (("number.txp", "ui_numeric_texture", "high"), ("font.txp", "reference_only", "reference")):
        source = START_ROOT / name
        folder = "reference_png/start" if relevance == "reference_only" else "source_png/start"
        target = OUTPUT / folder / source.with_suffix(".png").name
        image = decode_txp(source)
        width, height, _ = save_png(image, target)
        add_asset("txp", "START.DAT", str(source), sha256_file(source), target, width, height, priority, relevance)

    anime_sources = [START_ROOT / "anime00.dat"] + sorted(ANIME_ROOT.glob("anime*.dat"))
    anime_pages = 0
    for source in anime_sources:
        data = source.read_bytes()
        container = f"START/{source.name}" if source.name == "anime00.dat" else f"ANIME/{source.name}"
        for obj in parse_objects(data):
            for group in find_texture_groups(data, obj):
                for texture in group:
                    target = OUTPUT / "source_png/anime" / source.stem / f"object_{obj.index:03d}" / f"group_{texture.group_index:02d}_page_{texture.page_index:02d}.png"
                    image = decode_texture(data, texture)
                    width, height, _ = save_png(image, target)
                    priority = "high" if source.name == "anime00.dat" else "medium"
                    add_asset("anime_texture", container, str(source), sha256_bytes(data), target, width, height, priority, "ui_or_sprite_review", str(obj.index), str(texture.group_index), str(texture.page_index))
                    anime_pages += 1

    sheet_index: list[dict[str, Any]] = []
    by_asset = {row["asset_id"]: row for row in inventory}
    for group, items in sorted(sheet_groups.items()):
        for chunk_index in range(0, len(items), 40):
            chunk = items[chunk_index:chunk_index + 40]
            target = OUTPUT / "contact_sheets" / f"{group}_{chunk_index // 40 + 1:02d}.png"
            generated = contact_sheet(chunk, target)
            sheet_index.extend(generated)
            for item in generated:
                by_asset[item["asset_id"]]["contact_sheet"] = item["sheet"]
                by_asset[item["asset_id"]]["contact_cell"] = item["cell"]

    queue = [dict(row) for row in inventory if row["translation_relevance"] != "reference_only"]
    write_csv(OUTPUT / "image_inventory.csv", inventory)
    write_csv(OUTPUT / "translation_queue.csv", queue)
    write_csv(OUTPUT / "contact_sheet_index.csv", sheet_index)
    (OUTPUT / "translated/README.md").write_text(
        "수정한 PNG를 source_png와 같은 상대 경로로 이 폴더 아래에 복사하세요. 원본 source_png는 수정하지 마세요.\n",
        encoding="utf-8",
    )
    (OUTPUT / "README.md").write_text(
        "# Prinny 1 V7.15.4 이미지/UI 번역 작업 폴더\n\n"
        "이 폴더는 xdelta 기준 V7.15.4 ISO에서 검증한 내부 이미지의 PNG 미리보기입니다.\n\n"
        "- `contact_sheets/`: 빠르게 일본어/미번역 UI를 찾는 썸네일 모음\n"
        "- `source_png/`: 편집 기준 PNG. 직접 덮어쓰지 말 것\n"
        "- `reference_png/`: 폰트처럼 번역 대상이 아닌 참고 이미지\n"
        "- `translated/`: 편집본을 원본과 같은 상대 경로로 넣는 곳\n"
        "- `translation_queue.csv`: 번역 문구와 상태를 기록하는 작업표\n"
        "- `image_inventory.csv`: 원본 해시·크기·컨테이너·재삽입 식별자\n\n"
        "TXP와 anime 편집본은 캔버스 크기와 알파를 유지하고 원본 팔레트 색만 사용해야 안전하게 재삽입할 수 있습니다. 실제 ISO 적용 전에는 항목별 Expected Write와 독립 검증을 다시 수행합니다.\n",
        encoding="utf-8",
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "prinny1_v7_15_4_ui_image_export_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_iso": {"path": str(ISO), "sha256": sha256_file(ISO)},
        "verified_parent_resources": {name: sha256_bytes(blob) for name, blob in blobs.items()},
        "counts": {
            "inventory_rows": len(inventory), "translation_queue_rows": len(queue),
            "direct_iso_png": sum(row["category"] == "direct_iso_png" for row in inventory),
            "system_pack_png": sum(row["category"] == "system_pack_png" for row in inventory),
            "bg_txp_png": sum(row["container"] == "BG.DAT" for row in inventory),
            "start_txp_png": sum(row["container"] == "START.DAT" for row in inventory),
            "anime_containers": len(anime_sources), "anime_texture_pages": anime_pages,
            "contact_sheets": len({row["sheet"] for row in sheet_index}),
        },
        "artifacts": {
            "workspace": str(OUTPUT), "inventory": str(OUTPUT / "image_inventory.csv"),
            "queue": str(OUTPUT / "translation_queue.csv"),
            "contact_index": str(OUTPUT / "contact_sheet_index.csv"),
        },
        "checks": {
            "xdelta_authoritative_image_resources_used": True, "source_iso_modified": False,
            "all_png_files_reopened_after_save": True, "raw_sources_hash_recorded": True,
            "external_ppsspp_texture_override_created": False, "iso_created": False,
        },
        "status": "image_ui_translation_workspace_exported_independent_review_required",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PNG inventory: {len(inventory)}, translation queue: {len(queue)}")
    print(f"anime pages: {anime_pages}, contact sheets: {report['counts']['contact_sheets']}")
    print(f"output: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
