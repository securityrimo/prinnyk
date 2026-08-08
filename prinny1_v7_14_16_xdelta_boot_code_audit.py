#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "game.iso"
CANDIDATE_BOOT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/BOOT.BIN"
V16_BOOT = ROOT / "workspace/build/prinny1_v7_14_16_text_resources/BOOT.BIN"
V16_WRITES = ROOT / "workspace/reports/prinny1_v7_14_16_text_test_iso/sealed_expected_writes.csv"
RUNTIME = ROOT / "workspace/reports/prinny1_v7_14_16_runtime_test/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_16_xdelta_boot_code_audit"
BOOT_PATH = ["PSP_GAME", "SYSDIR", "BOOT.BIN"]


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def changed_spans(before: bytes, after: bytes) -> list[tuple[int, int]]:
    if len(before) != len(after):
        raise ValueError("BOOT 크기가 다릅니다.")
    indices = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not indices:
        return []
    spans: list[tuple[int, int]] = []
    start = previous = indices[0]
    for index in indices[1:]:
        if index != previous + 1:
            spans.append((start, previous + 1))
            start = index
        previous = index
    spans.append((start, previous + 1))
    return spans


def elf_sections(blob: bytes) -> list[dict[str, int | str]]:
    if blob[:4] != b"\x7fELF" or blob[4:6] != b"\x01\x01":
        raise ValueError("little-endian ELF32 BOOT가 아닙니다.")
    shoff = struct.unpack_from("<I", blob, 0x20)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", blob, 0x2E)
    headers = [struct.unpack_from("<IIIIIIIIII", blob, shoff + i * shentsize) for i in range(shnum)]
    strings_header = headers[shstrndx]
    strings = blob[strings_header[4]:strings_header[4] + strings_header[5]]
    sections = []
    for values in headers:
        name_offset, section_type, flags, address, offset, size = values[:6]
        name_end = strings.find(b"\0", name_offset)
        name = strings[name_offset:name_end].decode("ascii", errors="replace") if name_offset else ""
        sections.append({
            "name": name, "type": section_type, "flags": flags, "address": address,
            "offset": offset, "size": size, "end": offset + size,
        })
    return sections


def section_for(offset: int, sections: list[dict[str, int | str]]) -> str:
    matches = [s for s in sections if int(s["size"]) and int(s["offset"]) <= offset < int(s["end"])]
    return str(matches[-1]["name"]) if matches else "unsectioned_padding"


def virtual_address(offset: int, text: dict[str, int | str]) -> int:
    return int(text["address"]) + offset - int(text["offset"])


def decode_control(word: int, pc: int) -> dict[str, str] | None:
    opcode = word >> 26
    if opcode in (2, 3):
        target = ((pc + 4) & 0xF0000000) | ((word & 0x03FFFFFF) << 2)
        return {"instruction": "jal" if opcode == 3 else "j", "target": f"0x{target:08X}"}
    if opcode in (1, 4, 5, 6, 7):
        immediate = struct.unpack("<h", struct.pack("<H", word & 0xFFFF))[0]
        return {"instruction": "conditional_branch", "target": f"0x{pc + 4 + immediate * 4:08X}"}
    return None


def main() -> int:
    for path in (BASE_ISO, CANDIDATE_BOOT, V16_BOOT, V16_WRITES, RUNTIME):
        if not path.is_file():
            raise FileNotFoundError(path)
    runtime = json.loads(RUNTIME.read_text(encoding="utf-8"))
    if runtime.get("final_verdict") != "BLOCKER":
        raise ValueError("V7.14.16 런타임 BLOCKER가 봉인되지 않았습니다.")
    original = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, BOOT_PATH))
    candidate = CANDIDATE_BOOT.read_bytes()
    current = V16_BOOT.read_bytes()
    if not (len(original) == len(candidate) == len(current)):
        raise ValueError("비교 BOOT 크기가 일치하지 않습니다.")
    sections = elf_sections(original)
    text = next(section for section in sections if section["name"] == ".text")
    text_end = int(text["end"])
    data = next(section for section in sections if section["name"] == ".data")

    write_ranges: list[tuple[int, int, str]] = []
    with V16_WRITES.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["layer"] == "PSP_GAME/SYSDIR/BOOT.BIN":
                start = int(row["offset_hex"], 0)
                write_ranges.append((start, start + len(bytes.fromhex(row["write_after_hex"])), row["logical_id"]))

    spans = changed_spans(original, candidate)
    output_rows: list[dict[str, object]] = []
    category_counts: dict[str, int] = {}
    category_bytes: dict[str, int] = {}
    for start, end in spans:
        section = section_for(start, sections)
        all_zero_before = all(value == 0 for value in original[start:end])
        overlaps = [name for left, right, name in write_ranges if start < right and left < end]
        if section == ".text":
            category = "executable_text_change"
        elif text_end <= start < int(data["offset"]) and all_zero_before:
            category = "injected_code_in_zero_padding"
        elif start >= 0xED324:
            category = "translated_or_runtime_data"
        elif section == ".data":
            category = "other_data_change"
        else:
            category = "other_elf_change"
        category_counts[category] = category_counts.get(category, 0) + 1
        category_bytes[category] = category_bytes.get(category, 0) + end - start
        output_rows.append({
            "start_hex": f"0x{start:X}", "end_hex_exclusive": f"0x{end:X}",
            "length": end - start, "section": section, "category": category,
            "original_all_zero": all_zero_before, "overlap_v16_write_ids": ";".join(overlaps),
            "before_hex": original[start:end].hex(), "candidate_hex": candidate[start:end].hex(),
        })

    controls: list[dict[str, object]] = []
    text_start = int(text["offset"])
    for offset in range(text_start, text_end - 3, 4):
        before_word = struct.unpack_from("<I", original, offset)[0]
        after_word = struct.unpack_from("<I", candidate, offset)[0]
        if before_word == after_word:
            continue
        pc = virtual_address(offset, text)
        decoded = decode_control(after_word, pc)
        if decoded:
            controls.append({
                "file_offset": f"0x{offset:X}", "virtual_address": f"0x{pc:08X}",
                "before_word": f"0x{before_word:08X}", "after_word": f"0x{after_word:08X}",
                **decoded,
            })
    padding_start = text_end
    padding_end = int(data["offset"])
    injected_nonzero = [index for index in range(padding_start, padding_end) if original[index] == 0 and candidate[index] != 0]
    injection_range = None
    if injected_nonzero:
        injection_range = {"start_hex": f"0x{min(injected_nonzero):X}", "end_hex_exclusive": f"0x{max(injected_nonzero)+1:X}"}
    injection_va_start = virtual_address(min(injected_nonzero), text) if injected_nonzero else None
    hooks_into_injection = [
        item for item in controls
        if injection_va_start is not None and item.get("target")
        and injection_va_start <= int(str(item["target"]), 16) < virtual_address(padding_end, text)
    ]

    OUTPUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT / "changed_spans.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)
    report = {
        "format": "prinny1_v7_14_16_xdelta_boot_code_audit_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "original_iso": {"path": str(BASE_ISO), "sha256": sha256_file(BASE_ISO)},
            "original_boot": {"size": len(original), "sha256": sha256_bytes(original)},
            "candidate_boot": {"path": str(CANDIDATE_BOOT), "size": len(candidate), "sha256": sha256_bytes(candidate)},
            "current_v16_boot": {"path": str(V16_BOOT), "size": len(current), "sha256": sha256_bytes(current)},
        },
        "elf_boundaries": {
            "text": {"offset_hex": f"0x{text_start:X}", "end_hex_exclusive": f"0x{text_end:X}", "size": int(text["size"])},
            "data": {"offset_hex": f"0x{int(data['offset']):X}", "end_hex_exclusive": f"0x{int(data['end']):X}", "size": int(data["size"])},
        },
        "difference_summary": {
            "changed_bytes": sum(1 for a, b in zip(original, candidate) if a != b),
            "changed_spans": len(spans), "category_span_counts": category_counts,
            "category_changed_bytes": category_bytes, "injected_zero_padding_range": injection_range,
            "v16_boot_expected_write_count": len(write_ranges),
            "spans_overlapping_v16_boot_writes": sum(bool(row["overlap_v16_write_ids"]) for row in output_rows),
        },
        "changed_control_flow_words": controls,
        "hooks_targeting_injected_padding": hooks_into_injection,
        "injected_function_observations": [
            {
                "entry_file_offset": "0xCCE20", "entry_virtual_address": "0x088D0DCC",
                "inference": "character_or_display_width_counter",
                "evidence": "walks a zero-terminated byte string, treats space specially, and advances an extra byte for selected lead-byte ranges",
                "confidence": "provisional_requires_call_site_and_runtime_verification",
            },
            {
                "entry_file_offset": "0xCCEA4", "entry_virtual_address": "0x088D0E50",
                "inference": "bounded_multibyte_aware_string_copy",
                "evidence": "clears a 41-byte destination, copies from source with a length argument, preserves selected two-byte units, and zero-terminates",
                "confidence": "provisional_requires_call_site_and_runtime_verification",
            },
        ],
        "confirmed": [
            "The candidate BOOT contains executable .text changes.",
            "Candidate control-flow changes target code placed in formerly zero padding.",
            "Candidate data/string changes are separate from the executable hook mechanism.",
            "V7.14.16 F0 aliases alone do not reproduce the candidate runtime mechanism.",
        ],
        "decision": {
            "candidate_code_applied": False, "new_expected_writes_created": False,
            "new_iso_created": False,
            "next_gate": "disassemble_and_verify_hook_calling_convention_control_flow_and_required_data_dependencies",
        },
        "artifacts": {"changed_spans_csv": str(csv_path)},
        "status": "reference_code_separated_not_safe_to_apply",
        "final_verdict": "BLOCKER",
    }
    report_path = OUTPUT / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"BOOT changed bytes/spans: {report['difference_summary']['changed_bytes']}/{len(spans)}")
    print(f"hooks into injected padding: {len(hooks_into_injection)}")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: BLOCKER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
