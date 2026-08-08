#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.start_runtime import StartRuntimeArchive


ROOT = Path(__file__).resolve().parent
SOURCE_START = (
    ROOT / "workspace/build/prinny1_v7_14_9_prologue_full_punctuation/start.dat"
)
RETAINED_PLAN = (
    ROOT / "workspace/reports/prinny1_v7_14_12_screenshot_alignment_plan"
    / "expected_write_confirmed.csv"
)
REJECTED_PLAN = (
    ROOT / "workspace/reports/prinny1_v7_14_11_speaker_ligature_plan"
    / "expected_write_confirmed.csv"
)
BROKEN_MANIFEST = (
    ROOT / "workspace/reports/prinny1_v7_14_13_sealed_patch_manifest"
    / "sealed_expected_writes.csv"
)
TITLE_CAPTURE = (
    ROOT / "workspace/reports/prinny1_v7_14_14_title_difficulty_runtime"
    / "title_current.png"
)
DIFFICULTY_CAPTURE = (
    ROOT / "workspace/reports/prinny1_v7_14_14_title_difficulty_runtime"
    / "difficulty_current.png"
)
GOOD_TITLE_REFERENCE = (
    ROOT / "workspace/reports/prinny1_v7_14_6_v64_title_ready.png"
)
REPORT_DIR = (
    ROOT / "workspace/reports/prinny1_v7_14_14_font_regression_repair_plan"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"빈 CSV입니다: {path}")
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def identity(row: dict[str, str]) -> tuple[str, int, str, str]:
    return (
        row["target"].casefold(),
        int(row["offset_hex"], 0),
        row["expected_before_hex"].upper(),
        row["write_after_hex"].upper(),
    )


def main() -> int:
    required = (
        SOURCE_START,
        RETAINED_PLAN,
        REJECTED_PLAN,
        BROKEN_MANIFEST,
        TITLE_CAPTURE,
        DIFFICULTY_CAPTURE,
        GOOD_TITLE_REFERENCE,
    )
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)

    retained = read_csv(RETAINED_PLAN)
    rejected = read_csv(REJECTED_PLAN)
    broken = read_csv(BROKEN_MANIFEST)
    retained_ids = {identity(row) for row in retained}
    rejected_ids = {identity(row) for row in rejected}
    broken_ids = {identity(row) for row in broken}

    if len(retained) != 40 or len(rejected) != 28 or len(broken) != 68:
        raise ValueError("V7.14.11~13 Expected Write 개수가 예상과 다릅니다.")
    if retained_ids & rejected_ids:
        raise ValueError("유지/폐기 Expected Write가 겹칩니다.")
    if retained_ids | rejected_ids != broken_ids:
        raise ValueError("V7.14.13이 유지 40개와 폐기 28개의 합이 아닙니다.")
    if {row["target"] for row in rejected} != {"font.txp", "Demo00.dat"}:
        raise ValueError("폐기 계획의 자원 집합이 예상과 다릅니다.")
    font_rows = [row for row in rejected if row["target"] == "font.txp"]
    if len(font_rows) != 1 or font_rows[0]["offset_hex"].upper() != "0XEEC0":
        raise ValueError("문제 font.txp 쓰기를 유일하게 식별하지 못했습니다.")

    source = SOURCE_START.read_bytes()
    archive = StartRuntimeArchive.from_bytes(source, source=str(SOURCE_START))
    records = {record.output_name.casefold(): record for record in archive.records}
    simulated = bytearray(source)
    changed_offsets: set[int] = set()
    sealed_rows: list[dict[str, Any]] = []

    for sequence, row in enumerate(
        sorted(retained, key=lambda item: (item["target"].casefold(), int(item["offset_hex"], 0))),
        start=1,
    ):
        record = records.get(row["target"].casefold())
        if record is None:
            raise ValueError(f"START 레코드가 없습니다: {row['target']}")
        offset = int(row["offset_hex"], 0)
        before = bytes.fromhex(row["expected_before_hex"])
        after = bytes.fromhex(row["write_after_hex"])
        if not before or len(before) != len(after):
            raise ValueError(f"Expected Write 길이 오류: {row['logical_id']}")
        start = record.data_offset + offset
        end = start + len(before)
        if end > record.end_offset or source[start:end] != before:
            raise ValueError(f"before/경계 검증 실패: {row['logical_id']}")
        simulated[start:end] = after
        changed_offsets.update(
            start + index
            for index, (old, new) in enumerate(zip(before, after))
            if old != new
        )
        sealed_rows.append({
            "sequence": sequence,
            "source_plan": RETAINED_PLAN.parent.name,
            "group_id": row.get("group_id", ""),
            "logical_id": row.get("logical_id", ""),
            "target": row["target"],
            "offset_hex": row["offset_hex"],
            "expected_before_hex": row["expected_before_hex"],
            "write_after_hex": row["write_after_hex"],
            "write_length": len(after),
            "change_kind": row.get("change_kind", ""),
            "wording_changed": row.get("wording_changed", "no"),
            "user_wording_approval": row.get(
                "user_wording_approval", "not_required_mechanical_only"
            ),
            "expected_write_confirmed": row.get("expected_write_confirmed", ""),
        })

    actual_changed = {
        index for index, (old, new) in enumerate(zip(source, simulated)) if old != new
    }
    if actual_changed != changed_offsets or len(simulated) != len(source):
        raise ValueError("시뮬레이션 변경 범위 또는 크기가 선언과 다릅니다.")
    if {row["target"] for row in sealed_rows} != {"Demo00.dat", "StageInfo00.dat"}:
        raise ValueError("복구안에 예상 밖 자원이 포함됐습니다.")
    if any(row["wording_changed"].casefold() != "no" for row in sealed_rows):
        raise ValueError("복구안에 번역 문구 변경이 포함됐습니다.")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for name in (
        "sealed_expected_writes.csv",
        "confirmed_patch_plan.csv",
        "expected_write_confirmed.csv",
    ):
        write_csv(REPORT_DIR / name, sealed_rows)

    report = {
        "format": "prinny1_v7_14_14_font_regression_repair_plan_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "path": str(SOURCE_START),
            "size": len(source),
            "sha256": sha256(source),
        },
        "runtime_evidence": {
            "title_capture": {"path": str(TITLE_CAPTURE), "sha256": sha256_file(TITLE_CAPTURE)},
            "difficulty_capture": {
                "path": str(DIFFICULTY_CAPTURE),
                "sha256": sha256_file(DIFFICULTY_CAPTURE),
            },
            "good_title_reference": {
                "path": str(GOOD_TITLE_REFERENCE),
                "sha256": sha256_file(GOOD_TITLE_REFERENCE),
            },
            "observed": [
                "title_logo_texture_corruption",
                "difficulty_glyph_overlap_and_scanline_corruption",
            ],
        },
        "regression": {
            "introduced_by": "prinny1_v7_14_11_speaker_ligature_plan",
            "rejected_write_count": len(rejected),
            "rejected_resources": sorted({row["target"] for row in rejected}),
            "font_write": "font.txp+0xEEC0 length 140",
            "reason": "runtime_proves_contiguous_write_is_not_isolated_to_one_visible_glyph",
        },
        "repair": {
            "retained_write_count": len(sealed_rows),
            "changed_byte_count": len(actual_changed),
            "changed_resources": sorted({row["target"] for row in sealed_rows}),
            "font_txp_changed": False,
            "simulated_start_sha256": sha256(bytes(simulated)),
            "translation_wording_changed": False,
        },
        "checks": {
            "v7_14_13_partitioned_exactly_40_plus_28": True,
            "rejected_ranges_absent": True,
            "fresh_before_bytes_match": True,
            "record_boundaries_valid": True,
            "actual_changes_equal_declared_changes": True,
            "source_size_preserved": True,
            "source_file_unchanged": sha256_file(SOURCE_START) == sha256(source),
            "iso_created": False,
        },
        "status": "repair_manifest_sealed_iso_build_approval_required",
    }
    (REPORT_DIR / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"폐기 Expected Writes: {len(rejected)}")
    print(f"유지 Expected Writes: {len(sealed_rows)}")
    print(f"변경 자원: {', '.join(report['repair']['changed_resources'])}")
    print(f"예상 START SHA-256: {report['repair']['simulated_start_sha256']}")
    print("ISO 생성: 없음")
    print(f"보고서: {REPORT_DIR / 'all_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
