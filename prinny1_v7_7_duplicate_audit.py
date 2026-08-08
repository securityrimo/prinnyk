#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import shutil
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

KNOWN_UI_SHOTS = {
    "SHOT-001", "SHOT-003", "SHOT-006",
    "SHOT-007", "SHOT-014", "SHOT-018",
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
            "format": "prinny1_v7_7_duplicate_audit_state_v1",
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


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_int(value: Any) -> int | None:
    match = re.search(r"0x[0-9A-Fa-f]+|\d+", str(value or ""))
    if not match:
        return None
    try:
        return int(match.group(0), 0)
    except ValueError:
        return None


def clean_hex(value: Any) -> str:
    raw = re.sub(r"[^0-9A-Fa-f]", "", str(value or ""))
    if not raw or len(raw) % 2:
        return ""
    return raw.upper()


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def locate_file(root: Path, relative: str) -> Path:
    direct = root / relative
    if direct.is_file():
        return direct
    name = Path(relative).name.casefold()
    matches = [
        path for path in root.rglob("*")
        if path.is_file() and path.name.casefold() == name
    ]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(
        f"{relative}을 새 추출 루트에서 하나로 확정하지 못했습니다."
    )


def prepare_fresh_targets(
    game: Path,
    run_dir: Path,
    out: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from psp_localization.iso import prepare_disc
    from core.system_unpack import unpack_system
    from core.start_runtime import StartRuntimeArchive

    disc_dir = run_dir / "disc"
    system_dir = run_dir / "system"
    start_dir = run_dir / "start"

    for path in (disc_dir, system_dir, start_dir):
        shutil.rmtree(path, ignore_errors=True)

    try:
        disc_root, extract_manifest = prepare_disc(
            game,
            disc_dir,
            force=True,
            extraction_mode="minimal",
        )
    except TypeError:
        disc_root, extract_manifest = prepare_disc(
            game,
            disc_dir,
            force=True,
        )
    atomic_json(out / "fresh_extract_manifest.json", extract_manifest)

    system_path = locate_file(
        disc_root,
        "PSP_GAME/USRDIR/SYSTEM.DAT",
    )
    unpack_system(
        system_path,
        system_dir,
        out / "fresh_system_unpack.json",
        force=True,
    )

    start_path = system_dir / "start.dat"
    if not start_path.is_file():
        matches = [
            path for path in system_dir.rglob("*")
            if path.is_file() and path.name.casefold() == "start.dat"
        ]
        if len(matches) != 1:
            raise FileNotFoundError(
                "새 추출물에서 start.dat을 확정하지 못했습니다."
            )
        start_path = matches[0]

    archive = StartRuntimeArchive.load(start_path)
    archive.extract(start_dir)

    targets: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(path: Path, logical: str, scope: str) -> None:
        if not path.is_file():
            return
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        targets.append(
            {
                "path": path,
                "logical": logical.replace("\\", "/"),
                "scope": scope,
                "size": path.stat().st_size,
            }
        )

    for path in sorted(start_dir.rglob("*")):
        if path.is_file():
            add(
                path,
                path.relative_to(start_dir).as_posix(),
                "start_resource",
            )

    for relative, scope in (
        ("PSP_GAME/USRDIR/SYSTEM.DAT", "container"),
        ("PSP_GAME/USRDIR/SCRIPT.DAT", "container"),
        ("PSP_GAME/SYSDIR/BOOT.BIN", "executable"),
        ("PSP_GAME/SYSDIR/EBOOT.BIN", "executable"),
    ):
        try:
            add(locate_file(disc_root, relative), relative, scope)
        except FileNotFoundError:
            pass

    manifest = {
        "format": "prinny1_v7_7_fresh_target_manifest_v1",
        "source_iso": str(game),
        "source_iso_sha1": sha1_file(game),
        "source_iso_size": game.stat().st_size,
        "start_record_count": len(archive.records),
        "target_count": len(targets),
        "targets": [
            {
                "logical": item["logical"],
                "scope": item["scope"],
                "size": item["size"],
                "sha1": sha1_file(item["path"]),
            }
            for item in targets
        ],
    }
    atomic_json(out / "fresh_target_manifest.json", manifest)
    return targets, manifest


def normalized_name(value: str) -> str:
    return value.strip().replace("\\", "/").casefold().removeprefix("./")


def target_indexes(targets: list[dict[str, Any]]):
    exact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    basename: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        name = normalized_name(target["logical"])
        exact[name].append(target)
        basename[Path(name).name].append(target)
    return exact, basename


def resolve_target(
    requested: str,
    exact: dict[str, list[dict[str, Any]]],
    basename: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str]:
    name = normalized_name(requested)

    direct = exact.get(name, [])
    if len(direct) == 1:
        return direct[0], "exact"

    by_base = basename.get(Path(name).name, [])
    if len(by_base) == 1:
        return by_base[0], "unique_basename"
    if len(by_base) > 1:
        return None, "ambiguous_basename"

    suffix = []
    for key, values in exact.items():
        if key.endswith("/" + name) or name.endswith("/" + key):
            suffix.extend(values)
    unique = {
        str(item["path"].resolve()): item
        for item in suffix
    }
    if len(unique) == 1:
        return next(iter(unique.values())), "unique_suffix"

    return None, "unresolved"


def issue_kind(issue_id: str, group: str) -> str:
    if group.casefold() == "boot_eboot_ui" or issue_id in KNOWN_UI_SHOTS:
        return "ui"
    return "dialogue"


def candidate_kind(target: str) -> str:
    name = normalized_name(target)
    base = Path(name).name
    if base in {"boot.bin", "eboot.bin"}:
        return "ui"
    if base.endswith(".dat") or "start" in name or "script" in name:
        return "dialogue"
    return "unknown"


def mapping_key(target: str, offset: Any, expected: Any) -> str:
    parsed = parse_int(offset)
    offset_text = "" if parsed is None else f"0x{parsed:X}"
    return "|".join(
        (
            normalized_name(target),
            offset_text,
            clean_hex(expected),
        )
    )


def verify_candidate(
    candidate: dict[str, Any],
    *,
    exact: dict[str, list[dict[str, Any]]],
    basename: dict[str, list[dict[str, Any]]],
    cache: dict[str, bytes],
) -> dict[str, Any]:
    requested = str(candidate.get("target", ""))
    offset = parse_int(candidate.get("offset_hex", ""))
    expected_hex = clean_hex(candidate.get("expected_original_hex", ""))
    expected = bytes.fromhex(expected_hex) if expected_hex else b""

    target, method = resolve_target(requested, exact, basename)

    actual = b""
    resolved = ""
    scope = ""
    range_ok = False
    match = False

    if target is not None:
        resolved = target["logical"]
        scope = target["scope"]
        key = str(target["path"].resolve())
        if key not in cache:
            cache[key] = target["path"].read_bytes()
        data = cache[key]

        if (
            offset is not None
            and expected
            and 0 <= offset
            and offset + len(expected) <= len(data)
        ):
            range_ok = True
            actual = data[offset:offset + len(expected)]
            match = actual == expected

    if not requested:
        status = "missing_target"
    elif target is None:
        status = "target_unresolved"
    elif offset is None:
        status = "invalid_offset"
    elif not expected:
        status = "missing_expected"
    elif not range_ok:
        status = "out_of_range"
    elif not match:
        status = "expected_mismatch"
    else:
        status = "verified"

    return {
        **candidate,
        "requested_target": requested,
        "resolved_target": resolved,
        "resolved_scope": scope,
        "resolution_method": method,
        "normalized_offset_hex": (
            "" if offset is None else f"0x{offset:X}"
        ),
        "normalized_expected_hex": expected_hex,
        "actual_original_hex": actual.hex().upper(),
        "expected_match": match,
        "range_ok": range_ok,
        "verification_status": status,
        "mapping_key": mapping_key(
            resolved or requested,
            offset,
            expected_hex,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--links", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--top-candidates", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()

    game = args.game.expanduser().resolve()
    links_path = args.links.expanduser().resolve()
    expected_path = args.expected.expanduser().resolve()
    top_path = args.top_candidates.expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    out = args.out.expanduser().resolve()
    status_path = args.status_file.expanduser().resolve()

    out.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_state(
        status_path,
        status="running",
        progress=3,
        stage="V7.6 중복 감사",
        detail="18개 완전 연결이 실제 몇 개의 고유 위치인지 계산합니다.",
    )

    links = read_csv(links_path)
    expected_rows = read_csv(expected_path)
    top_doc = json.loads(top_path.read_text(encoding="utf-8-sig"))

    if len(links) != 18 or len(expected_rows) != 18:
        raise ValueError(
            f"입력 행 수 오류: links={len(links)}, expected={len(expected_rows)}"
        )
    if not isinstance(top_doc, dict) or len(top_doc) != 18:
        raise ValueError("top_candidates_by_issue.json 이슈 수가 18이 아닙니다.")

    selected_groups: dict[str, list[str]] = defaultdict(list)
    for row in links:
        key = mapping_key(
            row.get("target", ""),
            row.get("offset_hex", ""),
            row.get("expected_original_hex", ""),
        )
        selected_groups[key].append(row.get("issue_id", ""))

    selected_group_rows = []
    for key, issue_ids in sorted(
        selected_groups.items(),
        key=lambda item: -len(item[1]),
    ):
        target, offset, expected_hex = key.split("|", 2)
        selected_group_rows.append(
            {
                "target": target,
                "offset_hex": offset,
                "expected_original_hex": expected_hex,
                "issue_count": len(issue_ids),
                "issue_ids": "|".join(issue_ids),
                "is_duplicate_group": len(issue_ids) > 1,
            }
        )

    unique_selected = len(selected_groups)
    invalidated = sum(
        len(issue_ids)
        for issue_ids in selected_groups.values()
        if len(issue_ids) > 1
    )

    write_csv(
        out / "v76_selected_mapping_groups.csv",
        selected_group_rows,
        [
            "target", "offset_hex", "expected_original_hex",
            "issue_count", "issue_ids", "is_duplicate_group",
        ],
    )

    write_state(
        status_path,
        status="running",
        progress=18,
        stage="새 원본 추출",
        detail=(
            f"V7.6의 18개 선택은 고유 {unique_selected}개 위치로 수렴했습니다. "
            "원본 ISO를 새로 해제합니다."
        ),
        v76_unique_selected_mappings=unique_selected,
        invalidated_issue_links=invalidated,
    )

    targets, manifest = prepare_fresh_targets(game, run_dir, out)
    exact, basename = target_indexes(targets)
    cache: dict[str, bytes] = {}

    write_state(
        status_path,
        status="running",
        progress=42,
        stage="동점 후보 전체 검증",
        detail="각 이슈의 후보를 첫 행 선택 없이 모두 실제 바이트와 비교합니다.",
        fresh_targets=len(targets),
    )

    link_by_issue = {
        row.get("issue_id", ""): row
        for row in links
    }

    all_candidates: list[dict[str, Any]] = []
    issue_summaries: list[dict[str, Any]] = []

    for issue_index, issue_id in enumerate(sorted(top_doc), start=1):
        raw_candidates = top_doc.get(issue_id, [])
        if not isinstance(raw_candidates, list):
            raw_candidates = []

        link = link_by_issue.get(issue_id, {})
        group = link.get("group", "")
        kind = issue_kind(issue_id, group)
        verified_candidates = []

        for rank, raw in enumerate(raw_candidates, start=1):
            if not isinstance(raw, dict):
                continue

            base_score = int(raw.get("score", 0) or 0)
            verified = verify_candidate(
                {
                    **raw,
                    "issue_id": issue_id,
                    "candidate_rank": rank,
                    "issue_group": group,
                    "issue_kind": kind,
                    "candidate_kind": candidate_kind(
                        str(raw.get("target", ""))
                    ),
                },
                exact=exact,
                basename=basename,
                cache=cache,
            )

            category_bonus = 0
            if verified["candidate_kind"] == kind:
                category_bonus = 20
            elif verified["candidate_kind"] != "unknown":
                category_bonus = -35

            verification_bonus = (
                100
                if verified["verification_status"] == "verified"
                else -100
            )
            verified["base_score"] = base_score
            verified["category_bonus"] = category_bonus
            verified["verification_bonus"] = verification_bonus
            verified["adjusted_score"] = (
                base_score + category_bonus + verification_bonus
            )

            verified_candidates.append(verified)
            all_candidates.append(verified)

        valid = [
            row for row in verified_candidates
            if row["verification_status"] == "verified"
        ]
        valid.sort(
            key=lambda row: (
                -int(row["adjusted_score"]),
                int(row["candidate_rank"]),
            )
        )

        if valid:
            best_score = int(valid[0]["adjusted_score"])
            best = [
                row for row in valid
                if int(row["adjusted_score"]) == best_score
            ]
        else:
            best_score = 0
            best = []

        if not best:
            state = "no_verified_candidate"
        elif len(best) > 1:
            state = "verified_tie_unresolved"
        else:
            state = "provisional_unique_before_global_conflict"

        issue_summaries.append(
            {
                "issue_id": issue_id,
                "group": group,
                "issue_kind": kind,
                "v76_selected_target": link.get("target", ""),
                "v76_selected_offset": link.get("offset_hex", ""),
                "top_candidate_count": len(raw_candidates),
                "fresh_verified_count": len(valid),
                "best_adjusted_score": best_score,
                "best_tie_count": len(best),
                "provisional_target": (
                    best[0]["resolved_target"]
                    if len(best) == 1 else ""
                ),
                "provisional_offset_hex": (
                    best[0]["normalized_offset_hex"]
                    if len(best) == 1 else ""
                ),
                "provisional_source_text": (
                    best[0].get("source_text", "")
                    if len(best) == 1 else ""
                ),
                "provisional_mapping_key": (
                    best[0]["mapping_key"]
                    if len(best) == 1 else ""
                ),
                "status": state,
                "next_action": (
                    "스크린샷 장면·화자·원문 문맥으로 동점 후보 분리"
                    if state == "verified_tie_unresolved"
                    else "후보 원본 자료 재탐색"
                    if state == "no_verified_candidate"
                    else "다른 이슈와 위치 중복 여부 검사"
                ),
            }
        )

        progress = 42 + round(issue_index / 18 * 32)
        write_state(
            status_path,
            status="running",
            progress=progress,
            stage="동점 후보 전체 검증",
            detail=f"{issue_index}/18 · {issue_id} · {state}",
            fresh_verified_candidate_rows=sum(
                row["verification_status"] == "verified"
                for row in all_candidates
            ),
        )

    provisional_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in issue_summaries:
        if row["provisional_mapping_key"]:
            provisional_groups[row["provisional_mapping_key"]].append(row)

    independent = 0
    conflict_groups = 0
    for rows in provisional_groups.values():
        if len(rows) == 1:
            rows[0]["status"] = "provisional_unique"
            rows[0]["next_action"] = (
                "스크린샷 문맥 확인 후 Expected Write로 승격"
            )
            independent += 1
        else:
            conflict_groups += 1
            for row in rows:
                row["status"] = "provisional_duplicate_conflict"
                row["next_action"] = (
                    "같은 위치가 여러 스크린샷에 재사용됨; 자동 선택 금지"
                )

    invalidated_rows = []
    for row in links:
        key = mapping_key(
            row.get("target", ""),
            row.get("offset_hex", ""),
            row.get("expected_original_hex", ""),
        )
        invalidated_rows.append(
            {
                **row,
                "corrected_status": (
                    "invalid_duplicate_mapping"
                    if len(selected_groups[key]) > 1
                    else "single_mapping_needs_review"
                ),
            }
        )

    candidate_fields = [
        "issue_id", "candidate_rank", "issue_group", "issue_kind",
        "target", "requested_target", "resolved_target", "resolved_scope",
        "offset_hex", "normalized_offset_hex", "source_text",
        "expected_original_hex", "normalized_expected_hex",
        "actual_original_hex", "base_score", "category_bonus",
        "verification_bonus", "adjusted_score", "candidate_kind",
        "verification_status", "expected_match", "range_ok",
        "mapping_key", "evidence_file", "evidence_row",
    ]
    write_csv(
        out / "all_top_candidates_fresh_verified.csv",
        all_candidates,
        candidate_fields,
    )

    summary_fields = [
        "issue_id", "group", "issue_kind",
        "v76_selected_target", "v76_selected_offset",
        "top_candidate_count", "fresh_verified_count",
        "best_adjusted_score", "best_tie_count",
        "provisional_target", "provisional_offset_hex",
        "provisional_source_text", "provisional_mapping_key",
        "status", "next_action",
    ]
    write_csv(
        out / "issue_disambiguation_queue.csv",
        issue_summaries,
        summary_fields,
    )

    write_csv(
        out / "v76_invalidated_issue_links.csv",
        invalidated_rows,
        list(links[0].keys()) + ["corrected_status"],
    )

    fresh_verified_total = sum(
        row["verification_status"] == "verified"
        for row in all_candidates
    )
    status_counts = Counter(row["status"] for row in issue_summaries)

    duplicate_html = "".join(
        "<tr>"
        f"<td>{html.escape(row['target'])}</td>"
        f"<td>{html.escape(row['offset_hex'])}</td>"
        f"<td>{row['issue_count']}</td>"
        f"<td>{html.escape(row['issue_ids'])}</td>"
        "</tr>"
        for row in selected_group_rows
    )

    issues_html = "".join(
        "<tr>"
        f"<td>{html.escape(row['issue_id'])}</td>"
        f"<td>{html.escape(row['issue_kind'])}</td>"
        f"<td>{row['fresh_verified_count']}</td>"
        f"<td>{row['best_tie_count']}</td>"
        f"<td>{html.escape(row['provisional_target'])}</td>"
        f"<td>{html.escape(row['provisional_offset_hex'])}</td>"
        f"<td>{html.escape(row['status'])}</td>"
        "</tr>"
        for row in issue_summaries
    )

    report = f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>Prinny 1 V7.7 Duplicate Audit</title>
<style>
body{{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,"Noto Sans KR",sans-serif}}
header,main{{max-width:1450px;margin:auto;padding:20px}}
.grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px}}
.metric{{font-size:34px;font-weight:900;color:#58a6ff}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:7px;border-bottom:1px solid #30363d;text-align:left}}
.bad{{color:#f85149}}.ok{{color:#3fb950}}.muted{{color:#8b949e}}
</style></head><body>
<header><h1>프리니 1 V7.7 · V7.6 중복 매핑 감사</h1>
<p class="bad">V7.6의 18/18 완전 연결 표시는 무효화됐습니다.</p>
<p class="muted">ISO와 통합툴 HTML은 변경하지 않았습니다.</p></header>
<main>
<div class="grid">
<div class="card"><h3>V7.6 행</h3><div class="metric">18</div></div>
<div class="card"><h3>고유 위치</h3><div class="metric bad">{unique_selected}</div></div>
<div class="card"><h3>무효 이슈</h3><div class="metric bad">{invalidated}</div></div>
<div class="card"><h3>원본 일치 후보 행</h3><div class="metric">{fresh_verified_total}</div></div>
<div class="card"><h3>독립 임시 후보</h3><div class="metric ok">{independent}</div></div>
</div>
<div class="card" style="margin-top:12px">
<h2>V7.6 선택 위치 수렴</h2>
<table><thead><tr><th>대상</th><th>오프셋</th><th>건수</th><th>이슈</th></tr></thead>
<tbody>{duplicate_html}</tbody></table></div>
<div class="card" style="margin-top:12px">
<h2>이슈별 후보 재검증</h2>
<table><thead><tr><th>ID</th><th>유형</th><th>원본 일치</th><th>최고점 동점</th><th>임시 대상</th><th>오프셋</th><th>상태</th></tr></thead>
<tbody>{issues_html}</tbody></table></div>
</main></body></html>'''
    (out / "index.html").write_text(report, encoding="utf-8")

    summary = {
        "format": "prinny1_v7_7_duplicate_audit_report_v1",
        "created_at": now(),
        "v76_status": "invalidated_due_to_duplicate_mapping_and_tie_breaking",
        "v76_selected_rows": 18,
        "v76_unique_selected_mappings": unique_selected,
        "v76_invalidated_issue_links": invalidated,
        "fresh_target_count": manifest["target_count"],
        "fresh_verified_candidate_rows": fresh_verified_total,
        "issue_count": 18,
        "independent_provisional_links": independent,
        "provisional_duplicate_conflict_groups": conflict_groups,
        "status_counts": dict(status_counts),
        "expected_write_candidates_confirmed": 0,
        "patch_applied": False,
        "iso_created": False,
        "translation_wording_changed": False,
        "character_voice_changed": False,
        "status": "pass",
    }
    atomic_json(out / "all_report.json", summary)

    shutil.rmtree(run_dir / "disc", ignore_errors=True)
    shutil.rmtree(run_dir / "system", ignore_errors=True)
    shutil.rmtree(run_dir / "start", ignore_errors=True)

    write_state(
        status_path,
        status="complete",
        progress=100,
        stage="완료",
        detail=(
            f"V7.6 18개 링크 무효화 · 고유 위치 {unique_selected}개 · "
            f"독립 임시 후보 {independent}개 · 확정 Expected Write 0개"
        ),
        v76_unique_selected_mappings=unique_selected,
        invalidated_issue_links=invalidated,
        fresh_verified_candidate_rows=fresh_verified_total,
        independent_provisional_links=independent,
        expected_write_candidates_confirmed=0,
        report_html=str(out / "index.html"),
        disambiguation_csv=str(out / "issue_disambiguation_queue.csv"),
        candidate_matrix_csv=str(
            out / "all_top_candidates_fresh_verified.csv"
        ),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        status_path = None
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
