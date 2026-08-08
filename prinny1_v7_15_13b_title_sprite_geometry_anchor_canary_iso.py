#!/usr/bin/env python3
"""Build the top-left anchored 프 enlargement canary ISO."""
from pathlib import Path

import prinny1_v7_15_13_title_sprite_geometry_canary_iso as builder


ROOT = Path(__file__).resolve().parent
builder.SYSTEM = ROOT / "workspace/build/prinny1_v7_15_13b_title_sprite_geometry_anchor_canary_resources/SYSTEM.DAT"
builder.REVIEW = ROOT / "workspace/reports/prinny1_v7_15_13b_title_sprite_geometry_anchor_canary_review/all_report.json"
builder.OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_13b_title_sprite_geometry_anchor_canary"
builder.OUTPUT_ISO = builder.OUTPUT_DIR / "prinny_korean_v7_15_13b_title_sprite_geometry_anchor_canary.iso"
builder.REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_13b_title_sprite_geometry_anchor_canary_iso"
builder.EXPECTED = {
    builder.BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    builder.SYSTEM: "2aeb10e6c5dd474d0e0eddad79ce46424446f31bc19a196341a7b352d4bde6ef",
    builder.REVIEW: "d9f65f394867d4ba95d9504aebaef9d741accfeebfb626fd8d5f36bc48377834",
}


if __name__ == "__main__":
    raise SystemExit(builder.main())
