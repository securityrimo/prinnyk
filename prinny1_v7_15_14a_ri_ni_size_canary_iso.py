#!/usr/bin/env python3
"""Build the size-only runtime measurement canary ISO for 리 and 니."""
from pathlib import Path

import prinny1_v7_15_13_title_sprite_geometry_canary_iso as builder


ROOT = Path(__file__).resolve().parent
builder.SYSTEM = ROOT / "workspace/build/prinny1_v7_15_14a_ri_ni_size_canary_resources/SYSTEM.DAT"
builder.REVIEW = ROOT / "workspace/reports/prinny1_v7_15_14a_ri_ni_size_canary_review/all_report.json"
builder.OUTPUT_DIR = ROOT / "workspace/build/prinny1_v7_15_14a_ri_ni_size_canary"
builder.OUTPUT_ISO = builder.OUTPUT_DIR / "prinny_korean_v7_15_14a_ri_ni_size_canary.iso"
builder.REPORT_DIR = ROOT / "workspace/reports/prinny1_v7_15_14a_ri_ni_size_canary_iso"
builder.EXPECTED = {
    builder.BASE_ISO: "32ecd6dfc93c2d9a198e11b9625b99a9af9cf25bf1e41662c8eba8dbf08835a4",
    builder.SYSTEM: "8e1d2f04a742065b2877334700b33513b4d07730f1c83fbd735c3f2dc43ce4f3",
    builder.REVIEW: "f24c4ba8df5880757ccd48e6ae0cde936618179a63a8ab7b7a8075760fb2dc35",
}


if __name__ == "__main__":
    raise SystemExit(builder.main())
