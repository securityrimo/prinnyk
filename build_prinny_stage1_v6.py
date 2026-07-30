#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from profiles.prinny.stage1_hotfix import (
    DEFAULT_ALLOCATION,
    DEFAULT_FIXES,
    DEFAULT_MASTER,
    DEFAULT_PROGRESS,
    apply_start_hotfixes,
    load_encoded_map,
    load_fixes,
    update_master_csv,
)

LOCAL_REPORT_DIR = ROOT / "workspace/reports/prinny_stage1_fix"
LOCAL_PROGRESS = LOCAL_REPORT_DIR / "progress.json"
LOCAL_STATUS = LOCAL_REPORT_DIR / "status.json"


class BuildError(RuntimeError):
    pass


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
        "format": "prinny_stage1_v6_2_progress_v1",
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


def find_galmuri() -> Path:
    candidates = [
        Path.home() / ".local/share/fonts/Galmuri14.ttf",
        Path.home() / ".fonts/Galmuri14.ttf",
        Path("/usr/local/share/fonts/Galmuri14.ttf"),
        Path("/usr/share/fonts/truetype/galmuri/Galmuri14.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    if shutil.which("fc-match"):
        result = subprocess.run(
            ["fc-match", "-f", "%{file}\n", "Galmuri14"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            path = Path(line.strip())
            if path.is_file() and "galmuri" in path.name.casefold():
                return path.resolve()

    raise FileNotFoundError("Galmuri14.ttf를 찾지 못했습니다.")


def safe_cleanup(work_root: Path | None = None) -> dict[str, Any]:
    targets = [
        ROOT / "workspace/strings",
        ROOT / "workspace/translations/recovered",
        ROOT / "workspace/psp_toolkit/game1",
        ROOT / "workspace/psp_toolkit/game2",
    ]
    removed: list[dict[str, Any]] = []
    for target in targets:
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

    # 이전 실패 빌드의 대용량 중간 산출물은 최종 ISO가 없을 때만 제거한다.
    # 완성 ISO가 있는 폴더는 보호한다.
    if work_root is not None:
        for name in ("prinny_stage1_hotfix_v6", "prinny_stage1_hotfix_v6_1"):
            target = work_root / "build" / name
            if not target.is_dir() or any(target.glob("*.iso")):
                continue
            size = 0
            for path in target.rglob("*"):
                try:
                    if path.is_file():
                        size += path.stat().st_size
                except OSError:
                    pass
            shutil.rmtree(target)
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


def prepare_v5_globals(work_root: Path, hotfix_start: Path, galmuri: Path) -> dict[str, Path]:
    build_dir = work_root / "build/prinny_stage1_hotfix_v6_2"
    output_dir = build_dir / "system"
    font_source_dir = build_dir / "font_source"
    report_dir = work_root / "reports/prinny_stage1_fix"
    build_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    v5.GALMURI = galmuri
    v5.V4_START = hotfix_start
    v5.FONT_SOURCE_DIR = font_source_dir
    v5.OUTPUT_DIR = output_dir
    v5.OUTPUT_START = output_dir / "start.dat"
    v5.OUTPUT_LZS = output_dir / "start.lzs"
    v5.OUTPUT_SYSTEM = output_dir / "SYSTEM.DAT"
    v5.OUTPUT_TXP = output_dir / "font.txp"
    v5.OUTPUT_PREVIEW = output_dir / "preview.png"
    v5.OUTPUT_ISO = build_dir / "prinny_korean_stage1_hotfix_v6_2_977.iso"
    v5.OUTPUT_REPORT = report_dir / "prinny_stage1_hotfix_v6_2_build.json"

    return {
        "build_dir": build_dir,
        "output_dir": output_dir,
        "font_source_dir": font_source_dir,
        "report_dir": report_dir,
        "iso": v5.OUTPUT_ISO,
        "report": v5.OUTPUT_REPORT,
    }


def write_review_csv(path: Path, report: dict[str, Any]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id", "resource", "offset_hex", "old_translation", "new_translation",
        "new_encoded_length", "capacity", "reason", "review_status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in report["start"]["fixes"]:
            writer.writerow(
                {
                    **{field: item.get(field, "") for field in fields},
                    "review_status": "게임 화면 확인 필요",
                }
            )


def write_review_only_csv(path: Path, fix_document: dict[str, Any]) -> None:
    import csv

    rows = fix_document.get("review_only", [])
    if not isinstance(rows, list):
        rows = []
    fields = [
        "id", "resource", "offset", "current_translation",
        "observed_issue", "minimal_suggestion", "policy", "review_status",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in rows:
            if not isinstance(item, dict):
                continue
            writer.writerow({
                "id": item.get("id", ""),
                "resource": item.get("resource", ""),
                "offset": item.get("offset", ""),
                "current_translation": item.get("current_translation", ""),
                "observed_issue": item.get("observed_issue", ""),
                "minimal_suggestion": item.get("minimal_suggestion", ""),
                "policy": "역자 승인 전 자동 적용 금지",
                "review_status": "번역자 검토 필요",
            })


def assert_no_rejected_v6_rewrites(master_path: Path) -> None:
    import csv

    # V6 실패 직전에 원본 번역 마스터에 덮어써졌던 추정성 문장들이다.
    # V6.2은 역자 말투 보존 정책상 이 상태에서 빌드를 계속하지 않는다.
    rejected = {
        "TXT-0E1C5EBE1BD4": "내 스위츠를,",
        "TXT-BE520F2AA761": "누가 다 처먹었어어어!?",
        "TXT-C09DD74C12BA": "좋아, 내일 아침까지 화제인",
        "TXT-D287E7FC1B90": "……그렇게 생각했지?",
        "TXT-19DA872E02F7": "후훗, 그럴 줄 알고―.",
        "TXT-56FFB8CE5691": "알았지? 내일 아침까지.",
        "TXT-0F346321936F": "우리도 저승에서",
        "TXT-7E9DB3B70C57": "응원하겠슴다!!",
        "TXT-6F5F54FE7516": "마계 6곳의 흉악한 악마에게서",
        "TXT-458610B1D784": "재료를 얻어야 함다.",
        "TXT-C7F864C06E43": "이젠… 싫어…",
        "TXT-146237588658": "도망치고 싶어……",
        "TXT-79905A084470": "시공의 틈새바람",
        "TXT-8CD4A4D0BBAD": "기분 좋은 바람입니다.",
        "TXT-EE6E08FFA7E2": "돌려드림.",
        "TXT-65A9B2A7B100": "본명, 아사기리 아사기.",
    }
    if not master_path.is_file():
        raise FileNotFoundError(f"번역 마스터 없음: {master_path}")
    hits: list[str] = []
    with master_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            identifier = str(row.get("id", "")).strip()
            if identifier in rejected and str(row.get("translation", "")) == rejected[identifier]:
                hits.append(identifier)
    if hits:
        raise BuildError(
            "실패한 V6의 추정성 대사 수정이 translation_master.csv에 남아 있습니다: "
            + ", ".join(hits)
            + "\nV6.2 업데이트 설치기의 원본 복원 단계를 먼저 실행하세요."
        )


def build(args: argparse.Namespace) -> dict[str, Any]:
    work_root = find_work_root(args.work_root)
    report_dir = work_root / "reports/prinny_stage1_fix"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_path = report_dir / ("run_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".log")

    progress(1, "시작", f"작업 저장장치: {work_root}", external=work_root)
    status_file(
        {
            "format": "prinny_stage1_v6_2_status_v1",
            "status": "running",
            "pid": os.getpid(),
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "work_root": str(work_root),
            "log": str(log_path),
        },
        work_root,
    )

    cleanup_result: dict[str, Any] = {"skipped": True}
    if not args.no_cleanup:
        progress(4, "공간 정리", "재생성 가능한 대용량 중간 파일 삭제", external=work_root)
        cleanup_result = safe_cleanup(work_root)

    progress(7, "번역 보존 검사", "실패한 V6의 추정성 대사 덮어쓰기 잔존 여부 확인", external=work_root)
    assert_no_rejected_v6_rewrites(args.master)

    # 원본 V4 입력은 바꾸기 전에 강하게 검증한다.
    progress(8, "V4 입력 검증", "검증된 V4 START/SYSTEM/ISO 해시 확인", external=work_root)
    v5.verify_expected_hashes()

    galmuri = find_galmuri()
    fixes, fix_document = load_fixes(args.fixes)
    encoded_map, _ = load_encoded_map(args.allocation)

    hotfix_dir = work_root / "build/prinny_stage1_hotfix_v6_2/text_hotfix"
    hotfix_dir.mkdir(parents=True, exist_ok=True)
    hotfix_start = hotfix_dir / "start.dat"
    hotfix_master = hotfix_dir / "translation_master.stage1_hotfix.csv"

    progress(15, "번역 수정", f"스크린샷 연계 대사 {len(fixes)}개 바이트 검사", external=work_root)
    master_result = update_master_csv(args.master, hotfix_master, fixes, encoded_map)

    progress(28, "START 수정", f"대사 {len(fixes)}개를 V4 START에 안전 적용", external=work_root)
    start_result = apply_start_hotfixes(
        start_path=v5.V4_START,
        output_path=hotfix_start,
        master_path=args.master,
        fixes=fixes,
        encoded_map=encoded_map,
    )

    progress(39, "번역 원본 보호", "translation_master.csv는 변경하지 않고 빌드 전용 사본만 보관", external=work_root)
    master_result["source_preserved"] = True
    master_result["source_path"] = str(args.master)
    master_result["build_only_copy"] = str(hotfix_master)
    master_result["installed_to"] = None

    outputs = prepare_v5_globals(work_root, hotfix_start, galmuri)

    progress(48, "Galmuri14 생성", "977자 글리프를 Galmuri14로 다시 렌더링", external=work_root)
    galmuri_txp = v5.build_galmuri_font_texture()

    progress(63, "폰트 주입", "핫픽스 START의 font.txp 교체 및 리소스 무결성 검사", external=work_root)
    rebuilt_start, font_result = v5.replace_font_in_v4_start(galmuri_txp)

    progress(76, "SYSTEM.DAT 생성", "start.dat 압축 및 고정 영역 재패킹", external=work_root)
    new_system, system_result = v5.repack_system(rebuilt_start)

    progress(87, "ISO 생성", "검증된 V4 ISO에 새 SYSTEM.DAT 주입", external=work_root)
    iso_result = v5.inject_iso(new_system)

    progress(95, "최종 검증", "ISO 해시·7z 구조·수정 목록 보고서 작성", external=work_root)
    final_report = {
        "format": "prinny_stage1_hotfix_v6_2_build_v1",
        "status": "pass",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "work_root": str(work_root),
        "cleanup": cleanup_result,
        "galmuri": {"path": str(galmuri), "sha1": sha1_file(galmuri)},
        "fix_document": str(args.fixes),
        "fix_count": len(fixes),
        "master": master_result,
        "start": start_result,
        "font_result": font_result,
        "system_result": system_result,
        "iso_result": iso_result,
        "outputs": {
            "iso": str(outputs["iso"]),
            "iso_sha1": sha1_file(outputs["iso"]),
            "system": str(v5.OUTPUT_SYSTEM),
            "system_sha1": sha1_file(v5.OUTPUT_SYSTEM),
            "start": str(v5.OUTPUT_START),
            "start_sha1": sha1_file(v5.OUTPUT_START),
            "applied_fixes_csv": str(report_dir / "stage1_applied_fixes.csv"),
            "review_only_csv": str(report_dir / "stage1_review_only.csv"),
        },
        "translation_policy": fix_document.get("translation_policy", {}),
        "review_only_count": len(fix_document.get("review_only", [])),
        "unresolved_ui_groups": fix_document.get("unresolved_ui_groups", []),
        "errors": [],
    }
    atomic_json(outputs["report"], final_report)
    write_review_csv(report_dir / "stage1_applied_fixes.csv", final_report)
    write_review_only_csv(report_dir / "stage1_review_only.csv", fix_document)

    # 로컬에는 작은 상태/보고서만 복사한다. 대용량 ISO는 외장 저장장치에만 둔다.
    LOCAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(outputs["report"], LOCAL_REPORT_DIR / outputs["report"].name)
    shutil.copy2(report_dir / "stage1_applied_fixes.csv", LOCAL_REPORT_DIR / "stage1_applied_fixes.csv")
    shutil.copy2(report_dir / "stage1_review_only.csv", LOCAL_REPORT_DIR / "stage1_review_only.csv")

    completed = {
        "format": "prinny_stage1_v6_2_status_v1",
        "status": "complete",
        "pid": os.getpid(),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "work_root": str(work_root),
        "iso": str(outputs["iso"]),
        "iso_sha1": final_report["outputs"]["iso_sha1"],
        "report": str(outputs["report"]),
        "applied_fixes_csv": str(report_dir / "stage1_applied_fixes.csv"),
        "review_only_csv": str(report_dir / "stage1_review_only.csv"),
        "fix_count": len(fixes),
        "review_only_count": len(fix_document.get("review_only", [])),
        "unresolved_ui_group_count": len(final_report["unresolved_ui_groups"]),
    }
    status_file(completed, work_root)
    progress(100, "완료", f"보수적 자동 수정 {len(fixes)}건 · 검토 대기 {len(fix_document.get('review_only', []))}건 · ISO: {outputs['iso']}", status="complete", external=work_root)
    return final_report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="프리니 1 스테이지 1 보수적 오류 수정 + Galmuri14 V6.2 빌드")
    value.add_argument("--work-root", type=Path)
    value.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    value.add_argument("--allocation", type=Path, default=DEFAULT_ALLOCATION)
    value.add_argument("--fixes", type=Path, default=DEFAULT_FIXES)
    value.add_argument("--no-cleanup", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    work_root: Path | None = None
    try:
        work_root = find_work_root(args.work_root)
        result = build(args)
        print("=" * 88)
        print("PRINNY STAGE1 HOTFIX V6.2: PASS")
        print(f"FIXES : {result['fix_count']}")
        print(f"ISO   : {result['outputs']['iso']}")
        print(f"SHA1  : {result['outputs']['iso_sha1']}")
        print(f"REPORT: {work_root / 'reports/prinny_stage1_fix/prinny_stage1_hotfix_v6_2_build.json'}")
        print("PPSSPP는 자동 실행하지 않습니다. 생성된 V6 ISO를 명시적으로 실행하세요.")
        print("=" * 88)
        return 0
    except Exception as exc:
        payload = {
            "format": "prinny_stage1_v6_2_status_v1",
            "status": "error",
            "pid": os.getpid(),
            "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "error": str(exc),
        }
        status_file(payload, work_root)
        progress(100, "오류", str(exc), status="error", external=work_root)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
