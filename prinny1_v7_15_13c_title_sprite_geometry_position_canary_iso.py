#!/usr/bin/env python3
"""Build the measured-position 프 enlargement canary ISO."""
from pathlib import Path

import prinny1_v7_15_13_title_sprite_geometry_canary_iso as builder


ROOT = Path(__file__).resolve().parent
builder.SYSTEM = ROOT / "workspace/build/prinny1_v7_15_13c_title_sprite_geometry_position_canary_resources/SYSTEM.DAT"
builder.REVIEW = ROOT / "workspace/reports/prinny1_v7_15_13c_title_sprite_geometry_position_canary_review/all_report.json"
builder.OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_13c_title_sprite_geometry_position_canary"
builder.OUTPUT_ISO = builder.OUTPUT_DIR / "prinny_korean_v7_15_13c_title_sprite_geometry_position_canary.iso"
builder.REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_13c_title_sprite_geometry_position_canary_iso"
builder.EXPECTED = {
    builder.BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    builder.SYSTEM: "eb0ad5d33f1d1052ac4654a276bb6d9bbfcd8d09e6957b095feff9335dc18d23",
    builder.REVIEW: "0c1a42dcebc961bda9404cef3ac185d93ce59e53b4802492f00d4e4a6b889b81",
}


if __name__ == "__main__":
    raise SystemExit(builder.main())
