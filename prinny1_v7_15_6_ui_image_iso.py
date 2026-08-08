#!/usr/bin/env python3
"""Build the V7.15.6 UI/image PSP test ISO."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_15_text_test_iso import hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_5_character_voice/prinny_korean_v7_15_5_character_voice.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_6_ui_images_resources"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_6_ui_image_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_6_ui_images"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_6_ui_images.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_6_ui_image_iso"
EXPECTED = {
    BASE_ISO: "bf0cd2913bc5149762c22d0336092947b46f64412d1e8706ca06f2581c33400c",
    RESOURCE_DIR / "SYSTEM.DAT": "4b985bad0b0139fccab7d397d21477bd35bbd970318cb8de701a8f7a6b1f6c59",
    RESOURCE_DIR / "ANIME.DAT": "8a26453874bafb6f800ab3fe2c3cd9eb6ccd4aa43679016b59fea10d2f385d77",
    RESOURCE_DIR / "direct_iso/ICON0.PNG": "960555d1ef29d26eeea56bbf45b6c52723d31e062ecbbea7f7c0db576f1b2e80",
    RESOURCE_DIR / "direct_iso/PIC0.PNG": "5be9973e574f552443d0a7c77d00425719c193d85359ea1930f296ec685d3aa8",
    REVIEW: "047a750f39bab950636b25c2788d3ea8406b5be25b366a884601b8675f9c49eb",
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
            raise ValueError(f"V7.15.6 ISO 입력 해시 불일치: {path}")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_v7_15_6_ui_image_iso_build_ready_automatic_approval":
        raise ValueError("V7.15.6 독립 사전 검토 미통과")

    targets = (
        (["PSP_GAME", "USRDIR", "SYSTEM.DAT"], RESOURCE_DIR / "SYSTEM.DAT", False),
        (["PSP_GAME", "USRDIR", "ANIME.DAT"], RESOURCE_DIR / "ANIME.DAT", False),
        (["PSP_GAME", "ICON0.PNG"], RESOURCE_DIR / "direct_iso/ICON0.PNG", True),
        (["PSP_GAME", "PIC0.PNG"], RESOURCE_DIR / "direct_iso/PIC0.PNG", True),
    )
    writes = []
    for iso_path, source, pad in targets:
        record = find_iso_file(BASE_ISO, iso_path)
        blob = source.read_bytes()
        capacity = int(record["data_length"])
        if (not pad and len(blob) != capacity) or (pad and len(blob) > capacity):
            raise ValueError(f"ISO 고정 영역 크기 불일치: {'/'.join(iso_path)}")
        payload = blob + bytes(capacity - len(blob))
        writes.append((record, payload, blob, iso_path))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ISO.exists():
        raise ValueError("V7.15.6 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    intervals = []
    with temporary.open("r+b") as target:
        for record, payload, _blob, _iso_path in writes:
            offset = int(record["extent_lba"]) * SECTOR_SIZE
            target.seek(offset)
            target.write(payload)
            intervals.append((offset, offset + len(payload)))
        target.flush()
        os.fsync(target.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("V7.15.6 ISO 크기 변경")
    cursor = 0
    for left, right in merge_intervals(intervals):
        if hash_range(BASE_ISO, cursor, left) != hash_range(temporary, cursor, left):
            raise ValueError("허용 범위 앞 ISO 데이터 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(temporary, cursor, temporary.stat().st_size):
        raise ValueError("허용 범위 뒤 ISO 데이터 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.6 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    for _record, payload, blob, iso_path in writes:
        extracted = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, iso_path))
        if extracted != payload:
            raise ValueError(f"최종 ISO 재추출 불일치: {'/'.join(iso_path)}")
        if extracted[:len(blob)] != blob or any(extracted[len(blob):]):
            raise ValueError(f"최종 ISO PNG 패딩 불일치: {'/'.join(iso_path)}")

    report = {
        "format": "prinny1_v7_15_6_ui_image_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "user_requested_psp_test_iso_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "changed_iso_files": ["PSP_GAME/USRDIR/SYSTEM.DAT", "PSP_GAME/USRDIR/ANIME.DAT", "PSP_GAME/ICON0.PNG", "PSP_GAME/PIC0.PNG"],
        "checks": {
            "independent_prebuild_review_pass": True,
            "only_four_authorized_iso_extents_changed": True,
            "seven_zip_structure_test": True,
            "all_four_targets_reextracted_exactly": True,
            "v7_15_5_parent_not_overwritten": True,
            "ppsspp_not_auto_launched": True,
        },
        "status": "pass_v7_15_6_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
