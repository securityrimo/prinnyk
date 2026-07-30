#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_galmuri14_v5 as v5
import core.font_builder as font_builder

REPORT_DIR = ROOT / "workspace/reports/prinny_stage1_fix"
LOCAL_PROGRESS = REPORT_DIR / "progress_v6_4.json"
LOCAL_STATUS = REPORT_DIR / "status_v6_4.json"
DEFAULT_PLAN = ROOT / "profiles/prinny/stage1_two_byte_repairs_v6_4.json"
DEFAULT_ALLOCATION = ROOT / "workspace/font/audited_allocation_977/hangul_allocation.json"


class BuildError(RuntimeError):
    pass


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_progress(percent: int, stage: str, detail: str, status: str, work_root: Path | None) -> None:
    obj = {
        "format": "prinny_stage1_v6_4_progress_v1",
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "percent": max(0, min(100, int(percent))),
        "stage": stage,
        "detail": detail,
        "pid": os.getpid(),
    }
    atomic_json(LOCAL_PROGRESS, obj)
    if work_root is not None:
        atomic_json(work_root / "reports/prinny_stage1_fix/progress_v6_4.json", obj)


def write_status(obj: dict[str, Any], work_root: Path | None) -> None:
    atomic_json(LOCAL_STATUS, obj)
    if work_root is not None:
        atomic_json(work_root / "reports/prinny_stage1_fix/status_v6_4.json", obj)


def find_work_root(explicit: Path | None) -> Path:
    if explicit is not None:
        p = explicit.expanduser().resolve()
        if p.name != "PSP_Localization_Work":
            p = p / "PSP_Localization_Work"
        p.mkdir(parents=True, exist_ok=True)
        return p
    cfg = ROOT / "workspace/config/psp_storage_root.txt"
    if cfg.is_file():
        raw = cfg.read_text(encoding="utf-8", errors="replace").strip()
        if raw:
            p = Path(raw).expanduser()
            if p.name != "PSP_Localization_Work":
                p = p / "PSP_Localization_Work"
            p.mkdir(parents=True, exist_ok=True)
            return p.resolve()
    media = Path("/media") / os.environ.get("USER", "")
    candidates: list[tuple[int, Path]] = []
    if media.is_dir():
        for mount in media.iterdir():
            if mount.is_dir() and os.access(mount, os.W_OK):
                try:
                    candidates.append((shutil.disk_usage(mount).free, mount))
                except OSError:
                    pass
    if candidates:
        p = max(candidates)[1] / "PSP_Localization_Work"
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()
    p = ROOT / "workspace/external_fallback/PSP_Localization_Work"
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise BuildError(f"JSON 최상위가 객체가 아닙니다: {path}")
    return obj


def load_hangul_map(path: Path) -> dict[str, bytes]:
    doc = load_json(path)
    out: dict[str, bytes] = {}
    for item in doc.get("allocations", []):
        if isinstance(item, dict):
            ch = str(item.get("hangul", ""))
            code = str(item.get("sjis", ""))
            if len(ch) == 1 and code:
                out[ch] = bytes.fromhex(code)
    if len(out) < 900:
        raise BuildError(f"한글 배정표가 너무 작습니다: {len(out)}")
    return out


# 대사 렌더러의 2바이트 정렬을 보존하기 위한 전각 코드.
FULLWIDTH_BYTES: dict[str, bytes] = {
    " ": bytes.fromhex("81 40"),
    ",": bytes.fromhex("81 43"),
    ".": bytes.fromhex("81 44"),
    ":": bytes.fromhex("81 46"),
    ";": bytes.fromhex("81 47"),
    "?": bytes.fromhex("81 48"),
    "!": bytes.fromhex("81 49"),
    "~": bytes.fromhex("81 60"),
    "(": bytes.fromhex("81 69"),
    ")": bytes.fromhex("81 6A"),
    "-": bytes.fromhex("81 7C"),
    "/": bytes.fromhex("81 5E"),
    "%": bytes.fromhex("81 93"),
}
for i, ch in enumerate("0123456789"):
    FULLWIDTH_BYTES[ch] = bytes((0x82, 0x4F + i))
for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    FULLWIDTH_BYTES[ch] = chr(ord("Ａ") + ord(ch) - ord("A")).encode("cp932")
for ch in "abcdefghijklmnopqrstuvwxyz":
    FULLWIDTH_BYTES[ch] = chr(ord("ａ") + ord(ch) - ord("a")).encode("cp932")


def encode_two_byte(text: str, hangul_map: dict[str, bytes]) -> bytes:
    out = bytearray()
    for ch in text:
        if ch in hangul_map:
            token = hangul_map[ch]
        elif ch in FULLWIDTH_BYTES:
            token = FULLWIDTH_BYTES[ch]
        else:
            try:
                token = ch.encode("cp932", errors="strict")
            except UnicodeEncodeError as exc:
                raise BuildError(f"인코딩 불가 문자: {ch!r} U+{ord(ch):04X}") from exc
        if len(token) != 2:
            raise BuildError(f"1바이트 표시 코드가 남았습니다: {ch!r} -> {token.hex(' ').upper()}")
        out.extend(token)
    return bytes(out)


def choose_input_start(work_root: Path, explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    candidates += [
        work_root / "build/prinny_stage1_structural_repair_v6_3/system/start.dat",
        work_root / "build/prinny_stage1_hotfix_v6_2/system/start.dat",
        ROOT / "workspace/build/final_system_galmuri14_977_v5/start.dat",
        ROOT / "workspace/build/final_system_csv_revision_977_v4/start.dat",
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    raise FileNotFoundError("입력 START를 찾지 못했습니다:\n" + "\n".join(map(str, candidates)))


def apply_repairs(input_start: Path, output_start: Path, plan: dict[str, Any], hangul_map: dict[str, bytes]) -> dict[str, Any]:
    original = input_start.read_bytes()
    records = font_builder.parse_start_records(original)
    record_map = {str(r["name"]).casefold(): r for r in records}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for patch in plan.get("patches", []):
        grouped.setdefault(str(patch["resource"]).casefold(), []).append(patch)

    replacements: dict[str, bytes] = {}
    results: list[dict[str, Any]] = []
    for key, patches in grouped.items():
        record = record_map.get(key)
        if record is None:
            raise BuildError(f"START 리소스 없음: {key}")
        blob = bytearray(font_builder.resource_blob(original, record))
        occupied: list[tuple[int, int]] = []
        for p in sorted(patches, key=lambda x: int(str(x["offset"]), 0)):
            off = int(str(p["offset"]), 0)
            span = int(p["span"])
            end = off + span
            if end > len(blob):
                raise BuildError(f"범위 초과: {key}+0x{off:X} span={span}")
            if any(off < e and end > s for s, e in occupied):
                raise BuildError(f"패치 중첩: {key}+0x{off:X}")
            occupied.append((off, end))
            before = bytes(blob[off:end])
            before_sha = sha1_bytes(before)
            expected_sha = str(p["expected_before_sha1"])
            encoded = encode_two_byte(str(p["output_text"]), hangul_map)
            if len(encoded) > span:
                raise BuildError(f"슬롯 초과: {p['logical_id']} {len(encoded)} > {span}")
            after = encoded + b"\x00" * (span - len(encoded))
            after_sha = sha1_bytes(after)
            if before_sha not in {expected_sha, after_sha}:
                raise BuildError(
                    f"Expected Write 불일치: {p['logical_id']} {key}+0x{off:X}\n"
                    f"actual  : {before_sha}\nexpected: {expected_sha}\nafter   : {after_sha}"
                )
            changed = before != after
            blob[off:end] = after
            # 바이트 정렬 게이트: 0 패딩 전까지 표시 토큰은 모두 2바이트.
            display = after.rstrip(b"\x00")
            if len(display) % 2:
                raise BuildError(f"홀수 바이트 표시열: {p['logical_id']} len={len(display)}")
            results.append({
                "logical_id": p["logical_id"],
                "resource": p["resource"],
                "offset": off,
                "offset_hex": f"0x{off:X}",
                "span": span,
                "translation": p["translation"],
                "output_text": p["output_text"],
                "encoded_length": len(encoded),
                "changed": changed,
                "before_sha1": before_sha,
                "after_sha1": after_sha,
                "before_hex": before.hex(" ").upper(),
                "after_hex": after.hex(" ").upper(),
            })
        replacements[key] = bytes(blob)

    rebuilt = font_builder.rebuild_start_archive(original, records, replacements)
    if len(rebuilt) != len(original):
        raise BuildError(f"START 크기 변경: {len(original)} -> {len(rebuilt)}")
    changed_count = sum(1 for x in results if x["changed"])
    if changed_count == 0:
        raise BuildError("NO-OP 차단: 대상 14개 영역이 이미 V6.4 바이트와 동일합니다. ISO를 생성하지 않습니다.")

    # 리소스 변경 범위 검증
    rebuilt_records = font_builder.parse_start_records(rebuilt)
    rebuilt_map = {str(r["name"]).casefold(): r for r in rebuilt_records}
    changed_resources: list[str] = []
    for r in records:
        k = str(r["name"]).casefold()
        if font_builder.resource_blob(original, r) != font_builder.resource_blob(rebuilt, rebuilt_map[k]):
            changed_resources.append(str(r["name"]))
    expected_resources = sorted(grouped)
    actual_resources = sorted(x.casefold() for x in changed_resources)
    if actual_resources != expected_resources:
        raise BuildError(f"예상 외 리소스 변경: expected={expected_resources}, actual={actual_resources}")

    output_start.parent.mkdir(parents=True, exist_ok=True)
    output_start.write_bytes(rebuilt)
    return {
        "input": str(input_start),
        "output": str(output_start),
        "input_sha1": sha1_bytes(original),
        "output_sha1": sha1_bytes(rebuilt),
        "target_count": len(results),
        "changed_count": changed_count,
        "unchanged_count": len(results) - changed_count,
        "changed_resources": changed_resources,
        "patches": results,
    }


def configure_outputs(work_root: Path) -> dict[str, Path]:
    build_dir = work_root / "build/prinny_stage1_two_byte_repair_v6_4"
    system_dir = build_dir / "system"
    report_dir = work_root / "reports/prinny_stage1_fix"
    build_dir.mkdir(parents=True, exist_ok=True)
    system_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    v5.OUTPUT_DIR = system_dir
    v5.OUTPUT_START = system_dir / "start.dat"
    v5.OUTPUT_LZS = system_dir / "start.lzs"
    v5.OUTPUT_SYSTEM = system_dir / "SYSTEM.DAT"
    v5.OUTPUT_ISO = build_dir / "prinny_korean_stage1_two_byte_repair_v6_4_977.iso"
    v5.OUTPUT_REPORT = report_dir / "prinny_stage1_two_byte_repair_v6_4_build.json"
    return {"build_dir": build_dir, "system_dir": system_dir, "report_dir": report_dir,
            "start": v5.OUTPUT_START, "system": v5.OUTPUT_SYSTEM, "iso": v5.OUTPUT_ISO,
            "report": v5.OUTPUT_REPORT}


def safe_cleanup(work_root: Path) -> dict[str, Any]:
    removed = []
    for p in [ROOT / "workspace/strings", ROOT / "workspace/translations/recovered", work_root / "tmp"]:
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            removed.append(str(p))
    for p in ROOT.rglob("__pycache__"):
        try:
            shutil.rmtree(p)
        except OSError:
            pass
    return {"removed": removed}


def build(args: argparse.Namespace) -> dict[str, Any]:
    work_root = find_work_root(args.work_root)
    outputs = configure_outputs(work_root)
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    write_status({"format":"prinny_stage1_v6_4_status_v1","status":"running","pid":os.getpid(),"started_at":started,"work_root":str(work_root)}, work_root)
    write_progress(3, "시작", "V6.3 NO-OP 판정 후 2바이트 정렬 복구 시작", "running", work_root)
    cleanup = safe_cleanup(work_root) if not args.no_cleanup else {"skipped": True}
    write_progress(10, "입력 확인", "V6.3/V6.2 START와 V4 ISO 계보 확인", "running", work_root)
    input_start = choose_input_start(work_root, args.input_start)
    for p in [v5.V4_SYSTEM, v5.V4_ISO, v5.V4_ISO_REPORT, args.plan, args.allocation]:
        if not Path(p).is_file():
            raise FileNotFoundError(f"필수 파일 없음: {p}")
    plan = load_json(args.plan)
    hangul_map = load_hangul_map(args.allocation)
    write_progress(24, "인코딩 검사", "ASCII 1바이트 표시 코드를 전각 2바이트 코드로 변환", "running", work_root)
    write_progress(42, "대사 패치", "14개 확인 장면의 바이트 정렬 복구", "running", work_root)
    repair = apply_repairs(input_start, outputs["start"], plan, hangul_map)
    write_progress(65, "SYSTEM.DAT 생성", "복구 START를 LZS로 재패킹", "running", work_root)
    new_system, system_result = v5.repack_system(outputs["start"].read_bytes())
    write_progress(82, "ISO 생성", "검증된 V4 ISO의 SYSTEM.DAT만 교체", "running", work_root)
    iso_result = v5.inject_iso(new_system)
    write_progress(95, "최종 검증", "NO-OP 차단·변경 범위·출력 SHA1 검사", "running", work_root)
    report = {
        "format":"prinny_stage1_two_byte_repair_v6_4_build_v1","status":"pass",
        "created_at":datetime.now().astimezone().isoformat(timespec="seconds"),
        "work_root":str(work_root),"cleanup":cleanup,"policy":plan.get("policy",{}),
        "repair":repair,"system_result":system_result,"iso_result":iso_result,
        "outputs":{"start":str(outputs["start"]),"start_sha1":sha1_file(outputs["start"]),
                   "system":str(outputs["system"]),"system_sha1":sha1_file(outputs["system"]),
                   "iso":str(outputs["iso"]),"iso_sha1":sha1_file(outputs["iso"])},
        "mechanical_fit_adjustments":plan.get("mechanical_fit_adjustments",[]),
        "unresolved_ui_groups":plan.get("unresolved_ui_groups",[]),"errors":[]}
    atomic_json(outputs["report"], report)
    status = {"format":"prinny_stage1_v6_4_status_v1","status":"complete","pid":os.getpid(),
              "completed_at":datetime.now().astimezone().isoformat(timespec="seconds"),
              "iso":str(outputs["iso"]),"report":str(outputs["report"]),
              "target_count":repair["target_count"],"changed_count":repair["changed_count"],
              "semantic_retranslation":False,"mechanical_adjustment_count":len(plan.get("mechanical_fit_adjustments",[])),
              "unresolved_ui_group_count":len(plan.get("unresolved_ui_groups",[]))}
    write_status(status, work_root)
    write_progress(100, "완료", f"실제 변경 {repair['changed_count']}개 · 2바이트 정렬 복구 · ISO: {outputs['iso']}", "complete", work_root)
    return report


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="프리니 1 스테이지 1 2바이트 정렬 복구 V6.4")
    p.add_argument("--work-root", type=Path)
    p.add_argument("--input-start", type=Path)
    p.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    p.add_argument("--allocation", type=Path, default=DEFAULT_ALLOCATION)
    p.add_argument("--no-cleanup", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    work_root: Path | None = None
    try:
        work_root = find_work_root(args.work_root)
        report = build(args)
        print("PASS")
        print("ISO:", report["outputs"]["iso"])
        print("REPORT:", v5.OUTPUT_REPORT)
        return 0
    except Exception as exc:
        try:
            if work_root is None:
                work_root = find_work_root(args.work_root)
            write_status({"format":"prinny_stage1_v6_4_status_v1","status":"error","pid":os.getpid(),
                          "completed_at":datetime.now().astimezone().isoformat(timespec="seconds"),"error":str(exc)}, work_root)
            write_progress(100, "오류", str(exc), "error", work_root)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
