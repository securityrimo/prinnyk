#!/usr/bin/env python3
"""Independent integrity review of the V7.15.4 image translation workspace."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
WORKSPACE = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative"
EXPORT_REPORT = ROOT / "workspace/reports/prinny1_v7_15_4_ui_image_export/all_report.json"
INVENTORY = WORKSPACE / "image_inventory.csv"
QUEUE = WORKSPACE / "translation_queue.csv"
CONTACT_INDEX = WORKSPACE / "contact_sheet_index.csv"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_4_ui_image_export_review"
EXPECTED = {
    ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    EXPORT_REPORT: "aafa4abb919ba184fa97b2902ad1b31c35a2ca8d6fdfd8af4bf6672c8ab005c6",
    INVENTORY: "798d7bab443e2df17e1ea5e62b2cbe9c892dc3629cdd3fc8518d775c2b9c91e8",
    QUEUE: "87ee2d6fd495b004ade3f492731cdf901b3386edea6d141fc3ed986d010c27f8",
    CONTACT_INDEX: "af36fd2fc336c906963342d1f446104c9789d8d53f56f4f660b2e6abbd74d5e2",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"이미지 추출 독립 검토 입력 해시 불일치: {path}")
    report = json.loads(EXPORT_REPORT.read_text(encoding="utf-8"))
    inventory, queue, contact = rows(INVENTORY), rows(QUEUE), rows(CONTACT_INDEX)
    if len(inventory) != 747 or len(queue) != 746 or len(contact) != 747:
        raise ValueError("이미지 inventory/queue/contact 행 수 불일치")
    ids = {row["asset_id"] for row in inventory}
    if len(ids) != len(inventory) or {row["asset_id"] for row in contact} != ids:
        raise ValueError("이미지 ID 중복 또는 연락판 누락")
    queue_ids = {row["asset_id"] for row in queue}
    expected_queue_ids = {row["asset_id"] for row in inventory if row["translation_relevance"] != "reference_only"}
    if queue_ids != expected_queue_ids or len(queue_ids) != len(queue):
        raise ValueError("번역 큐가 inventory의 비참고 항목과 다릅니다.")

    raw_files_checked = 0
    png_files_checked = 0
    for row in inventory:
        png = WORKSPACE / row["png_source"]
        if not png.is_file() or sha256_file(png) != row["png_sha256"]:
            raise ValueError(f"추출 PNG 해시 불일치: {row['asset_id']}")
        with Image.open(png) as image:
            image.verify()
        with Image.open(png) as image:
            if image.size != (int(row["width"]), int(row["height"])):
                raise ValueError(f"추출 PNG 크기 불일치: {row['asset_id']}")
        png_files_checked += 1
        raw = Path(row["raw_source"])
        if raw.is_file():
            if sha256_file(raw) != row["raw_source_sha256"]:
                raise ValueError(f"원본 하위 자원 해시 불일치: {row['asset_id']}")
            raw_files_checked += 1

    sheets = {row["sheet"] for row in contact}
    if len(sheets) != 42:
        raise ValueError("연락판 수 불일치")
    for name in sheets:
        sheet = WORKSPACE / name
        if not sheet.is_file():
            raise ValueError(f"연락판 파일 누락: {name}")
        with Image.open(sheet) as image:
            image.verify()
    contact_pairs = {(row["sheet"], row["cell"]) for row in contact}
    if len(contact_pairs) != len(contact):
        raise ValueError("연락판 cell 인덱스 중복")
    translated_files = [path for path in (WORKSPACE / "translated").rglob("*") if path.is_file() and path.name != "README.md"]
    if translated_files:
        raise ValueError("사용자 편집 전 translated 폴더에 예상 밖 파일이 있습니다.")
    if sha256_file(ISO) != EXPECTED[ISO]:
        raise ValueError("이미지 추출 후 ISO 해시가 변경됐습니다.")

    result = {
        "format": "prinny1_v7_15_4_ui_image_export_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "inventory_rows": len(inventory), "translation_queue_rows": len(queue),
            "png_files_reopened_and_hashed": png_files_checked,
            "filesystem_raw_sources_rehashed": raw_files_checked,
            "contact_index_rows": len(contact), "contact_sheets_reopened": len(sheets),
            "anime_texture_pages": int(report["counts"]["anime_texture_pages"]),
            "bg_txp_png": int(report["counts"]["bg_txp_png"]),
        },
        "checks": {
            "inventory_ids_unique": True, "translation_queue_exact_nonreference_subset": True,
            "all_source_png_hashes_and_dimensions_match": True,
            "all_filesystem_raw_source_hashes_match": True,
            "all_assets_mapped_to_contact_sheet_cell": True,
            "translated_folder_has_no_edits_yet": True,
            "source_iso_unchanged": True, "iso_or_external_texture_override_created": False,
        },
        "status": "pass_image_ui_translation_workspace_ready_for_user_review",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PNG: {png_files_checked}, queue: {len(queue)}, contact sheets: {len(sheets)}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
