#!/usr/bin/env python3
"""Build the V7.15.9 runtime-safe Korean image PSP test ISO."""
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
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_8_runtime_safe_lzs/prinny_korean_v7_15_8_runtime_safe_lzs.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_9_safe_images_resources"
REVIEW = ROOT / "workspace/reports/prinny1_v7_15_9_safe_images_review/all_report.json"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_9_safe_images"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_9_safe_images.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_9_safe_images_iso"

EXPECTED = {
    BASE_ISO: "4ee4198acd01cbb4bda08e7b0d76b1cea3dea7de95e36b295ff6eede90876f6e",
    RESOURCE_DIR / "SYSTEM.DAT": "71a2df867e45579aa91de0c3a5344f93a28669c0a40982278aacb9e3d96e97bf",
    RESOURCE_DIR / "ANIME.DAT": "8a26453874bafb6f800ab3fe2c3cd9eb6ccd4aa43679016b59fea10d2f385d77",
    RESOURCE_DIR / "BG.DAT": "45f0de733dbf8ee53300090afceef5e8e52387e19c28c79b4631f59b49b0e068",
    RESOURCE_DIR / "direct_iso/ICON0.PNG": "960555d1ef29d26eeea56bbf45b6c52723d31e062ecbbea7f7c0db576f1b2e80",
    RESOURCE_DIR / "direct_iso/PIC0.PNG": "5be9973e574f552443d0a7c77d00425719c193d85359ea1930f296ec685d3aa8",
    REVIEW: "a35f81cee21bb9f8390f014a3062d89ec8bacb9ca9407d24760c8c11f3323e84",
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
            raise ValueError(f"V7.15.9 ISO 입력 해시 불일치: {path}")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review.get("status") != "pass_v7_15_9_test_iso_build_ready_automatic_approval":
        raise ValueError("V7.15.9 독립 사전 검토 미통과")

    targets = (
        (["PSP_GAME", "USRDIR", "SYSTEM.DAT"], RESOURCE_DIR / "SYSTEM.DAT", False),
        (["PSP_GAME", "USRDIR", "ANIME.DAT"], RESOURCE_DIR / "ANIME.DAT", False),
        (["PSP_GAME", "USRDIR", "BG.DAT"], RESOURCE_DIR / "BG.DAT", False),
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
        raise ValueError("V7.15.9 출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.")
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
        raise ValueError("V7.15.9 ISO 크기 변경")
    cursor = 0
    for left, right in merge_intervals(intervals):
        if hash_range(BASE_ISO, cursor, left) != hash_range(temporary, cursor, left):
            raise ValueError("허용 범위 밖 ISO 데이터 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(temporary, cursor, temporary.stat().st_size):
        raise ValueError("최종 허용 범위 뒤 ISO 데이터 변경")
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.9 ISO 7z 구조 검사 실패")
    os.replace(temporary, OUTPUT_ISO)

    for _record, payload, blob, iso_path in writes:
        extracted = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, iso_path))
        if extracted != payload or extracted[:len(blob)] != blob or any(extracted[len(blob):]):
            raise ValueError(f"최종 ISO 재추출/패딩 불일치: {'/'.join(iso_path)}")

    report = {
        "format": "prinny1_v7_15_9_safe_images_iso_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorization": "test_iso_automatic_approval_and_user_runtime_request_2026_08_01",
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "changed_iso_files": ["PSP_GAME/USRDIR/SYSTEM.DAT", "PSP_GAME/USRDIR/ANIME.DAT", "PSP_GAME/USRDIR/BG.DAT", "PSP_GAME/ICON0.PNG", "PSP_GAME/PIC0.PNG"],
        "checks": {
            "independent_prebuild_review_pass": True,
            "only_five_authorized_iso_extents_changed": True,
            "seven_zip_structure_test": True,
            "all_targets_reextracted_exactly": True,
            "runtime_safe_parent_not_overwritten": True,
        },
        "status": "pass_v7_15_9_test_iso_built_independent_post_review_required",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {report['output_iso']['sha256']}")
    print("7z/reextract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
