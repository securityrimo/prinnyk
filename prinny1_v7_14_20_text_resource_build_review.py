#!/usr/bin/env python3
from pathlib import Path
import prinny1_v7_14_18_text_resource_build_review as review
ROOT=Path(__file__).resolve().parent;review.VERSION="v7_14_20";review.EXPECTED_WRITE_COUNT=145
review.BUILD=ROOT/"workspace/build/prinny1_v7_14_20_text_resources";review.REPORT=ROOT/"workspace/reports/prinny1_v7_14_20_text_resource_build/all_report.json";review.SEALED=ROOT/"workspace/reports/prinny1_v7_14_20_text_resource_build/sealed_expected_writes.csv";review.OUTPUT=ROOT/"workspace/reports/prinny1_v7_14_20_text_resource_build_review"
if __name__=="__main__":raise SystemExit(review.main())
