#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import core.font_builder as font_builder
from core.font_runtime import FontRuntime
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_21_scoped_decoder_plan import BASE_ISO
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
ISO = ROOT / "workspace/build/prinny1_v7_14_22_coherent_f0/prinny_korean_v7_14_22_coherent_f0.iso"
ISO_REPORT = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_iso/all_report.json"
PLAN = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_plan/all_report.json"
CODEBOOK = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_plan/coherent_f0_codebook.csv"
QA = ROOT / "workspace/reports/prinny_qa/qa_rows.csv"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_iso_review"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def encode(text: str, mapping: dict[str, bytes]) -> bytes:
    out = bytearray()
    for character in text:
        out.extend(mapping[character] if character in mapping else character.encode("cp932", errors="strict"))
    return bytes(out)


def extract_start(system: bytes) -> bytes:
    entry = font_builder.parse_nispack_start_entry(system)
    start, _ = decompress_buffer(system[int(entry["data_offset"]):int(entry["data_offset"]) + int(entry["size"])])
    return start


def main() -> int:
    for path in (ISO, ISO_REPORT, PLAN, CODEBOOK, QA, BASE_ISO):
        if not path.is_file():
            raise FileNotFoundError(path)
    iso_report = json.loads(ISO_REPORT.read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if ISO.stat().st_size != int(iso_report["output_iso"]["size"]) or sha256_file(ISO) != iso_report["output_iso"]["sha256"]:
        raise ValueError("ISO 크기/해시가 빌드 보고서와 다릅니다.")
    test = subprocess.run(["7z", "t", str(ISO)], capture_output=True, text=True, check=False)
    if test.returncode != 0 or "Everything is Ok" not in test.stdout:
        raise ValueError("사후 7z 검사 실패")

    boot = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    eboot = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "SYSDIR", "EBOOT.BIN"]))
    system = read_iso_file(ISO, find_iso_file(ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    start = extract_start(system)
    if boot != eboot or sha256_bytes(boot) != plan["preflight"]["patched_boot_sha256"] or sha256_bytes(start) != plan["preflight"]["patched_start_sha256"]:
        raise ValueError("사후 BOOT/EBOOT/START 해시 검증 실패")
    if sha256_bytes(system) != iso_report["resources"]["system_sha256"]:
        raise ValueError("사후 SYSTEM 해시 검증 실패")

    archive = StartRuntimeArchive.from_bytes(start, source=f"{ISO}!/start.dat")
    records = {record.output_name.casefold(): record for record in archive.records}
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    base_start = extract_start(base_system)
    base_archive = StartRuntimeArchive.from_bytes(base_start, source=f"{BASE_ISO}!/start.dat")
    base_records = {record.output_name.casefold(): record for record in base_archive.records}
    font_txp, base_font_txp = records["font.txp"], base_records["font.txp"]
    if start[int(font_txp.data_offset):int(font_txp.end_offset)] != base_start[int(base_font_txp.data_offset):int(base_font_txp.end_offset)]:
        raise ValueError("사후 font.txp 무변경 검증 실패")

    codebook = read_csv(CODEBOOK)
    assigned = [row for row in codebook if row["hangul"]]
    mapping = {row["hangul"]: bytes.fromhex(row["f0_code"]) for row in assigned}
    if len(codebook) != 987 or len(mapping) != 980:
        raise ValueError("사후 코드맵 수 검증 실패")
    fnt = records["font.fnt"]
    table = FontRuntime._parse_fnt(start[int(fnt.data_offset):int(fnt.end_offset)])
    for row in assigned:
        index = FontRuntime.table_index_from_sjis(bytes.fromhex(row["f0_code"]))
        if table[index] != int(row["existing_glyph_index_hex"], 0):
            raise ValueError(f"사후 글리프 별칭 실패: {row['hangul']}")
    qa_rows = read_csv(QA)
    for qa in qa_rows:
        record = records[qa["resource"].casefold()]
        absolute, capacity = int(record.data_offset) + int(qa["offset"], 0), int(qa["capacity_bytes"])
        payload = encode(qa["translation"], mapping)
        if start[absolute:absolute + capacity] != payload + bytes(capacity - len(payload)):
            raise ValueError(f"사후 QA 슬롯 실패: {qa['id']}")

    excluded = ((0x957B4, 4), (0x95814, 4), (0x9599C, 8), (0x959B0, 12))
    if any(boot[o:o + n] != base_boot[o:o + n] for o, n in excluded):
        raise ValueError("사후 게임플레이 회귀 범위 제외 검증 실패")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {
        "format": "prinny1_v7_14_22_coherent_f0_iso_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "output_iso": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": sha256_file(ISO)},
        "verified": {"qa_slot_count": len(qa_rows), "f0_alias_count": len(mapping), "reserved_f0_count": len(codebook) - len(mapping)},
        "checks": {
            "seven_zip_structure_test": True, "boot_eboot_mirror": True, "sealed_resource_hashes_match": True,
            "all_qa_slots_match_user_translation": True, "all_f0_aliases_resolve_existing_glyphs": True,
            "font_txp_byte_identical_to_v14": True, "gameplay_regression_ranges_excluded": True,
            "candidate_wording_imported": False, "translation_wording_changed": False,
        },
        "status": "pass_runtime_validation_required",
        "final_verdict": "PASS",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ISO sha256: {report['output_iso']['sha256']}")
    print(f"QA slots: {len(qa_rows)}/{len(qa_rows)}")
    print(f"F0 aliases: {len(mapping)}/980")
    print("font.txp changed: no")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
