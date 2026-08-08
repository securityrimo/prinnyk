#!/usr/bin/env python3
"""Independent postbuild review of the V7.15.5 character-voice ISO."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_4_xdelta_authoritative/prinny_korean_v7_15_4_xdelta_authoritative.iso"
OUTPUT_ISO = ROOT / "workspace/build/prinny1_v7_15_5_character_voice/prinny_korean_v7_15_5_character_voice.iso"
SYSTEM = ROOT / "workspace/build/prinny1_v7_15_5_character_voice_resources/SYSTEM.DAT"
START = ROOT / "workspace/build/prinny1_v7_15_5_character_voice_resources/start.dat"
DEMO = ROOT / "workspace/build/prinny1_v7_15_5_character_voice_resources/Demo00.dat"
WRITES = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_plan/expected_write_confirmed.csv"
CODEBOOK = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/candidate_codebook_partial.csv"
BUILD_REPORT = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_iso/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_5_character_voice_iso_review"

EXPECTED = {
    BASE_ISO: "63c5f21334435c766ced56496157eafa27bc827af2444d3e28c39af5d1e2f2b7",
    OUTPUT_ISO: "bf0cd2913bc5149762c22d0336092947b46f64412d1e8706ca06f2581c33400c",
    SYSTEM: "618ad8fd09794f24dd24c829b93aa274b959202c7bd4c10d357a00f33cfb232f",
    START: "1a230abd89106a8847547fe7b91be3f21a2968fe0fc50168b65b368e127d68b2",
    DEMO: "a7e870ad1a1561f5c57e8273689bcd5bebd8d2069eb6038f22866419dab23f26",
    WRITES: "4c304013d28d2e5753ee7b125d8197d76fa4ff33c829898834dc5d6397346995",
    CODEBOOK: "f1ac6829d2c07450f6433b0daa95d413b85aaf1ed8b2ece22bcd5dcf2a5387a3",
    BUILD_REPORT: "90503eb31ca5fcbb221e146933a0b2dd85c40f8d56640323ff3eea67d9902732",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def changed_offsets(before: bytes, after: bytes) -> set[int]:
    if len(before) != len(after):
        raise ValueError("고정 크기 비교 대상 길이가 다릅니다.")
    return {index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}


def decode(payload: bytes, mapping: dict[str, str]) -> str:
    payload = payload.split(b"\0", 1)[0]
    output: list[str] = []
    cursor = 0
    while cursor < len(payload):
        lead = payload[cursor]
        if 0xF0 <= lead <= 0xF5:
            code = payload[cursor:cursor + 2].hex().upper()
            output.append(mapping[code])
            cursor += 2
        elif (0x81 <= lead <= 0x9F or 0xE0 <= lead <= 0xEF):
            output.append(payload[cursor:cursor + 2].decode("cp932"))
            cursor += 2
        elif lead < 0x80:
            output.append(chr(lead))
            cursor += 1
        else:
            raise ValueError(f"사후 적용 슬롯 디코드 실패: 0x{lead:02X}")
    return "".join(output)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"사후 검토 입력 해시 불일치: {path}")
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if build.get("status") != "pass_v7_15_5_test_iso_built_independent_post_review_required":
        raise ValueError("ISO 빌드 상태가 사후 검토 대기가 아닙니다.")
    if BASE_ISO.stat().st_size != OUTPUT_ISO.stat().st_size or OUTPUT_ISO.stat().st_size != 500465664:
        raise ValueError("ISO 크기 불일치")

    base_system_record = find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    final_system_record = find_iso_file(OUTPUT_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    if (base_system_record["extent_lba"], base_system_record["data_length"]) != (
        final_system_record["extent_lba"], final_system_record["data_length"]
    ):
        raise ValueError("ISO SYSTEM.DAT 파일 레코드가 바뀌었습니다.")
    system_left = int(base_system_record["extent_lba"]) * SECTOR_SIZE
    system_right = system_left + int(base_system_record["data_length"])
    if hash_range(BASE_ISO, 0, system_left) != hash_range(OUTPUT_ISO, 0, system_left):
        raise ValueError("SYSTEM.DAT 앞 ISO 범위가 다릅니다.")
    if hash_range(BASE_ISO, system_right, BASE_ISO.stat().st_size) != hash_range(OUTPUT_ISO, system_right, OUTPUT_ISO.stat().st_size):
        raise ValueError("SYSTEM.DAT 뒤 ISO 범위가 다릅니다.")

    base_system = read_iso_file(BASE_ISO, base_system_record)
    final_system = read_iso_file(OUTPUT_ISO, final_system_record)
    if final_system != SYSTEM.read_bytes():
        raise ValueError("ISO 재추출 SYSTEM.DAT이 봉인 자원과 다릅니다.")
    base_entry = font_builder.parse_nispack_start_entry(base_system)
    final_entry = font_builder.parse_nispack_start_entry(final_system)
    base_offset, base_size = int(base_entry["data_offset"]), int(base_entry["size"])
    final_offset, final_size = int(final_entry["data_offset"]), int(final_entry["size"])
    if base_offset != final_offset:
        raise ValueError("SYSTEM.DAT START.LZS 오프셋 변경")
    allowed_system = set(range(final_offset, final_offset + max(base_size, final_size)))
    size_field = int(final_entry["entry_offset"]) + 0x24
    allowed_system.update(range(size_field, size_field + 4))
    if not changed_offsets(base_system, final_system) <= allowed_system:
        raise ValueError("START.LZS/크기 필드 밖 SYSTEM.DAT 변경")

    base_start, _ = decompress_buffer(base_system[base_offset:base_offset + base_size])
    final_start, _ = decompress_buffer(final_system[final_offset:final_offset + final_size])
    if final_start != START.read_bytes():
        raise ValueError("ISO 내부 START.DAT이 봉인 자원과 다릅니다.")
    base_archive = StartRuntimeArchive.from_bytes(base_start)
    final_archive = StartRuntimeArchive.from_bytes(final_start)
    base_records = {record.output_name.casefold(): record for record in base_archive.records}
    final_records = {record.output_name.casefold(): record for record in final_archive.records}
    if base_records.keys() != final_records.keys():
        raise ValueError("START 자원 목록이 달라졌습니다.")
    changed_resources = []
    for name in base_records:
        before_record, after_record = base_records[name], final_records[name]
        before = base_start[before_record.data_offset:before_record.end_offset]
        after = final_start[after_record.data_offset:after_record.end_offset]
        if before != after:
            changed_resources.append(name)
    if changed_resources != ["demo00.dat"]:
        raise ValueError(f"Demo00.dat 외 START 자원 변경: {changed_resources}")
    demo_record = final_records["demo00.dat"]
    final_demo = final_start[demo_record.data_offset:demo_record.end_offset]
    base_demo_record = base_records["demo00.dat"]
    base_demo = base_start[base_demo_record.data_offset:base_demo_record.end_offset]
    if final_demo != DEMO.read_bytes():
        raise ValueError("ISO 내부 Demo00.dat이 봉인 자원과 다릅니다.")

    mapping = {
        row["candidate_code"]: row["unicode_character"]
        for row in read_csv(CODEBOOK)
        if row["unicode_character"]
    }
    writes = read_csv(WRITES)
    simulated = bytearray(base_demo)
    declared: set[int] = set()
    for row in writes:
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if simulated[offset:offset + len(before)] != before:
            raise ValueError(f"사후 Expected Write before 불일치: {row['logical_id']}")
        if decode(after, mapping) != row["text"]:
            raise ValueError(f"사후 문구 디코드 불일치: {row['logical_id']}")
        if final_demo[offset + len(after)] != 0:
            raise ValueError(f"사후 외부 NUL 불일치: {row['logical_id']}")
        simulated[offset:offset + len(after)] = after
        declared.update(offset + index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
    if bytes(simulated) != final_demo or declared != changed_offsets(base_demo, final_demo):
        raise ValueError("ISO 내부 Demo Expected Write 범위 불일치")

    for path_parts in (["PSP_GAME", "SYSDIR", "BOOT.BIN"], ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]):
        if read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, path_parts)) != read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, path_parts)):
            raise ValueError(f"V7.15.4 실행 파일 보존 실패: {path_parts[-1]}")
    seven_zip = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if seven_zip.returncode != 0 or "Everything is Ok" not in seven_zip.stdout:
        raise ValueError("사후 7z ISO 구조 검사 실패")

    report = {
        "format": "prinny1_v7_15_5_character_voice_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "iso_size": OUTPUT_ISO.stat().st_size,
            "expected_writes": len(writes),
            "demo_changed_bytes": len(declared),
            "changed_start_resources": changed_resources,
            "base_lzs_size": base_size,
            "final_lzs_size": final_size,
        },
        "checks": {
            "output_hash_locked": True,
            "iso_size_preserved": True,
            "outside_system_extent_byte_identical": True,
            "system_diff_only_start_lzs_and_size": True,
            "start_lzs_roundtrip": True,
            "only_demo_start_resource_changed": True,
            "demo_diff_matches_expected_writes": True,
            "all_replacements_decode_exactly": True,
            "all_external_nul_boundaries_preserved": True,
            "boot_eboot_preserved": True,
            "seven_zip_structure_test": True,
        },
        "runtime": {
            "ppsspp_launched_by_this_build": False,
            "in_game_character_voice_confirmation": "pending_user_runtime_check",
        },
        "caveat": "The V7.15.4 parent is still a forced-xdelta test baseline with patch-declared hash mismatch.",
        "status": "pass_v7_15_5_structural_post_review_runtime_pending",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO SHA-256: {sha256_file(OUTPUT_ISO)}")
    print(f"Expected Writes: {len(writes)}, Demo changed bytes: {len(declared)}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
