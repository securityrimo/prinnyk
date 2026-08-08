#!/usr/bin/env python3
from pathlib import Path
import prinny1_v7_14_19_candidate_glyph_review as review
ROOT=Path(__file__).resolve().parent;review.VERSION="v7_14_20";review.EXPECTED_WRITE_COUNT=145;review.SLOT_COUNT=62
review.PLAN_DIR=ROOT/"workspace/reports/prinny1_v7_14_20_mixed_renderer_plan";review.PLAN=review.PLAN_DIR/"all_report.json";review.WRITES=review.PLAN_DIR/"expected_write_confirmed.csv";review.SLOTS=review.PLAN_DIR/"candidate_glyph_slots.csv";review.OUTPUT=ROOT/"workspace/reports/prinny1_v7_14_20_mixed_renderer_review"
if __name__=="__main__":raise SystemExit(review.main())
