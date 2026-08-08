#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_14_16_runtime_test"
CONFIG = ROOT / "workspace/config/ppsspp_runtime_no_external_textures.ini"
ISO = (
    ROOT / "workspace/build/prinny1_v7_14_16_text_test_iso"
    / "prinny_korean_v7_14_16_text_test.iso"
)
ISO_REVIEW = ROOT / "workspace/reports/prinny1_v7_14_16_text_test_iso_review/all_report.json"
SCREEN = REPORT_DIR / "screens/difficulty/frame_001.png"
EXPECTED_ISO_SHA256 = "20d166fc9ee61633cf9f52cbb9ed9013f85c45dd30a411c9a915aa58c395f1fd"
EXPECTED_SCREEN_SHA256 = "ad4b243870757fda37988186c3e4230efafe449fbb52424327774a674097f6bd"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for path in (CONFIG, ISO, ISO_REVIEW, SCREEN):
        if not path.is_file():
            raise FileNotFoundError(path)
    config_text = CONFIG.read_text(encoding="utf-8")
    if "ReplaceTextures = False" not in config_text or "SaveNewTextures = False" not in config_text:
        raise ValueError("외부 텍스처 교체·덤프 비활성 설정이 봉인되지 않았습니다.")
    if sha256_file(ISO) != EXPECTED_ISO_SHA256:
        raise ValueError("V7.14.16 ISO 해시가 승인 빌드와 다릅니다.")
    if sha256_file(SCREEN) != EXPECTED_SCREEN_SHA256:
        raise ValueError("V7.14.16 런타임 캡처 해시가 달라졌습니다.")
    review = json.loads(ISO_REVIEW.read_text(encoding="utf-8"))
    if review.get("final_verdict") != "PASS" or review["iso"]["sha256"] != EXPECTED_ISO_SHA256:
        raise ValueError("V7.14.16 구조 검토 PASS를 확인할 수 없습니다.")

    report = {
        "format": "prinny1_v7_14_16_runtime_test_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "emulator": {
            "name": "PPSSPP", "version": "1.20.4", "graphics": "software",
            "window_size": "960x544", "external_texture_replacement": False,
            "texture_dump": False, "append_config": str(CONFIG),
            "append_config_sha256": sha256_file(CONFIG),
        },
        "input_sequence": ["Up", "Circle(x keyboard mapping)"],
        "build": {"path": str(ISO), "size": ISO.stat().st_size, "sha256": sha256_file(ISO)},
        "evidence": {
            "path": str(SCREEN), "sha256": sha256_file(SCREEN),
            "observation": "difficulty_dynamic_text_still_has_horizontal_line_and_missing_glyph_corruption",
            "verdict": "FAIL_REGRESSION",
        },
        "cross_check": {
            "structural_iso_review": "PASS", "v7_14_15_failure_reproduced": True,
            "f0_alias_count": 54, "f0_alias_only_fix_sufficient": False,
            "user_translation_wording_changed": False,
        },
        "diagnosis": {
            "confirmed": [
                "V7.14.16 boots and reaches the difficulty screen.",
                "The same corruption remains after encoding all 54 Hangul characters through F0 aliases.",
                "The xdelta reference changes BOOT executable code in addition to font and string data.",
            ],
            "working_hypothesis": "xdelta_reference_requires_boot_decoder_or_renderer_code_changes_not_font_aliases_alone",
            "not_confirmed": "minimal_safe_hook_and_all_required_control_flow_changes",
        },
        "decision": {
            "v7_14_16_release_candidate": False,
            "preserve_user_translation_wording": True,
            "directly_import_xdelta_code": False,
            "next_fix": "audit_and_independently_verify_xdelta_boot_code_hook_before_any_expected_write",
            "new_iso_requires_separate_user_approval": True,
        },
        "status": "runtime_blocker_v7_14_16_not_promotable",
        "final_verdict": "BLOCKER",
    }
    report_path = REPORT_DIR / "all_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V7.14.16 structural review: PASS")
    print("V7.14.16 clean runtime: FAIL")
    print("F0 alias-only fix: insufficient")
    print(f"report: {report_path}")
    print("FINAL_VERDICT: BLOCKER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
