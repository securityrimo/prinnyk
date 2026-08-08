#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import prinny1_v7_14_17_text_test_iso_review as review

ROOT=Path(__file__).resolve().parent
review.VERSION="v7_14_18";review.EXPECTED_WRITE_COUNT=71
review.ISO=ROOT/"workspace/build/prinny1_v7_14_18_text_test_iso/prinny_korean_v7_14_18_text_test.iso"
review.BUILD_REPORT=ROOT/"workspace/reports/prinny1_v7_14_18_text_test_iso/all_report.json"
review.SEALED=ROOT/"workspace/reports/prinny1_v7_14_18_text_resource_build/sealed_expected_writes.csv"
review.RESOURCE_REVIEW=ROOT/"workspace/reports/prinny1_v7_14_18_text_resource_build_review/all_report.json"
review.OUTPUT=ROOT/"workspace/reports/prinny1_v7_14_18_text_test_iso_review"

if __name__=="__main__":raise SystemExit(review.main())
