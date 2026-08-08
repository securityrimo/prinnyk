#!/usr/bin/env python3
"""Independent postbuild review for the V7.15.7 PSP test ISO."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image

from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from scripts.prinny_txp_preview import decode_txp


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_6_ui_images/prinny_korean_v7_15_6_ui_images.iso"
ISO = ROOT / "workspace/build/prinny1_v7_15_7_bg9803/prinny_korean_v7_15_7_bg9803.iso"
BG = ROOT / "workspace/build/prinny1_v7_15_7_bg9803_resources/BG.DAT"
PNG = ROOT / "workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized/bg/bg9803.png"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_7_bg9803_iso_review"
EXPECTED = {
    BASE_ISO: "384302e1aa98883b1e4ddc1e0535f78c5d303a992387fbc2d104b97cf3f538eb",
    ISO: "8ac9f3d0426dc9bdec6596cd604171a23fa25b1836e0b74d61edec024621718e",
    BG: "45f0de733dbf8ee53300090afceef5e8e52387e19c28c79b4631f59b49b0e068",
    PNG: "cf709c9fbf7870452afb92c0ce2391c39338b3772e9910547b4d4b83ed83326e",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.7 사후 검토 입력 해시 불일치: {path}")
    base_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "BG.DAT"])
    final_record = find_iso_file(ISO, ["PSP_GAME", "USRDIR", "BG.DAT"])
    if base_record["extent_lba"] != final_record["extent_lba"] or base_record["data_length"] != final_record["data_length"]:
        raise ValueError("최종 ISO BG.DAT 디렉터리 레코드 변경")
    offset = int(base_record["extent_lba"]) * SECTOR_SIZE
    length = int(base_record["data_length"])
    if hash_range(BASE_ISO, 0, offset) != hash_range(ISO, 0, offset):
        raise ValueError("BG.DAT 앞 허용 범위 밖 변경")
    if hash_range(BASE_ISO, offset + length, BASE_ISO.stat().st_size) != hash_range(ISO, offset + length, ISO.stat().st_size):
        raise ValueError("BG.DAT 뒤 허용 범위 밖 변경")
    final_bg = read_iso_file(ISO, final_record)
    if final_bg != BG.read_bytes():
        raise ValueError("최종 ISO BG.DAT 재추출 불일치")
    record = next(row for row in system_records(final_bg) if row["name"].casefold() == "bg9803.txp")
    txp = final_bg[record["data_offset"]:record["data_offset"] + record["size"]]
    with tempfile.NamedTemporaryFile(suffix=".txp") as handle:
        handle.write(txp)
        handle.flush()
        decoded = decode_txp(Path(handle.name))
    with Image.open(PNG) as opened:
        expected_png = opened.convert("RGBA")
    if decoded.tobytes() != expected_png.tobytes():
        raise ValueError("최종 ISO bg9803 TXP/PNG 불일치")
    test = subprocess.run(["7z", "t", str(ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("최종 ISO 7z 재검사 실패")

    report = {
        "format": "prinny1_v7_15_7_bg9803_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": sha256_file(ISO)},
        "checks": {"only_bg_dat_extent_changed": True, "bg_dat_reextracted_exactly": True, "bg9803_txp_png_roundtrip_exact": True, "v7_15_6_system_anime_direct_png_and_dialogue_preserved_by_outside_range_hash": True, "seven_zip_structure_retest": True},
        "status": "pass_v7_15_7_iso_ready_for_ppsspp_runtime_test",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {sha256_file(ISO)}")
    print("BG9803 reextract/decode: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
