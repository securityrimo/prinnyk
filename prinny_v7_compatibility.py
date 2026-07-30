#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from profiles.prinny.executable_qa import scan_prinny_executable_strings
from profiles.prinny.probe import compare_prinny_profiles, probe_prinny_disc
from psp_localization.compare import compare_disc_analyses
from psp_localization.iso import (
    analyze_disc,
    cleanup_prepared_disc,
    prepare_disc,
)
from psp_localization.util import atomic_write_json


PROJECT = Path(__file__).resolve().parent


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def write_state(
    path: Path,
    *,
    status: str,
    progress: int,
    stage: str,
    detail: str,
    **extra: Any,
) -> None:
    previous: dict[str, Any] = {}
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    payload = {
        **previous,
        "format": "prinny_v7_compatibility_state_v1",
        "status": status,
        "progress": int(progress),
        "stage": stage,
        "detail": detail,
        "updated_at": now(),
        "pid": os.getpid(),
        **extra,
    }
    atomic_write_json(path, payload)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_summary(analysis: dict[str, Any], wanted: str) -> dict[str, Any]:
    for item in analysis.get("files", []):
        if str(item.get("path", "")).casefold() == wanted.casefold():
            return {
                "path": item.get("path", wanted),
                "size": item.get("size", 0),
                "sha1": item.get("sha1", ""),
                "hash_mode": item.get("hash_mode", ""),
            }
    return {"path": wanted, "present": False}


def compatibility_plan(
    compatibility: dict[str, Any],
    analyses: dict[str, dict[str, Any]],
    probes: dict[str, dict[str, Any]],
    executable_scans: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    grade = str(compatibility.get("grade", "C"))
    simultaneous = grade in {"A", "B"}

    if grade == "A":
        strategy = (
            "프리니 1과 같은 추출·압축·폰트·빌드 코어를 재사용하고, "
            "프리니 2 번역 카탈로그와 Expected Write 자료만 별도 관리합니다."
        )
    elif grade == "B":
        strategy = (
            "공통 PSP/프리니 코어를 재사용하되 프리니 2용 자원 이름, "
            "압축 설정, 주소·제어코드 규칙을 별도 프로필로 추가합니다."
        )
    else:
        strategy = (
            "프리니 2 전용 프로필을 먼저 구현해야 합니다. 번역문과 고정 주소를 "
            "프리니 1에서 직접 복사하지 않습니다."
        )

    shared = [
        "PSP ISO/CSO 최소 추출기",
        "NISPACK 및 LZS 분석 코어",
        "문자열 후보 스캐너",
        "번역 QA와 글리프 인벤토리",
        "Expected Write 및 원본 SHA 검증",
        "PPSSPP 검증·보고서 파이프라인",
    ]
    separate = [
        "게임별 번역 카탈로그와 번역 마스터",
        "게임별 원본 SHA 및 Expected Write",
        "START/SYSTEM/SCRIPT 자원 주소",
        "BOOT.BIN/EBOOT.BIN UI 패치 주소",
        "게임별 화면 폭·제어코드 규칙",
    ]

    return {
        "format": "prinny_simultaneous_localization_plan_v1",
        "grade": grade,
        "simultaneous_localization_possible": simultaneous,
        "strategy": strategy,
        "shared_components": shared,
        "game_specific_components": separate,
        "safety_rules": [
            "원본 ISO는 읽기 전용으로 사용하고 결과 ISO는 별도 경로에 생성합니다.",
            "프리니 1 캐릭터 말투 번역을 자동 교정하지 않습니다.",
            "동일 원문이어도 문맥이 증명되기 전에는 프리니 2로 번역을 자동 복사하지 않습니다.",
            "Expected Write 불일치 또는 실제 변경 0개인 패치는 성공 처리하지 않습니다.",
            "저작 게임 데이터와 ISO는 Git 저장소에 포함하지 않습니다.",
        ],
        "games": {
            label: {
                "disc_id": analyses[label].get("game", {}).get("disc_id", ""),
                "title": analyses[label].get("game", {}).get("title", ""),
                "system_dat": file_summary(
                    analyses[label], "PSP_GAME/USRDIR/SYSTEM.DAT"
                ),
                "script_dat": file_summary(
                    analyses[label], "PSP_GAME/USRDIR/SCRIPT.DAT"
                ),
                "start_resource_count": probes[label]["start"]["record_count"],
                "font": probes[label].get("font", {}),
                "executable_japanese_candidates": executable_scans[label].get(
                    "candidate_count", 0
                ),
            }
            for label in ("game1", "game2")
        },
        "next_stages": [
            {
                "stage": "prinny1_runtime_repair",
                "description": "■·한자 잔존·문장 잘림을 실제 런타임 근거로 재연결",
            },
            {
                "stage": "prinny1_ui_profile",
                "description": "난이도·튜토리얼·HUD 등 BOOT/EBOOT UI 3개 그룹 분리",
            },
            {
                "stage": "prinny2_catalog",
                "description": (
                    "프리니 2 전용 문자열 카탈로그와 번역 준비 자료 생성"
                    if simultaneous
                    else "프리니 2 전용 포맷 연구와 프로필 구현"
                ),
            },
            {
                "stage": "psp_localization_studio",
                "description": "프로젝트·번역·폰트·QA·빌드 UI 통합",
            },
        ],
        "created_at": now(),
    }


def write_html(
    path: Path,
    *,
    analyses: dict[str, dict[str, Any]],
    compatibility: dict[str, Any],
    plan: dict[str, Any],
    scans: dict[str, dict[str, Any]],
) -> None:
    grade = html.escape(str(compatibility.get("grade", "?")))
    verdict = html.escape(str(compatibility.get("verdict", "")))
    strategy = html.escape(str(plan.get("strategy", "")))

    game_cards = []
    for label in ("game1", "game2"):
        analysis = analyses[label]
        game = analysis.get("game", {})
        probe_game = plan["games"][label]
        game_cards.append(
            f"""
            <section class="card">
              <h2>{html.escape(label.upper())}</h2>
              <p class="title">{html.escape(str(game.get("title", "")))}</p>
              <div class="metrics">
                <div><b>{html.escape(str(game.get("disc_id", "-")))}</b><span>DISC ID</span></div>
                <div><b>{analysis.get("file_count", 0)}</b><span>최소 추출 파일</span></div>
                <div><b>{probe_game.get("start_resource_count", 0)}</b><span>START 자원</span></div>
                <div><b>{scans[label].get("candidate_count", 0)}</b><span>BOOT/UI 후보</span></div>
              </div>
            </section>
            """
        )

    reasons = "".join(
        f"<li>{html.escape(str(reason))}</li>"
        for reason in compatibility.get("reasons", [])
    )
    next_stages = "".join(
        f"<li><b>{html.escape(item['stage'])}</b> — "
        f"{html.escape(item['description'])}</li>"
        for item in plan.get("next_stages", [])
    )
    raw = html.escape(
        json.dumps(
            {
                "compatibility": compatibility,
                "plan": plan,
                "analyses": analyses,
                "executable_scans": scans,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    document = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prinny 1 / 2 V7.0 Compatibility</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--ok:#3fb950}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,"Noto Sans KR",sans-serif}}
header{{padding:22px;border-bottom:1px solid var(--line);background:var(--panel)}}
main{{max-width:1250px;margin:auto;padding:18px;display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:14px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:17px}}
h1,h2{{margin:0 0 10px}} .title{{color:var(--muted)}}
.metrics{{display:grid;grid-template-columns:repeat(2,minmax(100px,1fr));gap:8px}}
.metrics div{{border:1px solid var(--line);border-radius:9px;padding:10px;background:#0d1117}}
.metrics b{{display:block;font-size:18px}} .metrics span{{font-size:12px;color:var(--muted)}}
.grade{{font-size:72px;font-weight:900;color:var(--accent);line-height:1}}
.wide{{grid-column:1/-1}} pre{{white-space:pre-wrap;word-break:break-word;max-height:560px;overflow:auto;background:#06090e;padding:12px;border-radius:9px}}
.badge{{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:5px 10px;color:var(--ok)}}
</style>
</head>
<body>
<header>
  <h1>Prinny 1 / Prinny 2 V7.0 호환성 분석</h1>
  <span class="badge">원본 ISO 읽기 전용 · 최소 추출 · 분석 후 추출본 정리</span>
</header>
<main>
{''.join(game_cards)}
<section class="card wide">
  <div class="grade">{grade}</div>
  <h2>호환성 판정</h2>
  <p>{verdict}</p>
  <p><b>동시 진행 전략:</b> {strategy}</p>
  <ul>{reasons}</ul>
</section>
<section class="card wide">
  <h2>다음 단계</h2>
  <ol>{next_stages}</ol>
</section>
<details class="card wide">
  <summary>전체 분석 JSON</summary>
  <pre>{raw}</pre>
</details>
</main>
</body>
</html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def checkpoint_v7() -> dict[str, Any]:
    script = PROJECT / "RELEASE_CHECKPOINT.sh"
    if not script.is_file():
        return {
            "status": "skipped",
            "reason": f"체크포인트 스크립트 없음: {script}",
        }

    process = subprocess.run(
        ["bash", str(script), "7.0"],
        cwd=PROJECT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "status": "pass" if process.returncode == 0 else "warning",
        "returncode": process.returncode,
        "stdout": process.stdout[-8000:],
        "stderr": process.stderr[-8000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game1", type=Path, required=True)
    parser.add_argument("--game2", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--keep-extracted", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-checkpoint", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    report_dir = args.report_dir.expanduser().resolve()
    status_file = args.status_file.expanduser().resolve()
    game1 = args.game1.expanduser().resolve()
    game2 = args.game2.expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    status_file.parent.mkdir(parents=True, exist_ok=True)

    write_state(
        status_file,
        status="running",
        progress=1,
        stage="입력 확인",
        detail="프리니 1·2 ISO와 분석 환경을 확인합니다.",
        game1=str(game1),
        game2=str(game2),
        report_dir=str(report_dir),
    )

    for label, source in (("game1", game1), ("game2", game2)):
        if not source.is_file():
            raise FileNotFoundError(f"{label} ISO가 없습니다: {source}")
    if shutil.which("7z") is None:
        raise RuntimeError("7z 명령을 찾지 못했습니다.")

    analyses: dict[str, dict[str, Any]] = {}
    probes: dict[str, dict[str, Any]] = {}
    scans: dict[str, dict[str, Any]] = {}
    cleanup: dict[str, dict[str, Any]] = {}

    stages = {
        "game1": (8, 30),
        "game2": (36, 62),
    }

    for label, source in (("game1", game1), ("game2", game2)):
        start_progress, end_progress = stages[label]
        write_state(
            status_file,
            status="running",
            progress=start_progress,
            stage=f"{label} 최소 추출",
            detail=f"{source.name}에서 핵심 파일 6개를 읽기 전용으로 추출합니다.",
        )
        disc_root, manifest = prepare_disc(
            source,
            run_dir / label,
            force=args.force,
            extraction_mode="minimal",
        )
        atomic_write_json(report_dir / f"{label}_extract_manifest.json", manifest)

        write_state(
            status_file,
            status="running",
            progress=start_progress + 8,
            stage=f"{label} 구조 분석",
            detail="PARAM.SFO, SYSTEM.DAT, SCRIPT.DAT 구조와 해시를 분석합니다.",
        )
        analysis = analyze_disc(disc_root, analysis_scope="minimal")
        analyses[label] = analysis
        atomic_write_json(report_dir / f"{label}_analysis.json", analysis)

        write_state(
            status_file,
            status="running",
            progress=start_progress + 14,
            stage=f"{label} 프리니 프로필 탐지",
            detail="NISPACK, START.LZS, 폰트 테이블과 START 자원을 검사합니다.",
        )
        probe = probe_prinny_disc(disc_root)
        probes[label] = probe
        atomic_write_json(report_dir / f"{label}_probe.json", probe)

        write_state(
            status_file,
            status="running",
            progress=end_progress - 3,
            stage=f"{label} 실행 파일 UI 스캔",
            detail="BOOT.BIN/EBOOT.BIN의 일본어 UI 문자열 후보를 수집합니다.",
        )
        scan = scan_prinny_executable_strings(
            disc_root,
            report_dir / f"{label}_executable_strings",
        )
        scans[label] = {
            "source": scan.get("source", ""),
            "candidate_count": scan.get("candidate_count", 0),
            "csv": str(
                report_dir / f"{label}_executable_strings" / "strings.csv"
            ),
            "json": str(
                report_dir / f"{label}_executable_strings" / "strings.json"
            ),
        }

        if not args.keep_extracted:
            cleanup[label] = cleanup_prepared_disc(run_dir / label)

    write_state(
        status_file,
        status="running",
        progress=70,
        stage="공통 구조 비교",
        detail="프리니 1과 프리니 2의 파일·압축·폰트·스크립트 구조를 비교합니다.",
    )
    generic = compare_disc_analyses(analyses["game1"], analyses["game2"])
    compatibility = compare_prinny_profiles(probes["game1"], probes["game2"])
    atomic_write_json(report_dir / "disc_comparison.json", generic)
    atomic_write_json(report_dir / "prinny_compatibility.json", compatibility)

    write_state(
        status_file,
        status="running",
        progress=82,
        stage="동시 한글화 계획 생성",
        detail="A/B/C 판정에 따라 공통 코어와 게임별 프로필 범위를 분리합니다.",
        grade=compatibility.get("grade", "?"),
    )
    plan = compatibility_plan(
        compatibility,
        analyses,
        probes,
        scans,
    )
    atomic_write_json(report_dir / "simultaneous_localization_plan.json", plan)

    combined = {
        "format": "prinny_v7_compatibility_report_v1",
        "created_at": now(),
        "inputs": {"game1": str(game1), "game2": str(game2)},
        "analyses": analyses,
        "probes": probes,
        "executable_scans": scans,
        "disc_comparison": generic,
        "compatibility": compatibility,
        "plan": plan,
        "cleanup": cleanup,
        "status": "pass",
    }
    atomic_write_json(report_dir / "all_report.json", combined)
    write_html(
        report_dir / "index.html",
        analyses=analyses,
        compatibility=compatibility,
        plan=plan,
        scans=scans,
    )

    checkpoint: dict[str, Any]
    if args.no_checkpoint:
        checkpoint = {"status": "skipped", "reason": "--no-checkpoint"}
    else:
        write_state(
            status_file,
            status="running",
            progress=94,
            stage="GitHub V7.0 체크포인트",
            detail="소스와 문서를 커밋하고 v7.0 태그를 저장합니다.",
            grade=compatibility.get("grade", "?"),
        )
        checkpoint = checkpoint_v7()
    combined["github_checkpoint"] = checkpoint
    atomic_write_json(report_dir / "all_report.json", combined)

    checkpoint_text = checkpoint.get("status", "unknown")
    write_state(
        status_file,
        status="complete",
        progress=100,
        stage="완료",
        detail=(
            f"호환성 {compatibility['grade']} · "
            f"동시 진행 {'가능' if plan['simultaneous_localization_possible'] else '전용 프로필 필요'} · "
            f"GitHub {checkpoint_text}"
        ),
        grade=compatibility["grade"],
        verdict=compatibility["verdict"],
        simultaneous_localization_possible=plan[
            "simultaneous_localization_possible"
        ],
        report_html=str(report_dir / "index.html"),
        report_json=str(report_dir / "all_report.json"),
        github_checkpoint=checkpoint,
    )
    print(json.dumps(
        {
            "grade": compatibility["grade"],
            "verdict": compatibility["verdict"],
            "simultaneous_localization_possible": plan[
                "simultaneous_localization_possible"
            ],
            "report_html": str(report_dir / "index.html"),
            "report_json": str(report_dir / "all_report.json"),
            "github_checkpoint": checkpoint,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # 상태 파일 인자를 최소한으로 다시 찾는다.
        status_path: Path | None = None
        try:
            if "--status-file" in sys.argv:
                status_path = Path(
                    sys.argv[sys.argv.index("--status-file") + 1]
                ).expanduser().resolve()
        except Exception:
            status_path = None

        if status_path is not None:
            try:
                write_state(
                    status_path,
                    status="error",
                    progress=100,
                    stage="오류",
                    detail=str(error),
                    error=str(error),
                    traceback=traceback.format_exc()[-12000:],
                )
            except Exception:
                pass
        traceback.print_exc()
        raise SystemExit(2)
