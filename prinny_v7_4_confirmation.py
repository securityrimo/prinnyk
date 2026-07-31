#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import shutil
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw
except ImportError as exc:
    raise SystemExit(
        "Pillow가 필요합니다. 기존 폰트 도구가 사용하는 python3-pil/Pillow를 설치하세요."
    ) from exc


PROJECT = Path(__file__).resolve().parent

LAYOUT_RE = re.compile(
    r"^(?P<width>\d+)x(?P<height>\d+)_(?P<bpp>[1248])bpp$"
)


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
        except Exception:
            previous = {}
    atomic_json(
        path,
        {
            **previous,
            "format": "prinny_v7_4_state_v1",
            "status": status,
            "progress": int(progress),
            "stage": stage,
            "detail": detail,
            "updated_at": now(),
            "pid": os.getpid(),
            **extra,
        },
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV 헤더가 없습니다: {path}")
        return [
            {str(key): value or "" for key, value in row.items()}
            for row in reader
        ]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_int(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def unpack_pixels(
    block: bytes,
    width: int,
    height: int,
    bpp: int,
) -> list[int]:
    total = width * height
    pixels: list[int] = []

    if bpp == 8:
        pixels = list(block[:total])
    elif bpp == 4:
        for byte in block:
            pixels.extend((byte & 0x0F, (byte >> 4) & 0x0F))
            if len(pixels) >= total:
                break
        pixels = [round(value * 255 / 15) for value in pixels]
    elif bpp == 2:
        for byte in block:
            pixels.extend(
                (
                    byte & 0x03,
                    (byte >> 2) & 0x03,
                    (byte >> 4) & 0x03,
                    (byte >> 6) & 0x03,
                )
            )
            if len(pixels) >= total:
                break
        pixels = [round(value * 255 / 3) for value in pixels]
    elif bpp == 1:
        for byte in block:
            for shift in range(8):
                pixels.append(255 if (byte >> shift) & 1 else 0)
                if len(pixels) >= total:
                    break
            if len(pixels) >= total:
                break
    else:
        raise ValueError(f"지원하지 않는 BPP: {bpp}")

    if len(pixels) < total:
        pixels.extend([0] * (total - len(pixels)))
    return pixels[:total]


def tile_metrics(pixels: list[int], width: int, height: int) -> dict[str, float]:
    if not pixels:
        return {
            "nonzero_ratio": 0.0,
            "unique_levels": 0.0,
            "edge_ratio": 0.0,
            "center_ratio": 0.0,
        }

    nonzero = sum(value != 0 for value in pixels)
    unique_levels = len(set(pixels))
    edge_indices = set()
    for x in range(width):
        edge_indices.add(x)
        edge_indices.add((height - 1) * width + x)
    for y in range(height):
        edge_indices.add(y * width)
        edge_indices.add(y * width + width - 1)

    edge_nonzero = sum(pixels[index] != 0 for index in edge_indices)
    center_indices = [
        y * width + x
        for y in range(1, max(1, height - 1))
        for x in range(1, max(1, width - 1))
        if y < height - 1 and x < width - 1
    ]
    center_nonzero = sum(pixels[index] != 0 for index in center_indices)

    return {
        "nonzero_ratio": nonzero / len(pixels),
        "unique_levels": float(unique_levels),
        "edge_ratio": (
            edge_nonzero / len(edge_indices)
            if edge_indices
            else 0.0
        ),
        "center_ratio": (
            center_nonzero / len(center_indices)
            if center_indices
            else 0.0
        ),
    }


def layout_score(
    tile_results: list[dict[str, float]],
    tile_count: int,
) -> tuple[float, dict[str, float]]:
    if not tile_results:
        return -100.0, {
            "nonempty_tile_ratio": 0.0,
            "balanced_tile_ratio": 0.0,
            "mean_edge_ratio": 0.0,
            "mean_levels": 0.0,
        }

    nonempty = [
        item for item in tile_results
        if item["nonzero_ratio"] >= 0.01
    ]
    balanced = [
        item for item in tile_results
        if 0.03 <= item["nonzero_ratio"] <= 0.75
    ]
    nonempty_ratio = len(nonempty) / len(tile_results)
    balanced_ratio = len(balanced) / len(tile_results)
    mean_edge = sum(item["edge_ratio"] for item in tile_results) / len(tile_results)
    mean_levels = sum(item["unique_levels"] for item in tile_results) / len(tile_results)

    score = (
        nonempty_ratio * 30
        + balanced_ratio * 45
        + min(mean_levels, 16) * 1.2
        - max(0.0, mean_edge - 0.55) * 30
    )
    if tile_count < 16:
        score -= 30
    elif tile_count >= 64:
        score += 5

    return round(score, 4), {
        "nonempty_tile_ratio": round(nonempty_ratio, 6),
        "balanced_tile_ratio": round(balanced_ratio, 6),
        "mean_edge_ratio": round(mean_edge, 6),
        "mean_levels": round(mean_levels, 6),
    }


def render_layout(
    data: bytes,
    *,
    layout: str,
    output: Path,
    max_tiles: int = 256,
    scale: int = 2,
) -> dict[str, Any]:
    match = LAYOUT_RE.match(layout)
    if not match:
        raise ValueError(f"레이아웃 이름을 해석하지 못했습니다: {layout}")

    width = int(match.group("width"))
    height = int(match.group("height"))
    bpp = int(match.group("bpp"))
    bytes_per_tile = math.ceil(width * height * bpp / 8)
    available_tiles = len(data) // bytes_per_tile
    tile_count = min(available_tiles, max_tiles)

    if tile_count <= 0:
        return {
            "layout": layout,
            "bytes_per_tile": bytes_per_tile,
            "available_tiles": available_tiles,
            "rendered_tiles": 0,
            "score": -100,
            "preview": "",
        }

    columns = 16 if tile_count >= 16 else max(1, math.ceil(math.sqrt(tile_count)))
    rows = math.ceil(tile_count / columns)
    label_height = 12
    canvas = Image.new(
        "L",
        (
            columns * width * scale,
            rows * (height * scale + label_height),
        ),
        0,
    )
    draw = ImageDraw.Draw(canvas)
    metrics = []

    for index in range(tile_count):
        start = index * bytes_per_tile
        block = data[start:start + bytes_per_tile]
        pixels = unpack_pixels(block, width, height, bpp)
        metrics.append(tile_metrics(pixels, width, height))

        tile = Image.new("L", (width, height))
        tile.putdata(pixels)
        tile = tile.resize((width * scale, height * scale), Image.Resampling.NEAREST)

        x = (index % columns) * width * scale
        y = (index // columns) * (height * scale + label_height)
        canvas.paste(tile, (x, y))
        draw.text((x + 1, y + height * scale), f"{index:03X}", fill=180)

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)

    score, summary = layout_score(metrics, tile_count)
    return {
        "layout": layout,
        "width": width,
        "height": height,
        "bpp": bpp,
        "bytes_per_tile": bytes_per_tile,
        "available_tiles": available_tiles,
        "rendered_tiles": tile_count,
        "score": score,
        **summary,
        "preview": str(output),
    }


def candidate_layouts(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []

    for item in candidate.get("glyph_block_hypotheses", []):
        layout = str(item.get("layout", ""))
        if LAYOUT_RE.match(layout) and layout not in values:
            values.append(layout)

    defaults = (
        "16x16_4bpp",
        "16x20_4bpp",
        "20x16_4bpp",
        "16x16_8bpp",
        "8x8_4bpp",
        "24x24_4bpp",
    )
    for layout in defaults:
        if layout not in values:
            values.append(layout)

    return values[:12]


def enrich_translation_batch(
    batch: list[dict[str, str]],
    occurrences: list[dict[str, str]],
) -> list[dict[str, Any]]:
    by_text: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in occurrences:
        text = row.get("text", "").strip()
        if text:
            by_text[text].append(row)

    enriched = []
    for row in batch:
        source = row.get("source", "").strip()
        matches = by_text.get(source, [])

        lengths = [
            value
            for value in (
                parse_int(item.get("length"))
                for item in matches
            )
            if value is not None and value > 0
        ]
        representative = matches[:5]
        occurrence_refs = " | ".join(
            f"{item.get('resource', '')}@{item.get('offset_hex', '')}"
            for item in representative
        )
        source_sjis = len(source.encode("shift_jis", errors="replace"))

        safe_budget = min(lengths) if lengths else None
        enriched.append(
            {
                **row,
                "source_sjis_bytes": source_sjis,
                "safe_slot_bytes": "" if safe_budget is None else safe_budget,
                "slot_count_with_length": len(lengths),
                "representative_occurrences": occurrence_refs,
                "context_link_status": (
                    "linked" if matches else "unlinked"
                ),
                "translation_sjis_bytes": "",
                "capacity_status": "untranslated",
            }
        )

    return enriched


def create_prinny1_evidence_queue(
    path: Path | None,
    output: Path,
) -> list[dict[str, Any]]:
    if path is not None and path.is_file():
        rows = read_csv(path)
    else:
        rows = []

    result = []
    for index, row in enumerate(rows, start=1):
        result.append(
            {
                "issue_id": (
                    row.get("issue_id")
                    or row.get("id")
                    or f"P1-{index:03d}"
                ),
                "group": row.get("group", ""),
                "observation": row.get("observation", ""),
                "source_link_status": row.get(
                    "source_link_status",
                    "unlinked",
                ),
                "candidate_source": "",
                "candidate_offset": "",
                "expected_original_hex": "",
                "runtime_evidence": "",
                "translation_change_allowed": "no",
                "repair_status": "evidence_required",
            }
        )

    if not result:
        defaults = (
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
        )
        for issue_id, group, observation in defaults:
            result.append(
                {
                    "issue_id": issue_id,
                    "group": group,
                    "observation": observation,
                    "source_link_status": "unlinked",
                    "candidate_source": "",
                    "candidate_offset": "",
                    "expected_original_hex": "",
                    "runtime_evidence": "",
                    "translation_change_allowed": "no",
                    "repair_status": "evidence_required",
                }
            )

    write_csv(output, result)
    return result


def editor_html(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prinny 2 Translation Editor V7.4</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--ok:#3fb950;--bad:#f85149;--warn:#d29922}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,"Noto Sans KR",sans-serif;height:100vh;overflow:hidden}}
header{{height:66px;padding:12px 16px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px}}
header h1{{font-size:18px;margin:0;flex:1}}button,input,select,textarea{{font:inherit}}
button{{background:#21262d;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:7px 10px;cursor:pointer}}
main{{display:grid;grid-template-columns:420px 1fr;height:calc(100vh - 66px)}}aside{{border-right:1px solid var(--line);display:flex;flex-direction:column;min-width:0}}
.filters{{padding:10px;border-bottom:1px solid var(--line);display:grid;grid-template-columns:1fr 120px;gap:7px}}
.filters input,.filters select,section select{{background:#0d1117;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:8px}}
#list{{overflow:auto;flex:1}}.item{{padding:10px 12px;border-bottom:1px solid var(--line);cursor:pointer}}
.item:hover,.item.active{{background:#1f2937}}.src{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.meta{{font-size:11px;color:var(--muted);margin-top:4px}}
section{{overflow:auto;padding:20px}}.panel{{max-width:920px;margin:auto}}.label{{font-size:12px;color:var(--muted);margin:14px 0 6px}}
.source,.context{{background:#0d1117;border:1px solid var(--line);border-radius:9px;padding:13px;white-space:pre-wrap;line-height:1.55}}
textarea{{width:100%;min-height:145px;background:#0d1117;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:12px;resize:vertical}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}}.metrics div{{background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:9px}}
.metrics b{{display:block;font-size:18px}}.metrics span{{font-size:11px;color:var(--muted)}}.ok{{color:var(--ok)}}.bad{{color:var(--bad)}}.warn{{color:var(--warn)}}code{{color:#79c0ff;word-break:break-all}}
@media(max-width:800px){{main{{grid-template-columns:1fr}}aside{{height:42vh;border-right:0;border-bottom:1px solid var(--line)}}section{{height:58vh}}}}
</style></head>
<body>
<header>
<h1>Prinny 2 Translation Editor · V7.4 · Batch 001</h1>
<button id="save">브라우저 저장</button><button id="csv">CSV 내보내기</button><button id="json">JSON 내보내기</button>
</header>
<main>
<aside><div class="filters"><input id="search" placeholder="원문·번역·자원 검색">
<select id="filter"><option value="">전체</option><option value="untranslated">미번역</option><option value="working">작업 중</option><option value="done">완료</option><option value="review">검토</option></select></div><div id="list"></div></aside>
<section><div id="editor" class="panel"></div></section>
</main>
<script>
const initial={payload};
const storageKey="prinny2_v7_4_batch_001";
let rows=initial.map(x=>({{...x}}));
try{{const saved=JSON.parse(localStorage.getItem(storageKey)||"null");if(Array.isArray(saved)&&saved.length===rows.length)rows=saved;}}catch(_e){{}}
let current=rows.length?rows[0].batch_id:null;
const list=document.getElementById("list"),editor=document.getElementById("editor"),search=document.getElementById("search"),filter=document.getElementById("filter");
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[c]));
function visible(){{const q=search.value.trim().toLowerCase();return rows.filter(r=>(!filter.value||r.status===filter.value)&&(!q||`${{r.source}} ${{r.translation}} ${{r.resources}} ${{r.representative_occurrences}}`.toLowerCase().includes(q)));}}
function renderList(){{const data=visible();list.innerHTML=data.length?data.map(r=>`<div class="item ${{r.batch_id===current?"active":""}}" data-id="${{r.batch_id}}"><div class="src">${{esc(r.source)}}</div><div class="meta">${{esc(r.status)}} · 슬롯 ${{r.safe_slot_bytes||"?"}}B · ${{r.context_link_status}}</div></div>`).join(""):'<div class="item">검색 결과 없음</div>';list.querySelectorAll("[data-id]").forEach(el=>el.onclick=()=>{{current=Number(el.dataset.id);renderList();renderEditor();}});}}
function sjisEstimate(text){{let total=0;for(const ch of [...text])total+=ch.charCodeAt(0)<=0x7f?1:2;return total;}}
function renderEditor(){{const r=rows.find(x=>x.batch_id===current);if(!r){{editor.innerHTML="항목을 선택하세요.";return;}}const used=sjisEstimate(r.translation||"");const budget=Number(r.safe_slot_bytes||0);const cap=!budget?"unknown":used<=budget?"pass":"overflow";editor.innerHTML=`<div class="label">원문</div><div class="source">${{esc(r.source)}}</div><div class="label">대표 발생 위치</div><div class="context">${{esc(r.representative_occurrences||"연결 정보 없음")}}</div><div class="label">번역</div><textarea id="translation">${{esc(r.translation)}}</textarea><div class="label">번역자 메모</div><textarea id="note" style="min-height:75px">${{esc(r.translator_note)}}</textarea><div class="label">상태</div><select id="status">${{["untranslated","working","done","review"].map(v=>`<option value="${{v}}" ${{r.status===v?"selected":""}}>${{v}}</option>`).join("")}}</select><div class="metrics"><div><b>${{r.source_sjis_bytes}}</b><span>원문 SJIS 바이트</span></div><div><b>${{r.safe_slot_bytes||"?"}}</b><span>안전 슬롯 바이트</span></div><div><b id="used" class="${{cap==="overflow"?"bad":cap==="pass"?"ok":"warn"}}">${{used}}</b><span>번역 추정 바이트</span></div><div><b>${{r.occurrence_count}}</b><span>발생 횟수</span></div></div><div class="label">자원</div><code>${{esc(r.resources)}}</code>`;const t=document.getElementById("translation"),n=document.getElementById("note"),s=document.getElementById("status");t.oninput=()=>{{r.translation=t.value;const size=sjisEstimate(r.translation);r.translation_sjis_bytes=size;r.capacity_status=!budget?"unknown":size<=budget?"pass":"overflow";document.getElementById("used").textContent=size;document.getElementById("used").className=r.capacity_status==="overflow"?"bad":r.capacity_status==="pass"?"ok":"warn";}};t.onchange=renderList;n.oninput=()=>r.translator_note=n.value;s.onchange=()=>{{r.status=s.value;renderList();}};}}
function download(name,content,type){{const blob=new Blob([content],{{type}}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}
const cell=v=>`"${{String(v??"").replaceAll('"','""')}}"`;
document.getElementById("save").onclick=()=>{{localStorage.setItem(storageKey,JSON.stringify(rows));alert("브라우저에 임시 저장했습니다.");}};
document.getElementById("json").onclick=()=>download("prinny2_batch_001_v7_4.json",JSON.stringify(rows,null,2),"application/json");
document.getElementById("csv").onclick=()=>{{const f=Object.keys(rows[0]||{{}});download("prinny2_batch_001_v7_4.csv","\\ufeff"+[f.map(cell).join(","),...rows.map(r=>f.map(k=>cell(r[k])).join(","))].join("\\r\\n"),"text/csv;charset=utf-8");}};
search.oninput=renderList;filter.onchange=renderList;renderList();renderEditor();
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--blobs", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--prinny1-queue", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()

    evidence_path = args.evidence.expanduser().resolve()
    blobs_dir = args.blobs.expanduser().resolve()
    batch_path = args.batch.expanduser().resolve()
    occurrences_path = args.occurrences.expanduser().resolve()
    p1_queue = (
        args.prinny1_queue.expanduser().resolve()
        if args.prinny1_queue is not None
        else None
    )
    out = args.out.expanduser().resolve()
    status_file = args.status_file.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    write_state(
        status_file,
        status="running",
        progress=3,
        stage="입력 확인",
        detail="V7.3 폰트 증거와 번역 묶음, V7.2 발생 위치를 확인합니다.",
    )
    evidence_doc = json.loads(evidence_path.read_text(encoding="utf-8"))
    candidates = evidence_doc.get("candidates", [])
    high = [
        item for item in candidates
        if item.get("verdict") == "high_priority"
    ]
    if not high:
        high = sorted(
            candidates,
            key=lambda item: -int(item.get("evidence_score", 0)),
        )[:2]

    write_state(
        status_file,
        status="running",
        progress=14,
        stage="고우선 폰트 후보 확보",
        detail=f"{len(high)}개 후보의 실제 바이너리와 레이아웃 가설을 확인합니다.",
        high_priority_fonts=len(high),
    )

    preview_root = out / "font_previews"
    preview_rows: list[dict[str, Any]] = []
    preview_details: list[dict[str, Any]] = []

    for candidate_index, candidate in enumerate(high, start=1):
        blob_path = Path(str(candidate.get("blob_path", "")))
        if not blob_path.is_file():
            fallback = blobs_dir / blob_path.name
            if fallback.is_file():
                blob_path = fallback
        if not blob_path.is_file():
            preview_rows.append(
                {
                    "candidate": candidate.get("name", ""),
                    "layout": "",
                    "score": -100,
                    "rendered_tiles": 0,
                    "available_tiles": 0,
                    "preview": "",
                    "status": "blob_missing",
                }
            )
            continue

        data = blob_path.read_bytes()
        candidate_dir = preview_root / f"{candidate_index:02d}_{re.sub(r'[^A-Za-z0-9._-]+', '_', str(candidate.get('name', 'candidate')))}"
        layouts = candidate_layouts(candidate)
        results = []
        for layout in layouts:
            result = render_layout(
                data,
                layout=layout,
                output=candidate_dir / f"{layout}.png",
            )
            result["candidate"] = candidate.get("name", "")
            result["candidate_sha1"] = candidate.get("sha1", "")
            results.append(result)
            preview_rows.append(
                {
                    "candidate": candidate.get("name", ""),
                    "layout": layout,
                    "score": result["score"],
                    "rendered_tiles": result["rendered_tiles"],
                    "available_tiles": result["available_tiles"],
                    "nonempty_tile_ratio": result.get("nonempty_tile_ratio", ""),
                    "balanced_tile_ratio": result.get("balanced_tile_ratio", ""),
                    "mean_edge_ratio": result.get("mean_edge_ratio", ""),
                    "preview": result["preview"],
                    "status": "rendered",
                }
            )
        results.sort(key=lambda item: -float(item["score"]))
        preview_details.append(
            {
                "candidate": candidate,
                "layout_results": results,
                "best_layout": results[0] if results else None,
            }
        )

    preview_rows.sort(
        key=lambda row: (
            str(row.get("candidate", "")),
            -float(row.get("score", -100)),
        )
    )
    write_csv(out / "font_preview_ranking.csv", preview_rows)
    atomic_json(
        out / "font_preview_report.json",
        {
            "format": "prinny2_font_visual_confirmation_v1",
            "warning": (
                "원시 타일 미리보기는 글리프 배열 후보를 좁히는 증거이며 "
                "실제 렌더러 연결 확정은 아닙니다."
            ),
            "candidates": preview_details,
            "created_at": now(),
        },
    )

    write_state(
        status_file,
        status="running",
        progress=55,
        stage="번역 문맥 연결",
        detail="번역 묶음 200개에 실제 자원·오프셋·안전 슬롯 바이트를 연결합니다.",
        font_previews=len(preview_rows),
    )
    batch = read_csv(batch_path)
    occurrences = read_csv(occurrences_path)
    enriched = enrich_translation_batch(batch, occurrences)
    enriched_csv = out / "prinny2_translation_batch_001_context.csv"
    write_csv(enriched_csv, enriched)

    linked_count = sum(
        row["context_link_status"] == "linked"
        for row in enriched
    )
    budget_count = sum(bool(row["safe_slot_bytes"]) for row in enriched)

    editor_path = out / "prinny2_translation_editor_batch_001_v7_4.html"
    editor_path.write_text(editor_html(enriched), encoding="utf-8")
    shutil.copy2(
        editor_path,
        PROJECT / "studio" / "prinny2_translation_editor_v7_4.html",
    )

    write_state(
        status_file,
        status="running",
        progress=76,
        stage="프리니 1 증거 큐 유지",
        detail="18개 오류를 대사 수정 없이 런타임 근거 연결 대기 상태로 정리합니다.",
        context_linked=linked_count,
        safe_budget_linked=budget_count,
    )
    p1_rows = create_prinny1_evidence_queue(
        p1_queue,
        out / "prinny1_runtime_evidence_queue.csv",
    )

    write_state(
        status_file,
        status="running",
        progress=90,
        stage="통합 보고서 생성",
        detail="폰트 미리보기, 번역 편집기, 프리니 1 증거 큐를 한 보고서에 연결합니다.",
        prinny1_issues=len(p1_rows),
    )

    preview_html = []
    for detail in preview_details:
        candidate = detail["candidate"]
        best = detail.get("best_layout")
        images = []
        for item in detail.get("layout_results", [])[:6]:
            image_path = Path(item["preview"])
            relative = image_path.relative_to(out)
            images.append(
                f'<figure><img src="{html.escape(str(relative))}" alt="{html.escape(item["layout"])}">'
                f'<figcaption>{html.escape(item["layout"])} · 점수 {item["score"]}</figcaption></figure>'
            )
        preview_html.append(
            "<section class='card wide'>"
            f"<h2>{html.escape(str(candidate.get('name', '')))}</h2>"
            f"<p>증거 점수 {candidate.get('evidence_score', '')} · "
            f"최우선 레이아웃 {html.escape(str(best.get('layout', '') if best else '없음'))}</p>"
            f"<div class='gallery'>{''.join(images)}</div>"
            "</section>"
        )

    report = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSP Localization Studio V7.4</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,"Noto Sans KR",sans-serif}}
header{{padding:20px 24px;background:var(--panel);border-bottom:1px solid var(--line)}}main{{max-width:1300px;margin:auto;padding:18px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}.wide{{grid-column:1/-1}}.metric{{font-size:32px;font-weight:900;color:var(--accent)}}.muted{{color:var(--muted)}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}}figure{{margin:0;background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:8px}}img{{width:100%;image-rendering:pixelated;background:#000}}figcaption{{font-size:12px;color:var(--muted);margin-top:6px}}a{{color:#79c0ff}}
@media(max-width:900px){{main{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:600px){{main{{grid-template-columns:1fr}}.wide{{grid-column:auto}}}}
</style></head><body>
<header><h1>PSP Localization Studio · V7.4</h1>
<p class="muted">프리니 2 폰트 시각 확인과 번역 문맥 연결 · 프리니 1 대사 말투 잠금</p></header><main>
<section class="card"><h2>고우선 폰트</h2><div class="metric">{len(high)}</div></section>
<section class="card"><h2>미리보기</h2><div class="metric">{len(preview_rows)}</div></section>
<section class="card"><h2>문맥 연결</h2><div class="metric">{linked_count}/{len(enriched)}</div></section>
<section class="card"><h2>안전 슬롯 연결</h2><div class="metric">{budget_count}/{len(enriched)}</div></section>
<section class="card wide"><h2>번역 작업</h2>
<p><a href="{html.escape(editor_path.name)}">V7.4 번역 편집기 열기</a></p>
<p>대표 발생 위치와 안전 슬롯 바이트를 표시합니다. 브라우저의 바이트 값은 1차 추정이며 실제 적용 전 Python 인코더가 재검증합니다.</p></section>
{''.join(preview_html)}
<section class="card wide"><h2>프리니 1 수정 트랙</h2>
<p>오류 큐 {len(p1_rows)}건 · 번역 문구 변경 허용 0건 · Expected Write와 런타임 근거 연결 후에만 수정합니다.</p>
</section>
</main></body></html>"""
    (out / "index.html").write_text(report, encoding="utf-8")

    combined = {
        "format": "prinny_v7_4_confirmation_report_v1",
        "created_at": now(),
        "prinny2_font": {
            "high_priority_candidates": len(high),
            "preview_count": len(preview_rows),
            "preview_ranking_csv": str(out / "font_preview_ranking.csv"),
            "preview_report_json": str(out / "font_preview_report.json"),
            "preview_directory": str(preview_root),
        },
        "prinny2_translation": {
            "batch_count": len(enriched),
            "context_linked": linked_count,
            "safe_budget_linked": budget_count,
            "context_csv": str(enriched_csv),
            "editor_html": str(editor_path),
            "source_changed": False,
            "auto_translation_applied": False,
        },
        "prinny1": {
            "issue_count": len(p1_rows),
            "evidence_queue_csv": str(
                out / "prinny1_runtime_evidence_queue.csv"
            ),
            "translation_wording_locked": True,
            "patch_applied": False,
        },
        "github_checkpoint": {
            "status": "not_due",
            "reason": "V7.4는 0.5 단위가 아니며 다음 체크포인트는 V7.5",
        },
        "status": "pass",
    }
    atomic_json(out / "all_report.json", combined)

    write_state(
        status_file,
        status="complete",
        progress=100,
        stage="완료",
        detail=(
            f"폰트 후보 {len(high)}개 시각 확인 · "
            f"미리보기 {len(preview_rows)}개 · "
            f"번역 문맥 {linked_count}/{len(enriched)}개 연결 · "
            f"프리니 1 오류 {len(p1_rows)}건 유지"
        ),
        high_priority_fonts=len(high),
        font_previews=len(preview_rows),
        translation_batch=len(enriched),
        context_linked=linked_count,
        safe_budget_linked=budget_count,
        prinny1_issues=len(p1_rows),
        translation_editor_html=str(editor_path),
        font_preview_directory=str(preview_root),
        prinny1_evidence_queue=str(
            out / "prinny1_runtime_evidence_queue.csv"
        ),
        report_html=str(out / "index.html"),
        report_json=str(out / "all_report.json"),
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
