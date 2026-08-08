#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
XDELTA = Path("/home/hyuk/다운로드/Prinny_ULJS00150_KR_20260729.xdelta")
ORIGINAL_ISO = ROOT / "game.iso"
CURRENT_ISO = (
    ROOT
    / "workspace/build/prinny1_v7_14_14_title_difficulty_repair"
    / "prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
)
CANDIDATE_ISO = ROOT / "workspace/analysis/prinny1_xdelta_20260729/decoded_from_game_iso.iso"
OUTPUT = ROOT / "workspace/analysis/prinny1_xdelta_20260729"
EXTRACTED = OUTPUT / "extracted"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_xdelta_import_audit"

EXPECTED_SOURCE_SHA256 = "7eee0174e1fe5361fbb37afa6a2bfda5514f580483fcb8ee07684cb9cf0399a2"
EXPECTED_OUTPUT_SHA256 = "1b8eebaf30c269d08d9c6e47f8e7f095a106732f7e1f8e29dffa8cef922e9d80"
XDELTA_SHA256 = "a6578aea12a23d570a8604ce8552a80cf6d52e3b6a04bb4261077203090790f8"

ISO_TARGETS = {
    "boot": ["PSP_GAME", "SYSDIR", "BOOT.BIN"],
    "eboot": ["PSP_GAME", "SYSDIR", "EBOOT.BIN"],
    "system": ["PSP_GAME", "USRDIR", "SYSTEM.DAT"],
    "anime": ["PSP_GAME", "USRDIR", "ANIME.DAT"],
    "bg": ["PSP_GAME", "USRDIR", "BG.DAT"],
    "script": ["PSP_GAME", "USRDIR", "SCRIPT.DAT"],
    "stage": ["PSP_GAME", "USRDIR", "STAGE.DAT"],
    "sound": ["PSP_GAME", "USRDIR", "SOUND.DAT"],
}

TEXT_COUPLED = {
    "font.fnt",
    "font.txp",
    "Demo00.dat",
    "StageInfo00.dat",
    "MusicShop.dat",
    "PictureBook.dat",
    "Honor.dat",
    "Collection.dat",
    "LuckyDoll.dat",
    "LuckyItem.dat",
    "ClearTime00.dat",
}
IMAGE_DEFERRED = {"anime00.dat", "number.txp"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def changed_byte_count(left: bytes, right: bytes) -> int | None:
    if len(left) != len(right):
        return None
    return sum(a != b for a, b in zip(left, right))


def iso_blobs(path: Path) -> dict[str, bytes]:
    return {
        name: read_iso_file(path, find_iso_file(path, parts))
        for name, parts in ISO_TARGETS.items()
    }


def start_from_system(system: bytes, source: str) -> tuple[bytes, StartRuntimeArchive, dict[str, Any]]:
    entry = font_builder.parse_nispack_start_entry(system)
    begin = int(entry["data_offset"])
    end = begin + int(entry["size"])
    start, lzs_header = decompress_buffer(system[begin:end])
    return start, StartRuntimeArchive.from_bytes(start, source=source), {
        "entry_offset": int(entry["entry_offset"]),
        "data_offset": begin,
        "compressed_size": int(entry["size"]),
        "decompressed_size": len(start),
        "lzs_header": lzs_header,
    }


def record_map(archive: StartRuntimeArchive) -> dict[str, Any]:
    return {record.output_name.casefold(): record for record in archive.records}


def record_blob(archive: StartRuntimeArchive, record: Any) -> bytes:
    return archive.data[int(record.data_offset):int(record.end_offset)]


def table_index_to_sjis(index: int) -> str:
    if index < 0x5F:
        return f"{index + 0x20:02X}"
    lead_slot, trail_slot = divmod(index - 0x5F, 0xC0)
    lead = lead_slot + 0x81 if lead_slot <= 0x1E else lead_slot + 0xC1
    return f"{lead:02X} {trail_slot + 0x40:02X}"


def parse_fnt(blob: bytes) -> list[int]:
    if len(blob) < 2:
        raise ValueError("font.fnt가 너무 작습니다.")
    count = struct.unpack_from("<H", blob, 0)[0]
    if len(blob) != 2 + count * 2:
        raise ValueError("font.fnt 테이블 크기가 헤더와 다릅니다.")
    return list(struct.unpack_from(f"<{count}H", blob, 2))


def main() -> int:
    for path in (XDELTA, ORIGINAL_ISO, CURRENT_ISO, CANDIDATE_ISO):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(XDELTA) != XDELTA_SHA256:
        raise ValueError("xdelta 입력 해시가 최초 분석값과 다릅니다.")

    iso_test = subprocess.run(
        ["7z", "t", str(CANDIDATE_ISO)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if iso_test.returncode != 0 or "Everything is Ok" not in iso_test.stdout:
        raise ValueError("강제 디코드 후보 ISO 구조 검사에 실패했습니다.")

    source_hash = sha256_file(ORIGINAL_ISO)
    current_hash = sha256_file(CURRENT_ISO)
    candidate_hash = sha256_file(CANDIDATE_ISO)
    source_match = source_hash == EXPECTED_SOURCE_SHA256
    output_match = candidate_hash == EXPECTED_OUTPUT_SHA256

    iso_data = {
        "original": iso_blobs(ORIGINAL_ISO),
        "current": iso_blobs(CURRENT_ISO),
        "candidate": iso_blobs(CANDIDATE_ISO),
    }
    starts: dict[str, bytes] = {}
    archives: dict[str, StartRuntimeArchive] = {}
    start_meta: dict[str, Any] = {}
    for label in ("original", "current", "candidate"):
        starts[label], archives[label], start_meta[label] = start_from_system(
            iso_data[label]["system"], f"{label}!/start.dat"
        )

    EXTRACTED.mkdir(parents=True, exist_ok=True)
    candidate_dir = EXTRACTED / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    for name, blob in iso_data["candidate"].items():
        (candidate_dir / ISO_TARGETS[name][-1]).write_bytes(blob)
    (candidate_dir / "start.dat").write_bytes(starts["candidate"])

    records = {label: record_map(archive) for label, archive in archives.items()}
    all_names = sorted(set(records["original"]) | set(records["current"]) | set(records["candidate"]))
    record_rows: list[dict[str, Any]] = []
    changed_candidate_names: list[str] = []
    changed_current_names: list[str] = []
    resource_dir = candidate_dir / "start_resources"
    resource_dir.mkdir(parents=True, exist_ok=True)
    for folded_name in all_names:
        row: dict[str, Any] = {"name_key": folded_name}
        blobs: dict[str, bytes] = {}
        display_name = folded_name
        for label in ("original", "current", "candidate"):
            record = records[label].get(folded_name)
            if record is None:
                row[label] = None
                continue
            display_name = record.output_name
            blob = record_blob(archives[label], record)
            blobs[label] = blob
            row[label] = {"size": len(blob), "sha256": sha256_bytes(blob)}
        row["name"] = display_name
        row["candidate_changed_from_original"] = (
            "candidate" in blobs and "original" in blobs and blobs["candidate"] != blobs["original"]
        )
        row["current_changed_from_original"] = (
            "current" in blobs and "original" in blobs and blobs["current"] != blobs["original"]
        )
        row["candidate_equals_current"] = (
            "candidate" in blobs and "current" in blobs and blobs["candidate"] == blobs["current"]
        )
        if row["candidate_changed_from_original"]:
            changed_candidate_names.append(display_name)
            (resource_dir / display_name).write_bytes(blobs["candidate"])
        if row["current_changed_from_original"]:
            changed_current_names.append(display_name)
        if display_name in TEXT_COUPLED:
            row["classification"] = "text_font_coupled_do_not_mix"
        elif display_name in IMAGE_DEFERRED:
            row["classification"] = "internal_image_candidate_deferred"
        else:
            row["classification"] = "unchanged_or_other"
        record_rows.append(row)

    iso_rows = []
    for name in ISO_TARGETS:
        original = iso_data["original"][name]
        current = iso_data["current"][name]
        candidate = iso_data["candidate"][name]
        classification = "unchanged_or_other"
        if name in {"boot", "eboot", "system"}:
            classification = "text_executable_or_container_do_not_blind_merge"
        elif name in {"anime", "bg"}:
            classification = "internal_image_container_deferred"
        iso_rows.append(
            {
                "name": name,
                "iso_path": "/".join(ISO_TARGETS[name]),
                "classification": classification,
                "original": {"size": len(original), "sha256": sha256_bytes(original)},
                "current": {"size": len(current), "sha256": sha256_bytes(current)},
                "candidate": {"size": len(candidate), "sha256": sha256_bytes(candidate)},
                "candidate_changed_from_original": candidate != original,
                "current_changed_from_original": current != original,
                "candidate_equals_current": candidate == current,
                "candidate_changed_bytes_same_size": changed_byte_count(original, candidate),
            }
        )

    missing_current_only = sorted(set(changed_current_names) - set(changed_candidate_names))
    original_font_fnt = record_blob(archives["original"], records["original"]["font.fnt"])
    candidate_font_fnt = record_blob(archives["candidate"], records["candidate"]["font.fnt"])
    original_font_txp = record_blob(archives["original"], records["original"]["font.txp"])
    current_font_txp = record_blob(archives["current"], records["current"]["font.txp"])
    candidate_font_txp = record_blob(archives["candidate"], records["candidate"]["font.txp"])
    original_fnt_table = parse_fnt(original_font_fnt)
    candidate_fnt_table = parse_fnt(candidate_font_fnt)
    changed_fnt_indices = [
        index
        for index, (before, after) in enumerate(zip(original_fnt_table, candidate_fnt_table))
        if before != after
    ]
    if not changed_fnt_indices:
        raise ValueError("후보 font.fnt에 변경된 매핑이 없습니다.")
    contiguous_fnt_range = changed_fnt_indices == list(
        range(changed_fnt_indices[0], changed_fnt_indices[-1] + 1)
    )
    font_coupling = {
        "fnt_table_entries": len(candidate_fnt_table),
        "changed_fnt_entry_count": len(changed_fnt_indices),
        "changed_fnt_range_contiguous": contiguous_fnt_range,
        "changed_fnt_first_table_index_hex": f"0x{changed_fnt_indices[0]:04X}",
        "changed_fnt_last_table_index_hex": f"0x{changed_fnt_indices[-1]:04X}",
        "changed_fnt_first_sjis": table_index_to_sjis(changed_fnt_indices[0]),
        "changed_fnt_last_sjis": table_index_to_sjis(changed_fnt_indices[-1]),
        "candidate_txp_changed_bytes_from_original": changed_byte_count(original_font_txp, candidate_font_txp),
        "candidate_txp_changed_bytes_from_current": changed_byte_count(current_font_txp, candidate_font_txp),
        "candidate_uses_separate_f0_f5_code_range": (
            table_index_to_sjis(changed_fnt_indices[0]) == "F0 40"
            and table_index_to_sjis(changed_fnt_indices[-1]) == "F5 6E"
        ),
    }
    report = {
        "format": "prinny1_v7_14_15_xdelta_import_audit_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "xdelta": {"path": str(XDELTA), "size": XDELTA.stat().st_size, "sha256": sha256_file(XDELTA)},
            "declared_source_sha256": EXPECTED_SOURCE_SHA256,
            "declared_output_sha256": EXPECTED_OUTPUT_SHA256,
            "available_source": {"path": str(ORIGINAL_ISO), "size": ORIGINAL_ISO.stat().st_size, "sha256": source_hash},
            "current_patch_base": {"path": str(CURRENT_ISO), "size": CURRENT_ISO.stat().st_size, "sha256": current_hash},
            "forced_decode_candidate": {"path": str(CANDIDATE_ISO), "size": CANDIDATE_ISO.stat().st_size, "sha256": candidate_hash},
        },
        "checks": {
            "xdelta_hash_matches_recorded_input": True,
            "available_source_matches_declared_source": source_match,
            "candidate_matches_declared_output": output_match,
            "candidate_iso_7z_test_pass": True,
            "candidate_system_lzs_roundtrip_parse": True,
            "candidate_start_record_count": len(archives["candidate"].records),
            "blind_xdelta_promotion_allowed": source_match and output_match,
            "translation_wording_generated_or_changed_by_codex": False,
            "final_iso_created": False,
        },
        "start_metadata": start_meta,
        "font_coupling": font_coupling,
        "iso_file_comparison": iso_rows,
        "start_resource_comparison": record_rows,
        "summary": {
            "candidate_changed_start_resources": changed_candidate_names,
            "current_changed_start_resources": changed_current_names,
            "current_only_changed_resources_at_risk": missing_current_only,
            "text_font_coupled_resources": sorted(TEXT_COUPLED & set(changed_candidate_names)),
            "deferred_internal_image_resources": sorted(IMAGE_DEFERRED & set(changed_candidate_names)),
            "deferred_internal_image_containers": ["ANIME.DAT", "BG.DAT"],
        },
        "decision": {
            "status": "blocked_exact_source_missing_and_font_map_incompatible",
            "safe_result": "candidate_resources_extracted_for_reference_only",
            "reason": [
                "보유 game.iso가 xdelta 헤더의 요구 원본 SHA-256과 다릅니다.",
                "강제 디코드 ISO가 구조 검사는 통과하지만 선언된 결과 SHA-256과 다릅니다.",
                "후보 폰트와 텍스트는 현재 980자 코드맵과 결합할 수 없는 별도 인코딩 묶음입니다.",
                "후보를 통째로 적용하면 현재 패치에서만 수정된 자원이 회귀할 위험이 있습니다.",
            ],
            "allowed_next_steps": [
                "정확한 원본 ISO를 제공받아 xdelta 결과 해시를 일치시킨다.",
                "후보 전용 코드맵을 복구한 뒤 사용자 번역과 기계적으로 대조한다.",
                "내부 이미지 자원은 텍스트 완료 후 별도 Expected Write로 검토한다.",
            ],
        },
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(report_path, OUTPUT / "all_report.json")

    print(f"xdelta source hash match: {source_match}")
    print(f"xdelta output hash match: {output_match}")
    print(f"candidate ISO structure: PASS")
    print(f"candidate changed START resources: {len(changed_candidate_names)}")
    print(f"current-only changed resources at risk: {missing_current_only}")
    print(f"extracted: {candidate_dir}")
    print(f"report: {report_path}")
    print("final ISO created: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
