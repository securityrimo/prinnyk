#!/usr/bin/env python3
"""Build the final white, enlarged three-glyph title ISO."""
from pathlib import Path

import prinny1_v7_15_13_title_sprite_geometry_canary_iso as builder


ROOT = Path(__file__).resolve().parent
builder.SYSTEM = ROOT / "workspace/build/prinny1_v7_15_14_white_large_title_resources/SYSTEM.DAT"
builder.REVIEW = ROOT / "workspace/reports/prinny1_v7_15_14_white_large_title_review/all_report.json"
builder.OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_14_white_large_title"
builder.OUTPUT_ISO = builder.OUTPUT_DIR / "prinny_korean_v7_15_14_white_large_title.iso"
builder.REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_14_white_large_title_iso"
builder.EXPECTED = {
    builder.BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    builder.SYSTEM: "0956e2db4b7f30f03632accce2122fd4693c5d2d088675856ca236e518db5fce",
    builder.REVIEW: "226dbf2e7d64505d10be7ab04de11a96b7f616d71d04bb283c747bc983d51ecd",
}


if __name__ == "__main__":
    raise SystemExit(builder.main())
