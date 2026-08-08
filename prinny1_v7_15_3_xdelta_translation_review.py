#!/usr/bin/env python3
"""Independent structural review of the V7.15.3 wording selection."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file


ROOT = Path(__file__).resolve().parent
SELECTED = ROOT / "workspace/translations/selected_v7_15_3/boot_executable_translation_selected_v7_15_3.csv"
COMPARISON = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_translation_selection/translation_comparison.csv"
CHANGES = ROOT / "workspace/reports/prinny1_v7_15_2_boot_translation_shortening/approved_shortening_changes.csv"
FONT_REQUIRED = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_translation_selection/required_font_extension.csv"
BASE_ISO = ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair/prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
CANDIDATE_BOOT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/BOOT.BIN"
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_3_xdelta_translation_review"
EXPECTED = {
    SELECTED: "5f70bd572d54d71b3a80fd94b814a9034feebf059262a64f2b9ef396cf46673a",
    COMPARISON: "7b0a5d3622b8bb9cf204fe420abd5e2501b981c651d89905c8258a4b1e5edbbf",
    CHANGES: "6b6e21aeac105c0938bce9c9ea7f9acde314bb432d7e1fa5a07eb96ea354e859",
    FONT_REQUIRED: "3718a6811e354e2bdbceeda8cfa647b20055a77168eb4e77653e21000d5a8c1c",
    BASE_ISO: "bd5168a461adfd4a41b8daf9dfe6037d7a9838ab2fc8ee0affd1e0f5521bd5b5",
    CANDIDATE_BOOT: "97cbc41bd5617d1076b6eacc5907fb4edc85babcd433d65992b5b9d881ab73e6",
}
COMPOSITE = {
    "P1-V7.15.2-BOOT-0387", "P1-V7.15.2-BOOT-0388",
    "P1-V7.15.2-BOOT-0390", "P1-V7.15.2-BOOT-0391",
}
USER_IDS = {"P1-V7.15.2-BOOT-0002", "P1-V7.15.2-BOOT-0345"}
PLACEHOLDER = re.compile(r"%(?:\d+\$)?(?:0\d+)?[sd]")
JAPANESE = re.compile(r"[ぁ-ゖァ-ヺヽヾ一-龯]")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def measure(text: str) -> int:
    return sum(2 if "가" <= char <= "힣" else len(char.encode("cp932")) for char in text)


def main() -> int:
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"독립 검토 입력 해시 불일치: {path}")
    selected = rows(SELECTED)
    compared = rows(COMPARISON)
    by_id = {row["id"]: row for row in compared}
    overflow_ids = {row["id"] for row in rows(CHANGES)}
    if len(selected) != 542 or len(compared) != 542 or len(by_id) != 542 or len(overflow_ids) != 56:
        raise ValueError("독립 검토 행 수 또는 ID가 다릅니다.")
    base_boot = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "SYSDIR", "BOOT.BIN"]))
    candidate = CANDIDATE_BOOT.read_bytes()
    decisions = Counter()
    individual_overflow = set()
    changed = 0
    for final in selected:
        evidence = by_id[final["id"]]
        text = final["user_translation_korean"]
        if text != evidence["selected_translation_korean"]:
            raise ValueError(f"선택 큐와 비교표 불일치: {final['id']}")
        if JAPANESE.search(text) or PLACEHOLDER.findall(final["source_japanese"]) != PLACEHOLDER.findall(text):
            raise ValueError(f"최종 문구 언어/플레이스홀더 오류: {final['id']}")
        size = measure(text)
        if size > int(final["byte_length"]):
            individual_overflow.add(final["id"])
        if final["id"] not in COMPOSITE and evidence["candidate_raw_hex"]:
            raw = bytes.fromhex(evidence["candidate_raw_hex"])
            offset = int(final["offset_hex"], 0)
            if candidate[offset:offset + len(raw)] != raw:
                raise ValueError(f"후보 BOOT 바이트 근거 불일치: {final['id']}")
        source = bytes.fromhex(final["base_bytes_hex"])
        offset = int(final["offset_hex"], 0)
        if base_boot[offset:offset + len(source)] != source:
            raise ValueError(f"기준 BOOT 원문 불일치: {final['id']}")
        if final["id"] in overflow_ids and not evidence["selection_source"].startswith("xdelta"):
            raise ValueError(f"기존 초과 행이 후보 문구가 아닙니다: {final['id']}")
        decisions[evidence["selection_source"]] += 1
        changed += text != evidence["user_translation_korean"]
    if individual_overflow != {"P1-V7.15.2-BOOT-0390", "P1-V7.15.2-BOOT-0391"}:
        raise ValueError(f"복합 그룹 외 개별 용량 상태가 다릅니다: {sorted(individual_overflow)}")
    if {row["id"] for row in compared if row["selection_source"] == "user"} != USER_IDS:
        raise ValueError("사용자 문구 유지 ID가 다릅니다.")
    required = {row["character"] for row in rows(FONT_REQUIRED)}
    if required != {"꿉", "냅", "돕", "랗", "쏩", "짧", "켠", "횟"}:
        raise ValueError("폰트 확장 문자 집합이 다릅니다.")
    report = {
        "format": "prinny1_v7_15_3_xdelta_translation_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {str(path): sha256_file(path) for path in EXPECTED},
        "verified": {
            "rows": len(selected), "changed_from_current_queue": changed,
            "previous_overflow_rows_using_xdelta": len(overflow_ids),
            "decision_counts": dict(sorted(decisions.items())),
            "user_fidelity_overrides": len(USER_IDS), "font_extension_characters": len(required),
            "candidate_raw_slots_rechecked": len(selected) - len(COMPOSITE),
            "base_source_slots_rechecked": len(selected),
            "nongrouped_overflow_rows": 0,
            "composite_group_rows": len(COMPOSITE),
            "composite_individual_overflow_rows": len(individual_overflow),
            "placeholder_mismatches": 0, "japanese_residue_rows": 0
        },
        "checks": {
            "all_previous_overflows_use_xdelta": True,
            "selection_matches_comparison_evidence": True,
            "candidate_raw_bytes_match_for_nongrouped_rows": True,
            "source_bytes_match_base_iso": True,
            "direct_boot_or_iso_write_performed": False,
            "font_extension_and_composite_grouping_required_before_build": True
        },
        "status": "pass_selection_sealed_binary_build_blocked_on_font_and_composite_plan",
        "final_verdict": "PASS"
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"selected rows: {len(selected)}, changed: {changed}")
    print(f"font extension: {len(required)}, composite rows: {len(COMPOSITE)}")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
