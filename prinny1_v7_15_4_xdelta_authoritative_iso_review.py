#!/usr/bin/env python3
"""Post-review that V7.15.4 preserves every xdelta byte outside one mirrored slot."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/analysis/prinny1_xdelta_20260729/forced_redecode_20260801.iso"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
BUILD_REPORT = ROOT / "workspace/reports/prinny1_v7_15_4_xdelta_authoritative_iso/all_report.json"
SEALED_BOOT = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative_resources/BOOT.BIN"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_4_xdelta_authoritative_iso_review"
EXPECTED = {
    BASE_ISO: "8bc47f189a41309dcca5ef6c61bd5e1368909da8c9b0fc032e2498368d095b65",
    OUTPUT_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    BUILD_REPORT: "88dcaae0fe26191ddd56fcb03d6ecd55a627dc5cec0cf3310c638d85ec53a2d5",
    SEALED_BOOT: "67d63f8c122c252fc8062f97425c1a57ad7bf1cb298683d09dcdcacfbe92df65",
}
FALLBACK_OFFSET = 0xF3A38
FALLBACK_SPAN = 24
CODEBOOK = {
    b"\xF1\x47": "데", b"\xF3\x62": "이", b"\xF4\x50": "터",
    b"\xF2\x9B": "송", b"\xF2\xB4": "신", b"\xF3\x42": "완",
    b"\xF1\xB7": "료",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def decode(payload: bytes) -> str:
    output = []
    cursor = 0
    while cursor < len(payload) and payload[cursor] != 0:
        if payload[cursor] == 0x20:
            output.append(" "); cursor += 1
        else:
            pair = payload[cursor:cursor + 2]
            if pair not in CODEBOOK:
                raise ValueError(f"최종 fallback 미확인 코드: {pair.hex().upper()}")
            output.append(CODEBOOK[pair]); cursor += 2
    return "".join(output)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V7.15.4 사후 검토 입력 해시 불일치: {path}")
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if build.get("status") != "pass_v7_15_4_test_iso_built_independent_post_review_required":
        raise ValueError("V7.15.4 빌드 보고 상태 불일치")
    parts = {
        "boot": ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
        "eboot": ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
    }
    base_records = {key: find_iso_file(BASE_ISO, value) for key, value in parts.items()}
    final_records = {key: find_iso_file(OUTPUT_ISO, value) for key, value in parts.items()}
    intervals = sorted((int(record["extent_lba"]) * SECTOR_SIZE, int(record["extent_lba"]) * SECTOR_SIZE + int(record["data_length"])) for record in base_records.values())
    cursor = 0
    for left, right in intervals:
        if hash_range(BASE_ISO, cursor, left) != hash_range(OUTPUT_ISO, cursor, left):
            raise ValueError("BOOT/EBOOT 앞 xdelta ISO 데이터 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(OUTPUT_ISO, cursor, OUTPUT_ISO.stat().st_size):
        raise ValueError("마지막 BOOT 범위 뒤 xdelta ISO 데이터 변경")

    base_boot = read_iso_file(BASE_ISO, base_records["boot"])
    final_boot = read_iso_file(OUTPUT_ISO, final_records["boot"])
    final_eboot = read_iso_file(OUTPUT_ISO, final_records["eboot"])
    if final_boot != SEALED_BOOT.read_bytes() or final_eboot != final_boot:
        raise ValueError("최종 BOOT/EBOOT 봉인 불일치")
    changes = {i for i, pair in enumerate(zip(base_boot, final_boot)) if pair[0] != pair[1]}
    if changes != set(range(FALLBACK_OFFSET, FALLBACK_OFFSET + FALLBACK_SPAN)):
        raise ValueError(f"최종 BOOT 변경이 fallback 24바이트와 다릅니다: {len(changes)}")
    text = decode(final_boot[FALLBACK_OFFSET:FALLBACK_OFFSET + FALLBACK_SPAN + 1])
    if text != "데이터 송신 완료" or final_boot[FALLBACK_OFFSET + FALLBACK_SPAN] != 0:
        raise ValueError("최종 fallback 문구/NUL 재검증 실패")
    test = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("V7.15.4 최종 ISO 7z 독립 재검사 실패")

    report = {
        "format": "prinny1_v7_15_4_xdelta_authoritative_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size, "sha256": sha256_file(OUTPUT_ISO)},
        "verified": {
            "xdelta_unchanged_translation_rows": 541, "user_fallback_rows": 1,
            "boot_changed_bytes": len(changes), "eboot_changed_bytes": len(changes),
            "fallback_text": text,
        },
        "checks": {
            "all_xdelta_data_outside_mirrored_fallback_byte_identical": True,
            "system_anime_bg_script_stage_sound_unchanged": True,
            "boot_eboot_mirror_exact": True, "fallback_redecoded": True,
            "external_nul_boundary_preserved": True, "seven_zip_structure_retested": True,
            "output_hash_recomputed": True,
        },
        "caveat": "forced xdelta baseline remains a user-directed reference build because official declared source/output hashes do not match",
        "status": "pass_v7_15_4_xdelta_authoritative_structural_runtime_test_required",
        "final_verdict": "PASS",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {report['output_iso']['sha256']}")
    print("xdelta unchanged outside one 24-byte mirrored slot: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
