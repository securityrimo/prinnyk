#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import shutil
import subprocess
import sys
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from core.start_runtime import StartRuntimeArchive
from core.system_unpack import unpack_system
from core.text_catalog import build_catalog, save_catalog
from psp_localization.iso import prepare_disc
from psp_localization.util import atomic_write_json


PROJECT = Path(__file__).resolve().parent


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
    atomic_write_json(
        path,
        {
            **previous,
            "format": "prinny_v7_1_parallel_state_v1",
            "status": status,
            "progress": int(progress),
            "stage": stage,
            "detail": detail,
            "updated_at": now(),
            "pid": os.getpid(),
            **extra,
        },
    )


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 최상위 값이 객체가 아닙니다: {path}")
    return value


def prepare_minimal(source: Path, output: Path) -> tuple[Path, dict[str, Any]]:
    try:
        return prepare_disc(
            source,
            output,
            force=True,
            extraction_mode="minimal",
        )
    except TypeError:
        # 구형 API에서는 전체 추출로 폴백한다. 작업 폴더는 외장 저장장치다.
        return prepare_disc(source, output, force=True)


def normalized_names(items: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("name", "")).casefold()
        for item in items
        if str(item.get("name", "")).strip()
    }


def resource_diff(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> dict[str, Any]:
    a = {str(item["name"]).casefold(): item for item in left}
    b = {str(item["name"]).casefold(): item for item in right}
    common = sorted(set(a) & set(b))
    changed = []
    same = []
    for name in common:
        if (
            int(a[name].get("size", -1)) == int(b[name].get("size", -2))
            and str(a[name].get("sha1", "")) == str(b[name].get("sha1", ""))
        ):
            same.append(name)
        else:
            changed.append(
                {
                    "name": name,
                    "game1_size": int(a[name].get("size", 0)),
                    "game2_size": int(b[name].get("size", 0)),
                    "game1_sha1": str(a[name].get("sha1", "")),
                    "game2_sha1": str(b[name].get("sha1", "")),
                }
            )
    return {
        "common_count": len(common),
        "same_content_count": len(same),
        "changed_count": len(changed),
        "only_game1": sorted(set(a) - set(b)),
        "only_game2": sorted(set(b) - set(a)),
        "changed": changed,
    }


def build_engine_matrix(report: dict[str, Any]) -> dict[str, Any]:
    probes = report["probes"]
    scans = report.get("executable_scans", {})
    game1 = probes["game1"]
    game2 = probes["game2"]

    checks = [
        {
            "engine": "nispack_system",
            "status": "pass"
            if game1["system"].get("entries") and game2["system"].get("entries")
            else "fail",
            "meaning": "SYSTEM.DAT 목차를 공통 NISPACK 파서로 읽음",
        },
        {
            "engine": "start_lzs",
            "status": "pass"
            if game1["start"].get("lzs_header") and game2["start"].get("lzs_header")
            else "fail",
            "meaning": "START.LZS를 공통 LZS 해제기로 읽음",
        },
        {
            "engine": "start_archive",
            "status": "pass"
            if int(game1["start"].get("record_count", 0)) > 0
            and int(game2["start"].get("record_count", 0)) > 0
            else "fail",
            "meaning": "START 자원 테이블을 공통 파서로 읽음",
        },
        {
            "engine": "font_reader",
            "status": "pass"
            if game1.get("font", {}).get("status") == "pass"
            and game2.get("font", {}).get("status") == "pass"
            else "fail",
            "meaning": "font.fnt/font.txp를 공통 검사기로 읽음",
        },
        {
            "engine": "nispack_script",
            "status": "pass"
            if game1.get("script", {}).get("entries")
            and game2.get("script", {}).get("entries")
            else "review",
            "meaning": "SCRIPT.DAT 목차 공통 파서 사용 여부",
        },
        {
            "engine": "executable_string_scan",
            "status": "pass"
            if int(scans.get("game1", {}).get("candidate_count", 0)) > 0
            and int(scans.get("game2", {}).get("candidate_count", 0)) > 0
            else "review",
            "meaning": "BOOT/EBOOT 문자열 후보 공통 스캐너 사용 여부",
        },
    ]

    pass_count = sum(item["status"] == "pass" for item in checks)
    conclusion = (
        "shared_core_with_dedicated_profile"
        if pass_count >= 4
        else "dedicated_engine_research_required"
    )
    return {
        "format": "prinny_shared_engine_matrix_v1",
        "checks": checks,
        "pass_count": pass_count,
        "total": len(checks),
        "conclusion": conclusion,
        "parallel_development_possible": pass_count >= 4,
        "note": (
            "이 판정은 공통 포맷 엔진의 재사용 가능성입니다. "
            "프리니 1 번역문·주소·코드맵을 프리니 2에 복사해도 된다는 뜻은 아닙니다."
        ),
    }


def profile_document(
    report: dict[str, Any],
    matrix: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    analysis = report["analyses"]["game2"]
    probe = report["probes"]["game2"]
    game = analysis.get("game", {})
    compatibility = report.get("compatibility", {})
    return {
        "format": "psp_localization_game_profile_v1",
        "profile_id": "prinny2_jp",
        "display_name": "Prinny 2 Japanese",
        "game": {
            "disc_id": game.get("disc_id", ""),
            "title": game.get("title", ""),
            "disc_version": game.get("disc_version", ""),
        },
        "compatibility_origin": {
            "v7_grade": compatibility.get("grade", ""),
            "v7_verdict": compatibility.get("verdict", ""),
            "shared_engine_conclusion": matrix["conclusion"],
        },
        "containers": {
            "system": {
                "path": "PSP_GAME/USRDIR/SYSTEM.DAT",
                "format": "nispack",
                "entry_names": [
                    item["name"] for item in probe["system"].get("entries", [])
                ],
            },
            "script": {
                "path": "PSP_GAME/USRDIR/SCRIPT.DAT",
                "format": "nispack",
                "entry_names": [
                    item["name"] for item in probe.get("script", {}).get("entries", [])
                ],
            },
            "start": {
                "entry": "start.lzs",
                "compression": "nis_lzs",
                "record_count": probe["start"].get("record_count", 0),
                "resource_names": [
                    item["name"] for item in probe["start"].get("resources", [])
                ],
            },
        },
        "font": probe.get("font", {}),
        "translation_catalog": {
            "format": catalog.get("format", ""),
            "entry_count": catalog.get("entry_count", 0),
            "resource_count": catalog.get("resource_count", 0),
            "catalog_sha1": catalog.get("catalog_sha1", ""),
            "status": "extracted_untranslated",
        },
        "translation_policy": {
            "character_voice": "translator_declared",
            "auto_copy_from_prinny1": False,
            "auto_rewrite_dialogue": False,
            "machine_safe_fixes_only": True,
        },
        "patch_policy": {
            "expected_write_required": True,
            "source_hash_required": True,
            "zero_actual_change_is_failure": True,
            "output_iso_must_be_separate": True,
        },
        "status": "discovery_profile",
        "created_at": now(),
    }


def locate_screenshot_findings() -> Path | None:
    candidates = [
        PROJECT / "workspace/reports/prinny_qa/screenshot_findings.csv",
        PROJECT / "workspace/reports/prinny_stage1_fix/screenshot_findings.csv",
        PROJECT / "workspace/reports/screenshot_findings.csv",
    ]
    for path in candidates:
        if path.is_file():
            return path
    matches = sorted(
        PROJECT.glob("workspace/**/screenshot_findings.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def build_prinny1_queue(
    report: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    source = locate_screenshot_findings()
    rows: list[dict[str, str]] = []
    if source is not None:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [
                {key: value or "" for key, value in row.items()}
                for row in csv.DictReader(handle)
            ]

    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "issue_id",
        "group",
        "observation",
        "source_link_status",
        "repair_policy",
        "translation_change_allowed",
        "status",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        if rows:
            for index, row in enumerate(rows, start=1):
                observation = (
                    row.get("observation")
                    or row.get("description")
                    or row.get("finding")
                    or ""
                )
                lowered = observation.casefold()
                if any(token in lowered for token in ("hud", "튜토리얼", "메뉴", "ui", "난이도", "결과")):
                    group = "boot_eboot_ui"
                elif any(token in lowered for token in ("■", "깨", "glyph", "한자", "영문")):
                    group = "runtime_glyph_or_boundary"
                elif any(token in lowered for token in ("잘림", "trunc", "줄", "spacing", "공백")):
                    group = "capacity_or_layout"
                else:
                    group = "unlinked_runtime_evidence"

                writer.writerow(
                    {
                        "issue_id": row.get("id") or f"SHOT-{index:03d}",
                        "group": group,
                        "observation": observation,
                        "source_link_status": row.get("source_link_status", "unlinked"),
                        "repair_policy": (
                            "실제 자원·오프셋·원본 바이트를 연결한 뒤 구조만 수정"
                        ),
                        "translation_change_allowed": "no",
                        "status": row.get("status", "todo"),
                    }
                )
        else:
            defaults = [
                (
                    "P1-GLYPH",
                    "runtime_glyph_or_boundary",
                    "■·엉뚱한 한자/영문 글리프 잔존",
                ),
                (
                    "P1-LAYOUT",
                    "capacity_or_layout",
                    "문장 중간 또는 끝 잘림",
                ),
                (
                    "P1-UI",
                    "boot_eboot_ui",
                    "난이도·튜토리얼·HUD·결과 화면 미번역",
                ),
            ]
            for issue_id, group, observation in defaults:
                writer.writerow(
                    {
                        "issue_id": issue_id,
                        "group": group,
                        "observation": observation,
                        "source_link_status": "unlinked",
                        "repair_policy": (
                            "실제 자원·오프셋·원본 바이트를 연결한 뒤 구조만 수정"
                        ),
                        "translation_change_allowed": "no",
                        "status": "todo",
                    }
                )

    executable = report.get("executable_scans", {}).get("game1", {})
    return {
        "format": "prinny1_runtime_repair_queue_v1",
        "source_findings": str(source) if source else "",
        "queue_csv": str(output),
        "issue_count": len(rows) if rows else 3,
        "boot_ui_candidate_count": executable.get("candidate_count", 0),
        "translation_policy": (
            "캐릭터 말투와 번역 문구는 변경하지 않고, 런타임 근거가 연결된 구조 결함만 수정"
        ),
    }


def write_markdown(
    path: Path,
    *,
    report: dict[str, Any],
    matrix: dict[str, Any],
    catalog: dict[str, Any],
    profile: dict[str, Any],
    queue: dict[str, Any],
) -> None:
    compatibility = report.get("compatibility", {})
    lines = [
        "# Prinny parallel development V7.1",
        "",
        f"- V7.0 grade: **{compatibility.get('grade', '')}**",
        f"- Verdict: {compatibility.get('verdict', '')}",
        f"- Shared engine checks: **{matrix['pass_count']}/{matrix['total']} pass**",
        (
            "- Parallel development: **possible with a dedicated Prinny 2 profile**"
            if matrix["parallel_development_possible"]
            else "- Parallel development: **additional format-engine research required**"
        ),
        "",
        "## Prinny 1",
        "",
        "- Dialogue wording and character voice are locked.",
        "- Runtime glyph/boundary, capacity/layout, and BOOT/EBOOT UI issues remain separate queues.",
        f"- Runtime queue: `{queue['queue_csv']}`",
        f"- BOOT/UI candidates from V7: {queue['boot_ui_candidate_count']}",
        "",
        "## Prinny 2",
        "",
        f"- Disc ID: `{profile['game']['disc_id']}`",
        f"- Title: {profile['game']['title']}",
        f"- START resources: {profile['containers']['start']['record_count']}",
        f"- Extracted Japanese candidates: {catalog.get('entry_count', 0)}",
        f"- Candidate resources: {catalog.get('resource_count', 0)}",
        "- Translation status: untranslated discovery catalog",
        "- Prinny 1 translations and fixed offsets were not copied.",
        "",
        "## Shared engine matrix",
        "",
    ]
    for item in matrix["checks"]:
        lines.append(
            f"- `{item['engine']}`: **{item['status']}** — {item['meaning']}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(
    path: Path,
    *,
    report: dict[str, Any],
    matrix: dict[str, Any],
    catalog: dict[str, Any],
    profile: dict[str, Any],
    queue: dict[str, Any],
) -> None:
    compatibility = report.get("compatibility", {})
    checks = "".join(
        "<tr>"
        f"<td>{html.escape(item['engine'])}</td>"
        f"<td>{html.escape(item['status'])}</td>"
        f"<td>{html.escape(item['meaning'])}</td>"
        "</tr>"
        for item in matrix["checks"]
    )
    document = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSP Localization Studio V7.1</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--good:#3fb950}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,"Noto Sans KR",sans-serif}}
header{{padding:20px 24px;border-bottom:1px solid var(--line);background:var(--panel)}}
main{{max-width:1280px;margin:auto;padding:18px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:17px}}
.wide{{grid-column:1/-1}}h1,h2{{margin:0 0 10px}}.muted{{color:var(--muted)}}
.metric{{font-size:34px;font-weight:800;color:var(--accent)}}table{{width:100%;border-collapse:collapse}}
th,td{{border-bottom:1px solid var(--line);padding:9px;text-align:left}}code{{color:#79c0ff}}
.badge{{display:inline-block;padding:4px 9px;border:1px solid var(--line);border-radius:999px;color:var(--good)}}
@media(max-width:800px){{main{{grid-template-columns:1fr}}.wide{{grid-column:auto}}}}
</style>
</head>
<body>
<header>
<h1>PSP Localization Studio · V7.1 작업 현황</h1>
<span class="badge">프리니 1 번역 보존 · 프리니 2 전용 프로필</span>
</header>
<main>
<section class="card">
<h2>V7.0 판정</h2>
<div class="metric">{html.escape(str(compatibility.get("grade", "")))}</div>
<p>{html.escape(str(compatibility.get("verdict", "")))}</p>
</section>
<section class="card">
<h2>공통 엔진 재사용</h2>
<div class="metric">{matrix["pass_count"]}/{matrix["total"]}</div>
<p>{html.escape(matrix["conclusion"])}</p>
</section>
<section class="card">
<h2>프리니 1 수정 트랙</h2>
<p>대사 문구와 캐릭터 말투는 잠금 상태입니다.</p>
<p>런타임 오류 큐: <b>{queue["issue_count"]}</b></p>
<p>BOOT/UI 후보: <b>{queue["boot_ui_candidate_count"]}</b></p>
</section>
<section class="card">
<h2>프리니 2 번역 준비</h2>
<p><code>{html.escape(str(profile["game"]["disc_id"]))}</code></p>
<p>{html.escape(str(profile["game"]["title"]))}</p>
<p>일본어 후보: <b>{catalog.get("entry_count", 0)}</b></p>
<p>후보 자원: <b>{catalog.get("resource_count", 0)}</b></p>
</section>
<section class="card wide">
<h2>공통 엔진 검사</h2>
<table><thead><tr><th>엔진</th><th>상태</th><th>의미</th></tr></thead>
<tbody>{checks}</tbody></table>
</section>
<section class="card wide">
<h2>원칙</h2>
<p class="muted">프리니 1 번역·고정 주소를 프리니 2로 자동 복사하지 않습니다.
Expected Write와 원본 해시가 없는 변경은 패치로 승격하지 않습니다.</p>
</section>
</main>
</body>
</html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v7-report", type=Path, required=True)
    parser.add_argument("--game1", type=Path, required=True)
    parser.add_argument("--game2", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()

    report_dir = args.report_dir.expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    status_file = args.status_file.expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_state(
        status_file,
        status="running",
        progress=2,
        stage="V7.0 결과 확인",
        detail="호환성 C의 원인을 공통 엔진과 게임별 프로필 차이로 분해합니다.",
    )
    report = load_json(args.v7_report)
    compatibility = report.get("compatibility", {})
    if compatibility.get("grade") != "C":
        raise ValueError(
            f"이 작업은 C 등급 전용입니다. 현재 등급: {compatibility.get('grade')}"
        )

    write_state(
        status_file,
        status="running",
        progress=12,
        stage="공통 엔진 재사용 판정",
        detail="NISPACK·LZS·START·폰트·실행 파일 스캐너를 항목별로 판정합니다.",
    )
    matrix = build_engine_matrix(report)
    atomic_write_json(report_dir / "shared_engine_matrix.json", matrix)

    write_state(
        status_file,
        status="running",
        progress=24,
        stage="프리니 1 오류 큐 고정",
        detail="번역 문구를 잠그고 런타임·레이아웃·BOOT/UI 문제를 분리합니다.",
        shared_engine_pass=f"{matrix['pass_count']}/{matrix['total']}",
    )
    queue = build_prinny1_queue(
        report,
        report_dir / "prinny1_runtime_repair_queue.csv",
    )
    atomic_write_json(report_dir / "prinny1_runtime_repair_queue.json", queue)

    write_state(
        status_file,
        status="running",
        progress=34,
        stage="프리니 2 최소 추출",
        detail="game2.iso에서 핵심 자원을 외장 작업 폴더로 추출합니다.",
    )
    disc_root, manifest = prepare_minimal(
        args.game2.expanduser().resolve(),
        run_dir / "game2_disc",
    )
    atomic_write_json(report_dir / "game2_extract_manifest.json", manifest)

    system_path = disc_root / "PSP_GAME" / "USRDIR" / "SYSTEM.DAT"
    if not system_path.is_file():
        raise FileNotFoundError(f"프리니 2 SYSTEM.DAT 없음: {system_path}")

    write_state(
        status_file,
        status="running",
        progress=47,
        stage="프리니 2 START 해제",
        detail="SYSTEM.DAT → start.lzs → start.dat을 공통 코어로 검증합니다.",
    )
    unpack_manifest = unpack_system(
        system_path,
        run_dir / "game2_system",
        report_dir / "game2_system_unpack.json",
        force=True,
    )

    archive = StartRuntimeArchive.load(run_dir / "game2_system" / "start.dat")
    runtime_dir = run_dir / "game2_start_runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    archive.extract(runtime_dir)

    write_state(
        status_file,
        status="running",
        progress=63,
        stage="프리니 2 번역 후보 추출",
        detail="START 자원에서 Shift-JIS 일본어 후보와 용량 기초 정보를 만듭니다.",
    )
    catalog = build_catalog(runtime_dir)
    catalog_dir = report_dir / "game2_translation_catalog"
    save_catalog(catalog, catalog_dir)

    write_state(
        status_file,
        status="running",
        progress=76,
        stage="프리니 2 전용 프로필 생성",
        detail="게임별 자원·번역·Expected Write를 프리니 1과 분리합니다.",
    )
    profile = profile_document(report, matrix, catalog)
    atomic_write_json(
        PROJECT / "profiles" / "prinny2" / "profile.json",
        profile,
    )
    atomic_write_json(report_dir / "prinny2_profile_discovery.json", profile)

    diff = resource_diff(
        report["probes"]["game1"]["start"].get("resources", []),
        report["probes"]["game2"]["start"].get("resources", []),
    )
    atomic_write_json(report_dir / "start_resource_diff.json", diff)

    write_state(
        status_file,
        status="running",
        progress=88,
        stage="PSP 종합툴 V7.1 대시보드 생성",
        detail="프리니 1 수정 큐와 프리니 2 번역 준비 현황을 한 화면에 묶습니다.",
    )
    write_markdown(
        report_dir / "README.md",
        report=report,
        matrix=matrix,
        catalog=catalog,
        profile=profile,
        queue=queue,
    )
    write_html(
        report_dir / "index.html",
        report=report,
        matrix=matrix,
        catalog=catalog,
        profile=profile,
        queue=queue,
    )
    shutil.copy2(
        report_dir / "index.html",
        PROJECT / "studio" / "psp_localization_studio_v7_1.html",
    )

    combined = {
        "format": "prinny_v7_1_parallel_report_v1",
        "created_at": now(),
        "v7_compatibility": compatibility,
        "shared_engine_matrix": matrix,
        "prinny1": queue,
        "prinny2": {
            "profile": profile,
            "translation_catalog": {
                "entry_count": catalog.get("entry_count", 0),
                "resource_count": catalog.get("resource_count", 0),
                "catalog_sha1": catalog.get("catalog_sha1", ""),
                "csv": str(catalog_dir / "catalog.csv"),
                "json": str(catalog_dir / "catalog.json"),
                "template": str(catalog_dir / "translation_template.json"),
            },
            "start_resource_diff": diff,
            "system_unpack": unpack_manifest,
        },
        "parallel_development_possible": matrix[
            "parallel_development_possible"
        ],
        "github_checkpoint": {
            "status": "not_due",
            "reason": "V7.1은 0.5 단위가 아니며 다음 자동 체크포인트는 V7.5입니다.",
        },
        "status": "pass",
    }
    atomic_write_json(report_dir / "all_report.json", combined)

    # 추출물은 재생성 가능하므로 삭제한다. 카탈로그와 보고서는 유지한다.
    shutil.rmtree(run_dir / "game2_start_runtime", ignore_errors=True)
    shutil.rmtree(run_dir / "game2_system", ignore_errors=True)
    shutil.rmtree(run_dir / "game2_disc", ignore_errors=True)

    write_state(
        status_file,
        status="complete",
        progress=100,
        stage="완료",
        detail=(
            f"프리니 2 전용 프로필 생성 · 일본어 후보 "
            f"{catalog.get('entry_count', 0)}개 · 공통 엔진 "
            f"{matrix['pass_count']}/{matrix['total']} · "
            f"병행 {'가능' if matrix['parallel_development_possible'] else '추가 연구 필요'}"
        ),
        shared_engine_pass=f"{matrix['pass_count']}/{matrix['total']}",
        parallel_development_possible=matrix[
            "parallel_development_possible"
        ],
        prinny2_catalog_entries=catalog.get("entry_count", 0),
        prinny2_catalog_resources=catalog.get("resource_count", 0),
        prinny1_issue_queue=queue.get("issue_count", 0),
        report_html=str(report_dir / "index.html"),
        report_json=str(report_dir / "all_report.json"),
        catalog_csv=str(catalog_dir / "catalog.csv"),
        profile_json=str(PROJECT / "profiles/prinny2/profile.json"),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
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
