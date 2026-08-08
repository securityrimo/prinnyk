#!/usr/bin/env python3
"""Build resources for the top-left anchored 프 geometry canary."""
from pathlib import Path

import prinny1_v7_15_13_title_sprite_geometry_canary_plan as canary


ROOT = Path(__file__).resolve().parent
canary.OUTPUT = ROOT / "workspace/build/prinny1_v7_15_13b_title_sprite_geometry_anchor_canary_resources"
canary.REPORT = ROOT / "workspace/reports/prinny1_v7_15_13b_title_sprite_geometry_anchor_canary_plan"
canary.PATCHES = (
    (0x23B4, (-63, -29, 32, 32), (-63, -29, 64, 64)),
    (0x23C4, (-63, -37, 32, 32), (-63, -37, 64, 64)),
)
canary.GEOMETRY_POLICY = "top_left_anchor_preserved"


if __name__ == "__main__":
    raise SystemExit(canary.main())
