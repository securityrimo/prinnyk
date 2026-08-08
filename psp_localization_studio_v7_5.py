#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parent


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"객체 JSON이 아닙니다: {path}")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV 헤더가 없습니다: {path}")
        return [
            {str(key): value or "" for key, value in row.items()}
            for row in reader
        ]


def write_state(
    path: Path,
    *,
    status: str,
    progress: int,
    stage: str,
    detail: str,
    **extra: Any,
) -> None:
    old: dict[str, Any] = {}
    if path.is_file():
        try:
            old = read_json(path)
        except Exception:
            old = {}
    atomic_json(
        path,
        {
            **old,
            "format": "psp_localization_studio_v7_5_state_v1",
            "status": status,
            "progress": int(progress),
            "stage": stage,
            "detail": detail,
            "updated_at": now(),
            "pid": os.getpid(),
            **extra,
        },
    )


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_preview_assets(source_root: Path, output_root: Path) -> list[str]:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    if not source_root.is_dir():
        return copied

    for source in sorted(source_root.rglob("*.png")):
        relative = source.relative_to(source_root)
        target = output_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(str(Path("assets/font_previews") / relative))
    return copied


def parse_preview_data(
    preview_report: dict[str, Any],
    copied_assets: list[str],
) -> list[dict[str, Any]]:
    by_name = {Path(item).name: item for item in copied_assets}
    result: list[dict[str, Any]] = []

    for candidate in preview_report.get("candidates", []):
        candidate_meta = candidate.get("candidate", {})
        name = str(candidate_meta.get("name", "unknown"))
        layouts = []
        for item in candidate.get("layout_results", []):
            preview = Path(str(item.get("preview", ""))).name
            relative = by_name.get(preview, "")
            layouts.append(
                {
                    "layout": str(item.get("layout", "")),
                    "score": item.get("score", ""),
                    "rendered_tiles": item.get("rendered_tiles", 0),
                    "available_tiles": item.get("available_tiles", 0),
                    "nonempty_tile_ratio": item.get(
                        "nonempty_tile_ratio", ""
                    ),
                    "balanced_tile_ratio": item.get(
                        "balanced_tile_ratio", ""
                    ),
                    "preview": relative,
                }
            )
        result.append(
            {
                "name": name,
                "scope": str(candidate_meta.get("scope", "")),
                "sha1": str(candidate_meta.get("sha1", "")),
                "evidence_score": candidate_meta.get(
                    "evidence_score", ""
                ),
                "verdict": str(candidate_meta.get("verdict", "")),
                "layouts": layouts,
            }
        )
    return result


def count_status(rows: list[dict[str, str]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        status = row.get("status", "").strip() or "unknown"
        result[status] = result.get(status, 0) + 1
    return result


def build_summary(
    reports: dict[str, dict[str, Any]],
    translations: list[dict[str, str]],
    p1_queue: list[dict[str, str]],
    fonts: list[dict[str, Any]],
) -> dict[str, Any]:
    v7_0 = reports["v7_0"]
    v7_1 = reports["v7_1"]
    v7_2 = reports["v7_2"]
    v7_3 = reports["v7_3"]
    v7_4 = reports["v7_4"]

    v7_2_stats = v7_2.get("statistics", {})
    p2_translation = v7_4.get("prinny2_translation", {})
    p2_font = v7_4.get("prinny2_font", {})

    return {
        "format": "psp_localization_studio_project_state_v1",
        "version": "7.5",
        "created_at": now(),
        "projects": {
            "prinny1": {
                "name": "Prinny 1",
                "status": "runtime_repair_required",
                "hangul_rendering": "pass_user_verified",
                "character_voice": "pass_user_verified",
                "unresolved_runtime_issues": len(p1_queue),
                "known_symptoms": [
                    "문장 깨짐",
                    "■ 글리프",
                    "한자 잔존",
                    "문장 잘림",
                    "BOOT/EBOOT UI 미번역",
                ],
                "translation_wording_locked": True,
                "build_gate": "blocked",
                "build_gate_reason": (
                    "18개 오류의 실제 자원·오프셋·Expected Write "
                    "연결이 완료되지 않았습니다."
                ),
            },
            "prinny2": {
                "name": "Prinny 2",
                "compatibility_grade": (
                    v7_0.get("compatibility", {}).get("grade", "")
                ),
                "dedicated_profile": True,
                "parallel_localization_possible": bool(
                    v7_1.get("parallel_development_possible", True)
                ),
                "raw_candidates": v7_2_stats.get(
                    "raw_occurrences", 0
                ),
                "unique_strings": v7_2_stats.get(
                    "unique_strings", 0
                ),
                "translate_candidates": (
                    v7_2_stats.get("unique_categories", {})
                    .get("translate", 0)
                ),
                "review_candidates": (
                    v7_2_stats.get("unique_categories", {})
                    .get("review", 0)
                ),
                "batch_001_count": len(translations),
                "context_linked": p2_translation.get(
                    "context_linked", 0
                ),
                "safe_budget_linked": p2_translation.get(
                    "safe_budget_linked", 0
                ),
                "high_priority_font_candidates": p2_font.get(
                    "high_priority_candidates", len(fonts)
                ),
                "font_layout_confirmation": "pending",
                "build_gate": "blocked",
                "build_gate_reason": (
                    "실제 렌더러에 연결된 폰트·코드맵 위치가 아직 "
                    "확정되지 않았고 승인 번역도 없습니다."
                ),
            },
        },
        "translation": {
            "batch_status_counts": count_status(translations),
            "auto_translation_applied": False,
            "prinny1_translation_copied_to_prinny2": False,
            "character_voice_policy": "translator_declared",
        },
        "tool": {
            "name": "PSP Localization Studio",
            "stage": "alpha",
            "features": [
                "프로젝트 현황",
                "번역 편집·검색·상태 분류",
                "CSV/JSON 가져오기·내보내기",
                "바이트 용량 1차 검사",
                "폰트 미리보기와 후보 선택",
                "QA 및 빌드 게이트",
                "내부 분류 조회",
                "우선 참고 자료와 안전 규칙",
            ],
            "not_implemented": [
                "브라우저에서 ISO 직접 수정",
                "렌더러 연결이 증명되지 않은 폰트 자동 적용",
                "Expected Write 없는 패치 생성",
                "번역자 말투 자동 교정",
            ],
        },
        "source_reports": {
            "v7_0": v7_0.get("format", ""),
            "v7_1": v7_1.get("format", ""),
            "v7_2": v7_2.get("format", ""),
            "v7_3": v7_3.get("format", ""),
            "v7_4": v7_4.get("format", ""),
        },
    }


def app_html(
    *,
    summary: dict[str, Any],
    translations: list[dict[str, str]],
    p1_queue: list[dict[str, str]],
    fonts: list[dict[str, Any]],
    report_links: dict[str, str],
) -> str:
    state_json = json.dumps(summary, ensure_ascii=False).replace(
        "</", "<\\/"
    )
    translation_json = json.dumps(
        translations, ensure_ascii=False
    ).replace("</", "<\\/")
    p1_json = json.dumps(p1_queue, ensure_ascii=False).replace(
        "</", "<\\/"
    )
    font_json = json.dumps(fonts, ensure_ascii=False).replace(
        "</", "<\\/"
    )
    links_json = json.dumps(report_links, ensure_ascii=False).replace(
        "</", "<\\/"
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSP Localization Studio V7.5 Alpha</title>
<style>
:root{{--bg:#0b0f14;--panel:#121821;--panel2:#171f2b;--line:#293343;--text:#e8eef7;--muted:#8d99aa;--accent:#5da8ff;--ok:#45c56d;--warn:#e5ad35;--bad:#f05d62;--purple:#b38cff}}
*{{box-sizing:border-box}}html,body{{margin:0;height:100%;background:var(--bg);color:var(--text);font-family:system-ui,"Noto Sans KR",sans-serif}}
button,input,select,textarea{{font:inherit}}button{{cursor:pointer}}
header{{height:66px;display:flex;align-items:center;gap:12px;padding:10px 18px;background:var(--panel);border-bottom:1px solid var(--line)}}
header h1{{font-size:19px;margin:0;flex:1}}.version{{color:var(--accent);font-weight:800}}
header button{{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 11px}}
.shell{{display:grid;grid-template-columns:230px 1fr;height:calc(100% - 66px)}}
nav{{background:var(--panel);border-right:1px solid var(--line);padding:12px;overflow:auto}}
nav button{{display:block;width:100%;text-align:left;background:transparent;color:var(--muted);border:0;border-radius:8px;padding:11px;margin-bottom:4px}}
nav button:hover,nav button.active{{background:var(--panel2);color:var(--text)}}main{{overflow:auto;padding:18px}}
.view{{display:none}}.view.active{{display:block}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:15px;min-width:0}}.wide{{grid-column:1/-1}}.half{{grid-column:span 2}}
.metric{{font-size:32px;font-weight:900;color:var(--accent)}}.muted{{color:var(--muted)}}.ok{{color:var(--ok)}}.warn{{color:var(--warn)}}.bad{{color:var(--bad)}}.purple{{color:var(--purple)}}
.badge{{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:4px 8px;font-size:12px;margin:2px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--muted);font-size:12px}}
a{{color:#79b8ff}}code{{color:#8dc2ff;word-break:break-all}}.toolbar{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}}
.toolbar input,.toolbar select,.editor select{{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px}}
.toolbar input{{min-width:260px;flex:1}}.toolbar button,.editor button{{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px}}
.translation-layout{{display:grid;grid-template-columns:430px 1fr;height:calc(100vh - 135px);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
.string-list{{overflow:auto;background:var(--panel);border-right:1px solid var(--line)}}.string-item{{padding:10px 12px;border-bottom:1px solid var(--line);cursor:pointer}}
.string-item:hover,.string-item.active{{background:var(--panel2)}}.string-source{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.string-meta{{font-size:11px;color:var(--muted);margin-top:4px}}
.editor{{overflow:auto;padding:18px;background:var(--panel)}}.label{{font-size:12px;color:var(--muted);margin:13px 0 6px}}.source-box,.context-box{{background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:12px;white-space:pre-wrap;line-height:1.55}}
textarea{{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:11px;min-height:130px;resize:vertical}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}}.metrics div{{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px}}.metrics b{{display:block;font-size:18px}}.metrics span{{font-size:11px;color:var(--muted)}}
.font-candidate{{margin-bottom:16px}}.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:9px}}figure{{margin:0;background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:8px}}figure.selected{{outline:2px solid var(--accent)}}figure img{{width:100%;image-rendering:pixelated;background:#000;max-height:330px;object-fit:contain}}figcaption{{font-size:12px;color:var(--muted);margin-top:6px}}
.gate{{display:grid;grid-template-columns:130px 1fr;gap:10px;padding:10px;border-bottom:1px solid var(--line)}}.gate:last-child{{border:0}}.gate strong{{text-transform:uppercase}}
details{{border:1px solid var(--line);border-radius:9px;padding:10px;margin:8px 0;background:var(--panel2)}}summary{{cursor:pointer;font-weight:700}}
.empty{{color:var(--muted);padding:25px}}.notice{{border-left:4px solid var(--warn);padding:10px 12px;background:rgba(229,173,53,.08);border-radius:6px}}
@media(max-width:1050px){{.grid{{grid-template-columns:repeat(2,1fr)}}.translation-layout{{grid-template-columns:360px 1fr}}}}
@media(max-width:760px){{.shell{{grid-template-columns:1fr}}nav{{display:flex;border-right:0;border-bottom:1px solid var(--line);overflow:auto}}nav button{{min-width:max-content}}main{{padding:10px}}.grid{{grid-template-columns:1fr}}.wide,.half{{grid-column:auto}}.translation-layout{{grid-template-columns:1fr;height:auto}}.string-list{{height:40vh;border-right:0;border-bottom:1px solid var(--line)}}.editor{{min-height:55vh}}}}
</style>
</head>
<body>
<header>
<h1>3순위 · PSP Localization Studio <span class="version">V7.5.2 Alpha</span></h1>
<button id="openMainReport">통합 보고서</button>
<button id="exportProject">프로젝트 상태 저장</button>
</header>
<div class="shell">
<nav>
<button data-view="dashboard" class="active">프로젝트 현황</button>
<button data-view="translation">번역 편집</button>
<button data-view="font">폰트 연구실</button>
<button data-view="qa">QA·빌드 게이트</button>
<button data-view="classification">내부 분류 조회</button>
<button data-view="rules">사용법·안전 규칙</button>
</nav>
<main>
<section id="dashboard" class="view active">
<section class="card wide notice priority-banner"><strong>작업 우선순위:</strong> 1순위 프리니 1 · 2순위 프리니 2 · 3순위 통합툴. 프리니 1의 18개 오류 증거 연결 전까지 프리니 2 신규 묶음과 일반 통합툴 확장을 보류합니다.</section>
<div class="grid">
<div class="card"><h3>1순위 · 프리니 1</h3><div class="metric bad" id="p1Issues"></div><p class="muted">미해결 런타임 오류</p></div>
<div class="card"><h3>2순위 · 프리니 2</h3><div class="metric" id="p2Candidates"></div><p class="muted">우선 번역 후보</p></div>
<div class="card"><h3>번역 묶음 001</h3><div class="metric purple" id="batchCount"></div><p class="muted">문맥·슬롯 연결 완료</p></div>
<div class="card"><h3>폰트 후보</h3><div class="metric warn" id="fontCount"></div><p class="muted">고우선 후보</p></div>
<div class="card half"><h3>프리니 1 상태</h3><div id="p1Summary"></div></div>
<div class="card half"><h3>프리니 2 상태</h3><div id="p2Summary"></div></div>
<div class="card wide"><h3>현재 결론 · 프리니 1 최우선</h3>
<p>프리니 1은 한글 폰트와 캐릭터 말투는 정상이나, 문장 깨짐·■·한자 잔존·잘림·UI 미번역이 남아 있어 새 패치를 만들 수 없습니다.</p>
<p>프리니 2는 전용 프로필로 병행 한글화가 가능하며, 번역 후보와 폰트 후보를 확보했습니다. 렌더러 연결과 승인 번역 전에는 ISO를 생성하지 않습니다.</p>
</div>
</div>
</section>

<section id="translation" class="view">
<div class="toolbar">
<input id="stringSearch" placeholder="원문·번역·자원·오프셋 검색">
<select id="stringStatus"><option value="">전체 상태</option><option value="untranslated">미번역</option><option value="working">작업 중</option><option value="done">완료</option><option value="review">검토</option></select>
<button id="importTranslation">CSV/JSON 열기</button><input id="translationFile" type="file" accept=".csv,.json" hidden>
<button id="saveBrowser">브라우저 임시 저장</button>
<button id="exportCsv">편집 CSV 저장</button>
<button id="exportJson">JSON 저장</button>
<button id="runSafety">지금 전체 검사</button>
</div>
<div class="translation-layout">
<div id="stringList" class="string-list"></div>
<div id="translationEditor" class="editor"></div>
</div>
</section>

<section id="font" class="view">
<div class="toolbar">
<button id="exportFontDecision">폰트 선택 결과 저장</button>
<span class="muted">미리보기는 레이아웃 후보 증거이며 실제 렌더러 확정이 아닙니다.</span>
</div>
<div id="fontLab"></div>
</section>

<section id="qa" class="view">
<div class="grid">
<div class="card half"><h3>프리니 1 빌드 게이트</h3><div id="p1Gates"></div></div>
<div class="card half"><h3>프리니 2 빌드 게이트</h3><div id="p2Gates"></div></div>
<div class="card wide"><h3>프리니 1 런타임 증거 큐</h3><div id="p1Queue"></div></div>
<div class="card wide"><h3>자동 검사 결과</h3><pre id="safetyResult" class="source-box">아직 실행하지 않았습니다.</pre></div>
</div>
</section>

<section id="classification" class="view">
<div class="grid">
<div class="card"><h3>원시 후보</h3><div class="metric" id="rawCandidates"></div></div>
<div class="card"><h3>고유 문자열</h3><div class="metric" id="uniqueStrings"></div></div>
<div class="card"><h3>수동 검토</h3><div class="metric warn" id="reviewCandidates"></div></div>
<div class="card"><h3>제외 후보</h3><div class="metric muted" id="rejectedCandidates"></div></div>
<div class="card wide"><h3>원본 분석 보고서</h3><div id="reportLinks"></div></div>
</div>
</section>

<section id="rules" class="view">
<div class="grid">
<div class="card wide"><h3>우선 참고 자료</h3>
<ol>
<li>create-kr-patch-template — 원본 계보, Expected Write, 재현 가능한 빌드, 런타임 증거</li>
<li>Font Share — 플랫폼·글리프 크기·BPP·라이선스 조사</li>
<li>hancharacter — translator_declared 말투 보존, LOSS/INVENTION 방지</li>
<li>hanpatch — 한글패치 프로젝트 구조 참고</li>
<li>제공된 SRWF_F_CUE_BIN_Translation_Editor_v5_2.html — 탭·번역·폰트·안전검사 작업 흐름 참고</li>
</ol></div>
<div class="card half"><h3>허용되는 자동 수정</h3><p>바이트 초과, 미등록 글리프, 종료·포인터·제어코드 오류, 명백한 일본어 잔존처럼 기계적으로 증명되는 결함만 허용합니다.</p></div>
<div class="card half"><h3>금지되는 자동 수정</h3><p>캐릭터 말투, 어미, 감탄사, 반복, 말줄임표, 번역자의 표현 선택을 자동 교정하지 않습니다.</p></div>
<div class="card wide notice"><strong>V7.5 알파 제한:</strong> 이 HTML은 번역 자료와 선택 결과만 저장합니다. ISO, SYSTEM.DAT, START.DAT, BOOT.BIN, EBOOT.BIN을 브라우저에서 수정하지 않습니다.</div>
</div>
</section>
</main>
</div>

<script>
const projectState={state_json};
const initialTranslations={translation_json};
const prinny1Queue={p1_json};
const fontCandidates={font_json};
const reportLinks={links_json};

const storageKey="psp_localization_studio_v7_5_translations";
const fontStorageKey="psp_localization_studio_v7_5_font_decision";
let translations=initialTranslations.map(row=>({{...row}}));
try{{
 const saved=JSON.parse(localStorage.getItem(storageKey)||"null");
 if(Array.isArray(saved)&&saved.length)translations=saved;
}}catch(_e){{}}
let selectedTranslation=translations.length?String(translations[0].batch_id||translations[0].source_id||0):null;
let fontDecision={{candidate:"",layout:"",note:"",status:"pending"}};
try{{fontDecision={{...fontDecision,...JSON.parse(localStorage.getItem(fontStorageKey)||"{{}}")}};}}catch(_e){{}}

const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
const cell=value=>`"${{String(value??"").replaceAll('"','""')}}"`;
function download(name,content,type){{const blob=new Blob([content],{{type}}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}
function switchView(id){{document.querySelectorAll(".view").forEach(x=>x.classList.toggle("active",x.id===id));document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("active",x.dataset.view===id));}}
document.querySelectorAll("nav button").forEach(button=>button.onclick=()=>switchView(button.dataset.view));

function badge(text,kind=""){{return `<span class="badge ${{kind}}">${{esc(text)}}</span>`;}}
function renderDashboard(){{
 const p1=projectState.projects.prinny1,p2=projectState.projects.prinny2;
 document.getElementById("p1Issues").textContent=p1.unresolved_runtime_issues;
 document.getElementById("p2Candidates").textContent=p2.translate_candidates;
 document.getElementById("batchCount").textContent=p2.batch_001_count;
 document.getElementById("fontCount").textContent=p2.high_priority_font_candidates;
 document.getElementById("p1Summary").innerHTML=
   badge("한글 표기 정상","ok")+badge("말투 유지","ok")+badge("빌드 차단","bad")+
   `<p>${{esc(p1.build_gate_reason)}}</p>`;
 document.getElementById("p2Summary").innerHTML=
   badge(`호환성 ${{p2.compatibility_grade}}`,"warn")+badge("전용 프로필","purple")+badge("병행 가능","ok")+badge("빌드 차단","bad")+
   `<p>${{esc(p2.build_gate_reason)}}</p>`;
 document.getElementById("rawCandidates").textContent=p2.raw_candidates;
 document.getElementById("uniqueStrings").textContent=p2.unique_strings;
 document.getElementById("reviewCandidates").textContent=p2.review_candidates;
 document.getElementById("rejectedCandidates").textContent=projectState.projects.prinny2.raw_candidates-projectState.projects.prinny2.translate_candidates-projectState.projects.prinny2.review_candidates;
 document.getElementById("reportLinks").innerHTML=Object.entries(reportLinks).map(([name,path])=>`<p><a href="${{esc(path)}}">${{esc(name)}}</a></p>`).join("");
}}

function translationId(row){{return String(row.batch_id||row.source_id||row.unique_id||row.id||"");}}
function filteredTranslations(){{
 const query=document.getElementById("stringSearch").value.trim().toLowerCase();
 const status=document.getElementById("stringStatus").value;
 return translations.filter(row=>{{
   const hay=`${{row.source||row.text||""}} ${{row.translation||""}} ${{row.resources||""}} ${{row.representative_occurrences||""}}`.toLowerCase();
   return(!status||row.status===status)&&(!query||hay.includes(query));
 }});
}}
function estimateBytes(text){{let total=0;for(const ch of [...String(text||"")])total+=ch.charCodeAt(0)<=0x7f?1:2;return total;}}
function renderTranslationList(){{
 const rows=filteredTranslations(),list=document.getElementById("stringList");
 list.innerHTML=rows.length?rows.map(row=>{{
  const id=translationId(row),source=row.source||row.text||"";
  return `<div class="string-item ${{id===selectedTranslation?"active":""}}" data-id="${{esc(id)}}"><div class="string-source">${{esc(source)}}</div><div class="string-meta">${{esc(row.status||"untranslated")}} · 슬롯 ${{esc(row.safe_slot_bytes||"?")}}B · ${{esc(row.context_link_status||"")}}</div></div>`;
 }}).join(""):'<div class="empty">검색 결과가 없습니다.</div>';
 list.querySelectorAll("[data-id]").forEach(item=>item.onclick=()=>{{selectedTranslation=item.dataset.id;renderTranslationList();renderTranslationEditor();}});
}}
function renderTranslationEditor(){{
 const row=translations.find(item=>translationId(item)===selectedTranslation),editor=document.getElementById("translationEditor");
 if(!row){{editor.innerHTML='<div class="empty">왼쪽에서 항목을 선택하세요.</div>';return;}}
 const source=row.source||row.text||"",budget=Number(row.safe_slot_bytes||0),used=estimateBytes(row.translation||"");
 const capacity=!budget?"unknown":used<=budget?"pass":"overflow";
 editor.innerHTML=`<div class="label">원문</div><div class="source-box">${{esc(source)}}</div>
 <div class="label">대표 발생 위치</div><div class="context-box">${{esc(row.representative_occurrences||"연결 정보 없음")}}</div>
 <div class="label">번역</div><textarea id="editTranslation">${{esc(row.translation||"")}}</textarea>
 <div class="label">번역자 메모</div><textarea id="editNote" style="min-height:75px">${{esc(row.translator_note||"")}}</textarea>
 <div class="label">상태</div><select id="editStatus">${{["untranslated","working","done","review"].map(value=>`<option value="${{value}}" ${{row.status===value?"selected":""}}>${{value}}</option>`).join("")}}</select>
 <div class="metrics"><div><b>${{esc(row.source_sjis_bytes||estimateBytes(source))}}</b><span>원문 바이트</span></div><div><b>${{esc(row.safe_slot_bytes||"?")}}</b><span>안전 슬롯</span></div><div><b id="usedBytes" class="${{capacity==="overflow"?"bad":capacity==="pass"?"ok":"warn"}}">${{used}}</b><span>번역 추정 바이트</span></div><div><b>${{esc(row.occurrence_count||0)}}</b><span>발생 횟수</span></div></div>
 <div class="label">자원</div><code>${{esc(row.resources||"")}}</code>`;
 const translation=document.getElementById("editTranslation"),note=document.getElementById("editNote"),status=document.getElementById("editStatus");
 translation.oninput=()=>{{row.translation=translation.value;const size=estimateBytes(row.translation);row.translation_sjis_bytes=size;row.capacity_status=!budget?"unknown":size<=budget?"pass":"overflow";const usedEl=document.getElementById("usedBytes");usedEl.textContent=size;usedEl.className=row.capacity_status==="overflow"?"bad":row.capacity_status==="pass"?"ok":"warn";}};
 translation.onchange=renderTranslationList;note.oninput=()=>row.translator_note=note.value;status.onchange=()=>{{row.status=status.value;renderTranslationList();}};
}}
function renderTranslations(){{renderTranslationList();renderTranslationEditor();}}

function parseCsv(text){{
 const rows=[];let row=[],field="",quote=false;
 for(let i=0;i<text.length;i++){{const ch=text[i];if(quote){{if(ch==='"'&&text[i+1]==='"'){{field+='"';i++;}}else if(ch==='"')quote=false;else field+=ch;}}else{{if(ch==='"')quote=true;else if(ch===','){{row.push(field);field="";}}else if(ch==='\\n'){{row.push(field.replace(/\\r$/,""));rows.push(row);row=[];field="";}}else field+=ch;}}}}
 if(field.length||row.length){{row.push(field);rows.push(row);}}
 if(!rows.length)return[];const headers=rows.shift().map(x=>x.replace(/^\\ufeff/,""));
 return rows.filter(r=>r.some(v=>v!=="")).map(r=>Object.fromEntries(headers.map((h,i)=>[h,r[i]??""])));
}}
document.getElementById("stringSearch").oninput=renderTranslationList;
document.getElementById("stringStatus").onchange=renderTranslationList;
document.getElementById("saveBrowser").onclick=()=>{{localStorage.setItem(storageKey,JSON.stringify(translations));alert("브라우저에 임시 저장했습니다.");}};
document.getElementById("exportJson").onclick=()=>download("prinny2_batch_001_v7_5.json",JSON.stringify(translations,null,2),"application/json");
document.getElementById("exportCsv").onclick=()=>{{const fields=Object.keys(translations[0]||{{}});const csv="\\ufeff"+[fields.map(cell).join(","),...translations.map(row=>fields.map(field=>cell(row[field])).join(","))].join("\\r\\n");download("prinny2_batch_001_v7_5.csv",csv,"text/csv;charset=utf-8");}};
document.getElementById("importTranslation").onclick=()=>document.getElementById("translationFile").click();
document.getElementById("translationFile").onchange=event=>{{const file=event.target.files[0];if(!file)return;const reader=new FileReader();reader.onload=()=>{{try{{const loaded=file.name.toLowerCase().endsWith(".json")?JSON.parse(reader.result):parseCsv(reader.result);if(!Array.isArray(loaded))throw new Error("목록 형식이 아닙니다.");translations=loaded;selectedTranslation=translations.length?translationId(translations[0]):null;renderTranslations();alert(`${{translations.length}}개 항목을 불러왔습니다.`);}}catch(error){{alert("불러오기 실패: "+error.message);}}}};reader.readAsText(file,"utf-8");}};

function renderFonts(){{
 const root=document.getElementById("fontLab");
 root.innerHTML=fontCandidates.map(candidate=>`<div class="font-candidate card"><h3>${{esc(candidate.name)}} ${{badge(candidate.verdict,candidate.verdict==="high_priority"?"ok":"warn")}}</h3><p class="muted">증거 점수 ${{esc(candidate.evidence_score)}} · SHA-1 <code>${{esc(candidate.sha1)}}</code></p><div class="gallery">${{candidate.layouts.map(layout=>`<figure data-candidate="${{esc(candidate.name)}}" data-layout="${{esc(layout.layout)}}" class="${{fontDecision.candidate===candidate.name&&fontDecision.layout===layout.layout?"selected":""}}">${{layout.preview?`<img src="${{esc(layout.preview)}}" alt="${{esc(layout.layout)}}">`:""}}<figcaption><input type="radio" name="fontLayout" ${{fontDecision.candidate===candidate.name&&fontDecision.layout===layout.layout?"checked":""}}> ${{esc(layout.layout)}} · 점수 ${{esc(layout.score)}} · 타일 ${{esc(layout.rendered_tiles)}}</figcaption></figure>`).join("")}}</div></div>`).join("")||'<div class="empty">폰트 미리보기가 없습니다.</div>';
 root.querySelectorAll("figure[data-layout]").forEach(figure=>figure.onclick=()=>{{fontDecision.candidate=figure.dataset.candidate;fontDecision.layout=figure.dataset.layout;fontDecision.status="user_selected_pending_runtime_confirmation";localStorage.setItem(fontStorageKey,JSON.stringify(fontDecision));renderFonts();}});
}}
document.getElementById("exportFontDecision").onclick=()=>download("prinny2_font_layout_decision_v7_5.json",JSON.stringify({{...fontDecision,created_at:new Date().toISOString(),warning:"런타임 렌더러 확인 전 임시 선택"}},null,2),"application/json");

function gate(status,title,detail){{const kind=status==="pass"?"ok":status==="blocked"?"bad":"warn";return `<div class="gate"><strong class="${{kind}}">${{esc(status)}}</strong><div><b>${{esc(title)}}</b><div class="muted">${{esc(detail)}}</div></div></div>`;}}
function renderQa(){{
 document.getElementById("p1Gates").innerHTML=[
 gate("pass","한글 폰트 표시","사용자 검수에서 정상"),
 gate("pass","캐릭터 말투","사용자 검수에서 유지"),
 gate("blocked","런타임 구조","18개 오류의 자원·오프셋 미연결"),
 gate("blocked","UI 패치","BOOT/EBOOT UI 그룹 미해결"),
 gate("blocked","새 ISO","Expected Write 증거 부족")
 ].join("");
 document.getElementById("p2Gates").innerHTML=[
 gate("pass","전용 프로필","프리니 1과 분리 완료"),
 gate("pass","번역 문맥","200/200 자원·오프셋 연결"),
 gate("pending","번역 승인","번역자 작업 대기"),
 gate("pending","폰트 레이아웃","시각 후보는 있으나 렌더러 연결 미확정"),
 gate("blocked","첫 패치 ISO","폰트·번역·Expected Write 게이트 미통과")
 ].join("");
 document.getElementById("p1Queue").innerHTML=`<table><thead><tr><th>ID</th><th>분류</th><th>현상</th><th>연결</th><th>수정</th></tr></thead><tbody>${{prinny1Queue.map(row=>`<tr><td>${{esc(row.issue_id||row.id)}}</td><td>${{esc(row.group)}}</td><td>${{esc(row.observation)}}</td><td>${{esc(row.source_link_status)}}</td><td>${{esc(row.translation_change_allowed)}}</td></tr>`).join("")}}</tbody></table>`;
}}
document.getElementById("runSafety").onclick=()=>{{
 const result={{checked_at:new Date().toISOString(),total:translations.length,untranslated:0,overflow:0,missing_context:0,done:0}};
 for(const row of translations){{if(!String(row.translation||"").trim())result.untranslated++;if(row.status==="done")result.done++;const budget=Number(row.safe_slot_bytes||0),used=estimateBytes(row.translation||"");if(budget&&used>budget)result.overflow++;if(row.context_link_status!=="linked")result.missing_context++;}}
 result.build_ready=result.untranslated===0&&result.overflow===0&&result.missing_context===0;
 document.getElementById("safetyResult").textContent=JSON.stringify(result,null,2);switchView("qa");
}};

document.getElementById("exportProject").onclick=()=>download("psp_localization_studio_v7_5_project_state.json",JSON.stringify({{projectState,translation_status:translations.map(row=>({{id:translationId(row),status:row.status,capacity_status:row.capacity_status}})),fontDecision,exported_at:new Date().toISOString()}},null,2),"application/json");
document.getElementById("openMainReport").onclick=()=>window.location.href=reportLinks["V7.4 통합 보고서"];
renderDashboard();renderTranslations();renderFonts();renderQa();
</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    out = args.out.expanduser().resolve()
    status = args.status_file.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    paths = {
        "v7_0": root / "reports/prinny_v7_compatibility/all_report.json",
        "v7_1": root / "reports/prinny_v7_1_parallel/all_report.json",
        "v7_2": root / "reports/prinny_v7_2_curation/all_report.json",
        "v7_3": root / "reports/prinny_v7_3_font_and_editor/all_report.json",
        "v7_4": root / "reports/prinny_v7_4_confirmation/all_report.json",
        "translations": root / "reports/prinny_v7_4_confirmation/prinny2_translation_batch_001_context.csv",
        "p1_queue": root / "reports/prinny_v7_4_confirmation/prinny1_runtime_evidence_queue.csv",
        "preview_report": root / "reports/prinny_v7_4_confirmation/font_preview_report.json",
        "preview_root": root / "reports/prinny_v7_4_confirmation/font_previews",
    }

    write_state(
        status,
        status="running",
        progress=5,
        stage="보고서 수집",
        detail="V7.0부터 V7.4까지의 분석·번역·폰트·QA 자료를 읽습니다.",
    )

    reports = {
        name: read_json(path)
        for name, path in paths.items()
        if name.startswith("v7_")
    }
    translations = read_csv(paths["translations"])
    p1_queue = read_csv(paths["p1_queue"])
    preview_report = read_json(paths["preview_report"])

    write_state(
        status,
        status="running",
        progress=28,
        stage="프로젝트 상태 통합",
        detail="프리니 1·2 상태와 빌드 게이트를 하나의 모델로 통합합니다.",
        prinny1_issues=len(p1_queue),
        translation_batch=len(translations),
    )

    copied_assets = copy_preview_assets(
        paths["preview_root"],
        out / "assets/font_previews",
    )
    fonts = parse_preview_data(preview_report, copied_assets)
    summary = build_summary(
        reports,
        translations,
        p1_queue,
        fonts,
    )

    data_dir = out / "data"
    copy_file(paths["translations"], data_dir / "prinny2_batch_001.csv")
    copy_file(paths["p1_queue"], data_dir / "prinny1_runtime_evidence_queue.csv")
    copy_file(paths["preview_report"], data_dir / "font_preview_report.json")
    atomic_json(data_dir / "project_state.json", summary)

    write_state(
        status,
        status="running",
        progress=58,
        stage="종합툴 화면 생성",
        detail="번역 편집·폰트 연구실·QA·분류·안전 규칙 탭을 생성합니다.",
        font_candidates=len(fonts),
        font_previews=len(copied_assets),
    )

    report_links = {
        "V7.0 호환성 보고서": "../prinny_v7_compatibility/index.html",
        "V7.1 전용 프로필 보고서": "../prinny_v7_1_parallel/index.html",
        "V7.2 후보 정제 보고서": "../prinny_v7_2_curation/index.html",
        "V7.3 폰트·편집기 보고서": "../prinny_v7_3_font_and_editor/index.html",
        "V7.4 통합 보고서": "../prinny_v7_4_confirmation/index.html",
    }
    application = app_html(
        summary=summary,
        translations=translations,
        p1_queue=p1_queue,
        fonts=fonts,
        report_links=report_links,
    )
    app_path = out / "index.html"
    app_path.write_text(application, encoding="utf-8")

    manifest = {
        "format": "psp_localization_studio_v7_5_manifest_v1",
        "version": "7.5",
        "stage": "alpha",
        "created_at": now(),
        "application": str(app_path),
        "project_state": str(data_dir / "project_state.json"),
        "translation_batch": str(data_dir / "prinny2_batch_001.csv"),
        "prinny1_evidence_queue": str(
            data_dir / "prinny1_runtime_evidence_queue.csv"
        ),
        "font_preview_count": len(copied_assets),
        "font_candidate_count": len(fonts),
        "build_capability": {
            "prinny1": False,
            "prinny2": False,
            "reason": (
                "V7.5 알파는 편집·검증·증거 관리 도구이며 "
                "빌드 게이트를 통과하기 전 ISO를 생성하지 않습니다."
            ),
        },
        "translation_policy": {
            "character_voice": "translator_declared",
            "automatic_dialogue_rewrite": False,
            "prinny1_to_prinny2_auto_copy": False,
        },
    }
    atomic_json(out / "manifest.json", manifest)

    write_state(
        status,
        status="complete",
        progress=100,
        stage="완료",
        detail=(
            f"PSP 종합툴 V7.5 알파 생성 · 번역 {len(translations)}개 · "
            f"폰트 후보 {len(fonts)}개 · 프리니 1 오류 {len(p1_queue)}개"
        ),
        application_html=str(app_path),
        manifest_json=str(out / "manifest.json"),
        project_state_json=str(data_dir / "project_state.json"),
        translation_batch=len(translations),
        font_candidates=len(fonts),
        font_previews=len(copied_assets),
        prinny1_issues=len(p1_queue),
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
