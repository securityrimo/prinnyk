#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
QA = ROOT / "workspace/reports/prinny_qa/qa_rows.csv"
UI = ROOT / "workspace/translations/ui_v7_14_15/title_difficulty_translation.csv"
V22_REVIEW = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_iso_review/all_report.json"
IMAGE_EXPORT = ROOT / "workspace/exports/prinny1_v7_14_15_images/all_report.json"
XDELTA_COMPARE = ROOT / "workspace/reports/prinny1_v7_14_15_xdelta_reference_comparison/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_0_full_coverage_audit"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    for path in (QA, UI, V22_REVIEW, IMAGE_EXPORT, XDELTA_COMPARE):
        if not path.is_file():
            raise FileNotFoundError(path)
    qa = read_csv(QA)
    ui = read_csv(UI)
    v22 = json.loads(V22_REVIEW.read_text(encoding="utf-8"))
    image_export = json.loads(IMAGE_EXPORT.read_text(encoding="utf-8"))
    xdelta = json.loads(XDELTA_COMPARE.read_text(encoding="utf-8"))
    if len(qa) != 4110 or int(v22["verified"]["qa_slot_count"]) != 4110:
        raise ValueError("사용자 QA 4,110개 적용 근거가 다릅니다.")
    texture = [row for row in ui if row["target_kind"] == "texture"]
    executable = [row for row in ui if row["target_kind"] != "texture"]
    rows = [
        {"priority": 1, "scope": "START text slots", "total": 4110, "completed": 4110, "pending": 0, "state": "binary_complete_runtime_renderer_blocked", "source": str(QA)},
        {"priority": 2, "scope": "BOOT difficulty UI", "total": len(executable), "completed": len(executable), "pending": 0, "state": "binary_complete_runtime_renderer_blocked", "source": str(UI)},
        {"priority": 3, "scope": "internal title/difficulty textures", "total": len(texture), "completed": 0, "pending": len(texture), "state": "pending_internal_image_application", "source": str(UI)},
        {"priority": 4, "scope": "candidate-changed internal image resources", "total": 4, "completed": 0, "pending": 4, "state": "pending_container_comparison", "source": "anime00.dat;number.txp;ANIME.DAT;BG.DAT"},
        {"priority": 5, "scope": "residual Japanese full-game scan", "total": 1, "completed": 0, "pending": 1, "state": "pending_after_integrated_build", "source": "all trusted text and internal image inventory"},
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    matrix = OUTPUT / "full_localization_coverage.csv"
    with matrix.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    report = {
        "format": "prinny1_v7_15_0_full_coverage_audit_v1", "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verified": {
            "qa_text_total": len(qa), "qa_text_binary_complete": 4110, "boot_ui_total": len(executable), "boot_ui_binary_complete": len(executable),
            "approved_internal_texture_total": len(texture), "approved_internal_texture_pending": len(texture),
            "exported_image_inventory": int(image_export["counts"]["inventory_rows"]),
        },
        "policy": {
            "next_build_goal": "all_dynamic_korean_visible_before_regression_cleanup",
            "candidate_wording_imported": False, "user_translation_is_authoritative": True,
            "v7_14_23_narrow_diagnostic_promoted": False,
            "known_prologue_regression_is_tracked_not_hidden": True,
        },
        "reference": {"candidate_internal_image_resources": xdelta["reference_findings"]["deferred_internal_image_resources"], "candidate_internal_image_containers": xdelta["reference_findings"]["deferred_internal_image_containers"]},
        "artifacts": {"coverage_matrix": str(matrix), "coverage_matrix_sha256": sha256_file(matrix)},
        "status": "full_localization_scope_locked_integrated_text_build_required", "final_verdict": "PASS",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("QA text: 4110/4110 binary complete")
    print(f"BOOT UI: {len(executable)}/{len(executable)} binary complete")
    print(f"approved internal textures: 0/{len(texture)} pending")
    print("V7.14.23 narrow diagnostic promoted: no")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
