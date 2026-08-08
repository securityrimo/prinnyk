#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_17_runtime_test"
ISO = ROOT / "workspace/build/prinny1_v7_14_17_text_test_iso/prinny_korean_v7_14_17_text_test.iso"
SCREEN = REPORT_DIR / "screens/difficulty/frame_001.png"
V16_SCREEN = ROOT / "workspace/reports/prinny1_v7_14_16_runtime_test/screens/difficulty/frame_001.png"
XDELTA_SCREEN = ROOT / "workspace/reports/prinny1_v7_14_15_runtime_test/screens/xdelta_reference_difficulty/frame_001.png"
CONFIG = ROOT / "workspace/config/ppsspp_runtime_no_external_textures.ini"
ISO_REVIEW = ROOT / "workspace/reports/prinny1_v7_14_17_text_test_iso_review/all_report.json"
EXPECTED_ISO_SHA256 = "0fd1a029bf9f31a7c12f0653216e4fe5f664e86675a842503e0d0d8ea9f22689"
EXPECTED_SCREEN_SHA256 = "2971f978dde01918f96ec3d89a6eb357d62ed0f10238bcaa6a2d60935b3eb050"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def different_pixels(left: Path, right: Path) -> int:
    a, b = Image.open(left).convert("RGB"), Image.open(right).convert("RGB")
    if a.size != b.size:
        raise ValueError("런타임 비교 화면 크기가 다릅니다.")
    difference = ImageChops.difference(a, b)
    return sum(1 for pixel in difference.getdata() if pixel != (0, 0, 0))


def main() -> int:
    for path in (ISO, SCREEN, V16_SCREEN, XDELTA_SCREEN, CONFIG, ISO_REVIEW):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(ISO) != EXPECTED_ISO_SHA256 or sha256_file(SCREEN) != EXPECTED_SCREEN_SHA256:
        raise ValueError("V7.14.17 ISO 또는 캡처 해시가 다릅니다.")
    iso_review = json.loads(ISO_REVIEW.read_text(encoding="utf-8"))
    if iso_review.get("final_verdict") != "PASS":
        raise ValueError("V7.14.17 ISO 구조 검토가 PASS가 아닙니다.")
    config = CONFIG.read_text(encoding="utf-8")
    if "ReplaceTextures = False" not in config or "SaveNewTextures = False" not in config:
        raise ValueError("외부 텍스처 비활성 설정이 아닙니다.")
    v16_delta = different_pixels(SCREEN, V16_SCREEN)
    reference_delta = different_pixels(SCREEN, XDELTA_SCREEN)
    report = {
        "format": "prinny1_v7_14_17_runtime_test_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "emulator": {"name": "PPSSPP", "version": "1.20.4", "external_texture_replacement": False,
                     "texture_dump": False, "append_config": str(CONFIG)},
        "input_sequence": ["Up", "Circle(x keyboard mapping)"],
        "build": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": sha256_file(ISO)},
        "evidence": {"path": str(SCREEN), "sha256": sha256_file(SCREEN),
                     "observation": "more_glyph_strokes_than_v16_but_all_dynamic_korean_remains_unreadable",
                     "verdict": "FAIL_REGRESSION"},
        "pixel_cross_check": {"different_pixels_from_v16": v16_delta,
                              "different_pixels_from_readable_xdelta_reference": reference_delta},
        "diagnosis": {"boot_decoder_hook_has_visible_effect": True, "boot_decoder_hook_sufficient": False,
                      "next_hypothesis": "current_sequential_f0_alias_codes_do_not_match_candidate_native_f0_code_to_glyph_system"},
        "decision": {"v7_14_17_release_candidate": False, "preserve_user_translation_wording": True,
                     "next_fix": "recover_candidate_native_code_mapping_for_the_same_54_user_characters",
                     "automatic_test_iso_approval_active": True},
        "status": "runtime_blocker_v7_14_17_not_promotable", "final_verdict": "BLOCKER",
    }
    path = REPORT_DIR / "all_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.14.17 structural review: PASS")
    print("V7.14.17 runtime: FAIL")
    print(f"different pixels from V16: {v16_delta}")
    print(f"report: {path}")
    print("FINAL_VERDICT: BLOCKER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
