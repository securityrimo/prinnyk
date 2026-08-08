#!/usr/bin/env python3
"""Review resources for the top-left anchored 프 geometry canary."""
from pathlib import Path

import prinny1_v7_15_13_title_sprite_geometry_canary_review as review


ROOT = Path(__file__).resolve().parent
review.BUILD = ROOT / "workspace/build/prinny1_v7_15_13b_title_sprite_geometry_anchor_canary_resources"
review.PLAN = ROOT / "workspace/reports/prinny1_v7_15_13b_title_sprite_geometry_anchor_canary_plan/all_report.json"
review.OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_13b_title_sprite_geometry_anchor_canary_review"
review.PATCHES = (
    (0x23B4, (-63, -29, 32, 32), (-63, -29, 64, 64)),
    (0x23C4, (-63, -37, 32, 32), (-63, -37, 64, 64)),
)
review.GEOMETRY_POLICY = "top_left_anchor_preserved"


if __name__ == "__main__":
    raise SystemExit(review.main())
