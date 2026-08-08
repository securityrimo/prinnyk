#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [
                {str(key): value or "" for key, value in row.items()}
                for row in csv.DictReader(handle)
            ]
    except OSError:
        return []


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def milestone(
    identifier: str,
    label: str,
    weight: float,
    completion: float,
    evidence: str,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    completion = max(0.0, min(1.0, float(completion)))
    if status is None:
        if completion >= 1:
            status = "complete"
        elif completion > 0:
            status = "partial"
        else:
            status = "pending"
    return {
        "id": identifier,
        "label": label,
        "weight": weight,
        "completion": round(completion, 4),
        "earned": round(weight * completion, 4),
        "status": status,
        "evidence": evidence,
    }


def find_latest_status(reports_root: Path) -> dict[str, Any]:
    candidates = []
    for path in reports_root.glob("*/status.json"):
        try:
            data = load_json(path)
            stamp = path.stat().st_mtime
        except OSError:
            continue
        candidates.append((stamp, path, data))
    if not candidates:
        return {}
    _stamp, path, data = max(candidates, key=lambda item: item[0])
    return {
        "path": str(path),
        "status": data.get("status", ""),
        "stage": data.get("stage", ""),
        "detail": data.get("detail", ""),
        "task_progress": data.get("progress", 0),
        "updated_at": data.get("updated_at", ""),
    }


def prinny1_progress(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    compatibility = load_json(
        root / "reports/prinny_v7_compatibility/all_report.json"
    )
    queue = csv_rows(
        root / "reports/prinny_v7_4_confirmation/"
        "prinny1_runtime_evidence_queue.csv"
    )
    evidence = load_json(
        root / "reports/prinny1_v7_6_evidence_link/all_report.json"
    )
    verified = load_json(
        root / "reports/prinny1_v7_7_expected_write_verify/all_report.json"
    )
    build = load_json(
        root / "reports/prinny1_v7_8_patch_build/all_report.json"
    )
    runtime = load_json(
        root / "reports/prinny1_v7_9_runtime_validation/all_report.json"
    )
    release = load_json(
        root / "reports/prinny1_v8_0_release/all_report.json"
    )

    manual = config.get("manual_verified", {})
    issue_count = len(queue)
    duplicate_audit = load_json(
        root / "reports/prinny1_v7_7_duplicate_audit/all_report.json"
    )
    full_links = int(
        duplicate_audit.get("independent_provisional_links", 0) or 0
    )
    total_issues = int(evidence.get("issue_count", 18) or 18)

    verified_count = int(
        verified.get("verified_expected_writes", 0) or 0
    )
    verified_total = int(
        verified.get("candidate_count", total_issues) or total_issues
    )

    milestones = [
        milestone(
            "source_profile",
            "원본 ISO·자원 프로필",
            10,
            1 if compatibility.get("analyses", {}).get("game1") else 0,
            "V7.0 프리니 1 분석 보고서",
        ),
        milestone(
            "translation_font_baseline",
            "한글 폰트·번역 기반",
            15,
            1
            if (
                manual.get("prinny1_hangul_rendering")
                and manual.get("prinny1_character_voice_preserved")
            )
            else 0,
            "사용자 검수: 한글 폰트 정상·캐릭터 말투 유지",
        ),
        milestone(
            "issue_inventory",
            "런타임 오류 18건 목록화",
            10,
            min(issue_count / 18, 1) if issue_count else 0,
            f"V7.4 오류 큐 {issue_count}/18",
        ),
        milestone(
            "evidence_candidate_link",
            "오류 증거 후보 연결",
            20,
            min(full_links / total_issues, 1) if total_issues else 0,
            (
                "V7.6 18/18은 중복 매핑으로 무효. "f"V7.7 독립 임시 후보 {full_links}/{total_issues}; "
                "Expected Write 재검증 전에는 최종 확정 아님"
            ),
            status=(
                "candidate_complete"
                if full_links >= total_issues and total_issues
                else "partial"
                if full_links
                else "pending"
            ),
        ),
        milestone(
            "expected_write_verification",
            "Expected Write 원본 재검증",
            15,
            (
                min(verified_count / verified_total, 1)
                if verified_total
                else 0
            ),
            f"수동·바이너리 재검증 {verified_count}/{verified_total}",
        ),
        milestone(
            "patch_build",
            "구조 수정·재압축·ISO 빌드",
            15,
            1
            if (
                build.get("status") == "pass"
                and int(build.get("actual_changes", 0) or 0) > 0
            )
            else 0,
            "V7.8 실제 변경·재압축·별도 ISO 게이트",
        ),
        milestone(
            "runtime_validation",
            "PPSSPP 실제 화면 검증",
            10,
            1
            if (
                runtime.get("status") == "pass"
                and runtime.get("user_verified") is True
            )
            else 0,
            "V7.9 사용자 화면 검수",
        ),
        milestone(
            "release",
            "최종 패치·문서화",
            5,
            1 if release.get("status") == "pass" else 0,
            "V8.0 최종 배포 산출물",
        ),
    ]
    score = sum(item["earned"] for item in milestones)
    return {
        "name": "프리니 1",
        "priority": 1,
        "weight": 60,
        "progress": round(score, 1),
        "milestones": milestones,
        "next_milestone": "Expected Write 원본 재검증 18건",
    }


def prinny2_progress(root: Path) -> dict[str, Any]:
    profile = Path.home() / "PrinnyReverseToolkit/profiles/prinny2/profile.json"
    v71 = load_json(root / "reports/prinny_v7_1_parallel/all_report.json")
    v72 = load_json(root / "reports/prinny_v7_2_curation/all_report.json")
    v74 = load_json(root / "reports/prinny_v7_4_confirmation/all_report.json")
    batch = csv_rows(
        root / "reports/prinny_v7_4_confirmation/"
        "prinny2_translation_batch_001_context.csv"
    )

    done = sum(
        row.get("status", "").casefold() == "done"
        and bool(row.get("translation", "").strip())
        for row in batch
    )
    total_translation = int(
        v72.get("statistics", {})
        .get("unique_categories", {})
        .get("translate", 4286)
        or 4286
    )
    context = v74.get("prinny2_translation", {})
    font = v74.get("prinny2_font", {})

    milestones = [
        milestone(
            "dedicated_profile",
            "전용 프로필",
            10,
            1 if profile.is_file() else 0,
            "profiles/prinny2/profile.json",
        ),
        milestone(
            "catalog",
            "문자열 카탈로그",
            10,
            1
            if v71.get("prinny2", {}).get("translation_catalog")
            else 0,
            "V7.1 프리니 2 독립 카탈로그",
        ),
        milestone(
            "curation",
            "후보 정제",
            10,
            1 if v72.get("status") == "pass" else 0,
            "V7.2 후보 정제 보고서",
        ),
        milestone(
            "context_link",
            "문맥·슬롯 연결",
            10,
            (
                min(
                    int(context.get("context_linked", 0) or 0)
                    / max(int(context.get("batch_count", 200) or 200), 1),
                    1,
                )
            ),
            "V7.4 번역 묶음 문맥 연결",
        ),
        milestone(
            "font_confirmation",
            "폰트·코드맵 확정",
            10,
            0.5
            if int(font.get("high_priority_candidates", 0) or 0) > 0
            else 0,
            "고우선 폰트 후보는 있으나 렌더러 연결 미확정",
            status="partial",
        ),
        milestone(
            "translation",
            "번역 완료",
            30,
            min(done / total_translation, 1)
            if total_translation
            else 0,
            f"승인 번역 {done}/{total_translation}",
        ),
        milestone(
            "build",
            "주입·빌드",
            10,
            0,
            "프리니 1 우선 정책으로 신규 빌드 보류",
        ),
        milestone(
            "runtime_release",
            "실행 검증·배포",
            10,
            0,
            "프리니 1 우선 정책으로 보류",
        ),
    ]
    score = sum(item["earned"] for item in milestones)
    return {
        "name": "프리니 2",
        "priority": 2,
        "weight": 25,
        "progress": round(score, 1),
        "milestones": milestones,
        "next_milestone": "프리니 1 핵심 이정표 전까지 현 상태 보존",
    }


def studio_progress(root: Path, project: Path) -> dict[str, Any]:
    manifest = load_json(
        root / "reports/psp_localization_studio_v7_5/manifest.json"
    )
    app = (
        root / "reports/psp_localization_studio_v7_5/index.html"
    )
    text = ""
    if app.is_file():
        try:
            text = app.read_text(encoding="utf-8")
        except OSError:
            text = ""

    plugin_score = 2 / 3 if (
        (project / "profiles/prinny2/profile.json").is_file()
        and (project / "profiles/prinny").is_dir()
    ) else 1 / 3 if (project / "profiles").is_dir() else 0

    milestones = [
        milestone(
            "architecture",
            "공통 코어·프로필 구조",
            10,
            1 if manifest else 0,
            "V7.5 매니페스트와 공통 프로젝트 구조",
        ),
        milestone(
            "dashboard",
            "프로젝트 현황 화면",
            10,
            1 if "프로젝트 현황" in text else 0,
            "V7.5 오프라인 대시보드",
        ),
        milestone(
            "translation_editor",
            "번역 편집기",
            15,
            1 if "번역 편집" in text else 0,
            "CSV/JSON 편집·가져오기·내보내기",
        ),
        milestone(
            "font_lab",
            "폰트 연구실",
            10,
            1 if "폰트 연구실" in text else 0,
            "폰트 후보 미리보기·임시 선택",
        ),
        milestone(
            "qa_gate",
            "QA·빌드 게이트",
            10,
            1 if "QA·빌드 게이트" in text else 0,
            "게임별 빌드 차단 조건 표시",
        ),
        milestone(
            "plugin_framework",
            "게임 플러그인 체계",
            15,
            plugin_score,
            "프리니 1·2 프로필은 있으나 범용 플러그인 완성 전",
            status="partial",
        ),
        milestone(
            "build_integration",
            "실제 빌드 통합",
            20,
            0,
            "검증된 Expected Write 기반 통합 빌더 미완성",
        ),
        milestone(
            "emulator_validation",
            "에뮬레이터 자동 검증",
            10,
            0,
            "PPSSPP 자동 실행·화면 비교 미완성",
        ),
    ]
    score = sum(item["earned"] for item in milestones)
    return {
        "name": "PSP 한글화 통합툴",
        "priority": 3,
        "weight": 15,
        "progress": round(score, 1),
        "milestones": milestones,
        "next_milestone": "프리니 1 수정에 필요한 기능만 지원",
    }


def make_html(state: dict[str, Any]) -> str:
    projects_html = []
    for key in ("prinny1", "prinny2", "studio"):
        project = state["projects"][key]
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(item['label'])}</td>"
            f"<td>{item['weight']}</td>"
            f"<td>{round(item['completion'] * 100)}%</td>"
            f"<td>{html.escape(item['status'])}</td>"
            f"<td>{html.escape(item['evidence'])}</td>"
            "</tr>"
            for item in project["milestones"]
        )
        projects_html.append(
            f"""<section class="card wide">
<h2>{project['priority']}순위 · {html.escape(project['name'])}</h2>
<div class="progress"><div style="width:{project['progress']}%"></div></div>
<p class="metric">{project['progress']}%</p>
<p>전체 프로젝트 가중치 {project['weight']}% · 다음: {html.escape(project['next_milestone'])}</p>
<table><thead><tr><th>마일스톤</th><th>비중</th><th>완료</th><th>상태</th><th>근거</th></tr></thead>
<tbody>{rows}</tbody></table>
</section>"""
        )

    current = state.get("current_task", {})
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSP 전체 프로젝트 진행률</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--ok:#3fb950}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,"Noto Sans KR",sans-serif}}
header{{padding:22px;background:var(--panel);border-bottom:1px solid var(--line)}}main{{max-width:1300px;margin:auto;padding:18px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}.wide{{grid-column:1/-1}}
.metric{{font-size:38px;font-weight:900;color:var(--accent)}}.muted{{color:var(--muted)}}.progress{{height:14px;background:#0d1117;border:1px solid var(--line);border-radius:999px;overflow:hidden}}.progress div{{height:100%;background:var(--accent)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
@media(max-width:800px){{main{{grid-template-columns:1fr}}.wide{{grid-column:auto}}}}
</style></head><body>
<header><h1>PSP 한글화 전체 프로젝트 진행률</h1>
<p class="muted">작업별 100%가 아니라 검증된 전체 마일스톤의 가중 합계입니다.</p></header>
<main>
<section class="card wide">
<h2>전체 진행률</h2>
<div class="progress"><div style="width:{state['overall_progress']}%"></div></div>
<div class="metric">{state['overall_progress']}%</div>
<p>프리니 1 60% · 프리니 2 25% · 통합툴 15%</p>
</section>
<section class="card wide">
<h2>현재 실행 작업</h2>
<p>{html.escape(str(current.get('detail', '실행 중인 작업 없음')))}</p>
<p class="muted">작업 자체 진행률 {current.get('task_progress', 0)}% · 전체 진행률과 별도</p>
</section>
{''.join(projects_html)}
</main></body></html>"""


def calculate(project: Path, root: Path) -> dict[str, Any]:
    config = load_json(
        project / "config/project_progress_weights.json"
    )
    projects = {
        "prinny1": prinny1_progress(root, config),
        "prinny2": prinny2_progress(root),
        "studio": studio_progress(root, project),
    }
    overall = sum(
        item["progress"] * item["weight"] / 100
        for item in projects.values()
    )
    return {
        "format": "psp_localization_overall_progress_v1",
        "version": "7.6.1",
        "updated_at": now(),
        "overall_progress": round(overall, 1),
        "projects": projects,
        "current_task": find_latest_status(root / "reports"),
        "calculation_note": (
            "시간 예측이 아니라 검증된 마일스톤의 가중 합계. "
            "V7.6의 18/18은 자동 증거 후보 연결이며 Expected Write "
            "원본 재검증 전에는 최종 패치 완료로 계산하지 않음."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    root = args.root.expanduser().resolve()
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    state = calculate(project, root)
    atomic_json(out / "project_progress.json", state)
    (out / "index.html").write_text(
        make_html(state),
        encoding="utf-8",
    )

    if args.print:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        print(
            f"전체 {state['overall_progress']}% · "
            f"프리니 1 {state['projects']['prinny1']['progress']}% · "
            f"프리니 2 {state['projects']['prinny2']['progress']}% · "
            f"통합툴 {state['projects']['studio']['progress']}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
