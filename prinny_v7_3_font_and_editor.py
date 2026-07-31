#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import importlib.util
import json
import math
import os
import re
import shutil
import statistics
import struct
import sys
import tempfile
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from core.nispack import NISPack
from core.start_runtime import StartRuntimeArchive


PROJECT = Path(__file__).resolve().parent
POWER_DIMENSIONS = {
    8, 16, 20, 24, 32, 40, 48, 64, 80, 96, 128, 160, 192,
    256, 320, 384, 512, 640, 768, 1024, 1280, 1536, 2048,
}
COMMON_GLYPH_BLOCKS = {
    "8x8_1bpp": 8,
    "8x8_2bpp": 16,
    "8x8_4bpp": 32,
    "8x8_8bpp": 64,
    "16x16_1bpp": 32,
    "16x16_2bpp": 64,
    "16x16_4bpp": 128,
    "16x16_8bpp": 256,
    "16x20_1bpp": 40,
    "16x20_2bpp": 80,
    "16x20_4bpp": 160,
    "16x20_8bpp": 320,
    "20x16_1bpp": 40,
    "20x16_2bpp": 80,
    "20x16_4bpp": 160,
    "20x16_8bpp": 320,
    "24x24_1bpp": 72,
    "24x24_2bpp": 144,
    "24x24_4bpp": 288,
    "24x24_8bpp": 576,
}


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
            "format": "prinny_v7_3_state_v1",
            "status": status,
            "progress": int(progress),
            "stage": stage,
            "detail": detail,
            "updated_at": now(),
            "pid": os.getpid(),
            **extra,
        },
    )


def load_discovery_engine(path: Path):
    spec = importlib.util.spec_from_file_location(
        "prinny_v7_discovery_engine",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"발견 엔진을 불러오지 못했습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = (
        "prepare_minimal",
        "locate_system_dat",
        "permissive_unpack_system",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            "발견 엔진 함수가 부족합니다: " + ", ".join(missing)
        )
    return module


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


def safe_name(name: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return value or fallback


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum(
        (count / total) * math.log2(count / total)
        for count in counts.values()
    )


def magic_name(data: bytes) -> str:
    signatures = [
        (b"MIG.00.1PSP", "psp_gim"),
        (b"TIM2", "tim2"),
        (b"PK\x03\x04", "zip"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"OggS", "ogg"),
        (b"RIFF", "riff"),
        (b"NISPACK", "nispack"),
        (b"LZS", "lzs"),
    ]
    for signature, label in signatures:
        if data.startswith(signature):
            return label
    prefix = data[:16]
    printable = "".join(
        chr(byte) if 0x20 <= byte <= 0x7E else "."
        for byte in prefix
    )
    return f"unknown:{printable}"


def ascii_strings(data: bytes, minimum: int = 4, limit: int = 20) -> list[str]:
    values: list[str] = []
    current = bytearray()
    for byte in data:
        if 0x20 <= byte <= 0x7E:
            current.append(byte)
        else:
            if len(current) >= minimum:
                values.append(current.decode("ascii", errors="replace"))
                if len(values) >= limit:
                    break
            current.clear()
    if len(current) >= minimum and len(values) < limit:
        values.append(current.decode("ascii", errors="replace"))
    return values


def dimension_candidates(data: bytes) -> list[dict[str, Any]]:
    head = data[:0x200]
    found: Counter[tuple[int, int, str]] = Counter()
    for endian, fmt in (("le", "<HH"), ("be", ">HH")):
        for offset in range(0, max(0, len(head) - 3), 2):
            width, height = struct.unpack_from(fmt, head, offset)
            if width in POWER_DIMENSIONS and height in POWER_DIMENSIONS:
                if width * height <= 2048 * 2048:
                    found[(width, height, endian)] += 1
    results = [
        {
            "width": width,
            "height": height,
            "endian": endian,
            "occurrences_in_header": count,
        }
        for (width, height, endian), count in found.most_common(20)
    ]
    return results


def bpp_hypotheses(size: int, dimensions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = []
    for item in dimensions[:10]:
        width = int(item["width"])
        height = int(item["height"])
        pixels = width * height
        if pixels <= 0:
            continue
        bpp = size * 8 / pixels
        nearest = min((1, 2, 4, 8, 16, 32), key=lambda value: abs(value - bpp))
        if abs(nearest - bpp) <= max(0.2, nearest * 0.08):
            values.append(
                {
                    "width": width,
                    "height": height,
                    "estimated_bpp": round(bpp, 4),
                    "nearest_common_bpp": nearest,
                }
            )
    return values


def glyph_block_hypotheses(size: int) -> list[dict[str, Any]]:
    results = []
    for label, block_size in COMMON_GLYPH_BLOCKS.items():
        if block_size > 0 and size % block_size == 0:
            count = size // block_size
            if 16 <= count <= 65536:
                results.append(
                    {
                        "layout": label,
                        "bytes_per_glyph": block_size,
                        "possible_glyph_count": count,
                    }
                )
    results.sort(
        key=lambda item: (
            abs(item["possible_glyph_count"] - 2048),
            item["bytes_per_glyph"],
        )
    )
    return results[:20]


def u16_table_evidence(data: bytes) -> dict[str, Any]:
    if len(data) < 0x100 or len(data) % 2:
        return {
            "possible_u16_table": False,
            "entry_count": len(data) // 2,
        }

    count = len(data) // 2
    sample_count = min(count, 4096)
    values = struct.unpack_from(f"<{sample_count}H", data, 0)
    ascii_identity = (
        sample_count >= 0x7F
        and all(values[index] == index for index in range(0x7F))
    )
    monotonic_pairs = sum(
        values[index] <= values[index + 1]
        for index in range(sample_count - 1)
    )
    monotonic_ratio = (
        monotonic_pairs / (sample_count - 1)
        if sample_count > 1
        else 0.0
    )
    zero_ratio = values.count(0) / sample_count if sample_count else 0.0
    unique_ratio = len(set(values)) / sample_count if sample_count else 0.0

    return {
        "possible_u16_table": (
            ascii_identity
            or len(data) in {0x10000, 0x20000}
            or monotonic_ratio >= 0.85
        ),
        "entry_count": count,
        "ascii_identity": ascii_identity,
        "monotonic_ratio_sample": round(monotonic_ratio, 6),
        "zero_ratio_sample": round(zero_ratio, 6),
        "unique_ratio_sample": round(unique_ratio, 6),
    }


def find_all(data: bytes, needle: bytes, limit: int = 100) -> list[int]:
    if not needle:
        return []
    offsets = []
    start = 0
    while len(offsets) < limit:
        offset = data.find(needle, start)
        if offset < 0:
            break
        offsets.append(offset)
        start = offset + 1
    return offsets


def get_start_blob(archive: StartRuntimeArchive, name: str) -> bytes | None:
    for record in archive.records:
        if record.name.casefold() == name.casefold():
            return archive.data[record.data_offset:record.end_offset]
    return None


def get_system_blob(pack: NISPack, entries: list[dict[str, Any]], name: str) -> bytes | None:
    for item in entries:
        if str(item.get("name", "")).casefold() == name.casefold():
            start = int(item["offset"])
            end = int(item["end"])
            return pack.data[start:end]
    return None


def candidate_verdict(
    *,
    name: str,
    data: bytes,
    magic: str,
    table: dict[str, Any],
    dimensions: list[dict[str, Any]],
    glyphs: list[dict[str, Any]],
    xref_count: int,
) -> tuple[str, int, list[str]]:
    score = 0
    reasons: list[str] = []
    lowered = name.casefold()

    if magic in {"psp_gim", "tim2"}:
        score += 80
        reasons.append("known_texture_magic")
    if lowered.endswith((".gim", ".tm2", ".txp")):
        score += 40
        reasons.append("texture_extension")
    if lowered.endswith(".fnt"):
        score += 55
        reasons.append("font_extension")
    if "font" in lowered or "moji" in lowered or "glyph" in lowered:
        score += 35
        reasons.append("font_semantic_name")
    if "jis" in lowered or "ucs" in lowered:
        score += 35
        reasons.append("code_map_semantic_name")
    if table.get("possible_u16_table"):
        score += 45
        reasons.append("u16_mapping_evidence")
    if table.get("ascii_identity"):
        score += 30
        reasons.append("ascii_identity_map")
    if dimensions:
        score += 15
        reasons.append("plausible_dimensions_in_header")
    if glyphs:
        score += 12
        reasons.append("divisible_by_common_glyph_block")
    if xref_count:
        score += min(30, xref_count * 10)
        reasons.append("executable_name_reference")
    if len(data) < 64:
        score -= 40
        reasons.append("too_small")
    if entropy(data) > 7.95:
        score -= 8
        reasons.append("near_random_entropy")

    if score >= 100:
        verdict = "high_priority"
    elif score >= 60:
        verdict = "medium_priority"
    else:
        verdict = "low_priority"
    return verdict, score, reasons


def select_translation_batch(
    rows: list[dict[str, str]],
    limit: int,
) -> list[dict[str, Any]]:
    prepared = []
    for row in rows:
        text = row.get("text", "").strip()
        if not text:
            continue
        try:
            best_score = int(float(row.get("best_score", "0") or 0))
        except ValueError:
            best_score = 0
        try:
            occurrences = int(float(row.get("occurrence_count", "0") or 0))
        except ValueError:
            occurrences = 0
        try:
            resource_count = int(float(row.get("resource_count", "0") or 0))
        except ValueError:
            resource_count = 0

        length = len(text)
        if length < 2 or length > 160:
            continue

        priority = (
            best_score * 100
            + min(occurrences, 999) * 5
            + min(resource_count, 50) * 3
            - max(0, length - 80)
        )
        prepared.append(
            {
                "batch_id": 0,
                "source_id": row.get("unique_id", ""),
                "source": text,
                "translation": row.get("translation", ""),
                "status": "untranslated",
                "translator_note": row.get("translator_note", ""),
                "best_score": best_score,
                "occurrence_count": occurrences,
                "resource_count": resource_count,
                "resources": row.get("resources", ""),
                "reasons": row.get("reasons", ""),
                "priority": priority,
            }
        )

    prepared.sort(
        key=lambda item: (
            -int(item["priority"]),
            -int(item["occurrence_count"]),
            str(item["source"]),
        )
    )
    selected = prepared[:limit]
    for index, item in enumerate(selected, start=1):
        item["batch_id"] = index
    return selected


def editor_html(rows: list[dict[str, Any]], title: str) -> str:
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escaped_title}</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--ok:#3fb950;--warn:#d29922}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,"Noto Sans KR",sans-serif;height:100vh;overflow:hidden}}
header{{height:64px;padding:12px 18px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px}}
header h1{{font-size:18px;margin:0;flex:1}}button,input,select,textarea{{font:inherit}}
button{{background:#21262d;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:7px 11px;cursor:pointer}}
button:hover{{border-color:var(--accent)}}main{{display:grid;grid-template-columns:420px 1fr;height:calc(100vh - 64px)}}
aside{{border-right:1px solid var(--line);display:flex;flex-direction:column;min-width:0}}
.filters{{padding:10px;border-bottom:1px solid var(--line);display:grid;grid-template-columns:1fr 120px;gap:7px}}
.filters input,.filters select{{background:#0d1117;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:8px}}
#list{{overflow:auto;flex:1}}.item{{padding:10px 12px;border-bottom:1px solid var(--line);cursor:pointer}}
.item:hover,.item.active{{background:#1f2937}}.item .meta{{font-size:11px;color:var(--muted);margin-top:5px}}
.item .src{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}section{{padding:20px;overflow:auto}}
.panel{{max-width:900px;margin:auto}}.label{{font-size:12px;color:var(--muted);margin:14px 0 6px}}
.source{{background:#0d1117;border:1px solid var(--line);border-radius:9px;padding:14px;white-space:pre-wrap;line-height:1.6}}
textarea{{width:100%;min-height:150px;background:#0d1117;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:12px;resize:vertical}}
.info{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}}.info div{{background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:9px}}
.info b{{display:block;font-size:18px}}.info span{{font-size:11px;color:var(--muted)}}.actions{{display:flex;gap:8px;margin-top:14px}}
.status-untranslated{{color:var(--warn)}}.status-done{{color:var(--ok)}}.empty{{padding:30px;color:var(--muted)}}code{{color:#79c0ff;word-break:break-all}}
@media(max-width:800px){{main{{grid-template-columns:1fr}}aside{{height:42vh;border-right:0;border-bottom:1px solid var(--line)}}section{{height:58vh}}}}
</style>
</head>
<body>
<header>
<h1>{escaped_title}</h1>
<button id="saveLocal">브라우저 임시 저장</button>
<button id="exportCsv">CSV 내보내기</button>
<button id="exportJson">JSON 내보내기</button>
</header>
<main>
<aside>
<div class="filters">
<input id="search" placeholder="원문·번역·자원 검색">
<select id="statusFilter">
<option value="">전체 상태</option>
<option value="untranslated">미번역</option>
<option value="working">작업 중</option>
<option value="done">완료</option>
<option value="review">검토</option>
</select>
</div>
<div id="list"></div>
</aside>
<section>
<div id="editor" class="panel"></div>
</section>
</main>
<script>
const initialRows = {payload};
const storageKey = "prinny2_v7_3_batch_001";
let rows = initialRows.map(x => ({{...x}}));
try {{
  const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
  if (Array.isArray(saved) && saved.length === rows.length) rows = saved;
}} catch (_) {{}}
let currentId = rows.length ? rows[0].batch_id : null;

const listEl = document.getElementById("list");
const editorEl = document.getElementById("editor");
const searchEl = document.getElementById("search");
const statusEl = document.getElementById("statusFilter");

function esc(value) {{
  return String(value ?? "").replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch]));
}}
function filteredRows() {{
  const q = searchEl.value.trim().toLowerCase();
  const status = statusEl.value;
  return rows.filter(row => {{
    const hay = `${{row.source}} ${{row.translation}} ${{row.resources}}`.toLowerCase();
    return (!q || hay.includes(q)) && (!status || row.status === status);
  }});
}}
function renderList() {{
  const filtered = filteredRows();
  listEl.innerHTML = filtered.length ? filtered.map(row => `
    <div class="item ${{row.batch_id === currentId ? "active" : ""}}" data-id="${{row.batch_id}}">
      <div class="src">${{esc(row.source)}}</div>
      <div class="meta"><span class="status-${{esc(row.status)}}">${{esc(row.status)}}</span>
      · ${{row.occurrence_count}}회 · 점수 ${{row.best_score}}</div>
    </div>`).join("") : '<div class="empty">검색 결과가 없습니다.</div>';
  listEl.querySelectorAll(".item").forEach(el => {{
    el.addEventListener("click", () => {{
      currentId = Number(el.dataset.id);
      renderList();
      renderEditor();
    }});
  }});
}}
function renderEditor() {{
  const row = rows.find(item => item.batch_id === currentId);
  if (!row) {{
    editorEl.innerHTML = '<div class="empty">왼쪽에서 항목을 선택하세요.</div>';
    return;
  }}
  editorEl.innerHTML = `
    <div class="label">원문</div>
    <div class="source">${{esc(row.source)}}</div>
    <div class="label">번역</div>
    <textarea id="translation">${{esc(row.translation)}}</textarea>
    <div class="label">번역자 메모</div>
    <textarea id="note" style="min-height:80px">${{esc(row.translator_note)}}</textarea>
    <div class="label">상태</div>
    <select id="rowStatus" style="padding:8px;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:7px">
      ${{["untranslated","working","done","review"].map(value =>
        `<option value="${{value}}" ${{row.status === value ? "selected" : ""}}>${{value}}</option>`
      ).join("")}}
    </select>
    <div class="info">
      <div><b>${{row.occurrence_count}}</b><span>발생 횟수</span></div>
      <div><b>${{row.resource_count}}</b><span>자원 수</span></div>
      <div><b id="charCount">${{[...row.translation].length}}</b><span>번역 문자 수</span></div>
    </div>
    <div class="label">자원</div><code>${{esc(row.resources)}}</code>
    <div class="label">분류 근거</div><code>${{esc(row.reasons)}}</code>
    <div class="actions">
      <button id="previous">이전</button>
      <button id="next">다음</button>
    </div>`;
  const translation = document.getElementById("translation");
  const note = document.getElementById("note");
  const rowStatus = document.getElementById("rowStatus");
  translation.addEventListener("input", () => {{
    row.translation = translation.value;
    document.getElementById("charCount").textContent = [...row.translation].length;
  }});
  translation.addEventListener("change", renderList);
  note.addEventListener("input", () => row.translator_note = note.value);
  rowStatus.addEventListener("change", () => {{
    row.status = rowStatus.value;
    renderList();
  }});
  document.getElementById("previous").onclick = () => move(-1);
  document.getElementById("next").onclick = () => move(1);
}}
function move(delta) {{
  const visible = filteredRows();
  const index = visible.findIndex(item => item.batch_id === currentId);
  if (index < 0 || !visible.length) return;
  const next = visible[(index + delta + visible.length) % visible.length];
  currentId = next.batch_id;
  renderList();
  renderEditor();
}}
function download(name, content, type) {{
  const blob = new Blob([content], {{type}});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}}
function csvCell(value) {{
  const text = String(value ?? "");
  return `"${{text.replaceAll('"','""')}}"`;
}}
document.getElementById("saveLocal").onclick = () => {{
  localStorage.setItem(storageKey, JSON.stringify(rows));
  alert("이 브라우저에 임시 저장했습니다.");
}};
document.getElementById("exportJson").onclick = () =>
  download("prinny2_batch_001_translated.json", JSON.stringify(rows, null, 2), "application/json");
document.getElementById("exportCsv").onclick = () => {{
  const fields = Object.keys(rows[0] || {{}});
  const csv = "\\ufeff" + [
    fields.map(csvCell).join(","),
    ...rows.map(row => fields.map(field => csvCell(row[field])).join(","))
  ].join("\\r\\n");
  download("prinny2_batch_001_translated.csv", csv, "text/csv;charset=utf-8");
}};
searchEl.addEventListener("input", renderList);
statusEl.addEventListener("change", renderList);
renderList(); renderEditor();
</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game2", type=Path, required=True)
    parser.add_argument("--translation-memory", type=Path, required=True)
    parser.add_argument("--font-ranking", type=Path, required=True)
    parser.add_argument("--font-discovery", type=Path, required=True)
    parser.add_argument("--discovery-engine", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    game2 = args.game2.expanduser().resolve()
    translation_memory = args.translation_memory.expanduser().resolve()
    font_ranking_path = args.font_ranking.expanduser().resolve()
    font_discovery_path = args.font_discovery.expanduser().resolve()
    discovery_engine_path = args.discovery_engine.expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    out = args.out.expanduser().resolve()
    status_file = args.status_file.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_state(
        status_file,
        status="running",
        progress=3,
        stage="입력 확인",
        detail="V7.2 번역 후보와 네 개의 폰트 후보를 확인합니다.",
    )
    memory_rows = read_csv(translation_memory)
    ranking_rows = read_csv(font_ranking_path)
    font_discovery = json.loads(
        font_discovery_path.read_text(encoding="utf-8")
    )
    if not ranking_rows:
        raise ValueError("폰트 후보 순위가 비어 있습니다.")

    write_state(
        status_file,
        status="running",
        progress=12,
        stage="프리니 2 최소 추출",
        detail="폰트 후보의 실제 바이트와 실행 파일 참조를 읽기 위해 최소 추출합니다.",
        font_candidates=len(ranking_rows),
    )
    engine = load_discovery_engine(discovery_engine_path)
    extract_workspace = run_dir / "game2_disc"
    disc_root, extract_manifest = engine.prepare_minimal(
        game2,
        extract_workspace,
    )
    atomic_json(out / "game2_extract_manifest.json", extract_manifest)
    system_path = engine.locate_system_dat(disc_root)

    write_state(
        status_file,
        status="running",
        progress=26,
        stage="SYSTEM/START 발견",
        detail="SYSTEM.DAT과 START 자원을 비엄격 발견 모드로 해제합니다.",
    )
    system_dir = run_dir / "game2_system"
    archive, system_manifest = engine.permissive_unpack_system(
        system_path,
        system_dir,
        out / "game2_system_discovery_unpack.json",
    )
    pack = NISPack(system_path)
    system_entries = pack.parse(verbose=False)

    executable_blobs: dict[str, bytes] = {}
    for name in ("BOOT.BIN", "EBOOT.BIN"):
        matches = [
            path for path in disc_root.rglob(name)
            if path.is_file()
        ]
        if len(matches) == 1:
            executable_blobs[name] = matches[0].read_bytes()

    write_state(
        status_file,
        status="running",
        progress=42,
        stage="폰트 후보 실제 검증",
        detail="매직·엔트로피·차원·글리프 블록·코드맵·실행 파일 참조를 검사합니다.",
    )
    blobs_dir = out / "font_candidate_blobs"
    blobs_dir.mkdir(parents=True, exist_ok=True)
    evidence_rows: list[dict[str, Any]] = []
    evidence_json: list[dict[str, Any]] = []

    for index, ranking in enumerate(ranking_rows, start=1):
        name = ranking.get("name", "").strip()
        scope = ranking.get("scope", "").strip().casefold()
        if not name:
            continue

        if scope == "start":
            data = get_start_blob(archive, name)
        elif scope == "system":
            data = get_system_blob(pack, system_entries, name)
        else:
            data = get_start_blob(archive, name)
            if data is None:
                data = get_system_blob(pack, system_entries, name)

        if data is None:
            evidence_rows.append(
                {
                    "rank": index,
                    "scope": scope,
                    "name": name,
                    "size": "",
                    "sha1": "",
                    "magic": "",
                    "entropy": "",
                    "zero_ratio": "",
                    "xref_count": 0,
                    "u16_table": False,
                    "ascii_identity": False,
                    "dimension_candidates": 0,
                    "glyph_layout_candidates": 0,
                    "verdict": "missing",
                    "evidence_score": -100,
                    "reasons": "candidate_blob_not_found",
                    "blob_path": "",
                }
            )
            continue

        blob_name = f"{index:02d}_{safe_name(name, f'candidate_{index}')}"
        blob_path = blobs_dir / blob_name
        blob_path.write_bytes(data)

        dimensions = dimension_candidates(data)
        bpp = bpp_hypotheses(len(data), dimensions)
        glyphs = glyph_block_hypotheses(len(data))
        table = u16_table_evidence(data)
        xrefs: dict[str, list[int]] = {}
        needle = name.encode("ascii", errors="ignore")
        for executable_name, executable_data in executable_blobs.items():
            offsets = find_all(executable_data, needle)
            if offsets:
                xrefs[executable_name] = offsets

        magic = magic_name(data)
        value_entropy = entropy(data)
        zero_ratio = data.count(0) / len(data) if data else 0.0
        verdict, score, reasons = candidate_verdict(
            name=name,
            data=data,
            magic=magic,
            table=table,
            dimensions=dimensions,
            glyphs=glyphs,
            xref_count=sum(len(value) for value in xrefs.values()),
        )

        detail = {
            "rank": index,
            "scope": scope,
            "name": name,
            "size": len(data),
            "sha1": sha1(data),
            "magic": magic,
            "entropy": round(value_entropy, 6),
            "zero_ratio": round(zero_ratio, 6),
            "ascii_strings": ascii_strings(data),
            "dimension_candidates": dimensions,
            "bpp_hypotheses": bpp,
            "glyph_block_hypotheses": glyphs,
            "u16_table_evidence": table,
            "executable_name_references": {
                executable: [f"0x{offset:X}" for offset in offsets]
                for executable, offsets in xrefs.items()
            },
            "verdict": verdict,
            "evidence_score": score,
            "reasons": reasons,
            "blob_path": str(blob_path),
        }
        evidence_json.append(detail)
        evidence_rows.append(
            {
                "rank": index,
                "scope": scope,
                "name": name,
                "size": len(data),
                "sha1": detail["sha1"],
                "magic": magic,
                "entropy": detail["entropy"],
                "zero_ratio": detail["zero_ratio"],
                "xref_count": sum(len(value) for value in xrefs.values()),
                "u16_table": table.get("possible_u16_table", False),
                "ascii_identity": table.get("ascii_identity", False),
                "dimension_candidates": len(dimensions),
                "glyph_layout_candidates": len(glyphs),
                "verdict": verdict,
                "evidence_score": score,
                "reasons": "|".join(reasons),
                "blob_path": str(blob_path),
            }
        )

    evidence_rows.sort(
        key=lambda row: (
            -int(row.get("evidence_score", -100)),
            int(row.get("rank", 999)),
        )
    )
    write_csv(out / "font_candidate_evidence.csv", evidence_rows)
    atomic_json(
        out / "font_candidate_evidence.json",
        {
            "format": "prinny2_font_candidate_evidence_v1",
            "warning": (
                "high_priority는 실제 폰트 가능성이 높은 후보라는 뜻이며 "
                "렌더러 연결이 증명되기 전에는 패치 대상으로 확정하지 않습니다."
            ),
            "candidates": evidence_json,
            "created_at": now(),
        },
    )

    write_state(
        status_file,
        status="running",
        progress=70,
        stage="번역 묶음 생성",
        detail="번역 후보 중 우선순위가 높은 200개를 첫 번역 묶음으로 만듭니다.",
        high_priority_fonts=sum(
            row.get("verdict") == "high_priority"
            for row in evidence_rows
        ),
    )
    batch = select_translation_batch(memory_rows, args.batch_size)
    batch_csv = out / "prinny2_translation_batch_001.csv"
    write_csv(batch_csv, batch)

    editor_path = out / "prinny2_translation_editor_batch_001.html"
    editor_path.write_text(
        editor_html(
            batch,
            "Prinny 2 Translation Editor · Batch 001 · V7.3",
        ),
        encoding="utf-8",
    )
    shutil.copy2(
        editor_path,
        PROJECT / "studio" / "prinny2_translation_editor_v7_3.html",
    )

    write_state(
        status_file,
        status="running",
        progress=88,
        stage="보고서 생성",
        detail="폰트 증거와 번역 편집기를 PSP 종합툴 작업 자료로 저장합니다.",
        translation_batch=len(batch),
    )

    high_priority = [
        row for row in evidence_rows
        if row.get("verdict") == "high_priority"
    ]
    medium_priority = [
        row for row in evidence_rows
        if row.get("verdict") == "medium_priority"
    ]

    font_rows_html = "".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('name', '')))}</td>"
        f"<td>{html.escape(str(row.get('scope', '')))}</td>"
        f"<td>{html.escape(str(row.get('magic', '')))}</td>"
        f"<td>{row.get('size', '')}</td>"
        f"<td>{row.get('evidence_score', '')}</td>"
        f"<td>{html.escape(str(row.get('verdict', '')))}</td>"
        "</tr>"
        for row in evidence_rows
    )
    report_html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSP Localization Studio V7.3</title>
<style>
body{{font-family:system-ui,"Noto Sans KR",sans-serif;background:#0d1117;color:#e6edf3;margin:0}}
header,main{{max-width:1200px;margin:auto;padding:20px}}section{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px;margin:12px 0}}
.metric{{font-size:32px;font-weight:900;color:#58a6ff}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #30363d;text-align:left}}
a{{color:#79c0ff}}.muted{{color:#8b949e}}
</style></head><body>
<header><h1>PSP Localization Studio · V7.3</h1>
<p class="muted">프리니 2 폰트 증거 검증과 첫 번역 묶음</p></header><main>
<section><h2>폰트 후보</h2>
<p><span class="metric">{len(evidence_rows)}</span>개 검증 ·
높은 우선순위 {len(high_priority)}개 · 중간 우선순위 {len(medium_priority)}개</p>
<table><thead><tr><th>이름</th><th>범위</th><th>매직</th><th>크기</th><th>점수</th><th>판정</th></tr></thead>
<tbody>{font_rows_html}</tbody></table></section>
<section><h2>번역 묶음 001</h2>
<p><span class="metric">{len(batch)}</span>개</p>
<p><a href="prinny2_translation_editor_batch_001.html">오프라인 번역 편집기 열기</a></p>
<p class="muted">브라우저 임시 저장 및 CSV/JSON 내보내기를 지원합니다. 게임 파일에는 자동 적용하지 않습니다.</p></section>
<section><h2>프리니 1</h2>
<p>오류 큐 18건은 별도 트랙으로 유지되며 대사 문구와 캐릭터 말투는 잠금 상태입니다.</p></section>
</main></body></html>"""
    (out / "index.html").write_text(report_html, encoding="utf-8")

    combined = {
        "format": "prinny_v7_3_font_and_editor_report_v1",
        "created_at": now(),
        "font_candidates": {
            "total": len(evidence_rows),
            "high_priority": len(high_priority),
            "medium_priority": len(medium_priority),
            "evidence_csv": str(out / "font_candidate_evidence.csv"),
            "evidence_json": str(out / "font_candidate_evidence.json"),
            "blob_directory": str(blobs_dir),
        },
        "translation_batch": {
            "count": len(batch),
            "csv": str(batch_csv),
            "editor_html": str(editor_path),
            "source_translation_memory": str(translation_memory),
            "auto_translation_applied": False,
        },
        "prinny1": {
            "issue_queue_count": 18,
            "translation_wording_locked": True,
            "status": "separate_runtime_repair_track",
        },
        "github_checkpoint": {
            "status": "not_due",
            "reason": "V7.3은 0.5 단위가 아니며 다음 체크포인트는 V7.5",
        },
        "status": "pass",
    }
    atomic_json(out / "all_report.json", combined)

    shutil.rmtree(run_dir / "game2_disc", ignore_errors=True)
    shutil.rmtree(run_dir / "game2_system", ignore_errors=True)

    write_state(
        status_file,
        status="complete",
        progress=100,
        stage="완료",
        detail=(
            f"폰트 후보 {len(evidence_rows)}개 검증 · "
            f"높은 우선순위 {len(high_priority)}개 · "
            f"번역 묶음 {len(batch)}개 생성"
        ),
        font_candidates=len(evidence_rows),
        high_priority_fonts=len(high_priority),
        medium_priority_fonts=len(medium_priority),
        translation_batch=len(batch),
        font_evidence_csv=str(out / "font_candidate_evidence.csv"),
        translation_batch_csv=str(batch_csv),
        translation_editor_html=str(editor_path),
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
