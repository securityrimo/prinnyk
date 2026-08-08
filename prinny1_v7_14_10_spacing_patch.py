#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_minimum_test_iso import (
    SECTOR_SIZE,
    find_iso_file,
    read_iso_file,
)


ROOT = Path(__file__).resolve().parent
ORIGINAL_BOOT = ROOT / "workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
V62_ISO = Path(
    "/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd/"
    "PSP_Localization_Work/build/prinny_stage1_hotfix_v6_2/"
    "prinny_korean_stage1_hotfix_v6_2_977.iso"
)
BASE_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_14_9_prologue_full_punctuation"
    / "prinny_korean_v7_14_9_prologue_full_punctuation_28.iso"
)
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_14_10_compact_spacing"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_14_10_compact_spacing_29.iso"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_10_spacing_patch"

# 0x088997BC~0x088997D8: 일반 2바이트 문자의 진행폭을 정하는 분기.
# 문맥은 원본 BOOT 전체에서 한 번만 나타나며, 변경은 즉시값 1바이트뿐이다.
CONTEXT_BEFORE = bytes.fromhex(
    "040040500D00062406000624020000103800A6AF"
)
CONTEXT_AFTER = bytes.fromhex(
    "040040500B00062406000624020000103800A6AF"
)
PATCH_IN_CONTEXT = 4
EXPECTED_BOOT_OFFSET = 0x95814
EXPECTED_VIRTUAL_ADDRESS = 0x088997C0


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def boot_from_iso(path: Path) -> tuple[dict[str, object], bytes]:
    entry = find_iso_file(path, ["PSP_GAME", "SYSDIR", "BOOT.BIN"])
    return entry, read_iso_file(path, entry)


def verify_boot(label: str, data: bytes) -> dict[str, object]:
    hits: list[int] = []
    cursor = 0
    while True:
        found = data.find(CONTEXT_BEFORE, cursor)
        if found < 0:
            break
        hits.append(found)
        cursor = found + 1
    if hits != [EXPECTED_BOOT_OFFSET - PATCH_IN_CONTEXT]:
        raise ValueError(
            f"{label} BOOT 문맥이 유일하지 않거나 위치가 다릅니다: {hits}"
        )
    actual = data[EXPECTED_BOOT_OFFSET:EXPECTED_BOOT_OFFSET + 4]
    if actual != bytes.fromhex("0D000624"):
        raise ValueError(f"{label} Expected Before 불일치: {actual.hex().upper()}")
    return {
        "source": label,
        "boot_size": len(data),
        "context_match_count": len(hits),
        "boot_offset_hex": f"0x{EXPECTED_BOOT_OFFSET:X}",
        "virtual_address_hex": f"0x{EXPECTED_VIRTUAL_ADDRESS:08X}",
        "expected_before_hex": actual.hex().upper(),
        "write_after_hex": "0B000624",
        "status": "pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-iso-build", action="store_true")
    args = parser.parse_args()

    for required in (ORIGINAL_BOOT, V62_ISO, BASE_ISO):
        if not required.is_file():
            raise FileNotFoundError(required)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    original = ORIGINAL_BOOT.read_bytes()
    _v62_entry, v62 = boot_from_iso(V62_ISO)
    base_entry, base = boot_from_iso(BASE_ISO)
    source_rows = [
        verify_boot("original_game_iso_extracted", original),
        verify_boot("v6.2_user_tested_iso", v62),
        verify_boot("v7.14.9_runtime_pass_iso", base),
    ]
    write_csv(REPORT_DIR / "source_byte_verification.csv", source_rows)

    expected_write = {
        "id": "P1-BOOT-KOREAN-ADVANCE-001",
        "target": "PSP_GAME/SYSDIR/BOOT.BIN",
        "boot_offset_hex": f"0x{EXPECTED_BOOT_OFFSET:X}",
        "virtual_address_hex": f"0x{EXPECTED_VIRTUAL_ADDRESS:08X}",
        "expected_before_hex": "0D000624",
        "write_after_hex": "0B000624",
        "changed_byte_count": 1,
        "semantic_change": "two_byte_character_advance_13_to_11_pixels",
        "context_before_hex": CONTEXT_BEFORE.hex().upper(),
        "context_after_hex": CONTEXT_AFTER.hex().upper(),
        "context_match_count": 1,
        "reason": "한글 자간 축소 및 5글자 이름 프리니대원 클리핑 해소",
        "status": "expected_write_confirmed",
    }
    write_csv(REPORT_DIR / "expected_write_confirmed.csv", [expected_write])

    if not args.allow_iso_build:
        write_json(
            REPORT_DIR / "all_report.json",
            {
                "format": "prinny1_v7_14_10_spacing_preflight_v1",
                "created_at": now(),
                "sources": source_rows,
                "expected_write": expected_write,
                "status": "iso_build_approval_required",
            },
        )
        print("Expected Write 확인 완료; ISO 생성은 --allow-iso-build 필요")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)

    boot_iso_offset = int(base_entry["extent_lba"]) * SECTOR_SIZE
    patch_iso_offset = boot_iso_offset + EXPECTED_BOOT_OFFSET
    before_size = BASE_ISO.stat().st_size
    with temporary.open("r+b") as handle:
        handle.seek(patch_iso_offset)
        actual = handle.read(4)
        if actual != bytes.fromhex("0D000624"):
            raise ValueError(f"ISO Expected Before 불일치: {actual.hex().upper()}")
        handle.seek(patch_iso_offset)
        handle.write(bytes.fromhex("0B000624"))
        handle.flush()
        os.fsync(handle.fileno())
    if temporary.stat().st_size != before_size:
        raise ValueError("ISO 크기가 변경됐습니다.")

    with BASE_ISO.open("rb") as before, temporary.open("rb") as after:
        changed: list[int] = []
        position = 0
        while True:
            left = before.read(1024 * 1024)
            right = after.read(1024 * 1024)
            if not left and not right:
                break
            if len(left) != len(right):
                raise ValueError("ISO 비교 중 길이가 달라졌습니다.")
            changed.extend(
                position + index
                for index, pair in enumerate(zip(left, right))
                if pair[0] != pair[1]
            )
            position += len(left)
    if changed != [patch_iso_offset]:
        raise ValueError(f"허용 범위 밖 ISO 변경: {changed[:20]}")

    test = subprocess.run(
        ["7z", "t", str(temporary)],
        capture_output=True,
        text=True,
        check=False,
    )
    if test.returncode:
        raise RuntimeError(test.stdout[-2000:] + test.stderr[-2000:])
    os.replace(temporary, OUTPUT_ISO)

    output_entry, output_boot = boot_from_iso(OUTPUT_ISO)
    if int(output_entry["extent_lba"]) != int(base_entry["extent_lba"]):
        raise ValueError("BOOT.BIN extent가 변경됐습니다.")
    if output_boot[:EXPECTED_BOOT_OFFSET] != base[:EXPECTED_BOOT_OFFSET]:
        raise ValueError("BOOT 패치 이전 영역이 변경됐습니다.")
    if output_boot[EXPECTED_BOOT_OFFSET + 4:] != base[EXPECTED_BOOT_OFFSET + 4:]:
        raise ValueError("BOOT 패치 이후 영역이 변경됐습니다.")
    if output_boot[EXPECTED_BOOT_OFFSET:EXPECTED_BOOT_OFFSET + 4] != bytes.fromhex("0B000624"):
        raise ValueError("완성 ISO BOOT 재추출 검증 실패")

    report = {
        "format": "prinny1_v7_14_10_spacing_iso_report_v1",
        "created_at": now(),
        "base_iso": str(BASE_ISO),
        "base_iso_sha256": sha256_file(BASE_ISO),
        "output_iso": str(OUTPUT_ISO),
        "output_iso_sha256": sha256_file(OUTPUT_ISO),
        "iso_size": before_size,
        "iso_changed_byte_count": len(changed),
        "iso_changed_offset_hex": f"0x{patch_iso_offset:X}",
        "boot_extent_lba": int(base_entry["extent_lba"]),
        "boot_expected_write": expected_write,
        "original_and_v62_bytes_verified": True,
        "previous_28_start_writes_preserved_by_exact_base_copy": True,
        "seven_zip_test": "pass",
        "fresh_boot_reextract_verification": "pass",
        "ppsspp_test_status": "not_run",
        "status": "build_pass_runtime_test_required",
    }
    write_json(REPORT_DIR / "all_report.json", report)
    write_csv(REPORT_DIR / "build_result.csv", [report])
    print(f"완료: {OUTPUT_ISO}")
    print(f"SHA256: {report['output_iso_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
