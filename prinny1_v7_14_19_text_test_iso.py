#!/usr/bin/env python3
from pathlib import Path
import prinny1_v7_14_17_text_test_iso as builder
ROOT=Path(__file__).resolve().parent;builder.VERSION="v7_14_19";builder.EXPECTED_WRITE_COUNT=125;builder.RESOURCE_REVIEW_READY_STATUS="pass_test_iso_build_ready_automatic_approval";builder.AUTHORIZATION="user_automatic_test_iso_approval_active_since_2026_08_01"
builder.RESOURCE_DIR=ROOT/"workspace/build/prinny1_v7_14_19_text_resources";builder.RESOURCE_REPORT=ROOT/"workspace/reports/prinny1_v7_14_19_text_resource_build/all_report.json";builder.RESOURCE_REVIEW=ROOT/"workspace/reports/prinny1_v7_14_19_text_resource_build_review/all_report.json";builder.SEALED=ROOT/"workspace/reports/prinny1_v7_14_19_text_resource_build/sealed_expected_writes.csv";builder.OUTPUT_DIR=ROOT/"workspace/build/prinny1_v7_14_19_text_test_iso";builder.OUTPUT_ISO=builder.OUTPUT_DIR/"prinny_korean_v7_14_19_text_test.iso";builder.REPORT_DIR=ROOT/"workspace/reports/prinny1_v7_14_19_text_test_iso"
if __name__=="__main__":raise SystemExit(builder.main())
