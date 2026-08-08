#!/usr/bin/env python3
"""Build resources for the measured-position 프 geometry canary."""
from pathlib import Path

import prinny1_v7_15_13_title_sprite_geometry_canary_plan as canary


ROOT = Path(__file__).resolve().parent
canary.OUTPUT = ROOT / "workspace/build/prinny1_v7_15_13c_title_sprite_geometry_position_canary_resources"
canary.REPORT = ROOT / "workspace/reports/prinny1_v7_15_13c_title_sprite_geometry_position_canary_plan"
canary.PATCHES = (
    (0x23B4, (-63, -29, 32, 32), (-35, 0, 64, 64)),
    (0x23C4, (-63, -37, 32, 32), (-35, -8, 64, 64)),
)
canary.GEOMETRY_POLICY = "runtime_measured_title_center_alignment"


if __name__ == "__main__":
    raise SystemExit(canary.main())
