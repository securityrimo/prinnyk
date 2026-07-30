from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from psp_localization.util import atomic_write_bytes


def _value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return html.escape(json.dumps(value, ensure_ascii=False, indent=2))
    return html.escape(str(value))


def write_dashboard(
    path: Path,
    *,
    analyses: dict[str, dict[str, Any]],
    comparison: dict[str, Any] | None,
    prinny_compatibility: dict[str, Any] | None,
    qa: dict[str, Any] | None,
) -> None:
    cards: list[str] = []
    for name, analysis in analyses.items():
        game = analysis.get("game", {})
        cards.append(
            f"""
            <section class='card'>
              <h2>{html.escape(name)}</h2>
              <div class='metrics'>
                <div><b>{html.escape(str(game.get('disc_id','-')))}</b><span>DISC ID</span></div>
                <div><b>{analysis.get('file_count',0)}</b><span>파일</span></div>
                <div><b>{analysis.get('candidate_file_count',0)}</b><span>분석 후보</span></div>
              </div>
              <p>{html.escape(str(game.get('title','')))}</p>
            </section>
            """
        )

    compatibility_html = ""
    if prinny_compatibility:
        grade = html.escape(str(prinny_compatibility.get("grade", "?")))
        verdict = html.escape(str(prinny_compatibility.get("verdict", "")))
        reasons = "".join(
            f"<li>{html.escape(str(reason))}</li>"
            for reason in prinny_compatibility.get("reasons", [])
        )
        compatibility_html = f"""
        <section class='card'>
          <h2>프리니 2 호환성</h2>
          <div class='grade'>{grade}</div>
          <p>{verdict}</p>
          <ul>{reasons}</ul>
        </section>
        """

    qa_html = ""
    if qa:
        summary = qa.get("summary", {})
        qa_html = f"""
        <section class='card'>
          <h2>번역 QA</h2>
          <div class='metrics'>
            <div><b>{summary.get('row_count',0)}</b><span>전체</span></div>
            <div><b>{summary.get('error_count',0)}</b><span>오류</span></div>
            <div><b>{summary.get('warning_count',0)}</b><span>경고</span></div>
            <div><b>{summary.get('uncovered_candidate_count',0)}</b><span>미포함 후보</span></div>
          </div>
          <p>세부 결과는 JSON/CSV 보고서에서 확인합니다.</p>
        </section>
        """

    raw_payload = html.escape(
        json.dumps(
            {
                "analyses": analyses,
                "comparison": comparison,
                "prinny_compatibility": prinny_compatibility,
                "qa": qa,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    document = f"""<!doctype html>
<html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>PSP Localization Toolkit Report</title>
<style>
:root{{color-scheme:dark;--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--accent:#58a6ff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,'Noto Sans KR',sans-serif}}header{{padding:20px;border-bottom:1px solid var(--line);background:var(--panel)}}main{{max-width:1300px;margin:auto;padding:18px;display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}h1,h2{{margin:0 0 10px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px}}.metrics div{{background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:10px}}.metrics b{{display:block;font-size:21px}}.metrics span{{color:var(--muted);font-size:12px}}.grade{{font-size:56px;font-weight:900;color:var(--accent)}}details{{grid-column:1/-1}}pre{{white-space:pre-wrap;word-break:break-word;background:#05080d;padding:12px;border-radius:8px;max-height:520px;overflow:auto}}
</style></head><body><header><h1>PSP Localization Toolkit</h1><div>비파괴 분석 · 번역 QA · 프리니 계열 호환성 판정</div></header><main>
{''.join(cards)}{compatibility_html}{qa_html}
<details class='card'><summary>전체 JSON</summary><pre>{raw_payload}</pre></details>
</main></body></html>"""
    atomic_write_bytes(path, document.encode("utf-8"))
