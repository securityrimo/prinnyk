#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ISO = ROOT / "workspace/build/prinny1_v7_14_22_coherent_f0/prinny_korean_v7_14_22_coherent_f0.iso"
SCREENS = ROOT / "workspace/reports/prinny1_v7_14_22_runtime_test/screens/user_checkpoint"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_14_22_runtime_test"
EXPECTED = {
    "frame_001.png": "title_screen_no_physical_font_corruption",
    "frame_002.png": "standard_difficulty_dynamic_text_corrupted",
    "frame_003.png": "title_screen_restored_without_residual_corruption",
    "frame_004.png": "hard_difficulty_dynamic_text_corrupted",
    "frame_005.png": "in_game_dialogue_dynamic_text_corrupted",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not ISO.is_file():
        raise FileNotFoundError(ISO)
    captures = []
    for name, observation in EXPECTED.items():
        path = SCREENS / name
        if not path.is_file():
            raise FileNotFoundError(path)
        captures.append({"name": name, "path": str(path), "sha256": sha256_file(path), "observation": observation})
    report = {
        "format": "prinny1_v7_14_22_runtime_report_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "iso": {"path": str(ISO), "sha256": sha256_file(ISO)},
        "captures": captures,
        "verified": {"capture_count": len(captures), "title_physical_corruption": False, "difficulty_dynamic_text_failure": True, "dialogue_dynamic_text_failure": True},
        "diagnosis": {
            "font_texture_regression": False,
            "coherent_f0_alias_failure": False,
            "scoped_decoder_missing_shared_byte_classification": True,
            "next_diagnostic": "add_byte_class_ranges_only_keep_parser_step_ranges_excluded",
        },
        "status": "runtime_blocker_byte_class_diagnostic_required",
        "final_verdict": "BLOCKER",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.14.22 runtime: BLOCKER")
    print("title corruption: no")
    print("difficulty/dialogue dynamic text: failed")
    print("FINAL_VERDICT: BLOCKER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
