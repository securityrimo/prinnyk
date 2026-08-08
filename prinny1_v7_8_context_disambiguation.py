#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import shutil
import sys
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV 헤더가 없습니다: {path}")
        return [{str(k): v or "" for k, v in row.items()} for row in reader]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def write_state(path: Path, status: str, progress: int, stage: str, detail: str, **extra: Any) -> None:
    previous: dict[str, Any] = {}
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    atomic_json(path, {
        **previous,
        "format": "prinny1_v7_8_context_state_v1",
        "status": status,
        "progress": progress,
        "stage": stage,
        "detail": detail,
        "updated_at": now(),
        "pid": os.getpid(),
        **extra,
    })


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or default)))
    except ValueError:
        return default


def get_target(row: dict[str, str]) -> str:
    return (row.get("resolved_target") or row.get("target") or "").replace("\\", "/")


def classify_target(target: str) -> str:
    base = Path(target.casefold()).name
    if base in {"boot.bin", "eboot.bin"}:
        return "ui"
    if base.endswith(".dat") or "start" in target.casefold() or "script" in target.casefold():
        return "dialogue"
    return "unknown"


def get_mapping_key(row: dict[str, str]) -> str:
    return row.get("mapping_key") or "|".join((
        get_target(row).casefold(),
        row.get("normalized_offset_hex") or row.get("offset_hex") or "",
        row.get("normalized_expected_hex") or row.get("expected_original_hex") or "",
    ))


def hungarian_max(weights: list[list[int]]) -> tuple[int, list[int]]:
    n = len(weights)
    if n == 0:
        return 0, []
    m = len(weights[0])
    if m < n:
        raise ValueError("배정 열 수가 행 수보다 작습니다.")
    max_weight = max(max(row) for row in weights)
    cost = [[max_weight - value for value in row] for row in weights]
    u = [0] * (n + 1)
    v = [0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [10**18] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = 10**18
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignment = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            assignment[p[j] - 1] = j - 1
    total = sum(weights[i][assignment[i]] for i in range(n) if assignment[i] >= 0)
    return total, assignment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    screenshots = args.screenshots.expanduser().resolve()
    candidates_path = args.candidates.expanduser().resolve()
    out = args.out.expanduser().resolve()
    status_path = args.status_file.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    write_state(status_path, "running", 5, "스크린샷 문맥 확인",
                "18개 스크린샷의 장면·화자·UI/대사 유형을 불러옵니다.")

    issues = read_csv(manifest_path)
    candidates = [row for row in read_csv(candidates_path)
                  if row.get("verification_status") == "verified"]
    if len(issues) != 18:
        raise ValueError(f"스크린샷 문맥 행 수가 18이 아닙니다: {len(issues)}")
    if not candidates:
        raise ValueError("원본 일치 후보가 없습니다.")

    copied = out / "screenshots"
    if copied.exists():
        shutil.rmtree(copied)
    shutil.copytree(screenshots, copied)

    issue_by_id = {row["issue_id"]: row for row in issues}
    by_issue: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    for row in candidates:
        issue_id = row.get("issue_id", "")
        if issue_id not in issue_by_id:
            continue
        key = get_mapping_key(row)
        if not key:
            continue
        score = to_int(row.get("adjusted_score"), to_int(row.get("base_score")))
        candidate = {**row, "mapping_key": key, "target": get_target(row),
                     "base_context_score": score}
        current = by_issue[issue_id].get(key)
        if current is None or score > current["base_context_score"]:
            by_issue[issue_id][key] = candidate

    write_state(status_path, "running", 22, "장면별 자원 지지도 계산",
                "같은 장면의 후보들이 어느 START/BOOT 자원에 모이는지 계산합니다.",
                verified_candidate_rows=len(candidates))

    scene_support: dict[tuple[str, str], dict[str, int]] = {}
    scene_rows = []
    for scene in sorted({row["scene"] for row in issues}):
        scene_issues = [row["issue_id"] for row in issues if row["scene"] == scene]
        targets = {candidate["target"] for issue_id in scene_issues
                   for candidate in by_issue.get(issue_id, {}).values()}
        for target in sorted(targets):
            coverage = 0
            score_sum = 0
            for issue_id in scene_issues:
                values = [candidate["base_context_score"]
                          for candidate in by_issue.get(issue_id, {}).values()
                          if candidate["target"] == target]
                if values:
                    coverage += 1
                    score_sum += max(values)
            scene_support[(scene, target)] = {
                "coverage": coverage,
                "score_sum": score_sum,
                "scene_issue_count": len(scene_issues),
            }
            scene_rows.append({
                "scene": scene,
                "target": target,
                "coverage": coverage,
                "scene_issue_count": len(scene_issues),
                "score_sum": score_sum,
                "coverage_ratio": round(coverage / len(scene_issues), 4),
            })

    write_csv(out / "scene_resource_support.csv", scene_rows,
              ["scene", "target", "coverage", "scene_issue_count",
               "score_sum", "coverage_ratio"])

    all_keys = sorted({key for values in by_issue.values() for key in values})
    dummy_keys = [f"__DUMMY_{index:03d}" for index in range(len(issues))]
    columns = all_keys + dummy_keys
    impossible = -100000
    weights: list[list[int]] = []
    edge_info: dict[tuple[int, int], dict[str, Any]] = {}

    for issue_index, issue in enumerate(issues):
        row_weights = []
        issue_id = issue["issue_id"]
        for column_index, key in enumerate(columns):
            if key.startswith("__DUMMY_"):
                row_weights.append(0 if key == dummy_keys[issue_index] else impossible)
                continue
            candidate = by_issue.get(issue_id, {}).get(key)
            if candidate is None:
                row_weights.append(impossible)
                continue
            kind_match = classify_target(candidate["target"]) == issue["issue_kind"]
            kind_bonus = 35 if kind_match else -80
            support = scene_support.get((issue["scene"], candidate["target"]), {})
            coverage = int(support.get("coverage", 0))
            scene_count = int(support.get("scene_issue_count", 1))
            support_bonus = round(30 * coverage / max(scene_count, 1))
            source_bonus = 5 if candidate.get("source_text", "").strip() else 0
            rank_penalty = min(to_int(candidate.get("candidate_rank"), 0), 20)
            final_score = (candidate["base_context_score"] + kind_bonus +
                           support_bonus + source_bonus - rank_penalty)
            row_weights.append(final_score)
            edge_info[(issue_index, column_index)] = {
                **candidate,
                "kind_match": kind_match,
                "kind_bonus": kind_bonus,
                "scene_support_bonus": support_bonus,
                "source_bonus": source_bonus,
                "rank_penalty": rank_penalty,
                "context_score": final_score,
            }
        weights.append(row_weights)

    write_state(status_path, "running", 45, "전역 1:1 배정",
                "18개 이슈가 같은 위치를 중복 선택하지 않도록 전체 점수를 동시에 최적화합니다.",
                unique_verified_mappings=len(all_keys))

    total_score, assignment = hungarian_max(weights)
    assignment_rows = []
    packets = []

    for issue_index, issue in enumerate(issues):
        column_index = assignment[issue_index]
        assigned = edge_info.get((issue_index, column_index))
        issue_edges = sorted(
            [info for (row_idx, _), info in edge_info.items() if row_idx == issue_index],
            key=lambda item: -int(item["context_score"]),
        )
        local_second = issue_edges[1]["context_score"] if len(issue_edges) > 1 else 0
        assigned_score = int(assigned["context_score"]) if assigned else 0
        local_margin = assigned_score - int(local_second)

        if assigned:
            alternative = [row[:] for row in weights]
            alternative[issue_index][column_index] = impossible
            alternative_total, _ = hungarian_max(alternative)
            global_margin = total_score - alternative_total
        else:
            global_margin = 0

        if assigned is None:
            state = "unassigned"
        elif not assigned["kind_match"]:
            state = "type_conflict"
        elif local_margin >= 15 and global_margin >= 10:
            state = "context_strong"
        elif local_margin > 0 and global_margin > 0:
            state = "context_provisional"
        else:
            state = "context_ambiguous"

        screenshot_name = Path(issue["screenshot"]).name
        result = {
            "issue_id": issue["issue_id"],
            "screenshot": f"screenshots/{screenshot_name}",
            "issue_kind": issue["issue_kind"],
            "scene": issue["scene"],
            "speaker": issue["speaker"],
            "sequence": issue["sequence"],
            "symptoms": issue["symptoms"],
            "assigned_target": assigned["target"] if assigned else "",
            "assigned_offset_hex": (
                (assigned.get("normalized_offset_hex")
                 or assigned.get("offset_hex") or "") if assigned else ""
            ),
            "assigned_source_text": assigned.get("source_text", "") if assigned else "",
            "assigned_expected_hex": (
                (assigned.get("normalized_expected_hex")
                 or assigned.get("expected_original_hex") or "") if assigned else ""
            ),
            "context_score": assigned_score,
            "local_margin": local_margin,
            "global_margin": global_margin,
            "status": state,
            "expected_write_confirmed": "no",
            "next_action": (
                "스크린샷 문맥과 후보 원문을 사람 또는 외부 AI가 대조"
                if state in {"context_ambiguous", "context_provisional"}
                else "원문·포인터·슬롯 검증 후 Expected Write 승격 검토"
                if state == "context_strong"
                else "후보 재탐색"
            ),
        }
        assignment_rows.append(result)
        packets.append({
            "issue": issue,
            "assignment": result,
            "top_alternatives": issue_edges[:10],
        })
        write_state(status_path, "running",
                    45 + round((issue_index + 1) / 18 * 35),
                    "배정 신뢰도 계산",
                    f"{issue_index + 1}/18 · {issue['issue_id']} · {state}")

    fields = [
        "issue_id", "screenshot", "issue_kind", "scene", "speaker",
        "sequence", "symptoms", "assigned_target", "assigned_offset_hex",
        "assigned_source_text", "assigned_expected_hex", "context_score",
        "local_margin", "global_margin", "status",
        "expected_write_confirmed", "next_action",
    ]
    write_csv(out / "context_assignment.csv", assignment_rows, fields)
    write_csv(out / "manual_review_queue.csv",
              [row for row in assignment_rows if row["status"] != "context_strong"],
              fields)
    atomic_json(out / "candidate_packets.json", {
        "format": "prinny1_v7_8_candidate_packets_v1",
        "created_at": now(),
        "packets": packets,
    })

    strong = sum(row["status"] == "context_strong" for row in assignment_rows)
    provisional = sum(row["status"] == "context_provisional" for row in assignment_rows)
    ambiguous = sum(row["status"] == "context_ambiguous" for row in assignment_rows)
    unassigned = sum(row["status"] in {"unassigned", "type_conflict"} for row in assignment_rows)

    cards = []
    for packet in packets:
        issue = packet["issue"]
        assigned = packet["assignment"]
        rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(str(item.get('target', '')))}</td>"
            f"<td>{html.escape(str(item.get('normalized_offset_hex') or item.get('offset_hex') or ''))}</td>"
            f"<td>{html.escape(str(item.get('source_text', '')))}</td>"
            f"<td>{item.get('context_score', '')}</td>"
            "</tr>"
            for item in packet["top_alternatives"][:5]
        )
        cards.append(f'''<section class="card">
<h2>{html.escape(issue["issue_id"])} · {html.escape(issue["scene"])}</h2>
<div class="split">
<img src="screenshots/{html.escape(Path(issue["screenshot"]).name)}" alt="{html.escape(issue["issue_id"])}">
<div>
<p><b>배정 상태:</b> {html.escape(assigned["status"])}</p>
<p><b>배정:</b> {html.escape(assigned["assigned_target"])} @ {html.escape(assigned["assigned_offset_hex"])}</p>
<p><b>후보 원문:</b> {html.escape(assigned["assigned_source_text"])}</p>
<p><b>점수 차이:</b> local {assigned["local_margin"]} / global {assigned["global_margin"]}</p>
</div></div>
<table><thead><tr><th>후보 자원</th><th>오프셋</th><th>원문</th><th>문맥 점수</th></tr></thead>
<tbody>{rows_html}</tbody></table>
</section>''')

    report = f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>Prinny 1 V7.8 Context Disambiguation</title>
<style>
body{{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,"Noto Sans KR",sans-serif}}
header,main{{max-width:1450px;margin:auto;padding:20px}}
.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px;margin-bottom:12px}}
.metric{{font-size:32px;font-weight:900;color:#58a6ff}}
.split{{display:grid;grid-template-columns:480px 1fr;gap:15px}}
img{{width:100%;border:1px solid #30363d}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:7px;border-bottom:1px solid #30363d;text-align:left}}
.warn{{color:#d29922}}.bad{{color:#f85149}}.ok{{color:#3fb950}}
@media(max-width:900px){{.split{{grid-template-columns:1fr}}.summary{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<header><h1>프리니 1 V7.8 · 스크린샷 문맥 전역 배정</h1>
<p>첫 행 자동 선택을 제거하고 18개 이슈를 동시에 1:1 배정했습니다. Expected Write 확정은 아직 0개입니다.</p></header>
<main>
<div class="summary">
<div class="card"><h3>강한 문맥</h3><div class="metric ok">{strong}</div></div>
<div class="card"><h3>임시 문맥</h3><div class="metric warn">{provisional}</div></div>
<div class="card"><h3>모호</h3><div class="metric bad">{ambiguous}</div></div>
<div class="card"><h3>미배정/충돌</h3><div class="metric bad">{unassigned}</div></div>
</div>
{''.join(cards)}
</main></body></html>'''
    (out / "index.html").write_text(report, encoding="utf-8")

    atomic_json(out / "all_report.json", {
        "format": "prinny1_v7_8_context_disambiguation_report_v1",
        "created_at": now(),
        "issue_count": 18,
        "verified_candidate_rows": len(candidates),
        "unique_verified_mappings": len(all_keys),
        "global_assignment_score": total_score,
        "context_strong": strong,
        "context_provisional": provisional,
        "context_ambiguous": ambiguous,
        "unassigned_or_conflict": unassigned,
        "expected_write_candidates_confirmed": 0,
        "patch_applied": False,
        "iso_created": False,
        "translation_wording_changed": False,
        "character_voice_changed": False,
        "status": "pass",
    })

    write_state(
        status_path, "complete", 100, "완료",
        f"스크린샷 18개 전역 배정 · 강한 문맥 {strong}개 · 임시 {provisional}개 · 모호 {ambiguous}개 · 미배정/충돌 {unassigned}개",
        context_strong=strong,
        context_provisional=provisional,
        context_ambiguous=ambiguous,
        unassigned_or_conflict=unassigned,
        expected_write_candidates_confirmed=0,
        report_html=str(out / "index.html"),
        assignment_csv=str(out / "context_assignment.csv"),
        manual_review_csv=str(out / "manual_review_queue.csv"),
        candidate_packets_json=str(out / "candidate_packets.json"),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        status_path = None
        try:
            if "--status-file" in sys.argv:
                status_path = Path(sys.argv[sys.argv.index("--status-file") + 1]).expanduser().resolve()
        except Exception:
            status_path = None
        if status_path is not None:
            try:
                write_state(status_path, "error", 100, "오류", str(exc),
                            error=str(exc),
                            traceback=traceback.format_exc()[-12000:])
            except Exception:
                pass
        traceback.print_exc()
        raise SystemExit(2)
