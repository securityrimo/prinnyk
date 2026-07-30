#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from profiles.prinny.executable_qa import scan_prinny_executable_strings
from profiles.prinny.probe import (
    PrinnyProbeError,
    compare_prinny_profiles,
    probe_prinny_disc,
)
from profiles.prinny.qa import DEFAULT_OUTPUT as DEFAULT_QA_OUTPUT
from profiles.prinny.qa import run_qa
from psp_localization.compare import compare_disc_analyses
from psp_localization.iso import (
    PSPImageError,
    analyze_disc,
    cleanup_prepared_disc,
    prepare_disc,
)
from psp_localization.maintenance import safe_cleanup
from psp_localization.reporting import write_dashboard
from psp_localization.string_scan import scan_file, write_scan_report
from psp_localization.storage import (
    StorageError,
    load_storage_config,
    prepare_external_storage,
    runtime_paths,
)
from psp_localization.util import atomic_write_json


ROOT = Path(__file__).resolve().parent
RUNTIME_PATHS = runtime_paths(ROOT)
DEFAULT_RUN_DIR = RUNTIME_PATHS["run_dir"]
DEFAULT_REPORT_DIR = RUNTIME_PATHS["report_dir"]
DEFAULT_QA_REPORT_DIR = RUNTIME_PATHS["qa_report_dir"]
DEFAULT_GAME2 = RUNTIME_PATHS["game2_iso"]


def _root_path(value: Path) -> Path:
    return value if value.is_absolute() else ROOT / value


def _write_progress(
    report_dir: Path,
    *,
    stage: str,
    percent: int,
    status: str = "running",
    message: str = "",
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "psp_toolkit_progress_v3",
        "stage": stage,
        "percent": max(0, min(100, int(percent))),
        "status": status,
        "message": message,
    }
    atomic_write_json(report_dir / "status.json", payload)
    (report_dir / "progress.txt").write_text(
        f"[{payload['percent']:3d}%] {stage} - {status}\n{message}\n",
        encoding="utf-8",
    )


def _print_heading(text: str) -> None:
    print("\n" + "=" * 88)
    print(text)
    print("=" * 88)


def _human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def doctor_report() -> dict[str, Any]:
    galmuri_candidates = [
        Path.home() / ".local/share/fonts/Galmuri14.ttf",
        Path.home() / ".fonts/Galmuri14.ttf",
        Path("/usr/local/share/fonts/Galmuri14.ttf"),
        Path("/usr/share/fonts/truetype/galmuri/Galmuri14.ttf"),
    ]
    usage = shutil.disk_usage(ROOT)
    required = {
        "translation_csv": ROOT / "workspace/translations/export/translation_master.csv",
        "allocation": ROOT / "workspace/font/audited_allocation_977/hangul_allocation.json",
        "v5_builder": ROOT / "build_galmuri14_v5.py",
    }
    return {
        "format": "psp_toolkit_doctor_v3",
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "supported": sys.version_info >= (3, 10),
        },
        "commands": {
            "7z": shutil.which("7z") or "",
            "flatpak": shutil.which("flatpak") or "",
            "xdelta3": shutil.which("xdelta3") or "",
        },
        "galmuri14": {
            "found": [str(path) for path in galmuri_candidates if path.is_file()],
            "candidates": [str(path) for path in galmuri_candidates],
        },
        "disk": {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "free_human": _human_bytes(usage.free),
        },
        "storage": load_storage_config(ROOT) or {"status": "not_configured"},
        "project": {
            "root": str(ROOT),
            "files": {
                label: {"path": str(path), "present": path.is_file()}
                for label, path in required.items()
            },
        },
        "status": "pass" if sys.version_info >= (3, 10) else "fail",
    }


def cmd_prepare_storage(args: argparse.Namespace) -> int:
    requested = args.data_root.expanduser() if args.data_root else None
    config = prepare_external_storage(
        ROOT,
        requested=requested,
        migrate_game2=not args.no_migrate_game2,
    )
    _print_heading("PSP TOOLKIT EXTERNAL STORAGE")
    print("DATA ROOT :", config["data_root"])
    print("RUN DIR   :", config["run_dir"])
    print("REPORT DIR:", config["report_dir"])
    print("GAME2 ISO :", config["game2_iso"])
    print("MIGRATION :", config["migration"].get("status", ""))
    print("CONFIG    :", ROOT / ".psp_toolkit_storage.json")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = doctor_report()
    output = _root_path(args.output)
    atomic_write_json(output, report)
    _print_heading("PSP TOOLKIT DOCTOR")
    print("Python  :", sys.version.split()[0])
    print("7z      :", report["commands"]["7z"] or "없음")
    print("Galmuri :", ", ".join(report["galmuri14"]["found"]) or "없음")
    print("Free    :", report["disk"]["free_human"])
    print("REPORT  :", output)
    return 0 if report["status"] == "pass" else 1


def _analyze_one(
    source: Path,
    label: str,
    run_dir: Path,
    *,
    force_extract: bool,
    extraction_mode: str,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    disc_root, extract_manifest = prepare_disc(
        source,
        run_dir / label,
        force=force_extract,
        extraction_mode=extraction_mode,
    )
    analysis = analyze_disc(disc_root, analysis_scope=extract_manifest.get("extraction_mode", extraction_mode))
    atomic_write_json(run_dir / label / "analysis.json", analysis)
    return disc_root, extract_manifest, analysis


def cmd_analyze(args: argparse.Namespace) -> int:
    run_dir = _root_path(args.run_dir)
    source = _root_path(args.source)
    mode = "minimal" if args.low_space else "full"
    disc_root, manifest, analysis = _analyze_one(
        source,
        args.label,
        run_dir,
        force_extract=args.force_extract,
        extraction_mode=mode,
    )
    output = _root_path(args.output) if args.output else run_dir / args.label / "analysis.json"
    atomic_write_json(output, analysis)
    _print_heading("PSP DISC ANALYSIS")
    print("SOURCE    :", source)
    print("DISC ROOT :", disc_root)
    print("MODE      :", mode)
    print("DISC ID   :", analysis["game"].get("disc_id", ""))
    print("TITLE     :", analysis["game"].get("title", ""))
    print("FILES     :", analysis["file_count"])
    print("REUSED    :", manifest.get("reused", False))
    print("REPORT    :", output)
    if args.cleanup_extracted and source.is_file():
        result = cleanup_prepared_disc(run_dir / args.label)
        print("CLEANUP   :", result["status"], _human_bytes(result.get("freed_bytes", 0)))
    return 0


def cmd_strings(args: argparse.Namespace) -> int:
    source = _root_path(args.source)
    output_dir = _root_path(args.output_dir)
    report = scan_file(source, require_terminator=not args.relaxed)
    write_scan_report(report, output_dir)
    _print_heading("PSP SHIFT-JIS STRING SCAN")
    print("SOURCE     :", source)
    print("CANDIDATES :", report["candidate_count"])
    print("CSV        :", output_dir / "strings.csv")
    print("JSON       :", output_dir / "strings.json")
    return 0


def cmd_prinny_qa(args: argparse.Namespace) -> int:
    report = run_qa(
        csv_path=_root_path(args.csv),
        master_path=_root_path(args.master),
        allocation_path=_root_path(args.allocation),
        catalog_path=_root_path(args.catalog),
        output_directory=_root_path(args.output_dir),
    )
    summary = report["summary"]
    _print_heading("PRINNY TRANSLATION QA")
    print("ROWS       :", summary["row_count"])
    print("ERRORS     :", summary["error_count"])
    print("WARNINGS   :", summary["warning_count"])
    print("UNCOVERED  :", summary["uncovered_candidate_count"])
    print("REPORT DIR :", _root_path(args.output_dir))
    return 0 if report["status"] == "pass" else 2


def cmd_cleanup(args: argparse.Namespace) -> int:
    output = _root_path(args.output)
    report = safe_cleanup(ROOT, apply=args.apply, report_path=output)
    _print_heading("PSP SAFE SPACE CLEANUP")
    print("MODE  :", "APPLY" if args.apply else "DRY-RUN")
    for item in report["actions"]:
        if item["status"] not in {"missing"}:
            print(f"{item['status']:>12}  {_human_bytes(item['size']):>10}  {item['path']}")
    print("FREED :", _human_bytes(report["freed_bytes"]))
    print("REPORT:", output)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    run_dir = _root_path(args.run_dir)
    output_dir = _root_path(args.output_dir)
    mode = "minimal" if args.low_space else "full"
    analyses: dict[str, Any] = {}
    probes: dict[str, Any] = {}
    for label, value in (("game1", args.game1), ("game2", args.game2)):
        source = _root_path(value)
        root, _, analysis = _analyze_one(
            source, label, run_dir, force_extract=args.force_extract, extraction_mode=mode
        )
        analyses[label] = analysis
        probes[label] = probe_prinny_disc(root)
        if args.cleanup_extracted and source.is_file():
            cleanup_prepared_disc(run_dir / label)
    generic = compare_disc_analyses(analyses["game1"], analyses["game2"])
    prinny = compare_prinny_profiles(probes["game1"], probes["game2"])
    atomic_write_json(output_dir / "disc_compare.json", generic)
    atomic_write_json(output_dir / "prinny1_probe.json", probes["game1"])
    atomic_write_json(output_dir / "prinny2_probe.json", probes["game2"])
    atomic_write_json(output_dir / "prinny_compatibility.json", prinny)
    write_dashboard(
        output_dir / "index.html",
        analyses=analyses,
        comparison=generic,
        prinny_compatibility=prinny,
        qa=None,
    )
    _print_heading("PRINNY 1 / PRINNY 2 COMPATIBILITY")
    print("MODE    :", mode)
    print("GRADE   :", prinny["grade"])
    print("VERDICT :", prinny["verdict"])
    print("REPORT  :", output_dir / "index.html")
    return 0


def _v5_missing_inputs() -> list[str]:
    required = (
        ROOT / "workspace/build/final_system_csv_revision_977_v4/start.dat",
        ROOT / "workspace/build/final_system_csv_revision_977_v4/SYSTEM.DAT",
        ROOT / "workspace/build/prinny_korean_v4_977.iso",
        ROOT / "workspace/reports/csv_revision_v4_iso_injection_977.json",
        ROOT / "workspace/translations/font_build_test.json",
    )
    return [str(path) for path in required if not path.is_file()]


def _run_v5_builder(*, launch: bool, qa_gate: bool) -> dict[str, Any]:
    missing = _v5_missing_inputs()
    if missing:
        return {
            "status": "skipped_missing_inputs",
            "reason": "V4 기준 빌드 산출물이 없습니다.",
            "missing": missing,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }
    command = [sys.executable, str(ROOT / "build_galmuri14_v5.py"), "--json-summary"]
    if not launch:
        command.append("--no-launch")
    if not qa_gate:
        command.append("--skip-qa-gate")
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": process.returncode,
        "stdout": process.stdout[-12000:],
        "stderr": process.stderr[-12000:],
        "status": "pass" if process.returncode == 0 else "fail",
    }


def cmd_build_v5(args: argparse.Namespace) -> int:
    result = _run_v5_builder(launch=args.launch, qa_gate=not args.skip_qa_gate)
    if result["stdout"]:
        print(result["stdout"], end="" if result["stdout"].endswith("\n") else "\n")
    if result["stderr"]:
        print(result["stderr"], file=sys.stderr)
    if result["status"] == "skipped_missing_inputs":
        print("V5 BUILD SKIPPED:", result["reason"])
        for path in result["missing"]:
            print("  -", path)
    return int(result.get("returncode", 0))


def cmd_all(args: argparse.Namespace) -> int:
    run_dir = _root_path(args.run_dir)
    report_dir = _root_path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    mode = "minimal" if args.low_space else "full"
    _write_progress(report_dir, stage="시작", percent=1, message="저장 공간 정리와 사전 검사를 준비합니다.")
    state: dict[str, Any] = {
        "format": "psp_toolkit_all_v3",
        "inputs": {
            "game1": str(_root_path(args.game1)),
            "game2": str(_root_path(args.game2)),
        },
        "mode": mode,
        "doctor": doctor_report(),
        "analyses": {},
        "probes": {},
        "errors": [],
    }

    if args.cleanup_regenerable:
        _write_progress(report_dir, stage="저장 공간 정리", percent=5)
        _print_heading("0/5 저장 공간 안전 정리")
        cleanup_report = safe_cleanup(
            ROOT,
            apply=True,
            report_path=report_dir / "pre_run_cleanup.json",
        )
        state["pre_run_cleanup"] = cleanup_report
        print("FREED:", _human_bytes(cleanup_report["freed_bytes"]))
        print("원본 ISO·번역 마스터·V4 빌드 산출물은 보호했습니다.")

    _write_progress(report_dir, stage="번역 QA", percent=15)
    _print_heading("1/5 번역 QA")
    try:
        qa = run_qa(
            csv_path=ROOT / "workspace/translations/export/translation_master.csv",
            master_path=ROOT / "workspace/translations/export/translation_master.json",
            allocation_path=ROOT / "workspace/font/audited_allocation_977/hangul_allocation.json",
            catalog_path=ROOT / "workspace/translations/catalog/catalog.json",
            output_directory=DEFAULT_QA_REPORT_DIR,
        )
        state["qa"] = qa
        print(json.dumps(qa["summary"], ensure_ascii=False, indent=2))
    except Exception as error:  # 일괄 실행은 가능한 다음 단계로 계속한다.
        qa = None
        state["errors"].append({"stage": "qa", "error": str(error)})
        print("QA ERROR:", error)

    for index, (label, input_value) in enumerate((("game1", args.game1), ("game2", args.game2)), start=2):
        _write_progress(report_dir, stage=f"{label} 저용량 분석", percent=30 if label == "game1" else 55)
        _print_heading(f"{index}/5 {label} 저용량 분석")
        source = _root_path(input_value)
        if not source.exists():
            message = f"입력 없음: {source}"
            state["errors"].append({"stage": label, "error": message})
            print("SKIP:", message)
            continue
        try:
            root, extract, analysis = _analyze_one(
                source,
                label,
                run_dir,
                force_extract=args.force_extract,
                extraction_mode=mode,
            )
        except Exception as error:
            state["errors"].append({"stage": label, "error": str(error)})
            print("ERROR:", error)
            continue
        state["analyses"][label] = analysis
        state[f"{label}_extract"] = extract
        print(analysis["game"].get("disc_id", ""), analysis["game"].get("title", ""))
        print("FILES:", analysis["file_count"], "MODE:", mode)

        try:
            probe = probe_prinny_disc(root)
        except Exception as error:
            state["errors"].append({"stage": f"{label}_probe", "error": str(error)})
            print("PRINNY PROBE ERROR:", error)
        else:
            state["probes"][label] = probe
            atomic_write_json(report_dir / f"{label}_probe.json", probe)
            print("START RESOURCES:", probe["start"]["record_count"])
            print("FONT STATUS:", probe["font"].get("status", ""))

        try:
            executable_scan = scan_prinny_executable_strings(
                root, report_dir / f"{label}_executable_strings"
            )
        except Exception as error:
            state["errors"].append(
                {"stage": f"{label}_executable_strings", "error": str(error)}
            )
            print("EXECUTABLE STRING SCAN ERROR:", error)
        else:
            state[f"{label}_executable_strings"] = {
                "source": executable_scan["source"],
                "candidate_count": executable_scan["candidate_count"],
                "csv": str(report_dir / f"{label}_executable_strings" / "strings.csv"),
                "json": str(report_dir / f"{label}_executable_strings" / "strings.json"),
            }
            print("BOOT/UI JAPANESE CANDIDATES:", executable_scan["candidate_count"])

        if args.cleanup_extracted and source.is_file():
            cleanup_result = cleanup_prepared_disc(run_dir / label)
            state[f"{label}_extract_cleanup"] = cleanup_result
            print("EXTRACT CLEANUP:", cleanup_result["status"], _human_bytes(cleanup_result.get("freed_bytes", 0)))

    generic_comparison = None
    prinny_compatibility = None
    if "game1" in state["analyses"] and "game2" in state["analyses"]:
        _write_progress(report_dir, stage="프리니 1/2 구조 비교", percent=75)
        _print_heading("4/5 프리니 1/2 구조 비교")
        try:
            generic_comparison = compare_disc_analyses(
                state["analyses"]["game1"], state["analyses"]["game2"]
            )
            if "game1" in state["probes"] and "game2" in state["probes"]:
                prinny_compatibility = compare_prinny_profiles(
                    state["probes"]["game1"], state["probes"]["game2"]
                )
                state["prinny_compatibility"] = prinny_compatibility
                print("GRADE:", prinny_compatibility["grade"])
                print(prinny_compatibility["verdict"])
            state["comparison"] = generic_comparison
        except Exception as error:
            state["errors"].append({"stage": "compare", "error": str(error)})
            print("COMPARE ERROR:", error)
    else:
        print("프리니 1/2 비교는 두 ISO가 모두 있을 때 자동 실행됩니다.")

    _write_progress(report_dir, stage="Galmuri14 V5 빌드", percent=85)
    _print_heading("5/5 V5 빌드")
    if args.skip_build:
        build = {"status": "skipped", "reason": "--skip-build"}
        print("SKIP: --skip-build")
    else:
        build = _run_v5_builder(launch=args.launch, qa_gate=not args.skip_qa_gate)
        print("BUILD:", build["status"], "returncode=", build.get("returncode"))
        if build.get("status") == "skipped_missing_inputs":
            print(build["reason"])
            for missing in build["missing"]:
                print("  -", missing)
        elif build.get("status") == "fail":
            print(build.get("stdout", "")[-3000:])
            print(build.get("stderr", "")[-3000:])
    state["build"] = build

    hard_fail = build.get("status") == "fail"
    state["status"] = "pass" if not hard_fail and not state["errors"] else "partial"
    atomic_write_json(report_dir / "all_report.json", state)
    if generic_comparison is not None:
        atomic_write_json(report_dir / "comparison.json", generic_comparison)
    if prinny_compatibility is not None:
        atomic_write_json(report_dir / "prinny_compatibility.json", prinny_compatibility)
    write_dashboard(
        report_dir / "index.html",
        analyses=state["analyses"],
        comparison=generic_comparison,
        prinny_compatibility=prinny_compatibility,
        qa=qa,
    )

    _write_progress(
        report_dir,
        stage="완료" if state["status"] == "pass" else "부분 완료",
        percent=100,
        status=state["status"],
        message=str(report_dir / "index.html"),
    )
    _print_heading("완료")
    print("HTML :", report_dir / "index.html")
    print("JSON :", report_dir / "all_report.json")
    if prinny_compatibility:
        print("PRINNY 2:", prinny_compatibility["grade"], prinny_compatibility["verdict"])
    print("추출본은 기본적으로 삭제되어 디스크 공간을 계속 차지하지 않습니다.")
    return 0 if state["status"] == "pass" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="psp_toolkit.py",
        description="PSP 게임 통합 한글패치 분석·QA·빌드 도구",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    storage = commands.add_parser("prepare-storage", help="D: 드라이브에 game2와 통합툴 작업 공간 준비")
    storage.add_argument("--data-root", type=Path, help="D:의 Linux 마운트 경로 또는 작업 폴더")
    storage.add_argument("--no-migrate-game2", action="store_true", help="game2.iso 이동은 하지 않음")
    storage.set_defaults(handler=cmd_prepare_storage)

    doctor = commands.add_parser("doctor", help="필수 도구와 프로젝트 상태 검사")
    doctor.add_argument("--output", type=Path, default=Path("workspace/reports/psp_toolkit/doctor.json"))
    doctor.set_defaults(handler=cmd_doctor)

    cleanup = commands.add_parser("cleanup", help="재생성 가능한 대용량 중간 파일 안전 정리")
    cleanup.add_argument("--apply", action="store_true", help="실제로 삭제; 없으면 미리보기만")
    cleanup.add_argument("--output", type=Path, default=Path("workspace/reports/psp_toolkit/cleanup.json"))
    cleanup.set_defaults(handler=cmd_cleanup)

    analyze = commands.add_parser("analyze", help="ISO/CSO/추출 폴더 분석")
    analyze.add_argument("source", type=Path)
    analyze.add_argument("--label", default="game")
    analyze.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    analyze.add_argument("--output", type=Path)
    analyze.add_argument("--force-extract", action="store_true")
    analyze.add_argument("--low-space", action="store_true", help="핵심 파일만 추출")
    analyze.add_argument("--cleanup-extracted", action="store_true", help="분석 후 추출본 삭제")
    analyze.set_defaults(handler=cmd_analyze)

    strings = commands.add_parser("strings", help="실행 파일/리소스의 Shift-JIS 문자열 후보 추출")
    strings.add_argument("source", type=Path)
    strings.add_argument("--output-dir", type=Path, default=Path("workspace/reports/string_scan"))
    strings.add_argument("--relaxed", action="store_true", help="NUL 종료가 아닌 후보도 포함")
    strings.set_defaults(handler=cmd_strings)

    qa = commands.add_parser("prinny-qa", help="프리니 번역·글리프·미포함 문자열 QA")
    qa.add_argument("--csv", type=Path, default=Path("workspace/translations/export/translation_master.csv"))
    qa.add_argument("--master", type=Path, default=Path("workspace/translations/export/translation_master.json"))
    qa.add_argument("--allocation", type=Path, default=Path("workspace/font/audited_allocation_977/hangul_allocation.json"))
    qa.add_argument("--catalog", type=Path, default=Path("workspace/translations/catalog/catalog.json"))
    qa.add_argument("--output-dir", type=Path, default=DEFAULT_QA_REPORT_DIR)
    qa.set_defaults(handler=cmd_prinny_qa)

    compare = commands.add_parser("compare", help="game.iso와 game2.iso 비교")
    compare.add_argument("game1", nargs="?", type=Path, default=Path("game.iso"))
    compare.add_argument("game2", nargs="?", type=Path, default=DEFAULT_GAME2)
    compare.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    compare.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    compare.add_argument("--force-extract", action="store_true")
    compare.add_argument("--full-extract", action="store_false", dest="low_space", help="전체 ISO 추출")
    compare.add_argument("--keep-extracted", action="store_false", dest="cleanup_extracted", help="추출본 유지")
    compare.set_defaults(handler=cmd_compare, low_space=True, cleanup_extracted=True)

    build_cmd = commands.add_parser("build-v5", help="Galmuri14 V5 안전 빌드")
    build_cmd.add_argument("--launch", action="store_true", help="완료 후 PPSSPP 실행")
    build_cmd.add_argument("--skip-qa-gate", action="store_true")
    build_cmd.set_defaults(handler=cmd_build_v5)

    all_parser = commands.add_parser("all", help="정리→QA→game1/game2 분석→호환성→V5 빌드")
    all_parser.add_argument("--game1", type=Path, default=Path("game.iso"))
    all_parser.add_argument("--game2", type=Path, default=DEFAULT_GAME2)
    all_parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    all_parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    all_parser.add_argument("--force-extract", action="store_true")
    all_parser.add_argument("--skip-build", action="store_true")
    all_parser.add_argument("--skip-qa-gate", action="store_true")
    all_parser.add_argument("--launch", action="store_true")
    all_parser.add_argument("--full-extract", action="store_false", dest="low_space", help="전체 ISO 추출")
    all_parser.add_argument("--keep-extracted", action="store_false", dest="cleanup_extracted", help="추출본 유지")
    all_parser.add_argument("--no-cleanup-regenerable", action="store_false", dest="cleanup_regenerable", help="대용량 재생성 파일 사전 정리를 하지 않음")
    all_parser.set_defaults(
        handler=cmd_all,
        low_space=True,
        cleanup_extracted=True,
        cleanup_regenerable=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (FileNotFoundError, PSPImageError, PrinnyProbeError, StorageError, ValueError, OSError) as error:
        print("ERROR:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
