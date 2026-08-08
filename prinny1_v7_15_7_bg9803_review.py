#!/usr/bin/env python3
"""Independent prebuild review for the translated bg9803 resource."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from scripts.prinny_txp_preview import decode_txp, txp_layout


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_6_ui_images/prinny_korean_v7_15_6_ui_images.iso"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_7_bg9803_plan/all_report.json"
WRITES = ROOT / "workspace/reports/prinny1_v7_15_7_bg9803_plan/expected_write_confirmed.csv"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_7_bg9803_resources"
PNG = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized/bg/bg9803.png"
CANDIDATE = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/bg_resources/bg9803.txp"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_7_bg9803_review"
EXPECTED_BASE_SHA256 = "384302e1aa98883b1e4ddc1e0535f78c5d303a992387fbc2d104b97cf3f538eb"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    csv.field_size_limit(sys.maxsize)
    if not BASE_ISO.is_file() or sha256_file(BASE_ISO) != EXPECTED_BASE_SHA256:
        raise ValueError("V7.15.6 부모 ISO 해시 불일치")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "bg9803_resource_sealed_independent_review_required":
        raise ValueError("bg9803 계획 상태 불일치")
    sealed_paths = {"BG.DAT": RESOURCE_DIR / "BG.DAT", "bg9803.txp": RESOURCE_DIR / "bg9803.txp", "bg9803.png": PNG}
    for name, path in sealed_paths.items():
        if sha256_file(path) != plan["sealed"][name]:
            raise ValueError(f"봉인 해시 불일치: {name}")

    base_bg = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "BG.DAT"]))
    final_bg = (RESOURCE_DIR / "BG.DAT").read_bytes()
    with WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError("bg9803 Expected Write 수 불일치")
    row = rows[0]
    offset, length = int(row["offset_hex"], 16), int(row["write_span"])
    before, after = bytes.fromhex(row["expected_before_hex"]), bytes.fromhex(row["write_after_hex"])
    if len(before) != length or len(after) != length or base_bg[offset:offset + length] != before:
        raise ValueError("bg9803 Expected Before/길이 불일치")
    rebuilt = bytearray(base_bg)
    rebuilt[offset:offset + length] = after
    if bytes(rebuilt) != final_bg:
        raise ValueError("Expected Write로 BG.DAT 재구성 실패")

    base_records = system_records(base_bg)
    final_records = system_records(final_bg)
    if base_records != final_records:
        raise ValueError("BG.DAT 목차 변경")
    record = next(item for item in base_records if item["name"].casefold() == "bg9803.txp")
    if offset != record["data_offset"] or length != record["size"]:
        raise ValueError("Expected Write가 bg9803 슬롯과 불일치")
    final_txp = (RESOURCE_DIR / "bg9803.txp").read_bytes()
    if after != final_txp or final_bg[offset:offset + length] != final_txp:
        raise ValueError("봉인 bg9803 TXP 불일치")
    candidate = CANDIDATE.read_bytes()
    if txp_layout(candidate) != txp_layout(final_txp) or candidate[:1040] != final_txp[:1040]:
        raise ValueError("bg9803 헤더/팔레트 변경")

    temporary = RESOURCE_DIR / ".bg9803.review.txp"
    temporary.write_bytes(final_txp)
    try:
        decoded = decode_txp(temporary)
    finally:
        temporary.unlink()
    with Image.open(PNG) as opened:
        png = opened.convert("RGBA")
    if decoded.tobytes() != png.tobytes() or decoded.size != (480, 272):
        raise ValueError("bg9803 TXP 재디코드/PNG 불일치")
    candidate_path = RESOURCE_DIR / ".bg9803.candidate.txp"
    candidate_path.write_bytes(candidate)
    try:
        candidate_image = decode_txp(candidate_path)
    finally:
        candidate_path.unlink()
    for y in range(272):
        for x in range(180):
            if decoded.getpixel((x, y)) != candidate_image.getpixel((x, y)):
                raise ValueError(f"패키지 그림 영역 변경: ({x},{y})")

    report = {
        "format": "prinny1_v7_15_7_bg9803_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {"base_iso": sha256_file(BASE_ISO), "plan": sha256_file(PLAN), "expected_writes": sha256_file(WRITES)},
        "verified": {"expected_writes": 1, "canvas": [480, 272], "txp_size": len(final_txp)},
        "checks": {"sealed_hashes_match": True, "expected_write_reconstructs_bg_dat": True, "bg_dat_table_preserved": True, "txp_header_and_palette_preserved": True, "txp_png_roundtrip_exact": True, "package_art_left_180px_preserved": True, "parent_iso_not_modified": True},
        "status": "pass_v7_15_7_bg9803_iso_build_ready",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Expected Writes: 1")
    print("TXP/PNG roundtrip: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
