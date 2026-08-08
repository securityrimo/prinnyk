#!/usr/bin/env python3
"""Select V7.15.3 BOOT wording from user and forced-xdelta translations."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_18_candidate_native_plan import NATIVE_HEX
from prinny1_v7_14_20_mixed_renderer_plan import EXTRA


ROOT = Path(__file__).resolve().parent
USER_QUEUE = ROOT / "workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_user_only.csv"
OVERFLOW_CHANGES = ROOT / "workspace/reports/prinny1_v7_15_2_boot_translation_shortening/approved_shortening_changes.csv"
CANDIDATE_BOOT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/BOOT.BIN"
PARTIAL_CODEBOOK = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/candidate_codebook_partial.csv"
ALLOCATION = ROOT / "workspace/font/audited_allocation_980/hangul_allocation.json"
OUTPUT_DIR = ROOT / "workspace/translations/selected_v7_15_3"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_translation_selection"
SELECTED = OUTPUT_DIR / "boot_executable_translation_selected_v7_15_3.csv"
COMPARISON = REPORT_DIR / "translation_comparison.csv"
SUPPLEMENT = REPORT_DIR / "boot_codebook_supplement.csv"
FONT_REQUIRED = REPORT_DIR / "required_font_extension.csv"

EXPECTED = {
    USER_QUEUE: "293efcb219632ce1a8f95143d0a629e28445c2d4eb83a663fded9ee100d4ca61",
    OVERFLOW_CHANGES: "6b6e21aeac105c0938bce9c9ea7f9acde314bb432d7e1fa5a07eb96ea354e859",
    CANDIDATE_BOOT: "97cbc41bd5617d1076b6eacc5907fb4edc85babcd433d65992b5b9d881ab73e6",
    PARTIAL_CODEBOOK: "f1ac6829d2c07450f6433b0daa95d413b85aaf1ed8b2ece22bcd5dcf2a5387a3",
    ALLOCATION: "f35f9bdac9c07c867e40b72e71323b16928b8dfdeb34de99420db289a49291f3",
}

SUPPLEMENTAL_CODEBOOK = {
    "F048": "갔", "F092": "꽃", "F093": "꿉", "F0B1": "꾼", "F0B2": "꾸",
    "F0B8": "끌", "F0C7": "낼", "F0C9": "냅", "F0E1": "놓", "F14D": "돕",
    "F15E": "뒤", "F162": "득", "F169": "디", "F18C": "눌", "F1C7": "립",
    "F1D3": "맞", "F1F5": "므", "F2B0": "슷", "F357": "위", "F379": "저",
    "F383": "갈", "F396": "랗", "F3BF": "치", "F45D": "튀", "F4A9": "획",
    "F4BB": "히", "F4BC": "힌", "F4C5": "뢰", "F4C8": "릅", "F4EF": "쏩",
    "F4F8": "왼", "F4F9": "웅", "F544": "짧", "F552": "켠", "F56A": "횟",
}

USER_OVERRIDES = {
    "P1-V7.15.2-BOOT-0002": "candidate_invents_replay_again_not_present_in_source",
    "P1-V7.15.2-BOOT-0345": "candidate_is_untranslated_japanese",
}
COMPOSITE_FIRST_LINE = {
    "P1-V7.15.2-BOOT-0387": "남은 프리니: %d명",
    "P1-V7.15.2-BOOT-0388": "남은 프리니: %d명",
    # The candidate compacts the first line of this whole format string.
    # Reading at the legacy inner-line offset therefore starts in the middle
    # of "플레이 시간" and produces the false fragment "이 시간".
    "P1-V7.15.2-BOOT-0390": "플레이 시간: %02d:%02d:%02d",
    "P1-V7.15.2-BOOT-0391": "플레이 시간: %02d:%02d:%02d",
}
PLACEHOLDER = re.compile(r"%(?:\d+\$)?(?:0\d+)?[sd]")
JAPANESE = re.compile(r"[ぁ-ゖァ-ヺヽヾ一-龯]")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def measure(text: str) -> int:
    return sum(2 if "가" <= char <= "힣" else len(char.encode("cp932")) for char in text)


def load_codebook() -> tuple[dict[str, str], dict[str, str]]:
    mapping = {
        row["candidate_code"]: row["unicode_character"]
        for row in read_csv(PARTIAL_CODEBOOK) if row["unicode_character"]
    }
    trusted = {value: key for key, value in {**NATIVE_HEX, **EXTRA}.items()}
    for code, character in trusted.items():
        mapping[code] = character
    mapping.update(SUPPLEMENTAL_CODEBOOK)
    return mapping, trusted


def decode_candidate(blob: bytes, offset: int, codebook: dict[str, str]) -> tuple[str, bytes]:
    output: list[str] = []
    cursor = offset
    while cursor < len(blob) and blob[cursor] != 0:
        lead = blob[cursor]
        if 0xF0 <= lead <= 0xF5:
            code = blob[cursor:cursor + 2].hex().upper()
            if code not in codebook:
                raise ValueError(f"미복구 후보 코드: {code} @ 0x{cursor:X}")
            output.append(codebook[code])
            cursor += 2
        elif lead == 0x0A:
            output.append("\n")
            cursor += 1
        elif (0x81 <= lead <= 0x9F or 0xE0 <= lead <= 0xEF) and cursor + 1 < len(blob):
            output.append(blob[cursor:cursor + 2].decode("cp932"))
            cursor += 2
        elif lead < 0x80:
            output.append(chr(lead))
            cursor += 1
        else:
            raise ValueError(f"후보 BOOT 디코드 실패: 0x{cursor:X}/0x{lead:02X}")
    return "".join(output), blob[offset:cursor]


def main() -> int:
    for path, expected_hash in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected_hash:
            raise ValueError(f"선택 입력 해시 불일치: {path}")
    rows = read_csv(USER_QUEUE)
    overflow_ids = {row["id"] for row in read_csv(OVERFLOW_CHANGES)}
    if len(rows) != 542 or len(overflow_ids) != 56:
        raise ValueError("선택 범위 행 수가 다릅니다.")
    candidate_boot = CANDIDATE_BOOT.read_bytes()
    codebook, trusted = load_codebook()
    allocation = json.loads(ALLOCATION.read_text(encoding="utf-8"))["allocations"]
    current_chars = {row["hangul"] for row in allocation}
    selected_rows: list[dict[str, object]] = []
    comparison_rows: list[dict[str, object]] = []
    required: dict[str, set[str]] = defaultdict(set)
    counts = Counter()

    for source in rows:
        identifier = source["id"]
        offset = int(source["offset_hex"], 0)
        slot = int(source["byte_length"])
        if identifier in COMPOSITE_FIRST_LINE:
            candidate = COMPOSITE_FIRST_LINE[identifier]
            candidate_raw = b""
            decision = "xdelta_composite_first_line"
            reason = "candidate_full_format_string_group_required"
        else:
            candidate, candidate_raw = decode_candidate(candidate_boot, offset, codebook)
        if identifier in COMPOSITE_FIRST_LINE:
            pass
        elif identifier in USER_OVERRIDES:
            decision = "user"
            reason = USER_OVERRIDES[identifier]
        elif identifier in overflow_ids:
            decision = "xdelta"
            reason = "user_translation_previously_exceeded_slot"
        elif candidate == source["user_translation_korean"]:
            decision = "same"
            reason = "user_and_xdelta_wording_equal"
        else:
            decision = "xdelta"
            reason = "xdelta_context_and_ui_style_preferred_after_comparison"

        selected = source["user_translation_korean"] if decision == "user" else candidate
        if JAPANESE.search(selected):
            raise ValueError(f"최종 일본어 잔존: {identifier}/{selected}")
        if PLACEHOLDER.findall(source["source_japanese"]) != PLACEHOLDER.findall(selected):
            raise ValueError(f"최종 플레이스홀더 불일치: {identifier}")
        selected_size = measure(selected)
        if selected_size > slot and identifier not in COMPOSITE_FIRST_LINE:
            raise ValueError(f"최종 문자열 슬롯 초과: {identifier}/{selected_size}/{slot}")
        missing = sorted({char for char in selected if "가" <= char <= "힣" and char not in current_chars})
        for character in missing:
            required[character].add(identifier)
        if identifier in overflow_ids and decision not in {"xdelta", "xdelta_composite_first_line"}:
            raise ValueError(f"기존 슬롯 초과 행이 xdelta를 사용하지 않습니다: {identifier}")

        counts[decision] += 1
        output = dict(source)
        output["user_translation_korean"] = selected
        output["selection_source"] = decision
        output["selection_reason"] = reason
        selected_rows.append(output)
        comparison_rows.append({
            "id": identifier,
            "offset_hex": source["offset_hex"],
            "slot_bytes": slot,
            "source_japanese": source["source_japanese"],
            "user_translation_korean": source["user_translation_korean"],
            "xdelta_translation_korean": candidate,
            "selected_translation_korean": selected,
            "selection_source": decision,
            "selection_reason": reason,
            "previously_overflowed": "yes" if identifier in overflow_ids else "no",
            "selected_payload_bytes": selected_size,
            "remaining_bytes_before_boundary": slot - selected_size,
            "required_new_glyphs": "".join(missing),
            "candidate_raw_hex": candidate_raw.hex().upper(),
        })

    if counts["xdelta"] + counts["xdelta_composite_first_line"] + counts["same"] != 540 or counts["user"] != 2:
        raise ValueError(f"최종 선택 개수가 예상과 다릅니다: {dict(counts)}")
    expected_required = {"꿉", "냅", "쏩", "짧", "랗", "켠", "횟", "돕"}
    if set(required) != expected_required:
        raise ValueError(f"폰트 확장 문자 집합이 다릅니다: {sorted(required)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(SELECTED, selected_rows)
    write_csv(COMPARISON, comparison_rows)
    write_csv(SUPPLEMENT, [
        {"candidate_code": code, "unicode_character": character, "unicode": f"U+{ord(character):04X}", "evidence": "boot_context_cross_occurrence"}
        for code, character in SUPPLEMENTAL_CODEBOOK.items()
    ])
    write_csv(FONT_REQUIRED, [
        {"character": character, "unicode": f"U+{ord(character):04X}", "occurrence_count": len(required[character]), "affected_ids": ";".join(sorted(required[character]))}
        for character in sorted(required)
    ])
    report = {
        "format": "prinny1_v7_15_3_xdelta_translation_selection_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "row_count": len(rows),
            "previous_overflow_rows_using_xdelta": len(overflow_ids),
            "xdelta_selected_after_comparison": counts["xdelta"] - len(overflow_ids),
            "xdelta_composite_first_line": counts["xdelta_composite_first_line"],
            "same_wording": counts["same"],
            "user_selected_for_fidelity_or_untranslated_candidate": counts["user"],
            "selected_rows_equal_to_xdelta_wording": 540,
            "selected_rows_equal_to_user_only": 2,
            "nongrouped_slot_overflow_rows_using_source_boundary_capacity": 0,
            "composite_rows": len(COMPOSITE_FIRST_LINE),
            "composite_rows_exceeding_individual_legacy_span": 2,
            "placeholder_mismatch_rows": 0,
            "selected_japanese_residue_rows": 0,
            "required_font_extension_characters": len(required),
            "boot_codes_supplemented_by_context": len(SUPPLEMENTAL_CODEBOOK),
        },
        "required_font_extension": sorted(required),
        "artifacts": {
            "selected_queue": str(SELECTED), "selected_queue_sha256": sha256_file(SELECTED),
            "comparison": str(COMPARISON), "comparison_sha256": sha256_file(COMPARISON),
            "codebook_supplement": str(SUPPLEMENT), "codebook_supplement_sha256": sha256_file(SUPPLEMENT),
            "font_extension": str(FONT_REQUIRED), "font_extension_sha256": sha256_file(FONT_REQUIRED),
        },
        "checks": {
            "all_previous_overflows_use_xdelta_wording": True,
            "nonoverflow_rows_compared": True,
            "candidate_bytes_directly_written_to_current_boot": False,
            "iso_modified": False,
            "composite_format_rows_require_grouped_expected_write": True,
        },
        "status": "selection_complete_font_extension_and_composite_group_review_required",
        "final_verdict": "PASS",
    }
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"selected rows: {len(rows)}")
    print(f"previous overflow rows using xdelta: {len(overflow_ids)}")
    print(f"xdelta-equivalent selections: 540, user selections: 2")
    print(f"required font extension: {''.join(sorted(required))}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
