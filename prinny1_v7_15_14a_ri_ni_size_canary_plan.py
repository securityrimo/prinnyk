#!/usr/bin/env python3
"""Build a size-only runtime measurement canary for 리 and 니."""
from pathlib import Path

import prinny1_v7_15_13_title_sprite_geometry_canary_plan as plan


ROOT = Path(__file__).resolve().parent
plan.OUTPUT = ROOT / "workspace/build/prinny1_v7_15_14a_ri_ni_size_canary_resources"
plan.REPORT = ROOT / "workspace/reports/prinny1_v7_15_14a_ri_ni_size_canary_plan"
plan.PATCHES = (
    (0x23D4, (-7, -38, 28, 24), (-7, -38, 56, 48)),
    (0x23E4, (-6, -46, 28, 24), (-6, -46, 56, 48)),
    (0x23F4, (-6, -38, 28, 24), (-6, -38, 56, 48)),
    (0x2404, (39, -50, 24, 24), (39, -50, 48, 48)),
    (0x2414, (39, -58, 24, 24), (39, -58, 48, 48)),
)
plan.GEOMETRY_POLICY = "ri_ni_size_only_runtime_measurement"


if __name__ == "__main__":
    raise SystemExit(plan.main())
