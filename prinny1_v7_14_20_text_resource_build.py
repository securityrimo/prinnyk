#!/usr/bin/env python3
from pathlib import Path
import prinny1_v7_14_18_text_resource_build as build
ROOT=Path(__file__).resolve().parent;build.VERSION="v7_14_20";build.EXPECTED_WRITE_COUNT=145
build.PLAN=ROOT/"workspace/reports/prinny1_v7_14_20_mixed_renderer_plan/all_report.json";build.REVIEW=ROOT/"workspace/reports/prinny1_v7_14_20_mixed_renderer_review/all_report.json";build.WRITES=ROOT/"workspace/reports/prinny1_v7_14_20_mixed_renderer_plan/expected_write_confirmed.csv";build.OUTPUT=ROOT/"workspace/build/prinny1_v7_14_20_text_resources";build.REPORT_DIR=ROOT/"workspace/reports/prinny1_v7_14_20_text_resource_build"
if __name__=="__main__":raise SystemExit(build.main())
