#!/usr/bin/env python3
"""Review resources for the final white, enlarged three-glyph title."""
from pathlib import Path

import prinny1_v7_15_13_title_sprite_geometry_canary_review as review


ROOT = Path(__file__).resolve().parent
review.BUILD = ROOT / "workspace/build/prinny1_v7_15_14_white_large_title_resources"
review.PLAN = ROOT / "workspace/reports/prinny1_v7_15_14_white_large_title_plan/all_report.json"
review.OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_14_white_large_title_review"
review.PATCHES = (
    (0x23B4, (-63, -29, 32, 32), (-31, 3, 64, 64)),
    (0x23C4, (-63, -37, 32, 32), (-31, -5, 64, 64)),
    (0x23D4, (-7, -38, 28, 24), (21, -14, 56, 48)),
    (0x23E4, (-6, -46, 28, 24), (22, -22, 56, 48)),
    (0x23F4, (-6, -38, 28, 24), (22, -14, 56, 48)),
    (0x2404, (39, -50, 24, 24), (63, -26, 48, 48)),
    (0x2414, (39, -58, 24, 24), (63, -34, 48, 48)),
)
review.GEOMETRY_POLICY = "preserve_runtime_position_by_adding_size_delta_to_xy"


if __name__ == "__main__":
    raise SystemExit(review.main())
