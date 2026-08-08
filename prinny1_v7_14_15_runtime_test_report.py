#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_15_runtime_test"
SCREENS = REPORT_DIR / "screens"
CONFIG = ROOT / "workspace/config/ppsspp_runtime_no_external_textures.ini"
V14_ISO = (
    ROOT / "workspace/build/prinny1_v7_14_14_title_difficulty_repair"
    / "prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
)
V15_ISO = (
    ROOT / "workspace/build/prinny1_v7_14_15_text_test_iso"
    / "prinny_korean_v7_14_15_text_test.iso"
)
XDELTA_REFERENCE_ISO = (
    ROOT / "workspace/analysis/prinny1_xdelta_20260729/decoded_from_game_iso.iso"
)

EVIDENCE = {
    "v14_baseline": SCREENS / "baseline_difficulty/frame_001.png",
    "v15_clean": SCREENS / "v15_clean_difficulty/frame_001.png",
    "xdelta_reference": SCREENS / "xdelta_reference_difficulty/frame_001.png",
}
EXPECTED_SCREEN_HASHES = {
    "v14_baseline": "c7e8aadc9fbcd02e5589d1f81ee94ccbcb9d3f080bca2e2097d080dd7513c7c4",
    "v15_clean": "aea74ffdd7bad6eebd6da9965e438c2ba12174a9c885ed2e9741f4e4391b32d2",
    "xdelta_reference": "3781e25d64dabe274cc896039a4e9f8230c51a70cac9707317327a054ac2f574",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for path in (CONFIG, V14_ISO, V15_ISO, XDELTA_REFERENCE_ISO, *EVIDENCE.values()):
        if not path.is_file():
            raise FileNotFoundError(path)
    config_text = CONFIG.read_text(encoding="utf-8")
    if "ReplaceTextures = False" not in config_text or "SaveNewTextures = False" not in config_text:
        raise ValueError("외부 텍스처 비활성 설정이 봉인되지 않았습니다.")
    for label, path in EVIDENCE.items():
        if sha256_file(path) != EXPECTED_SCREEN_HASHES[label]:
            raise ValueError(f"런타임 캡처 해시가 달라졌습니다: {label}")

    report = {
        "format": "prinny1_v7_14_15_runtime_test_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "emulator": {
            "name": "PPSSPP",
            "version": "1.20.4",
            "graphics": "software",
            "window_size": "960x544",
            "external_texture_replacement": False,
            "texture_dump": False,
            "append_config": str(CONFIG),
            "append_config_sha256": sha256_file(CONFIG),
        },
        "input_sequence": ["Up", "Circle(x keyboard mapping)"],
        "builds": {
            "v14_baseline": {"path": str(V14_ISO), "sha256": sha256_file(V14_ISO)},
            "v15_test": {"path": str(V15_ISO), "sha256": sha256_file(V15_ISO)},
            "xdelta_reference": {
                "path": str(XDELTA_REFERENCE_ISO),
                "sha256": sha256_file(XDELTA_REFERENCE_ISO),
                "role": "reference_only_not_build_base",
            },
        },
        "evidence": {
            "v14_baseline": {
                "path": str(EVIDENCE["v14_baseline"]),
                "sha256": sha256_file(EVIDENCE["v14_baseline"]),
                "observation": "difficulty_dynamic_text_physically_readable",
                "verdict": "PASS_BASELINE",
            },
            "v15_clean": {
                "path": str(EVIDENCE["v15_clean"]),
                "sha256": sha256_file(EVIDENCE["v15_clean"]),
                "observation": "translated_dynamic_text_has_horizontal_line_and_missing_glyph_corruption",
                "verdict": "FAIL_REGRESSION",
            },
            "xdelta_reference": {
                "path": str(EVIDENCE["xdelta_reference"]),
                "sha256": sha256_file(EVIDENCE["xdelta_reference"]),
                "observation": "difficulty_korean_text_readable_with_contiguous_f0_f5_mapping",
                "verdict": "PASS_REFERENCE",
            },
        },
        "static_cross_checks": {
            "v15_font_fnt_unchanged_from_v14": True,
            "v15_font_txp_changed_bytes": 332,
            "v15_font_changes_limited_to_three_declared_glyphs": True,
            "boot_translation_used_hangul_count": 54,
            "all_54_font_table_links_valid": True,
            "all_54_glyph_blobs_nonempty": True,
        },
        "diagnosis": {
            "confirmed": [
                "V7.14.15 boots and reaches the difficulty screen.",
                "The corruption reproduces with external texture replacement and dumping disabled.",
                "V7.14.14 is readable under the same emulator settings and input sequence.",
                "The xdelta reference F0-F5 font/code system is readable under the same settings.",
            ],
            "working_hypothesis": "difficulty_ui_renderer_is_incompatible_with_current_scattered_sjis_hangul_mapping",
            "not_confirmed": "exact_decoder_branch_or_lookup_operation_causing_the_difference",
        },
        "decision": {
            "v7_14_15_release_candidate": False,
            "preserve_user_translation_wording": True,
            "directly_import_xdelta_wording": False,
            "next_fix": "port_contiguous_f0_f5_mapping_mechanism_then_encode_existing_user_wording",
            "new_iso_created_during_runtime_diagnosis": False,
        },
        "status": "runtime_blocker_v7_14_15_not_promotable",
        "final_verdict": "BLOCKER",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.14.14 baseline: PASS")
    print("V7.14.15 clean runtime: FAIL")
    print("xdelta F0-F5 reference: PASS")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: BLOCKER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
