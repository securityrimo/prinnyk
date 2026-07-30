#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_galmuri14_v5 as v5
import core.font_builder as font_builder

LOCAL_REPORT_DIR = ROOT / "workspace/reports/prinny_stage1_fix"
LOCAL_PROGRESS = LOCAL_REPORT_DIR / "progress.json"
LOCAL_STATUS = LOCAL_REPORT_DIR / "status.json"
DEFAULT_PLAN = ROOT / "profiles/prinny/stage1_structural_repairs.json"
DEFAULT_MASTER = ROOT / "workspace/translations/export/translation_master.csv"
DEFAULT_ALLOCATION = ROOT / "workspace/font/audited_allocation_977/hangul_allocation.json"


class BuildError(RuntimeError):
    pass


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def progress(percent: int, stage: str, detail: str, *, status: str = "running", external: Path | None = None) -> None:
    payload = {
        "format": "prinny_stage1_v6_3_progress_v1",
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "percent": max(0, min(100, int(percent))),
        "stage": stage,
        "detail": detail,
        "pid": os.getpid(),
    }
    atomic_json(LOCAL_PROGRESS, payload)
    if external is not None:
        atomic_json(external / "reports/prinny_stage1_fix/progress.json", payload)


def status_file(value: dict[str, Any], external: Path | None = None) -> None:
    atomic_json(LOCAL_STATUS, value)
    if external is not None:
        atomic_json(external / "reports/prinny_stage1_fix/status.json", value)


def find_work_root(explicit: Path | None) -> Path:
    if explicit is not None:
        root = explicit.expanduser().resolve()
        if root.name != "PSP_Localization_Work":
            root = root / "PSP_Localization_Work"
        root.mkdir(parents=True, exist_ok=True)
        return root

    config = ROOT / "workspace/config/psp_storage_root.txt"
    if config.is_file():
        raw = config.read_text(encoding="utf-8", errors="replace").strip()
        if raw:
            base = Path(raw).expanduser()
            candidate = base if base.name == "PSP_Localization_Work" else base / "PSP_Localization_Work"
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate.resolve()
            except OSError:
                pass

    media = Path("/media") / os.environ.get("USER", "")
    if media.is_dir():
        candidates: list[tuple[int, Path]] = []
        for mount in media.iterdir():
            if not mount.is_dir() or not os.access(mount, os.W_OK):
                continue
            try:
                free = shutil.disk_usage(mount).free
            except OSError:
                continue
            candidates.append((free, mount))
        if candidates:
            _, mount = max(candidates)
            root = mount / "PSP_Localization_Work"
            root.mkdir(parents=True, exist_ok=True)
            return root.resolve()

    fallback = ROOT / "workspace/external_fallback/PSP_Localization_Work"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback.resolve()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON 파일 없음: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise BuildError(f"JSON 최상위 값이 객체가 아닙니다: {path}")
    return value


def load_master(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"번역 마스터 없음: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("id", "")).strip(): dict(row)
            for row in csv.DictReader(handle)
            if str(row.get("id", "")).strip()
        }


def load_encoded_map(path: Path) -> tuple[dict[str, bytes], dict[int, str]]:
    doc = load_json(path)
    mapping: dict[str, bytes] = {}
    reverse: dict[int, str] = {}
    for item in doc.get("allocations", []):
        if not isinstance(item, dict):
            continue
        char = str(item.get("hangul", ""))
        sjis = str(item.get("sjis", ""))
        if len(char) == 1 and sjis:
            raw = bytes.fromhex(sjis)
            mapping[char] = raw
            reverse[int.from_bytes(raw, "big")] = char
    if len(mapping) < 900:
        raise BuildError(f"한글 배정표가 비정상적으로 작습니다: {len(mapping)}")
    return mapping, reverse


def encode_text(text: str, mapping: dict[str, bytes]) -> bytes:
    out = bytearray()
    for character in text:
        if character in mapping:
            out.extend(mapping[character])
        else:
            try:
                out.extend(character.encode("shift_jis", errors="strict"))
            except UnicodeEncodeError as exc:
                raise BuildError(f"인코딩 불가 문자: {character!r} U+{ord(character):04X}") from exc
    return bytes(out)


def decode_text(data: bytes, reverse: dict[int, str]) -> str:
    out: list[str] = []
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0:
            break
        if i + 1 < len(data):
            value = (b << 8) | data[i + 1]
            if value in reverse:
                out.append(reverse[value])
                i += 2
                continue
            if 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xFC:
                try:
                    out.append(data[i : i + 2].decode("shift_jis"))
                except UnicodeDecodeError:
                    out.append(f"<{b:02X}{data[i+1]:02X}>")
                i += 2
                continue
        if 0x20 <= b <= 0x7E:
            out.append(chr(b))
        else:
            out.append(f"<{b:02X}>")
        i += 1
    return "".join(out)


def choose_input_start(work_root: Path, explicit: Path | None) -> Path:
    candidates = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    candidates.extend(
        [
            work_root / "build/prinny_stage1_hotfix_v6_2/system/start.dat",
            work_root / "build/prinny_stage1_hotfix_v6_2/text_hotfix/start.dat",
            ROOT / "workspace/build/final_system_galmuri14_977_v5/start.dat",
            ROOT / "workspace/build/final_system_csv_revision_977_v4/start.dat",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "V6.2/V5/V4 START를 찾지 못했습니다. 예상 위치:\n"
        + "\n".join(str(path) for path in candidates)
    )


def verify_master_matches_plan(master: dict[str, dict[str, str]], plan: dict[str, Any]) -> None:
    errors: list[str] = []
    for patch in plan.get("patches", []):
        translations = patch.get("translations", {})
        if not isinstance(translations, dict):
            continue
        for identifier, expected in translations.items():
            row = master.get(str(identifier))
            if row is None:
                errors.append(f"ID 없음: {identifier}")
                continue
            actual = str(row.get("translation", ""))
            if actual != str(expected):
                errors.append(f"{identifier}: master={actual!r}, plan={expected!r}")
    if errors:
        raise BuildError(
            "역자 번역문과 구조 복구 계획이 다릅니다. 문구를 임의 변경하지 않기 위해 중단합니다:\n"
            + "\n".join(errors[:30])
        )


def apply_structural_repairs(
    *,
    input_start: Path,
    output_start: Path,
    plan: dict[str, Any],
    reverse_map: dict[int, str],
) -> dict[str, Any]:
    original = input_start.read_bytes()
    records = font_builder.parse_start_records(original)
    record_map = {str(record["name"]).casefold(): record for record in records}
    replacements: dict[str, bytes] = {}
    results: list[dict[str, Any]] = []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for patch in plan.get("patches", []):
        if not isinstance(patch, dict):
            continue
        grouped.setdefault(str(patch["resource"]).casefold(), []).append(patch)

    for resource_key, patches in grouped.items():
        record = record_map.get(resource_key)
        if record is None:
            raise BuildError(f"START 리소스 없음: {resource_key}")
        resource = bytearray(font_builder.resource_blob(original, record))
        occupied: list[tuple[int, int]] = []

        for patch in sorted(patches, key=lambda item: int(str(item["offset"]), 0)):
            offset = int(str(patch["offset"]), 0)
            span = int(patch["span"])
            payload = bytes.fromhex(str(patch["payload_hex"]))
            if len(payload) != span:
                raise BuildError(f"계획 길이 오류: {patch.get('logical_ids')} {len(payload)} != {span}")
            end = offset + span
            if offset < 0 or end > len(resource):
                raise BuildError(f"패치 범위 초과: {resource_key} 0x{offset:X}+{span}")
            if any(offset < old_end and end > old_start for old_start, old_end in occupied):
                raise BuildError(f"패치 범위 중첩: {resource_key} 0x{offset:X}")
            occupied.append((offset, end))

            before = bytes(resource[offset:end])
            changed = before != payload
            resource[offset:end] = payload

            logical_ids = [str(value) for value in patch.get("logical_ids", [])]
            translations = patch.get("translations", {})
            decoded_fragments: dict[str, str] = {}
            if str(patch.get("kind")) == "ordinary" and logical_ids:
                decoded_fragments[logical_ids[0]] = decode_text(payload, reverse_map)
                expected = str(translations.get(logical_ids[0], ""))
                if decoded_fragments[logical_ids[0]] != expected:
                    raise BuildError(
                        f"복구 바이트 디코딩 불일치: {logical_ids[0]}\n"
                        f"decoded={decoded_fragments[logical_ids[0]]!r}\nexpected={expected!r}"
                    )

            results.append(
                {
                    "resource": str(patch["resource"]),
                    "offset": offset,
                    "offset_hex": f"0x{offset:X}",
                    "span": span,
                    "kind": patch.get("kind"),
                    "logical_ids": logical_ids,
                    "translations": translations,
                    "changed": changed,
                    "before_sha1": sha1_bytes(before),
                    "after_sha1": sha1_bytes(payload),
                    "before_hex": before.hex(" ").upper(),
                    "after_hex": payload.hex(" ").upper(),
                    "decoded": decoded_fragments,
                    "source_plan": patch.get("source"),
                }
            )

        replacements[resource_key] = bytes(resource)

    rebuilt = font_builder.rebuild_start_archive(original, records, replacements)
    if len(rebuilt) != len(original):
        raise BuildError(f"START 크기 변경: {len(original)} -> {len(rebuilt)}")

    rebuilt_records = font_builder.parse_start_records(rebuilt)
    rebuilt_map = {str(record["name"]).casefold(): record for record in rebuilt_records}
    changed_resources = []
    for record in records:
        key = str(record["name"]).casefold()
        after_record = rebuilt_map[key]
        before_blob = font_builder.resource_blob(original, record)
        after_blob = font_builder.resource_blob(rebuilt, after_record)
        if before_blob != after_blob:
            changed_resources.append(str(record["name"]))

    expected_resources = sorted(grouped)
    actual_resources = sorted(name.casefold() for name in changed_resources)
    changed_patch_count = sum(1 for result in results if result["changed"])
    if changed_patch_count and actual_resources != expected_resources:
        raise BuildError(f"예상 외 리소스 변경: expected={expected_resources}, actual={actual_resources}")
    if not changed_patch_count and actual_resources:
        raise BuildError(f"패치가 동일한데 리소스가 변경됨: {actual_resources}")

    output_start.parent.mkdir(parents=True, exist_ok=True)
    output_start.write_bytes(rebuilt)
    return {
        "input": str(input_start),
        "output": str(output_start),
        "input_size": len(original),
        "output_size": len(rebuilt),
        "input_sha1": sha1_bytes(original),
        "output_sha1": sha1_bytes(rebuilt),
        "physical_patch_count": len(results),
        "logical_string_count": sum(len(result["logical_ids"]) for result in results),
        "changed_patch_count": changed_patch_count,
        "unchanged_patch_count": len(results) - changed_patch_count,
        "changed_resources": changed_resources,
        "patches": results,
    }


def safe_cleanup(work_root: Path) -> dict[str, Any]:
    removed: list[dict[str, Any]] = []
    for target in [
        ROOT / "workspace/strings",
        ROOT / "workspace/translations/recovered",
        ROOT / "workspace/psp_toolkit/game1",
        ROOT / "workspace/psp_toolkit/game2",
        work_root / "tmp",
    ]:
        if not target.exists():
            continue
        size = 0
        if target.is_dir():
            for path in target.rglob("*"):
                try:
                    if path.is_file():
                        size += path.stat().st_size
                except OSError:
                    pass
            shutil.rmtree(target)
        else:
            size = target.stat().st_size
            target.unlink()
        removed.append({"path": str(target), "bytes": size})

    cache_bytes = 0
    for cache in ROOT.rglob("__pycache__"):
        try:
            for path in cache.rglob("*"):
                if path.is_file():
                    cache_bytes += path.stat().st_size
            shutil.rmtree(cache)
        except OSError:
            pass
    return {
        "removed": removed,
        "cache_bytes": cache_bytes,
        "freed_bytes": sum(item["bytes"] for item in removed) + cache_bytes,
    }


def configure_outputs(work_root: Path) -> dict[str, Path]:
    build_dir = work_root / "build/prinny_stage1_structural_repair_v6_3"
    system_dir = build_dir / "system"
    report_dir = work_root / "reports/prinny_stage1_fix"
    build_dir.mkdir(parents=True, exist_ok=True)
    system_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    v5.OUTPUT_DIR = system_dir
    v5.OUTPUT_START = system_dir / "start.dat"
    v5.OUTPUT_LZS = system_dir / "start.lzs"
    v5.OUTPUT_SYSTEM = system_dir / "SYSTEM.DAT"
    v5.OUTPUT_ISO = build_dir / "prinny_korean_stage1_structural_repair_v6_3_977.iso"
    v5.OUTPUT_REPORT = report_dir / "prinny_stage1_structural_repair_v6_3_build.json"
    return {
        "build_dir": build_dir,
        "system_dir": system_dir,
        "report_dir": report_dir,
        "start": v5.OUTPUT_START,
        "system": v5.OUTPUT_SYSTEM,
        "iso": v5.OUTPUT_ISO,
        "report": v5.OUTPUT_REPORT,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    work_root = find_work_root(args.work_root)
    outputs = configure_outputs(work_root)
    report_dir = outputs["report_dir"]

    progress(1, "시작", f"작업 저장장치: {work_root}", external=work_root)
    status_file(
        {
            "format": "prinny_stage1_v6_3_status_v1",
            "status": "running",
            "pid": os.getpid(),
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "work_root": str(work_root),
        },
        work_root,
    )

    progress(4, "공간 정리", "재생성 가능한 임시 자료와 캐시 삭제", external=work_root)
    cleanup = safe_cleanup(work_root) if not args.no_cleanup else {"skipped": True}

    progress(8, "입력 확인", "V6.2 결과 START와 검증된 V4 ISO 계보 확인", external=work_root)
    input_start = choose_input_start(work_root, args.input_start)
    for required in [v5.V4_SYSTEM, v5.V4_ISO, v5.V4_ISO_REPORT, args.master, args.allocation, args.plan]:
        if not Path(required).is_file():
            raise FileNotFoundError(f"필수 파일 없음: {required}")

    plan = load_json(args.plan)
    master = load_master(args.master)
    _, reverse_map = load_encoded_map(args.allocation)

    progress(16, "번역 보존 검사", "14개 대사 문구가 역자 마스터와 완전히 같은지 확인", external=work_root)
    verify_master_matches_plan(master, plan)

    progress(30, "구조 복구", "14개 대사의 검증된 코드·종료바이트·패딩을 동일 위치에 재기록", external=work_root)
    repair = apply_structural_repairs(
        input_start=input_start,
        output_start=outputs["start"],
        plan=plan,
        reverse_map=reverse_map,
    )

    progress(58, "SYSTEM.DAT 생성", "복구 START를 LZS로 압축해 고정 영역에 재패킹", external=work_root)
    rebuilt_start = outputs["start"].read_bytes()
    new_system, system_result = v5.repack_system(rebuilt_start)

    progress(78, "ISO 생성", "검증된 V4 ISO의 SYSTEM.DAT 영역만 교체", external=work_root)
    iso_result = v5.inject_iso(new_system)

    progress(94, "최종 검증", "ISO 구조 검사와 대사별 전후 바이트 보고서 작성", external=work_root)
    report = {
        "format": "prinny_stage1_structural_repair_v6_3_build_v1",
        "status": "pass",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "work_root": str(work_root),
        "cleanup": cleanup,
        "policy": plan.get("policy", {}),
        "input_start": str(input_start),
        "input_start_sha1": sha1_file(input_start),
        "repair": repair,
        "system_result": system_result,
        "iso_result": iso_result,
        "outputs": {
            "start": str(outputs["start"]),
            "start_sha1": sha1_file(outputs["start"]),
            "system": str(outputs["system"]),
            "system_sha1": sha1_file(outputs["system"]),
            "iso": str(outputs["iso"]),
            "iso_sha1": sha1_file(outputs["iso"]),
        },
        "unresolved_ui_groups": plan.get("unresolved_ui_groups", []),
        "errors": [],
    }
    atomic_json(outputs["report"], report)

    status = {
        "format": "prinny_stage1_v6_3_status_v1",
        "status": "complete",
        "pid": os.getpid(),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "iso": str(outputs["iso"]),
        "report": str(outputs["report"]),
        "logical_repair_count": repair["logical_string_count"],
        "physical_patch_count": repair["physical_patch_count"],
        "changed_patch_count": repair["changed_patch_count"],
        "dialogue_text_changed": False,
        "unresolved_ui_group_count": len(plan.get("unresolved_ui_groups", [])),
    }
    status_file(status, work_root)
    progress(
        100,
        "완료",
        f"대사 문구 변경 0건 · 구조 재기록 {repair['logical_string_count']}개 · ISO: {outputs['iso']}",
        status="complete",
        external=work_root,
    )
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="프리니 1 스테이지 1 구조 복구 V6.3")
    result.add_argument("--work-root", type=Path)
    result.add_argument("--input-start", type=Path)
    result.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    result.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    result.add_argument("--allocation", type=Path, default=DEFAULT_ALLOCATION)
    result.add_argument("--no-cleanup", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    work_root: Path | None = None
    try:
        work_root = find_work_root(args.work_root)
        report = build(args)
        print("PASS")
        print("ISO   :", report["outputs"]["iso"])
        print("REPORT:", report["outputs"].get("report", v5.OUTPUT_REPORT))
        return 0
    except Exception as exc:
        try:
            if work_root is None:
                work_root = find_work_root(args.work_root)
            status_file(
                {
                    "format": "prinny_stage1_v6_3_status_v1",
                    "status": "error",
                    "pid": os.getpid(),
                    "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "error": str(exc),
                },
                work_root,
            )
            progress(100, "오류", str(exc), status="error", external=work_root)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
