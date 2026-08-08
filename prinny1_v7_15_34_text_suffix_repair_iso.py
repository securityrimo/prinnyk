#!/usr/bin/env python3
"""Repair stale translated-text suffixes and rebuild six StageInfo pages."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_text_test_iso import hash_range
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_28_title_plaque_korean_iso import changed_start_resources, overlap_count
from prinny1_v7_15_29_title_plaque_white_index_iso import extract_start, extract_system
from prinny1_v7_15_3_xdelta_translation_select import load_codebook
from prinny1_v7_15_4_ui_image_export import system_records


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_33_intro_transform_gap/prinny_korean_v7_15_33_intro_transform_gap.iso"
ORIGINAL_ISO = ROOT / "game.iso"
MASTER = ROOT / "workspace/translations/export/translation_master_merged.json"
MASTER_CSV = ROOT / "workspace/translations/export/translation_master.csv"
CODEBOOK = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/candidate_codebook_partial.csv"
ALLOCATION = ROOT / "workspace/font/audited_allocation_988/hangul_allocation.json"
APPLY_WRITES = ROOT / "workspace/reports/prinny1_final_updated_master/expected_writes.csv"
OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_34_text_suffix_repair"
OUTPUT_ISO = OUTPUT_DIR / "prinny_korean_v7_15_34_text_suffix_repair.iso"
RESOURCE_DIR = ROOT / "workspace/build/prinny1_v7_15_34_text_suffix_repair_resources"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_34_text_suffix_repair"

EXPECTED_BASE_SHA256 = "2014a7dc13aafef53ab07ba66add1bfbb61c26c70b156a5a0d5876b79fb2eb25"
EXPECTED_ORIGINAL_SHA256 = "af0d2873a96c5fe6f95b3fc2fb3e8702f98bba67e32f2f78c5c3d1bdaa8b9d03"
EXPECTED_MASTER_SHA256 = "8276f3d63fd8a451804c7ee1abc5629d019a5e08d60eac65b71ff29a62fcb18f"
EXPECTED_MASTER_CSV_SHA256 = "ee9bf727a2ca1d96591a770f7a79e7850a2d1ab3d46937251c240f6512d81e2c"
EXPECTED_CODEBOOK_SHA256 = "720267af6a81eceb6ae81fbb28fb65f13af00ecc39d56ce62343bbb94994cd5b"
EXPECTED_ALLOCATION_SHA256 = "315ea9d4d1b0e6b911eda8014d9331958df035f872170350152f12e096817f38"
EXPECTED_APPLY_WRITES_SHA256 = "5b75442d3c4a5c78a230361b6417ec5da6719b1a449a1977df6e7bf86a53ae3f"
EXPECTED_SUFFIX_CANDIDATES = 321
EXPECTED_USER_STALE_OCCURRENCES = 256
STAGE_RANGE = (0x178, 0x9AE)
STAGE_TITLE_OFFSETS = {0x178, 0x2E8, 0x458, 0x5C8, 0x738, 0x8A8}
MENU_WRITES = {
    0xED358: ("시체대삼림", 10),
    0xED364: ("사신의처형탑", 12),
    0xED384: ("용암닌자요새", 12),
}
EVIDENCE = (
    (Path("/home/hyuk/사진/마풍초원.png"), "f3844ec4b9fea96d268256ea114efc1c8c723bd61fe47721553572a137c8e9ae"),
    (Path("/home/hyuk/사진/마해의아리아요새.png"), "48148a2863d3e92032ca58d745bde46fb72128bddd0a1cae2c1ea11246d0e2bf"),
    (Path("/home/hyuk/사진/모브 대요새.png"), "73f73d19090bca9177d678e6fb1835083cab6921b737bfdc048928744166e425"),
    (Path("/home/hyuk/사진/사신의처형탑.png"), "958b5483e7a400fdc552d70730c2a1ba2f937cbbd65f3354aff47efcba5b12f2"),
    (Path("/home/hyuk/사진/시체의 대삼림.png"), "cb72af26465b92e9d9ce63b07eacfdbc660a64eaf05550234e650de4f81077f7"),
    (Path("/home/hyuk/사진/용암성의닌자요새.png"), "1b8dee2ea4f6a9236f918fb343dd01f44f8d89d664699d644ba664406a89fe44"),
)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(name: str, payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def records(start: bytes) -> dict[str, object]:
    return {
        row.output_name.casefold(): row
        for row in StartRuntimeArchive.from_bytes(start).records
    }


def resources(iso: Path) -> tuple[bytes, bytes, dict[str, object]]:
    system, _ = extract_system(iso)
    start, _lzs, _row, _rows = extract_start(system)
    return system, start, records(start)


def resource_blob(start: bytes, table: dict[str, object], name: str) -> bytes:
    row = table[name.casefold()]
    return start[row.data_offset:row.end_offset]


def code_tables() -> tuple[dict[str, bytes], dict[str, str]]:
    by_code, _trusted = load_codebook()
    # Match the already approved master writer: the last audited CSV row wins
    # when the candidate font contains two code points for the same glyph.
    with CODEBOOK.open("r", encoding="utf-8-sig", newline="") as handle:
        by_char = {
            row["unicode_character"]: bytes.fromhex(row["candidate_code"])
            for row in csv.DictReader(handle) if row["unicode_character"]
        }
    for code, char in by_code.items():
        by_char.setdefault(char, bytes.fromhex(code))
    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))["mapping"]
    for char, row in allocation.items():
        code = (row["sjis"] if isinstance(row, dict) else row).replace(" ", "").upper()
        by_char.setdefault(char, bytes.fromhex(code))
        by_code.setdefault(code, char)
    return by_char, by_code


def encode_text(text: str, by_char: dict[str, bytes]) -> bytes:
    chunks: list[bytes] = []
    for char in text:
        if "가" <= char <= "힣":
            if char not in by_char:
                raise KeyError(char)
            chunks.append(by_char[char])
        else:
            chunks.append(char.encode("cp932"))
    return b"".join(chunks)


def decode_text(blob: bytes, by_code: dict[str, str]) -> str:
    out: list[str] = []
    at = 0
    while at < len(blob) and blob[at] != 0:
        lead = blob[at]
        if 0xF0 <= lead <= 0xF5 or 0x81 <= lead <= 0x9F or 0xE0 <= lead <= 0xEF:
            code = blob[at:at + 2].hex().upper()
            if code in by_code:
                out.append(by_code[code])
                at += 2
                continue
            if 0xF0 <= lead <= 0xF5:
                raise ValueError(f"미복구 코드 {code}")
            width = 2
            out.append(blob[at:at + width].decode("cp932"))
            at += width
        else:
            width = 1
            out.append(blob[at:at + width].decode("cp932"))
            at += width
    return "".join(out)


def master_occurrences() -> tuple[list[dict], dict[tuple[str, int, int], dict]]:
    document = json.loads(MASTER.read_text(encoding="utf-8"))
    unique: dict[tuple[str, int, int], dict] = {}
    for entry in document["entries"]:
        for occurrence in entry["occurrences"]:
            key = (
                occurrence["resource"].casefold(),
                int(occurrence["offset"]),
                int(occurrence["byte_length"]),
            )
            value = {"id": entry["id"], "translation": entry["translation"], **occurrence}
            if key in unique and unique[key]["id"] != entry["id"]:
                raise ValueError(f"번역 occurrence 충돌: {key}")
            unique[key] = value
    return document["entries"], unique


def stale_suffixes(
    base_start: bytes,
    base_records: dict[str, object],
    original_start: bytes,
    original_records: dict[str, object],
    occurrences: dict[tuple[str, int, int], dict],
) -> list[dict]:
    with APPLY_WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        applied_sources = {
            (row["resource"].casefold(), int(row["offset_hex"], 16), int(row["capacity"])): row["source"]
            for row in csv.DictReader(handle)
        }
    found: list[dict] = []
    payload_ranges = [(key, off, off + cap) for key, off, cap in occurrences]
    for (key, off, cap), occurrence in occurrences.items():
        if key not in base_records or key not in original_records:
            continue
        base_row, original_row = base_records[key], original_records[key]
        base_at = base_row.data_offset + off
        original_at = original_row.data_offset + off
        if original_start[original_at + cap] != 0 or base_start[base_at + cap] == 0:
            continue
        terminator = base_start.find(b"\0", base_at + cap, min(base_row.end_offset, base_at + cap + 256))
        if terminator < 0:
            raise ValueError(f"잔여 문자열 종단 없음: {key}@0x{off:X}")
        length = terminator - (base_at + cap)
        original_padding = original_start[original_at + cap:original_at + cap + length]
        if any(original_padding):
            continue
        clear_left, clear_right = off + cap, off + cap + length
        for other_key, other_left, other_right in payload_ranges:
            if other_key == key and (other_left, other_right) != (off, off + cap):
                if max(clear_left, other_left) < min(clear_right, other_right):
                    raise ValueError(f"잔여 제거가 다른 번역과 겹침: {key}@0x{off:X}")
        found.append(
            {
                "id": occurrence["id"], "resource": occurrence["resource"],
                "offset": clear_left, "length": length, "field_offset": off,
                "declared_capacity": cap,
                "before": base_start[base_at + cap:base_at + cap + length],
                "apply_source": applied_sources[(key, off, cap)],
            }
        )
    if len(found) != EXPECTED_SUFFIX_CANDIDATES:
        raise ValueError(f"잔여 occurrence 수 불일치: {len(found)}")
    if sum(item["apply_source"] == "user" for item in found) != EXPECTED_USER_STALE_OCCURRENCES:
        raise ValueError("user 적용 잔여 occurrence 수 불일치")
    return found


def rebuild_start() -> tuple[dict[str, bytes], list[dict], dict]:
    base_system, base_start, base_records = resources(BASE_ISO)
    _original_system, original_start, original_records = resources(ORIGINAL_ISO)
    _entries, occurrences = master_occurrences()
    by_char, by_code = code_tables()
    stale = stale_suffixes(base_start, base_records, original_start, original_records, occurrences)
    rebuilt = bytearray(base_start)
    writes: list[dict] = []

    # The six pages below are fixed 31-byte title / 33-byte description slots.
    stage_rows = [
        ((key, off, cap), value) for (key, off, cap), value in occurrences.items()
        if key == "stageinfo00.dat" and STAGE_RANGE[0] <= off <= STAGE_RANGE[1]
    ]
    if len(stage_rows) != 59:
        raise ValueError(f"6개 스테이지 occurrence 수 불일치: {len(stage_rows)}")
    stage_record = base_records["stageinfo00.dat"]
    original_stage_record = original_records["stageinfo00.dat"]
    rebuilt_stage = 0
    stage_ranges: list[tuple[int, int]] = []
    for (key, off, _cap), occurrence in sorted(stage_rows, key=lambda item: item[0][1]):
        size = 31 if off in STAGE_TITLE_OFFSETS else 33
        stage_ranges.append((off, off + size))
        base_at = stage_record.data_offset + off
        original_at = original_stage_record.data_offset + off
        original_field = original_start[original_at:original_at + size]
        original_nul = original_field.find(b"\0")
        if original_nul < 0 or any(original_field[original_nul + 1:]):
            raise ValueError(f"StageInfo 원본 고정 필드 검증 실패: 0x{off:X}")
        text = occurrence["translation"]
        before = bytes(rebuilt[base_at:base_at + size])
        encoded = encode_text(text, by_char)
        if len(encoded) > size - 1:
            raise ValueError(f"StageInfo 고정 필드 초과: 0x{off:X} {text}")
        after = encoded + bytes(size - len(encoded))
        if decode_text(after, by_code) != text:
            raise ValueError(f"StageInfo 왕복 불일치: 0x{off:X}")
        rebuilt[base_at:base_at + size] = after
        rebuilt_stage += 1
        writes.append({
            "id": f"P1-V7.15.34-STAGE-{rebuilt_stage:04d}", "target": "START.DAT/stageinfo00.dat",
            "operation": "rebuild_fixed_text_field", "offset_hex": f"0x{off:X}", "length": size,
            "translation_id": occurrence["id"], "text": text,
            "before_hex": before.hex().upper(), "after_hex": after.hex().upper(),
        })
    if rebuilt_stage != 59:
        raise ValueError(f"StageInfo 처리 수 불일치: rebuild={rebuilt_stage}")

    generic = 0
    excluded_stage = 0
    fallback_skipped = 0
    for item in stale:
        key, left, right = item["resource"].casefold(), item["offset"], item["offset"] + item["length"]
        if item["apply_source"] != "user":
            fallback_skipped += 1
            continue
        if key == "stageinfo00.dat" and any(max(left, a) < min(right, b) for a, b in stage_ranges):
            excluded_stage += 1
            continue
        row = base_records[key]
        absolute = row.data_offset + left
        before = bytes(rebuilt[absolute:absolute + item["length"]])
        if before != item["before"] or not any(before):
            raise ValueError(f"잔여 제거 기준 불일치: {key}@0x{left:X}")
        rebuilt[absolute:absolute + item["length"]] = bytes(item["length"])
        generic += 1
        writes.append({
            "id": f"P1-V7.15.34-SUFFIX-{generic:04d}", "target": f"START.DAT/{item['resource']}",
            "operation": "clear_proven_original_zero_padding", "offset_hex": f"0x{left:X}",
            "length": item["length"], "translation_id": item["id"], "text": "",
            "before_hex": before.hex().upper(), "after_hex": bytes(item["length"]).hex().upper(),
        })
    if (generic, excluded_stage, fallback_skipped) != (246, 10, 65):
        raise ValueError(
            f"잔여 처리 수 불일치: generic={generic}, stage={excluded_stage}, fallback={fallback_skipped}"
        )

    final_start = bytes(rebuilt)
    changed = changed_start_resources(base_start, final_start)
    expected_changed = [
        "collection.dat", "demo00.dat", "honor.dat", "luckydoll.dat", "luckyitem.dat",
        "musicshop.dat", "picturebook.dat", "stageinfo00.dat",
    ]
    if set(changed) != set(expected_changed) or len(changed) != len(expected_changed):
        raise ValueError(f"START 변경 자원 불일치: {changed}")

    base_lzs = extract_start(base_system)[1]
    rows = system_records(base_system)
    start_row = next(row for row in rows if row["name"].casefold() == "start.lzs")
    header = decompress_buffer(base_lzs)[1]
    new_lzs = compress_buffer_runtime_safe(final_start, base_lzs[:4], int(header["flag"]))
    capacity = rows[start_row["index"] + 1]["data_offset"] - start_row["data_offset"]
    if len(new_lzs) > capacity or decompress_buffer(new_lzs)[0] != final_start or overlap_count(new_lzs):
        raise ValueError("START.LZS 안전 압축/왕복 실패")
    final_system = bytearray(base_system)
    start_at = start_row["data_offset"]
    final_system[start_at:start_at + capacity] = bytes(capacity)
    final_system[start_at:start_at + len(new_lzs)] = new_lzs
    struct.pack_into("<I", final_system, 0x10 + start_row["index"] * 0x2C + 0x24, len(new_lzs))
    final_system_bytes = bytes(final_system)
    check_start, check_lzs, _row, _rows = extract_start(final_system_bytes)
    if check_start != final_start or check_lzs != new_lzs:
        raise ValueError("SYSTEM.DAT 재추출 불일치")
    return {
        "SYSTEM.DAT": final_system_bytes, "start.dat": final_start, "start.lzs": new_lzs,
        "stageinfo00.dat": resource_blob(final_start, records(final_start), "stageinfo00.dat"),
    }, writes, {
        "suffix_candidates": len(stale), "user_written_stale_occurrences": EXPECTED_USER_STALE_OCCURRENCES,
        "fallback_continuations_preserved": fallback_skipped, "generic_suffix_clears": generic,
        "stage_suffixes_subsumed_by_field_rebuild": excluded_stage,
        "stage_fields_rebuilt": rebuilt_stage, "stage_native_allocation_supplement_used": True,
        "changed_start_resources": changed, "lzs_old_size": len(base_lzs),
        "lzs_new_size": len(new_lzs), "lzs_capacity": capacity, "lzs_overlap_backreferences": 0,
    }


def patch_executables(by_char: dict[str, bytes], by_code: dict[str, str]) -> tuple[dict[str, bytes], list[dict]]:
    artifacts: dict[str, bytes] = {}
    writes: list[dict] = []
    for filename in ("BOOT.BIN", "EBOOT.BIN"):
        path = ["PSP_GAME", "SYSDIR", filename]
        blob = bytearray(read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, path)))
        for offset, (text, size) in MENU_WRITES.items():
            encoded = encode_text(text, by_char)
            if len(encoded) != size or decode_text(encoded, by_code) != text:
                raise ValueError(f"메뉴 문자열 인코딩 불일치: {text}")
            before = bytes(blob[offset:offset + size])
            blob[offset:offset + size] = encoded
            writes.append({
                "id": f"P1-V7.15.34-{filename}-{offset:X}", "target": filename,
                "operation": "replace_compact_stage_menu_label", "offset_hex": f"0x{offset:X}",
                "length": size, "translation_id": "approved_stage_name_compact_form", "text": text,
                "before_hex": before.hex().upper(), "after_hex": encoded.hex().upper(),
            })
        artifacts[filename] = bytes(blob)
    if artifacts["BOOT.BIN"] != artifacts["EBOOT.BIN"]:
        raise ValueError("BOOT/EBOOT 미러 결과 불일치")
    return artifacts, writes


def calculate_artifacts() -> tuple[dict[str, bytes], list[dict], dict]:
    by_char, by_code = code_tables()
    start_artifacts, writes, metadata = rebuild_start()
    executable_artifacts, executable_writes = patch_executables(by_char, by_code)
    return {**start_artifacts, **executable_artifacts}, writes + executable_writes, metadata


def seal() -> dict:
    sealed_inputs = {
        BASE_ISO: EXPECTED_BASE_SHA256, ORIGINAL_ISO: EXPECTED_ORIGINAL_SHA256,
        MASTER: EXPECTED_MASTER_SHA256, MASTER_CSV: EXPECTED_MASTER_CSV_SHA256,
        CODEBOOK: EXPECTED_CODEBOOK_SHA256, ALLOCATION: EXPECTED_ALLOCATION_SHA256,
        APPLY_WRITES: EXPECTED_APPLY_WRITES_SHA256,
        **dict(EVIDENCE),
    }
    for path, expected in sealed_inputs.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"입력 봉인값 불일치: {path}")
    artifacts, writes, metadata = calculate_artifacts()
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for name, blob in artifacts.items():
        (RESOURCE_DIR / name).write_bytes(blob)
    with (REPORT_DIR / "expected_writes.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(writes[0]))
        writer.writeheader()
        writer.writerows(writes)
    report = {
        "format": "prinny1_v7_15_34_text_suffix_repair_preflight_v1", "created_at": now(),
        "base_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
        "diagnosis": "user translations wrote only original Japanese byte_length and left bytes from longer prior Korean strings",
        "repair": metadata | {"executable_menu_writes": 6, "expected_write_rows": len(writes)},
        "sealed": {name: sha256_bytes(blob) for name, blob in artifacts.items()},
        "checks": {
            "all_suffix_clear_bytes_proven_zero_in_original_iso_and_source_was_user_write": True,
            "xdelta_overflow_and_missing_glyph_continuations_preserved": True,
            "no_suffix_clear_overlaps_another_translation_payload": True,
            "all_59_six_stage_fields_use_master_translations": True,
            "missing_candidate_codes_use_audited_native_font_allocation": True,
            "boot_eboot_mirror_equal": True, "external_textures_used": False,
        },
        "status": "sealed_independent_prebuild_review_required",
    }
    write_json("preflight_report.json", report)
    return report


def independent_prebuild_review() -> dict:
    artifacts, writes, metadata = calculate_artifacts()
    for name, blob in artifacts.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"독립 사전 봉인 불일치: {name}")
    report = {
        "format": "prinny1_v7_15_34_text_suffix_repair_prebuild_review_v1", "created_at": now(),
        "verified": metadata | {"expected_write_rows": len(writes)},
        "checks": {"fresh_original_padding_audit": True, "fresh_master_field_rebuild": True,
                   "sealed_resources_exact": True, "runtime_safe_lzs": True},
        "status": "pass_iso_build_ready_automatic_approval", "final_verdict": "PASS",
    }
    write_json("independent_prebuild_review.json", report)
    return report


def iso_targets() -> dict[str, dict]:
    return {
        "BOOT.BIN": find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]),
        "EBOOT.BIN": find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]),
        "SYSTEM.DAT": find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]),
    }


def verify_iso_outside_targets(candidate: Path, targets: dict[str, dict]) -> None:
    spans = sorted(
        (int(row["extent_lba"]) * SECTOR_SIZE,
         int(row["extent_lba"]) * SECTOR_SIZE + int(row["data_length"]))
        for row in targets.values()
    )
    cursor = 0
    for left, right in spans:
        if hash_range(BASE_ISO, cursor, left) != hash_range(candidate, cursor, left):
            raise ValueError("허용 ISO 범위 앞 데이터 변경")
        cursor = right
    if hash_range(BASE_ISO, cursor, BASE_ISO.stat().st_size) != hash_range(candidate, cursor, candidate.stat().st_size):
        raise ValueError("허용 ISO 범위 뒤 데이터 변경")


def build_iso() -> dict:
    review = json.loads((REPORT_DIR / "independent_prebuild_review.json").read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or OUTPUT_ISO.exists():
        raise ValueError("사전 검토 미통과 또는 출력 ISO 이미 존재")
    targets = iso_targets()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ISO.with_suffix(".iso.tmp")
    if temporary.exists():
        temporary.unlink()
    with BASE_ISO.open("rb") as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    with temporary.open("r+b") as handle:
        for name in ("BOOT.BIN", "EBOOT.BIN", "SYSTEM.DAT"):
            blob = (RESOURCE_DIR / name).read_bytes()
            row = targets[name]
            if len(blob) != int(row["data_length"]):
                raise ValueError(f"ISO 대상 크기 변경: {name}")
            handle.seek(int(row["extent_lba"]) * SECTOR_SIZE)
            handle.write(blob)
        handle.flush()
        os.fsync(handle.fileno())
    if temporary.stat().st_size != BASE_ISO.stat().st_size:
        raise ValueError("ISO 전체 크기 변경")
    verify_iso_outside_targets(temporary, targets)
    test = subprocess.run(["7z", "t", str(temporary)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("ISO 7z 검사 실패")
    os.replace(temporary, OUTPUT_ISO)
    report = {
        "format": "prinny1_v7_15_34_text_suffix_repair_iso_v1", "created_at": now(),
        "authorization": "test_iso_automatic_approval_2026_08_01",
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size,
                       "sha256": sha256_file(OUTPUT_ISO)},
        "checks": {"only_boot_eboot_system_extents_changed": True, "seven_zip_structure_test": True,
                   "parent_not_overwritten": True},
        "status": "built_independent_postbuild_review_required",
    }
    write_json("iso_build_report.json", report)
    return report


def independent_postbuild_review() -> dict:
    targets = iso_targets()
    verify_iso_outside_targets(OUTPUT_ISO, targets)
    for name, path in {
        "BOOT.BIN": ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
        "EBOOT.BIN": ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
        "SYSTEM.DAT": ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    }.items():
        extracted = read_iso_file(OUTPUT_ISO, find_iso_file(OUTPUT_ISO, path))
        if extracted != (RESOURCE_DIR / name).read_bytes():
            raise ValueError(f"사후 ISO 재추출 봉인 불일치: {name}")
    final_system, _ = extract_system(OUTPUT_ISO)
    final_start, final_lzs, _row, _rows = extract_start(final_system)
    if final_start != (RESOURCE_DIR / "start.dat").read_bytes() or overlap_count(final_lzs):
        raise ValueError("사후 START/LZS 검증 실패")
    artifacts, writes, metadata = calculate_artifacts()
    for name, blob in artifacts.items():
        if (RESOURCE_DIR / name).read_bytes() != blob:
            raise ValueError(f"사후 독립 재계산 불일치: {name}")
    test = subprocess.run(["7z", "t", str(OUTPUT_ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 ISO 7z 재검사 실패")
    report = {
        "format": "prinny1_v7_15_34_text_suffix_repair_postbuild_review_v1", "created_at": now(),
        "output_iso": {"path": str(OUTPUT_ISO), "size": OUTPUT_ISO.stat().st_size,
                       "sha256": sha256_file(OUTPUT_ISO)},
        "verified": metadata | {"expected_write_rows": len(writes), "ppsspp_launched": False},
        "checks": {"only_boot_eboot_system_extents_changed": True, "sealed_resources_reextracted_exactly": True,
                   "fresh_original_padding_audit": True, "fresh_master_field_rebuild": True,
                   "runtime_safe_lzs": True, "seven_zip_structure_retest": True},
        "status": "pass_ready_for_ppsspp_runtime_test", "final_verdict": "PASS",
    }
    write_json("independent_postbuild_review.json", report)
    return report


def main() -> int:
    seal()
    independent_prebuild_review()
    build = build_iso()
    review = independent_postbuild_review()
    print(f"ISO: {OUTPUT_ISO}")
    print(f"sha256: {build['output_iso']['sha256']}")
    print("user stale suffixes: 256 / stage fields rebuilt: 59 / BOOT+EBOOT labels: 6")
    print("preflight/prebuild/7z/reextract/postbuild: PASS")
    print(f"FINAL_VERDICT: {review['final_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
