#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.font_builder as font_builder

DEFAULT_FIXES = ROOT / "profiles/prinny/stage1_hotfixes.json"
DEFAULT_MASTER = ROOT / "workspace/translations/export/translation_master.csv"
DEFAULT_ALLOCATION = ROOT / "workspace/font/audited_allocation_977/hangul_allocation.json"
DEFAULT_START = ROOT / "workspace/build/final_system_csv_revision_977_v4/start.dat"
DEFAULT_OUTPUT_DIR = ROOT / "workspace/build/prinny_stage1_hotfix_v6"
DEFAULT_PROGRESS = ROOT / "workspace/reports/prinny_stage1_fix/progress.json"


class Stage1HotfixError(RuntimeError):
    pass


@dataclass(frozen=True)
class Fix:
    identifier: str
    resource: str
    offset: int
    old_translation: str
    new_translation: str
    reason: str
    write_capacity: int | None = None


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON 파일 없음: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise Stage1HotfixError(f"JSON 최상위 값이 객체가 아닙니다: {path}")
    return value


def load_fixes(path: Path) -> tuple[list[Fix], dict[str, Any]]:
    doc = load_json(path)
    raw = doc.get("fixes")
    if not isinstance(raw, list) or not raw:
        raise Stage1HotfixError("수정 목록이 비어 있습니다.")

    fixes: list[Fix] = []
    seen: set[tuple[str, int]] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise Stage1HotfixError("잘못된 수정 항목")
        fix = Fix(
            identifier=str(item.get("id", "")).strip(),
            resource=str(item.get("resource", "")).strip(),
            offset=int(str(item.get("offset", "0")), 0),
            old_translation=str(item.get("old_translation", "")),
            new_translation=str(item.get("new_translation", "")),
            reason=str(item.get("reason", "")),
            write_capacity=(
                int(str(item["write_capacity"]), 0)
                if item.get("write_capacity") not in (None, "")
                else None
            ),
        )
        if not fix.identifier or not fix.resource or fix.offset < 0:
            raise Stage1HotfixError(f"필수 필드 누락: {item}")
        key = (fix.resource.casefold(), fix.offset)
        if key in seen:
            raise Stage1HotfixError(
                f"중복 수정 위치: {fix.resource} 0x{fix.offset:X}"
            )
        seen.add(key)
        fixes.append(fix)
    return fixes, doc


def load_master(path: Path) -> tuple[list[dict[str, str]], dict[str, dict[str, str]], list[str]]:
    if not path.is_file():
        raise FileNotFoundError(f"번역 마스터 없음: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    by_id = {str(row.get("id", "")).strip(): row for row in rows}
    return rows, by_id, fieldnames


def load_encoded_map(path: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    doc = load_json(path)
    allocations = doc.get("allocations")
    if not isinstance(allocations, list):
        raise Stage1HotfixError("배정표 allocations 누락")
    mapping: dict[str, bytes] = {}
    for item in allocations:
        if not isinstance(item, dict):
            continue
        character = str(item.get("hangul", ""))
        sjis = str(item.get("sjis", ""))
        if len(character) != 1 or not sjis:
            continue
        mapping[character] = bytes.fromhex(sjis)
    return mapping, doc


def encode_text(text: str, encoded_map: dict[str, bytes]) -> bytes:
    output = bytearray()
    for character in text:
        mapped = encoded_map.get(character)
        if mapped is not None:
            output.extend(mapped)
            continue
        try:
            output.extend(character.encode("shift_jis", errors="strict"))
        except UnicodeEncodeError as exc:
            raise Stage1HotfixError(
                f"배정표와 Shift-JIS에 없는 문자: {character!r} U+{ord(character):04X}"
            ) from exc
    return bytes(output)


def write_progress(path: Path, *, percent: int, stage: str, detail: str, status: str = "running") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "prinny_stage1_fix_progress_v1",
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "percent": max(0, min(100, int(percent))),
        "stage": stage,
        "detail": detail,
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def update_master_csv(
    master_path: Path,
    output_path: Path,
    fixes: list[Fix],
    encoded_map: dict[str, bytes],
) -> dict[str, Any]:
    rows, by_id, fieldnames = load_master(master_path)
    if not fieldnames:
        raise Stage1HotfixError("번역 마스터 헤더가 없습니다.")

    changes: list[dict[str, Any]] = []
    for fix in fixes:
        row = by_id.get(fix.identifier)
        if row is None:
            raise Stage1HotfixError(f"번역 마스터 ID 없음: {fix.identifier}")
        capacity = int(str(row.get("translation_capacity_bytes", "0") or "0"), 0)
        encoded = encode_text(fix.new_translation, encoded_map)
        if len(encoded) > capacity:
            raise Stage1HotfixError(
                f"용량 초과: {fix.identifier} {len(encoded)} > {capacity}"
            )
        before = str(row.get("translation", ""))
        if before not in {fix.old_translation, fix.new_translation}:
            raise Stage1HotfixError(
                f"번역 마스터 예상값 불일치: {fix.identifier}\n"
                f"expected={fix.old_translation!r}\nactual={before!r}"
            )
        row["translation"] = fix.new_translation
        row["status"] = "translated"
        note = str(row.get("notes", "")).strip()
        marker = "stage1-screenshot-hotfix-v1"
        if marker not in note:
            row["notes"] = (note + ("; " if note else "") + marker).strip()
        changes.append(
            {
                "id": fix.identifier,
                "before": before,
                "after": fix.new_translation,
                "encoded_length": len(encoded),
                "capacity": capacity,
                "reason": fix.reason,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    return {
        "source": str(master_path),
        "output": str(output_path),
        "source_sha1": sha1_file(master_path),
        "output_sha1": sha1_file(output_path),
        "change_count": len(changes),
        "changes": changes,
    }


def classify_region(
    region: bytes,
    *,
    candidates: list[tuple[str, bytes]],
) -> tuple[str, bytes] | None:
    for name, candidate in candidates:
        if len(candidate) <= len(region) and region[: len(candidate)] == candidate:
            tail = region[len(candidate) :]
            if not tail or all(value == 0 for value in tail):
                return name, candidate
    return None


def apply_start_hotfixes(
    *,
    start_path: Path,
    output_path: Path,
    master_path: Path,
    fixes: list[Fix],
    encoded_map: dict[str, bytes],
) -> dict[str, Any]:
    if not start_path.is_file():
        raise FileNotFoundError(f"START 입력 없음: {start_path}")

    _, by_id, _ = load_master(master_path)
    original = start_path.read_bytes()
    records = font_builder.parse_start_records(original)
    record_map = {str(record["name"]).casefold(): record for record in records}
    replacements: dict[str, bytes] = {}
    results: list[dict[str, Any]] = []

    grouped: dict[str, list[Fix]] = {}
    for fix in fixes:
        grouped.setdefault(fix.resource.casefold(), []).append(fix)

    for resource_key, resource_fixes in grouped.items():
        record = record_map.get(resource_key)
        if record is None:
            raise Stage1HotfixError(f"START 리소스 없음: {resource_key}")
        resource = bytearray(font_builder.resource_blob(original, record))

        for fix in sorted(resource_fixes, key=lambda item: item.offset):
            row = by_id.get(fix.identifier)
            if row is None:
                raise Stage1HotfixError(f"번역 마스터 ID 없음: {fix.identifier}")
            row_resource = str(row.get("first_resource", "")).casefold()
            row_offset = int(str(row.get("first_offset_hex", "0")), 0)
            if row_resource != resource_key or row_offset != fix.offset:
                raise Stage1HotfixError(
                    f"수정 위치와 번역 마스터 불일치: {fix.identifier}"
                )
            capacity = int(str(row.get("translation_capacity_bytes", "0") or "0"), 0)
            write_capacity = fix.write_capacity or capacity
            if (
                capacity <= 0
                or write_capacity < capacity
                or fix.offset + write_capacity > len(resource)
            ):
                raise Stage1HotfixError(
                    f"수정 범위 오류: {fix.resource} 0x{fix.offset:X} "
                    f"logical={capacity} write={write_capacity}"
                )

            old_bytes = encode_text(fix.old_translation, encoded_map)
            new_bytes = encode_text(fix.new_translation, encoded_map)
            source_bytes = str(row.get("source_display", "")).encode("shift_jis", errors="strict")
            csv_bytes = encode_text(str(row.get("translation", "")), encoded_map)
            if len(new_bytes) > capacity:
                raise Stage1HotfixError(
                    f"수정 문자열 용량 초과: {fix.identifier} {len(new_bytes)} > {capacity}"
                )

            region = bytes(resource[fix.offset : fix.offset + write_capacity])
            state = classify_region(
                region,
                candidates=[
                    ("already_hotfixed", new_bytes),
                    ("old_translation", old_bytes),
                    ("csv_translation", csv_bytes),
                    ("original_japanese", source_bytes),
                ],
            )
            if state is None:
                raise Stage1HotfixError(
                    f"예상하지 못한 START 바이트: {fix.identifier} {fix.resource} 0x{fix.offset:X}\n"
                    f"actual={region.hex(' ').upper()}\n"
                    f"old={old_bytes.hex(' ').upper()}\n"
                    f"new={new_bytes.hex(' ').upper()}\n"
                    f"source={source_bytes.hex(' ').upper()}"
                )

            detected, _ = state
            payload = new_bytes + b"\x00" * (write_capacity - len(new_bytes))
            resource[fix.offset : fix.offset + write_capacity] = payload
            results.append(
                {
                    "id": fix.identifier,
                    "resource": fix.resource,
                    "offset": fix.offset,
                    "offset_hex": f"0x{fix.offset:X}",
                    "capacity": capacity,
                    "write_capacity": write_capacity,
                    "detected_input": detected,
                    "old_translation": fix.old_translation,
                    "new_translation": fix.new_translation,
                    "new_encoded_length": len(new_bytes),
                    "payload_sha1": sha1_bytes(payload),
                    "reason": fix.reason,
                }
            )

        replacements[str(record["name"]).casefold()] = bytes(resource)

    rebuilt = font_builder.rebuild_start_archive(original, records, replacements)
    if len(rebuilt) != len(original):
        raise Stage1HotfixError(
            f"START 크기 변경: {len(original)} -> {len(rebuilt)}"
        )

    rebuilt_records = font_builder.parse_start_records(rebuilt)
    rebuilt_map = {str(record["name"]).casefold(): record for record in rebuilt_records}
    changed_resources: list[str] = []
    for record in records:
        key = str(record["name"]).casefold()
        after_record = rebuilt_map.get(key)
        if after_record is None:
            raise Stage1HotfixError(f"재구성 후 리소스 누락: {key}")
        before = font_builder.resource_blob(original, record)
        after = font_builder.resource_blob(rebuilt, after_record)
        if before != after:
            changed_resources.append(str(record["name"]))

    expected_changed = sorted({
        str(item["resource"]).casefold()
        for item in results
        if item.get("detected_input") != "already_hotfixed"
    })
    actual_changed = sorted(name.casefold() for name in changed_resources)
    if actual_changed != expected_changed:
        raise Stage1HotfixError(
            f"예상 외 리소스 변경: expected={expected_changed}, actual={actual_changed}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(rebuilt)
    return {
        "input": str(start_path),
        "output": str(output_path),
        "input_size": len(original),
        "output_size": len(rebuilt),
        "input_sha1": sha1_bytes(original),
        "output_sha1": sha1_bytes(rebuilt),
        "changed_resources": changed_resources,
        "fix_count": len(results),
        "fixes": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="프리니 1 스테이지 1 대사 핫픽스")
    parser.add_argument("--start", type=Path, default=DEFAULT_START)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--allocation", type=Path, default=DEFAULT_ALLOCATION)
    parser.add_argument("--fixes", type=Path, default=DEFAULT_FIXES)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--update-master", action="store_true")
    parser.add_argument("--master-output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "stage1_hotfix_report.json"
    output_start = args.output_dir / "start.dat"

    try:
        write_progress(args.progress, percent=2, stage="준비", detail="수정 목록과 한글 배정표 확인")
        fixes, fix_doc = load_fixes(args.fixes)
        encoded_map, allocation = load_encoded_map(args.allocation)

        write_progress(args.progress, percent=15, stage="번역 검증", detail=f"{len(fixes)}개 수정문의 바이트 용량 검사")
        master_output = args.master_output or (args.output_dir / "translation_master.stage1_hotfix.csv")
        master_result = update_master_csv(args.master, master_output, fixes, encoded_map)

        write_progress(args.progress, percent=45, stage="START 수정", detail=f"{len(fixes)}개 대사를 실제 리소스에 적용")
        start_result = apply_start_hotfixes(
            start_path=args.start,
            output_path=output_start,
            master_path=args.master,
            fixes=fixes,
            encoded_map=encoded_map,
        )

        if args.update_master:
            backup = args.master.with_name(
                args.master.name + ".before_stage1_hotfix_" + datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            shutil.copy2(args.master, backup)
            shutil.copy2(master_output, args.master)
            master_result["installed_to"] = str(args.master)
            master_result["backup"] = str(backup)

        report = {
            "format": "prinny_stage1_hotfix_report_v1",
            "status": "pass",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "fix_document": str(args.fixes),
            "fix_document_sha1": sha1_file(args.fixes),
            "allocation": str(args.allocation),
            "allocation_sha1": sha1_file(args.allocation),
            "allocation_character_count": len(encoded_map),
            "master": master_result,
            "start": start_result,
            "unresolved_ui_groups": fix_doc.get("unresolved_ui_groups", []),
            "errors": [],
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_progress(args.progress, percent=100, stage="대사 핫픽스 완료", detail=str(output_start), status="complete")
        print(f"PASS: {len(fixes)}개 대사 수정")
        print(f"START : {output_start}")
        print(f"MASTER: {master_output}")
        print(f"REPORT: {report_path}")
        return 0
    except Exception as exc:
        write_progress(args.progress, percent=100, stage="대사 핫픽스 실패", detail=str(exc), status="error")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "format": "prinny_stage1_hotfix_report_v1",
                    "status": "error",
                    "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
