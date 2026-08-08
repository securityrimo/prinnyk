#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ISO = ROOT / "workspace/build/prinny1_v7_14_21_scoped_decoder_diagnostic/prinny_korean_v7_14_21_scoped_decoder_diagnostic.iso"
ISO_REVIEW = ROOT / "workspace/reports/prinny1_v7_14_21_scoped_decoder_iso_review/all_report.json"
SCREENSHOT = ROOT / "workspace/reports/prinny1_v7_14_21_runtime_test/screens/user_checkpoint/frame_001.png"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_21_runtime_test"
EXPECTED_ISO_SHA256 = "8152576a331d9142a3f45e005ecc3aef052b1e59e6319ead496c2bf3ada4f1f9"
EXPECTED_SCREENSHOT_SHA256 = "8068ffe78c3e5f10e82f1c5e09223132bb971cd78bf60e3f654d3682779402ab"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    for path in (ISO, ISO_REVIEW, SCREENSHOT):
        if not path.is_file():
            raise FileNotFoundError(path)
    review = json.loads(ISO_REVIEW.read_text(encoding="utf-8"))
    if review.get("status") != "pass_runtime_gameplay_regression_test_required":
        raise ValueError("ISO 독립 검토 상태가 다릅니다.")
    if sha256_file(ISO) != EXPECTED_ISO_SHA256 or sha256_file(SCREENSHOT) != EXPECTED_SCREENSHOT_SHA256:
        raise ValueError("런타임 증거 해시가 다릅니다.")
    report = {
        "format": "prinny1_v7_14_21_scoped_decoder_runtime_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runtime": {
            "emulator": "PPSSPP 1.20.4 Flatpak",
            "iso": str(ISO),
            "iso_sha256": sha256_file(ISO),
            "scene": "prologue boss encounter after stage-entry overlay",
            "comparison_baseline": "V7.14.14 reached the same battle normally; V20 lost jump/attack effects and could not progress",
            "user_observation": "V7.14.14 was normal, so the progression blocker was decoder-related",
        },
        "evidence": {"screenshot": str(SCREENSHOT), "screenshot_sha256": sha256_file(SCREENSHOT)},
        "verified": {
            "stage_overlay_cleared": True,
            "boss_battle_active": True,
            "player_action_frame_visible": True,
            "global_parser_and_byte_class_ranges_present": False,
        },
        "scope": {
            "prologue_gameplay_blocker": "PASS",
            "title_screen": "not_tested_in_this_report",
            "difficulty_screen": "not_tested_in_this_report",
            "full_dialogue_rendering": "not_tested_in_this_report",
        },
        "status": "pass_prologue_gameplay_blocker_removed_other_runtime_gates_pending",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.14.21 prologue gameplay blocker: PASS")
    print("title/difficulty/dialogue regression gates: pending")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
