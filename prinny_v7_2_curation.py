#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


JAPANESE_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
KANA_RE = re.compile(r"[\u3040-\u30ff]")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SPACE_RE = re.compile(r"\s+")
PUNCT_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)

TEXT_COLUMNS = (
    "text",
    "decoded_text",
    "source_text",
    "original",
    "string",
    "japanese",
    "source",
)
RESOURCE_COLUMNS = (
    "resource",
    "resource_name",
    "file",
    "filename",
    "path",
)
OFFSET_COLUMNS = (
    "offset",
    "file_offset",
    "start",
    "address",
)
LENGTH_COLUMNS = (
    "length",
    "byte_length",
    "size",
    "max_bytes",
)
ENCODING_COLUMNS = (
    "encoding",
    "codec",
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
            "format": "prinny_v7_2_1_state_v1",
            "status": status,
            "progress": int(progress),
            "stage": stage,
            "detail": detail,
            "updated_at": now(),
            "pid": os.getpid(),
            **extra,
        },
    )


def detect_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lookup = {name.casefold(): name for name in fieldnames}
    for candidate in candidates:
        if candidate.casefold() in lookup:
            return lookup[candidate.casefold()]
    return None


def parse_int(value: str) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        try:
            return int(float(raw))
        except ValueError:
            return None


def normalize_text(text: str) -> str:
    value = text.replace("\ufeff", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = SPACE_RE.sub(" ", value)
    return value.strip()


def japanese_count(text: str) -> int:
    return len(JAPANESE_RE.findall(text))


def score_candidate(text: str, *, resource: str, encoding: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    jp = japanese_count(text)
    kana = len(KANA_RE.findall(text))
    cjk = len(CJK_RE.findall(text))
    visible = sum(not char.isspace() and not CONTROL_RE.match(char) for char in text)

    if jp == 0:
        reasons.append("no_japanese")
        score -= 100
    else:
        score += min(40, jp * 3)

    if kana:
        score += 12
    if cjk and not kana:
        score += 2

    if len(text) < 2:
        reasons.append("too_short")
        score -= 30
    elif len(text) > 300:
        reasons.append("too_long")
        score -= 20

    if visible and jp / visible < 0.20:
        reasons.append("low_japanese_ratio")
        score -= 14

    if "\ufffd" in text:
        reasons.append("decode_replacement")
        score -= 35

    control_count = len(CONTROL_RE.findall(text))
    if control_count:
        reasons.append("control_chars")
        score -= min(40, control_count * 8)

    if PUNCT_ONLY_RE.match(text):
        reasons.append("punctuation_only")
        score -= 40

    repeated = max((text.count(char) for char in set(text)), default=0)
    if len(text) >= 12 and repeated / len(text) > 0.70:
        reasons.append("repeated_character_noise")
        score -= 25

    lowered_resource = resource.casefold()
    if any(token in lowered_resource for token in ("demo", "talk", "event", "scenario", "script")):
        score += 8
    if any(token in lowered_resource for token in ("font", "texture", "image", "sound", "movie")):
        reasons.append("binary_like_resource")
        score -= 15

    if encoding and encoding.casefold() not in {
        "shift_jis",
        "shift-jis",
        "sjis",
        "cp932",
        "utf-8",
        "utf8",
    }:
        reasons.append("unusual_encoding")
        score -= 5

    return score, reasons


def category_for(score: int, reasons: list[str], text: str) -> str:
    if "no_japanese" in reasons:
        return "reject"
    if "decode_replacement" in reasons or "control_chars" in reasons:
        return "review"
    if score >= 34 and japanese_count(text) >= 2:
        return "translate"
    if score >= 12:
        return "review"
    return "reject"


def read_catalog(path: Path) -> tuple[list[dict[str, str]], dict[str, str | None]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("catalog.csv에 헤더가 없습니다.")
        rows = [
            {str(key): value or "" for key, value in row.items()}
            for row in reader
        ]
        fieldnames = [str(name) for name in reader.fieldnames]

    # 현재 Prinny 2 카탈로그의 명시적 스키마:
    # resource = START 자원명, source = 일본어 원문.
    # source라는 이름을 경로로 오인하지 않도록 이 조합을 최우선 처리한다.
    lowered = {name.casefold(): name for name in fieldnames}
    if "resource" in lowered and "source" in lowered:
        text_column = lowered["source"]
        resource_column = lowered["resource"]
        schema = "prinny_text_catalog_v1"
    else:
        text_column = detect_column(fieldnames, TEXT_COLUMNS)
        resource_column = detect_column(fieldnames, RESOURCE_COLUMNS)
        schema = "generic"

    columns = {
        "text": text_column,
        "resource": resource_column,
        "offset": detect_column(fieldnames, OFFSET_COLUMNS),
        "length": detect_column(fieldnames, LENGTH_COLUMNS),
        "encoding": detect_column(fieldnames, ENCODING_COLUMNS),
        "schema": schema,
    }
    if columns["text"] is None:
        raise ValueError(
            "문자열 열을 찾지 못했습니다. 헤더: " + ", ".join(fieldnames)
        )
    return rows, columns


def curate(
    rows: list[dict[str, str]],
    columns: dict[str, str | None],
) -> dict[str, Any]:
    occurrences: list[dict[str, Any]] = []
    by_unique: dict[str, dict[str, Any]] = {}
    offset_groups: dict[str, list[tuple[int, int, int]]] = defaultdict(list)

    for index, row in enumerate(rows, start=1):
        text = normalize_text(row.get(columns["text"] or "", ""))
        resource = row.get(columns["resource"] or "", "").strip()
        encoding = row.get(columns["encoding"] or "", "").strip()
        offset = parse_int(row.get(columns["offset"] or "", ""))
        length = parse_int(row.get(columns["length"] or "", ""))

        score, reasons = score_candidate(
            text,
            resource=resource,
            encoding=encoding,
        )
        category = category_for(score, reasons, text)

        occurrence = {
            "occurrence_id": index,
            "resource": resource,
            "offset": "" if offset is None else offset,
            "offset_hex": "" if offset is None else f"0x{offset:X}",
            "length": "" if length is None else length,
            "encoding": encoding,
            "text": text,
            "score": score,
            "category": category,
            "reasons": "|".join(reasons),
            "translation": "",
            "translator_note": "",
            "status": "untranslated" if category == "translate" else category,
        }
        occurrences.append(occurrence)

        if text:
            group = by_unique.setdefault(
                text,
                {
                    "text": text,
                    "occurrence_count": 0,
                    "resources": set(),
                    "best_score": score,
                    "category_counts": Counter(),
                    "reasons": Counter(),
                    "first_occurrence_id": index,
                },
            )
            group["occurrence_count"] += 1
            if resource:
                group["resources"].add(resource)
            group["best_score"] = max(group["best_score"], score)
            group["category_counts"][category] += 1
            group["reasons"].update(reasons)

        if resource and offset is not None and length and length > 0:
            offset_groups[resource].append((offset, offset + length, index))

    overlaps: list[dict[str, Any]] = []
    overlap_ids: set[int] = set()
    for resource, ranges in offset_groups.items():
        ranges.sort()
        previous_start = -1
        previous_end = -1
        previous_id = -1
        for start, end, occurrence_id in ranges:
            if start < previous_end:
                overlaps.append(
                    {
                        "resource": resource,
                        "left_occurrence_id": previous_id,
                        "right_occurrence_id": occurrence_id,
                        "left_range": f"0x{previous_start:X}-0x{previous_end:X}",
                        "right_range": f"0x{start:X}-0x{end:X}",
                    }
                )
                overlap_ids.update({previous_id, occurrence_id})
            if end > previous_end:
                previous_start, previous_end, previous_id = start, end, occurrence_id

    for occurrence in occurrences:
        if occurrence["occurrence_id"] in overlap_ids:
            if occurrence["category"] == "translate":
                occurrence["category"] = "review"
                occurrence["status"] = "overlap_review"
            reasons = occurrence["reasons"].split("|") if occurrence["reasons"] else []
            if "overlapping_candidate" not in reasons:
                reasons.append("overlapping_candidate")
            occurrence["reasons"] = "|".join(reasons)

    unique_rows: list[dict[str, Any]] = []
    for text, group in by_unique.items():
        category_counts: Counter[str] = group["category_counts"]
        if category_counts["translate"]:
            category = "translate"
        elif category_counts["review"]:
            category = "review"
        else:
            category = "reject"
        unique_rows.append(
            {
                "unique_id": 0,
                "text": text,
                "category": category,
                "best_score": group["best_score"],
                "occurrence_count": group["occurrence_count"],
                "resource_count": len(group["resources"]),
                "resources": "|".join(sorted(group["resources"])),
                "reasons": "|".join(
                    reason
                    for reason, _count in group["reasons"].most_common()
                ),
                "translation": "",
                "translator_note": "",
                "status": "untranslated" if category == "translate" else category,
            }
        )

    unique_rows.sort(
        key=lambda item: (
            {"translate": 0, "review": 1, "reject": 2}[item["category"]],
            -int(item["occurrence_count"]),
            -int(item["best_score"]),
            str(item["text"]),
        )
    )
    for index, item in enumerate(unique_rows, start=1):
        item["unique_id"] = index

    stats = {
        "raw_occurrences": len(rows),
        "normalized_occurrences": len(occurrences),
        "unique_strings": len(unique_rows),
        "duplicate_occurrences_removed_for_translation_memory": (
            len(occurrences) - len(unique_rows)
        ),
        "occurrence_categories": dict(
            Counter(item["category"] for item in occurrences)
        ),
        "unique_categories": dict(
            Counter(item["category"] for item in unique_rows)
        ),
        "overlap_pairs": len(overlaps),
        "resources": len(
            {item["resource"] for item in occurrences if item["resource"]}
        ),
    }
    return {
        "occurrences": occurrences,
        "unique": unique_rows,
        "overlaps": overlaps,
        "stats": stats,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def font_rank(font_json: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for scope in ("start_candidates", "system_candidates"):
        for item in font_json.get(scope, []):
            name = str(item.get("name", ""))
            size = int(item.get("size", 0) or 0)
            lowered = name.casefold()
            score = 0
            reasons = []

            if lowered.endswith(".fnt"):
                score += 70
                reasons.append("fnt_extension")
            if lowered.endswith(".txp"):
                score += 70
                reasons.append("txp_extension")
            if lowered.endswith((".gim", ".tm2")):
                score += 45
                reasons.append("known_texture_extension")
            if "font" in lowered:
                score += 50
                reasons.append("font_name")
            if "moji" in lowered or "glyph" in lowered or "char" in lowered:
                score += 30
                reasons.append("character_name")
            if "jis" in lowered or "ucs" in lowered:
                score += 25
                reasons.append("code_map_name")
            if size >= 0x1000:
                score += 5
                reasons.append("nontrivial_size")
            if size >= 0x10000:
                score += 5
                reasons.append("texture_scale_size")
            if size == 0:
                score -= 20
                reasons.append("zero_size")

            candidates.append(
                {
                    "rank": 0,
                    "scope": scope.replace("_candidates", ""),
                    "name": name,
                    "size": size,
                    "size_hex": f"0x{size:X}",
                    "sha1": str(item.get("sha1", "")),
                    "score": score,
                    "reasons": "|".join(reasons),
                    "verification_status": "metadata_rank_only",
                    "next_check": "헤더·픽셀 배열·코드맵 크기·BOOT/EBOOT 참조 확인",
                }
            )
    candidates.sort(key=lambda item: (-item["score"], -item["size"], item["name"]))
    for index, item in enumerate(candidates, start=1):
        item["rank"] = index
    return candidates


def dashboard(
    path: Path,
    *,
    stats: dict[str, Any],
    fonts: list[dict[str, Any]],
    outputs: dict[str, str],
) -> None:
    top_fonts = "".join(
        "<tr>"
        f"<td>{item['rank']}</td>"
        f"<td>{html.escape(item['scope'])}</td>"
        f"<td>{html.escape(item['name'])}</td>"
        f"<td>{item['size']}</td>"
        f"<td>{item['score']}</td>"
        "</tr>"
        for item in fonts[:20]
    ) or '<tr><td colspan="5">이름 기반 후보 없음</td></tr>'

    unique_categories = stats["unique_categories"]
    document = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSP Localization Studio V7.2.1</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--ok:#3fb950;--warn:#d29922}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,"Noto Sans KR",sans-serif}}
header{{padding:20px 24px;background:var(--panel);border-bottom:1px solid var(--line)}}
main{{max-width:1300px;margin:auto;padding:18px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}
.wide{{grid-column:1/-1}}.metric{{font-size:32px;font-weight:900;color:var(--accent)}}.muted{{color:var(--muted)}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left}}
code{{color:#79c0ff;word-break:break-all}}@media(max-width:900px){{main{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:600px){{main{{grid-template-columns:1fr}}.wide{{grid-column:auto}}}}
</style>
</head>
<body>
<header><h1>PSP Localization Studio · V7.2.1</h1>
<p class="muted">원시 후보를 번역 확정·검토·제외로 분리하고 번역 문구는 변경하지 않음</p></header>
<main>
<section class="card"><h2>원시 후보</h2><div class="metric">{stats['raw_occurrences']}</div></section>
<section class="card"><h2>고유 문자열</h2><div class="metric">{stats['unique_strings']}</div></section>
<section class="card"><h2>번역 후보</h2><div class="metric">{unique_categories.get('translate', 0)}</div></section>
<section class="card"><h2>검토 후보</h2><div class="metric">{unique_categories.get('review', 0)}</div></section>
<section class="card wide"><h2>정제 결과</h2>
<p>중복 발생 수: <b>{stats['duplicate_occurrences_removed_for_translation_memory']}</b> ·
겹침 후보 쌍: <b>{stats['overlap_pairs']}</b> ·
자원 수: <b>{stats['resources']}</b></p>
<p><code>{html.escape(outputs['translation_memory'])}</code></p></section>
<section class="card wide"><h2>프리니 2 폰트 후보 순위</h2>
<table><thead><tr><th>순위</th><th>범위</th><th>이름</th><th>크기</th><th>점수</th></tr></thead>
<tbody>{top_fonts}</tbody></table>
<p class="muted">현재 순위는 이름·확장자·크기 메타데이터 기준이며 실제 폰트 확정이 아닙니다.</p></section>
</main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def self_test() -> int:
    rows = [
        {"resource": "Demo00.dat", "offset": "0x10", "length": "8", "encoding": "shift_jis", "text": "こんにちは"},
        {"resource": "Demo00.dat", "offset": "0x10", "length": "8", "encoding": "shift_jis", "text": "こんにちは"},
        {"resource": "Demo00.dat", "offset": "0x14", "length": "8", "encoding": "shift_jis", "text": "世界"},
        {"resource": "font.bin", "offset": "0x20", "length": "3", "encoding": "shift_jis", "text": "A"},
        {"resource": "Demo00.dat", "offset": "0x30", "length": "8", "encoding": "shift_jis", "text": "テスト\ufffd"},
    ]
    columns = {
        "text": "text",
        "resource": "resource",
        "offset": "offset",
        "length": "length",
        "encoding": "encoding",
    }
    result = curate(rows, columns)
    assert result["stats"]["raw_occurrences"] == 5
    assert result["stats"]["unique_strings"] == 4
    assert result["stats"]["overlap_pairs"] >= 1
    print("SELF TEST PASS: dedupe / overlap / category")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--font-json", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not all((args.catalog, args.font_json, args.out, args.status_file)):
        parser.error("필수 인자가 부족합니다.")

    catalog_path = args.catalog.expanduser().resolve()
    font_path = args.font_json.expanduser().resolve()
    out = args.out.expanduser().resolve()
    status = args.status_file.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    write_state(
        status,
        status="running",
        progress=4,
        stage="입력 확인",
        detail="프리니 2 원시 카탈로그와 폰트 탐색 보고서를 확인합니다.",
    )

    rows, columns = read_catalog(catalog_path)
    write_state(
        status,
        status="running",
        progress=18,
        stage="카탈로그 구조 인식",
        detail=f"{len(rows)}개 원시 후보의 열 구조를 자동 인식했습니다.",
        raw_candidates=len(rows),
        detected_columns=columns,
    )

    result = curate(rows, columns)
    stats = result["stats"]
    write_state(
        status,
        status="running",
        progress=55,
        stage="후보 정제",
        detail=(
            f"고유 문자열 {stats['unique_strings']}개 · "
            f"번역 {stats['unique_categories'].get('translate', 0)}개 · "
            f"검토 {stats['unique_categories'].get('review', 0)}개"
        ),
        unique_strings=stats["unique_strings"],
        translate_candidates=stats["unique_categories"].get("translate", 0),
        review_candidates=stats["unique_categories"].get("review", 0),
        rejected_candidates=stats["unique_categories"].get("reject", 0),
    )

    write_csv(out / "occurrences_all.csv", result["occurrences"])
    write_csv(out / "unique_strings_all.csv", result["unique"])
    write_csv(
        out / "translation_memory.csv",
        [item for item in result["unique"] if item["category"] == "translate"],
    )
    write_csv(
        out / "review_queue.csv",
        [item for item in result["unique"] if item["category"] == "review"],
    )
    write_csv(
        out / "rejected_candidates.csv",
        [item for item in result["unique"] if item["category"] == "reject"],
    )
    write_csv(out / "overlapping_candidates.csv", result["overlaps"])
    atomic_json(out / "catalog_stats.json", stats)

    write_state(
        status,
        status="running",
        progress=75,
        stage="폰트 후보 순위",
        detail="비표준 START 폰트 후보를 이름·확장자·크기 기준으로 우선순위화합니다.",
    )
    font_json = json.loads(font_path.read_text(encoding="utf-8"))
    fonts = font_rank(font_json)
    write_csv(out / "font_candidate_ranking.csv", fonts)
    atomic_json(
        out / "font_candidate_ranking.json",
        {
            "format": "prinny2_font_candidate_ranking_v1",
            "warning": "메타데이터 순위이며 실제 폰트 확정이 아님",
            "candidates": fonts,
            "created_at": now(),
        },
    )

    outputs = {
        "translation_memory": str(out / "translation_memory.csv"),
        "review_queue": str(out / "review_queue.csv"),
        "rejected": str(out / "rejected_candidates.csv"),
        "occurrences": str(out / "occurrences_all.csv"),
        "overlaps": str(out / "overlapping_candidates.csv"),
        "font_ranking": str(out / "font_candidate_ranking.csv"),
        "html": str(out / "index.html"),
    }
    dashboard(
        out / "index.html",
        stats=stats,
        fonts=fonts,
        outputs=outputs,
    )
    atomic_json(
        out / "all_report.json",
        {
            "format": "prinny_v7_2_1_curation_report_v1",
            "created_at": now(),
            "source_catalog": str(catalog_path),
            "detected_columns": columns,
            "statistics": stats,
            "font_candidate_count": len(fonts),
            "outputs": outputs,
            "translation_policy": {
                "source_text_changed": False,
                "character_voice_changed": False,
                "auto_translation_applied": False,
                "prinny1_translation_copied": False,
            },
            "github_checkpoint": {
                "status": "not_due",
                "reason": "V7.2는 0.5 단위가 아니며 다음 체크포인트는 V7.5",
            },
            "status": "pass",
        },
    )

    write_state(
        status,
        status="complete",
        progress=100,
        stage="완료",
        detail=(
            f"원시 {stats['raw_occurrences']}개 → 고유 {stats['unique_strings']}개 · "
            f"번역 {stats['unique_categories'].get('translate', 0)}개 · "
            f"검토 {stats['unique_categories'].get('review', 0)}개"
        ),
        raw_candidates=stats["raw_occurrences"],
        unique_strings=stats["unique_strings"],
        translate_candidates=stats["unique_categories"].get("translate", 0),
        review_candidates=stats["unique_categories"].get("review", 0),
        rejected_candidates=stats["unique_categories"].get("reject", 0),
        duplicate_occurrences=stats[
            "duplicate_occurrences_removed_for_translation_memory"
        ],
        overlap_pairs=stats["overlap_pairs"],
        font_candidates=len(fonts),
        translation_memory=outputs["translation_memory"],
        review_queue=outputs["review_queue"],
        font_ranking=outputs["font_ranking"],
        report_html=outputs["html"],
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
