#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
import os
import re
import shutil
import sys
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

TEXT_EXTENSIONS = {".json", ".csv", ".log", ".txt", ".md"}
SKIP_DIR_PARTS = {
    ".git",
    "__pycache__",
    "node_modules",
    "font_candidate_blobs",
    "font_previews",
}
MAX_TEXT_FILE_SIZE = 20 * 1024 * 1024
MAX_RECORDS = 250_000

TARGET_KEYS = (
    "resource",
    "resource_name",
    "file",
    "filename",
    "path",
    "target",
    "target_file",
    "source_file",
    "container",
)
OFFSET_KEYS = (
    "offset",
    "file_offset",
    "address",
    "start",
    "target_offset",
    "patch_offset",
)
SOURCE_TEXT_KEYS = (
    "source_text",
    "original",
    "japanese",
    "text",
    "source",
    "original_text",
)
EXPECTED_KEYS = (
    "expected_original_hex",
    "expected_hex",
    "original_hex",
    "before_hex",
    "expected_bytes",
    "original_bytes",
)
REPLACEMENT_KEYS = (
    "replacement_hex",
    "after_hex",
    "patched_hex",
    "translation",
    "translated",
)
NOTE_KEYS = (
    "observation",
    "description",
    "finding",
    "notes",
    "note",
    "reason",
    "status",
    "group",
    "issue_id",
    "screenshot",
)

STOPWORDS = {
    "todo",
    "review",
    "unlinked",
    "unknown",
    "none",
    "pass",
    "fail",
    "오류",
    "문제",
    "상태",
    "수정",
    "화면",
    "프리니",
}

CATEGORY_KEYWORDS = {
    "runtime_glyph_or_boundary": (
        "glyph", "font", "square", "black", "jis", "ucs", "code",
        "boundary", "alignment", "two_byte", "2byte", "2-byte",
        "글리프", "폰트", "한자", "영문", "깨짐", "검은", "사각", "■",
    ),
    "capacity_or_layout": (
        "capacity", "overflow", "length", "slot", "padding", "width",
        "truncate", "truncation", "cut", "layout",
        "용량", "초과", "길이", "슬롯", "패딩", "폭", "잘림", "공백",
    ),
    "boot_eboot_ui": (
        "boot", "eboot", "ui", "menu", "tutorial", "difficulty",
        "hud", "result", "system", "interface",
        "메뉴", "튜토리얼", "난이도", "결과", "인터페이스",
    ),
    "unlinked_runtime_evidence": (
        "runtime", "screenshot", "evidence", "start", "script",
        "실행", "스크린샷", "증거", "자원", "대사",
    ),
}

JAPANESE_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
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
    old: dict[str, Any] = {}
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    atomic_json(
        path,
        {
            **old,
            "format": "prinny1_v7_6_state_v1",
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
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.search(r"0x[0-9a-fA-F]+|\d+", raw)
    if not match:
        return None
    token = match.group(0)
    try:
        return int(token, 0)
    except ValueError:
        return None


def first_value(record: dict[str, Any], keys: Iterable[str]) -> str:
    lowered = {str(key).casefold(): value for key, value in record.items()}
    for key in keys:
        value = lowered.get(key.casefold())
        if value not in (None, "", [], {}):
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)
    return ""


def normalize_hex(value: str) -> str:
    raw = re.sub(r"[^0-9a-fA-F]", "", value or "")
    if len(raw) % 2:
        raw = raw[:-1]
    return raw.upper()


def looks_like_path(value: str) -> bool:
    text = value.strip()
    return (
        "/" in text
        or "\\" in text
        or bool(re.search(r"\.[A-Za-z0-9]{2,5}$", text))
    )


def normalize_record(
    record: dict[str, Any],
    *,
    evidence_file: Path,
    row_index: int,
) -> dict[str, Any] | None:
    target = first_value(record, TARGET_KEYS)
    source_text = first_value(record, SOURCE_TEXT_KEYS)

    if not target and source_text and looks_like_path(source_text):
        target, source_text = source_text, ""

    offset_raw = first_value(record, OFFSET_KEYS)
    offset = parse_int(offset_raw)
    expected = normalize_hex(first_value(record, EXPECTED_KEYS))
    replacement = normalize_hex(first_value(record, REPLACEMENT_KEYS))
    notes = " | ".join(
        value
        for value in (
            first_value(record, (key,))
            for key in NOTE_KEYS
        )
        if value
    )

    searchable = " ".join(
        [
            target,
            source_text,
            offset_raw,
            expected,
            replacement,
            notes,
            json.dumps(record, ensure_ascii=False),
            str(evidence_file),
        ]
    )

    if not any((target, source_text, offset_raw, expected, notes)):
        return None

    return {
        "evidence_file": str(evidence_file),
        "row_index": row_index,
        "target": target,
        "offset": offset,
        "offset_hex": "" if offset is None else f"0x{offset:X}",
        "source_text": source_text,
        "expected_original_hex": expected,
        "replacement_hex": replacement,
        "notes": notes,
        "searchable": searchable,
        "record": record,
    }


def walk_json(
    value: Any,
    *,
    evidence_file: Path,
    records: list[dict[str, Any]],
    counter: list[int],
) -> None:
    if len(records) >= MAX_RECORDS:
        return
    if isinstance(value, dict):
        candidate = normalize_record(
            value,
            evidence_file=evidence_file,
            row_index=counter[0],
        )
        counter[0] += 1
        if candidate is not None:
            records.append(candidate)
        for child in value.values():
            walk_json(
                child,
                evidence_file=evidence_file,
                records=records,
                counter=counter,
            )
    elif isinstance(value, list):
        for child in value:
            walk_json(
                child,
                evidence_file=evidence_file,
                records=records,
                counter=counter,
            )


def should_skip_path(path: Path, output: Path) -> bool:
    try:
        if output in path.parents or path == output:
            return True
    except Exception:
        pass
    for part in path.parts:
        lowered = part.casefold()
        if lowered in SKIP_DIR_PARTS:
            return True
        if lowered.startswith(
            (
                ".prinny",
                ".checkpoint",
                ".priority",
                ".psp_studio",
            )
        ):
            return True
    return False


def discover_evidence_files(
    project: Path,
    work_root: Path,
    output: Path,
) -> list[Path]:
    roots = [
        project / "workspace",
        project / "reports",
        project,
        work_root / "reports",
    ]
    found: dict[str, Path] = {}

    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if should_skip_path(path, output):
                continue
            if path.suffix.casefold() not in TEXT_EXTENSIONS:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size <= 0 or size > MAX_TEXT_FILE_SIZE:
                continue

            lowered = str(path).casefold()
            if any(
                token in lowered
                for token in (
                    "prinny2",
                    "v7_2_curation",
                    "v7_3_font",
                )
            ) and "prinny1" not in lowered:
                continue
            found[str(path.resolve())] = path

    return sorted(found.values())


def load_evidence_records(files: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []

    for path in files:
        before = len(records)
        error = ""
        try:
            suffix = path.suffix.casefold()
            if suffix == ".json":
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                walk_json(
                    value,
                    evidence_file=path,
                    records=records,
                    counter=[1],
                )
            elif suffix == ".csv":
                rows = read_csv(path)
                for index, row in enumerate(rows, start=1):
                    candidate = normalize_record(
                        row,
                        evidence_file=path,
                        row_index=index,
                    )
                    if candidate is not None:
                        records.append(candidate)
                    if len(records) >= MAX_RECORDS:
                        break
            else:
                text = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                for index, line in enumerate(text.splitlines(), start=1):
                    if not re.search(
                        r"0x[0-9A-Fa-f]+|offset|expected|original|"
                        r"BOOT|EBOOT|START|SCRIPT|font|glyph|truncate|"
                        r"잘림|한자|글리프|■",
                        line,
                        re.IGNORECASE,
                    ):
                        continue
                    offset = parse_int(line)
                    target_match = re.search(
                        r"([A-Za-z0-9_./\\-]+\.(?:dat|bin|lzs|fnt|txp))",
                        line,
                        re.IGNORECASE,
                    )
                    record = {
                        "target": (
                            target_match.group(1)
                            if target_match
                            else ""
                        ),
                        "offset": (
                            "" if offset is None else f"0x{offset:X}"
                        ),
                        "notes": line,
                    }
                    candidate = normalize_record(
                        record,
                        evidence_file=path,
                        row_index=index,
                    )
                    if candidate is not None:
                        records.append(candidate)
                    if len(records) >= MAX_RECORDS:
                        break
        except Exception as exc:
            error = str(exc)

        inventory.append(
            {
                "path": str(path),
                "records_added": len(records) - before,
                "error": error,
            }
        )
        if len(records) >= MAX_RECORDS:
            break

    return records, inventory


def tokens(text: str) -> list[str]:
    raw = re.findall(
        r"[A-Za-z][A-Za-z0-9_.-]{2,}|"
        r"[\u3040-\u30ff\u3400-\u9fff]{2,}|"
        r"[가-힣]{2,}|■",
        text.casefold(),
    )
    return [
        token
        for token in raw
        if token not in STOPWORDS
    ]


def score_candidate(
    issue: dict[str, str],
    candidate: dict[str, Any],
) -> tuple[int, list[str]]:
    issue_id = (
        issue.get("issue_id")
        or issue.get("id")
        or ""
    ).strip()
    group = issue.get("group", "").strip()
    observation = (
        issue.get("observation")
        or issue.get("description")
        or issue.get("finding")
        or ""
    ).strip()

    searchable = candidate["searchable"].casefold()
    score = 0
    reasons: list[str] = []

    if issue_id and issue_id.casefold() in searchable:
        score += 35
        reasons.append("issue_id")

    issue_tokens = tokens(
        " ".join([issue_id, group, observation])
    )
    for token in issue_tokens:
        if token in searchable:
            score += 9
            reasons.append(f"token:{token}")

    for keyword in CATEGORY_KEYWORDS.get(group, ()):
        if keyword.casefold() in searchable:
            score += 5
            reasons.append(f"category:{keyword}")

    if candidate["target"]:
        score += 5
        reasons.append("target")
    if candidate["offset"] is not None:
        score += 12
        reasons.append("offset")
    if candidate["expected_original_hex"]:
        score += 18
        reasons.append("expected_bytes")
    if candidate["source_text"]:
        score += 6
        reasons.append("source_text")
    if candidate["replacement_hex"]:
        score += 5
        reasons.append("replacement")

    target_lower = candidate["target"].casefold()
    if group == "boot_eboot_ui" and (
        "boot.bin" in target_lower
        or "eboot.bin" in target_lower
    ):
        score += 25
        reasons.append("executable_target")
    if group != "boot_eboot_ui" and any(
        name in target_lower
        for name in ("demo", "start", "script", ".dat")
    ):
        score += 8
        reasons.append("runtime_target")

    return score, reasons


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"모듈을 불러오지 못했습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def locate_file(root: Path, relative: str) -> Path:
    direct = root / relative
    if direct.is_file():
        return direct
    name = Path(relative).name.casefold()
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name.casefold() == name
    ]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(
        f"{relative}을 추출 루트에서 확정하지 못했습니다: {root}"
    )


def prepare_binary_targets(
    project: Path,
    game_iso: Path,
    run_dir: Path,
    report_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from psp_localization.iso import prepare_disc
    from core.system_unpack import unpack_system
    from core.start_runtime import StartRuntimeArchive

    extract_dir = run_dir / "disc"
    try:
        disc_root, extract_manifest = prepare_disc(
            game_iso,
            extract_dir,
            force=True,
            extraction_mode="minimal",
        )
    except TypeError:
        disc_root, extract_manifest = prepare_disc(
            game_iso,
            extract_dir,
            force=True,
        )
    atomic_json(
        report_dir / "prinny1_extract_manifest.json",
        extract_manifest,
    )

    system_path = locate_file(
        disc_root,
        "PSP_GAME/USRDIR/SYSTEM.DAT",
    )
    unpack_dir = run_dir / "system"
    unpack_system(
        system_path,
        unpack_dir,
        report_dir / "prinny1_system_unpack.json",
        force=True,
    )

    start_dat = unpack_dir / "start.dat"
    if not start_dat.is_file():
        raise FileNotFoundError(f"start.dat 생성 실패: {start_dat}")

    archive = StartRuntimeArchive.load(start_dat)
    runtime_dir = run_dir / "start_runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    archive.extract(runtime_dir)

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
                "logical": logical,
                "scope": scope,
                "size": path.stat().st_size,
            }
        )

    for path in sorted(runtime_dir.rglob("*")):
        if path.is_file():
            add(
                path,
                path.relative_to(runtime_dir).as_posix(),
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
        "format": "prinny1_v7_6_binary_targets_v1",
        "disc_root": str(disc_root),
        "start_resource_count": len(archive.records),
        "targets": [
            {
                "logical": item["logical"],
                "scope": item["scope"],
                "path": str(item["path"]),
                "size": item["size"],
            }
            for item in targets
        ],
    }
    atomic_json(report_dir / "binary_targets.json", manifest)
    return targets, manifest


def load_target_bytes(
    targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    loaded = []
    for item in targets:
        path = item["path"]
        try:
            data = path.read_bytes()
        except OSError:
            continue
        loaded.append({**item, "data": data})
    return loaded


def encoded_needles(text: str) -> list[tuple[str, bytes]]:
    value = text.strip()
    if len(value) < 2 or len(value) > 240:
        return []
    if not JAPANESE_RE.search(value):
        return []
    result = []
    for encoding in ("shift_jis", "cp932", "utf-8"):
        try:
            blob = value.encode(encoding)
        except UnicodeEncodeError:
            continue
        if blob and blob not in [item[1] for item in result]:
            result.append((encoding, blob))
    return result


def binary_matches(
    text: str,
    loaded_targets: list[dict[str, Any]],
    *,
    limit: int = 40,
) -> list[dict[str, Any]]:
    results = []
    for encoding, needle in encoded_needles(text):
        for target in loaded_targets:
            data = target["data"]
            start = 0
            while len(results) < limit:
                offset = data.find(needle, start)
                if offset < 0:
                    break
                results.append(
                    {
                        "evidence_file": "binary_exact_search",
                        "row_index": 0,
                        "target": target["logical"],
                        "offset": offset,
                        "offset_hex": f"0x{offset:X}",
                        "source_text": text,
                        "expected_original_hex": needle.hex().upper(),
                        "replacement_hex": "",
                        "notes": (
                            f"{encoding} exact match in "
                            f"{target['scope']}"
                        ),
                        "searchable": (
                            f"{target['logical']} {text} {encoding} "
                            f"0x{offset:X}"
                        ),
                        "record": {},
                        "binary_scope": target["scope"],
                        "binary_path": str(target["path"]),
                    }
                )
                start = offset + 1
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return results


def source_text_pool(
    issue: dict[str, str],
    ranked: list[dict[str, Any]],
) -> list[str]:
    values = []
    for key in (
        "source_text",
        "original",
        "japanese",
        "text",
        "source",
    ):
        value = issue.get(key, "").strip()
        if value and JAPANESE_RE.search(value):
            values.append(value)

    for item in ranked[:30]:
        text = item["candidate"].get("source_text", "").strip()
        if text and JAPANESE_RE.search(text):
            values.append(text)

    unique = []
    seen = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique[:20]


def classify_link(candidate: dict[str, Any], score: int) -> str:
    has_target = bool(candidate.get("target"))
    has_offset = candidate.get("offset") is not None
    has_expected = bool(candidate.get("expected_original_hex"))
    binary_exact = (
        candidate.get("evidence_file")
        == "binary_exact_search"
    )

    if (
        score >= 45
        and has_target
        and has_offset
        and has_expected
        and binary_exact
    ):
        return "full_link"
    if (
        score >= 60
        and has_target
        and has_offset
        and has_expected
    ):
        return "full_link"
    if score >= 35 and has_target and has_offset:
        return "partial_link"
    if score >= 25 and has_target:
        return "candidate_only"
    return "unresolved"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    work_root = args.work_root.expanduser().resolve()
    game = args.game.expanduser().resolve()
    queue_path = args.queue.expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    out = args.out.expanduser().resolve()
    status = args.status_file.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_state(
        status,
        status="running",
        progress=2,
        stage="18개 오류 큐 확인",
        detail="프리니 1 오류 큐를 읽고 실제 증거 연결 작업을 시작합니다.",
    )
    issues = read_csv(queue_path)
    if len(issues) != 18:
        raise ValueError(
            f"예상 오류 수 18개와 다릅니다: {len(issues)}"
        )

    write_state(
        status,
        status="running",
        progress=12,
        stage="기존 보고서·로그 수집",
        detail="V3~V7.5 보고서와 CSV, JSON, 로그에서 주소·원본 바이트 후보를 수집합니다.",
        issue_count=len(issues),
    )
    evidence_files = discover_evidence_files(
        project,
        work_root,
        out,
    )
    records, inventory = load_evidence_records(evidence_files)
    atomic_json(out / "evidence_source_inventory.json", {
        "files": inventory,
        "record_count": len(records),
        "created_at": now(),
    })

    write_state(
        status,
        status="running",
        progress=34,
        stage="프리니 1 실제 자원 해제",
        detail="game.iso에서 SYSTEM, START, SCRIPT, BOOT, EBOOT을 외장 작업 폴더에 준비합니다.",
        evidence_files=len(evidence_files),
        evidence_records=len(records),
    )
    targets, target_manifest = prepare_binary_targets(
        project,
        game,
        run_dir,
        out,
    )
    loaded_targets = load_target_bytes(targets)

    write_state(
        status,
        status="running",
        progress=55,
        stage="오류별 증거 점수화",
        detail="18개 현상을 기존 주소 자료와 실제 바이너리 검색 결과에 연결합니다.",
        binary_targets=len(loaded_targets),
    )

    issue_results = []
    expected_writes = []
    unresolved = []
    all_rankings = {}

    for issue_index, issue in enumerate(issues, start=1):
        issue_id = (
            issue.get("issue_id")
            or issue.get("id")
            or f"P1-{issue_index:03d}"
        )
        ranked = []
        for candidate in records:
            score, reasons = score_candidate(issue, candidate)
            if score <= 0:
                continue
            ranked.append(
                {
                    "score": score,
                    "reasons": reasons,
                    "candidate": candidate,
                }
            )
        ranked.sort(
            key=lambda item: (
                -item["score"],
                -int(
                    item["candidate"]["offset"] is not None
                ),
                -len(
                    item["candidate"]["expected_original_hex"]
                ),
            )
        )

        direct = []
        for source_text in source_text_pool(issue, ranked):
            direct.extend(
                binary_matches(
                    source_text,
                    loaded_targets,
                    limit=20,
                )
            )

        for candidate in direct:
            score, reasons = score_candidate(issue, candidate)
            score += 25
            reasons.append("binary_exact")
            ranked.append(
                {
                    "score": score,
                    "reasons": reasons,
                    "candidate": candidate,
                }
            )

        ranked.sort(
            key=lambda item: (
                -item["score"],
                -int(
                    item["candidate"].get("evidence_file")
                    == "binary_exact_search"
                ),
                -int(
                    item["candidate"].get("offset")
                    is not None
                ),
            )
        )

        top = ranked[0] if ranked else None
        if top is None:
            link_status = "unresolved"
            top_candidate = {}
            top_score = 0
            reasons = []
        else:
            top_candidate = top["candidate"]
            top_score = int(top["score"])
            reasons = top["reasons"]
            link_status = classify_link(
                top_candidate,
                top_score,
            )

        result = {
            "issue_id": issue_id,
            "group": issue.get("group", ""),
            "observation": issue.get(
                "observation",
                issue.get("description", ""),
            ),
            "link_status": link_status,
            "evidence_score": top_score,
            "target": top_candidate.get("target", ""),
            "offset_hex": top_candidate.get(
                "offset_hex", ""
            ),
            "source_text": top_candidate.get(
                "source_text", ""
            ),
            "expected_original_hex": top_candidate.get(
                "expected_original_hex", ""
            ),
            "replacement_hex": top_candidate.get(
                "replacement_hex", ""
            ),
            "evidence_file": top_candidate.get(
                "evidence_file", ""
            ),
            "evidence_row": top_candidate.get(
                "row_index", ""
            ),
            "match_reasons": "|".join(reasons),
            "translation_change_allowed": "no",
            "next_action": {
                "full_link": (
                    "Expected Write 후보 검토 후 패치 샌드박스에 등록"
                ),
                "partial_link": (
                    "원본 바이트 또는 정확한 자원 범위를 추가 확정"
                ),
                "candidate_only": (
                    "오프셋과 런타임 자원 연결 필요"
                ),
                "unresolved": (
                    "스크린샷 원문 또는 실행 위치 증거 필요"
                ),
            }[link_status],
        }
        issue_results.append(result)

        if link_status == "full_link":
            expected_writes.append(
                {
                    "issue_id": issue_id,
                    "target": result["target"],
                    "offset_hex": result["offset_hex"],
                    "expected_original_hex": result[
                        "expected_original_hex"
                    ],
                    "replacement_hex": result[
                        "replacement_hex"
                    ],
                    "source_text": result["source_text"],
                    "evidence_file": result[
                        "evidence_file"
                    ],
                    "status": "candidate_not_applied",
                    "translation_change_allowed": "no",
                }
            )
        else:
            unresolved.append(result)

        all_rankings[issue_id] = [
            {
                "score": item["score"],
                "reasons": item["reasons"],
                "target": item["candidate"].get(
                    "target", ""
                ),
                "offset_hex": item["candidate"].get(
                    "offset_hex", ""
                ),
                "source_text": item["candidate"].get(
                    "source_text", ""
                ),
                "expected_original_hex": item[
                    "candidate"
                ].get("expected_original_hex", ""),
                "evidence_file": item["candidate"].get(
                    "evidence_file", ""
                ),
                "evidence_row": item["candidate"].get(
                    "row_index", ""
                ),
            }
            for item in ranked[:10]
        ]

        progress = 55 + round(
            issue_index / len(issues) * 30
        )
        write_state(
            status,
            status="running",
            progress=progress,
            stage="오류별 증거 연결",
            detail=(
                f"{issue_index}/{len(issues)} · "
                f"{issue_id} · {link_status}"
            ),
            full_links=sum(
                row["link_status"] == "full_link"
                for row in issue_results
            ),
            partial_links=sum(
                row["link_status"] == "partial_link"
                for row in issue_results
            ),
            unresolved_count=sum(
                row["link_status"] in {
                    "candidate_only",
                    "unresolved",
                }
                for row in issue_results
            ),
        )

    write_csv(out / "prinny1_issue_evidence_links.csv", issue_results)
    write_csv(out / "expected_write_candidates.csv", expected_writes)
    write_csv(out / "unresolved_evidence_queue.csv", unresolved)
    atomic_json(out / "top_candidates_by_issue.json", all_rankings)

    counts = Counter(
        row["link_status"] for row in issue_results
    )
    full_count = counts["full_link"]
    partial_count = counts["partial_link"]
    unresolved_count = (
        counts["candidate_only"] + counts["unresolved"]
    )

    rows_html = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['issue_id']))}</td>"
        f"<td>{html.escape(str(row['group']))}</td>"
        f"<td>{html.escape(str(row['observation']))}</td>"
        f"<td>{html.escape(str(row['link_status']))}</td>"
        f"<td>{html.escape(str(row['target']))}</td>"
        f"<td>{html.escape(str(row['offset_hex']))}</td>"
        f"<td>{html.escape(str(row['expected_original_hex'][:40]))}</td>"
        "</tr>"
        for row in issue_results
    )

    report_html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prinny 1 V7.6 Evidence Link</title>
<style>
body{{margin:0;background:#0d1117;color:#e6edf3;font-family:system-ui,"Noto Sans KR",sans-serif}}
header,main{{max-width:1400px;margin:auto;padding:20px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px}}
.metric{{font-size:34px;font-weight:900;color:#58a6ff}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:8px;border-bottom:1px solid #30363d;text-align:left;vertical-align:top}}
.ok{{color:#3fb950}}.warn{{color:#d29922}}.bad{{color:#f85149}}.muted{{color:#8b949e}}
@media(max-width:900px){{.grid{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<header><h1>프리니 1 V7.6 · 18개 오류 실제 증거 연결</h1>
<p class="muted">게임 데이터와 번역 문구는 변경하지 않았습니다.</p></header>
<main>
<div class="grid">
<div class="card"><h3>전체 오류</h3><div class="metric">18</div></div>
<div class="card"><h3>완전 연결</h3><div class="metric ok">{full_count}</div></div>
<div class="card"><h3>부분 연결</h3><div class="metric warn">{partial_count}</div></div>
<div class="card"><h3>미해결</h3><div class="metric bad">{unresolved_count}</div></div>
</div>
<div class="card" style="margin-top:12px">
<h2>오류별 연결 결과</h2>
<table><thead><tr><th>ID</th><th>분류</th><th>현상</th><th>연결</th><th>대상</th><th>오프셋</th><th>원본 바이트</th></tr></thead>
<tbody>{rows_html}</tbody></table></div>
<div class="card" style="margin-top:12px">
<h2>다음 게이트</h2>
<p>완전 연결 항목만 Expected Write 후보로 승격했습니다. 아직 어떤 항목도 ISO에 적용하지 않았습니다.</p>
</div>
</main></body></html>"""
    (out / "index.html").write_text(
        report_html,
        encoding="utf-8",
    )

    summary = {
        "format": "prinny1_v7_6_evidence_link_report_v1",
        "created_at": now(),
        "issue_count": len(issue_results),
        "full_links": full_count,
        "partial_links": partial_count,
        "candidate_only": counts["candidate_only"],
        "unresolved": counts["unresolved"],
        "evidence_files": len(evidence_files),
        "evidence_records": len(records),
        "binary_targets": len(loaded_targets),
        "expected_write_candidates": len(expected_writes),
        "patch_applied": False,
        "translation_wording_changed": False,
        "character_voice_changed": False,
        "outputs": {
            "links_csv": str(
                out / "prinny1_issue_evidence_links.csv"
            ),
            "expected_write_csv": str(
                out / "expected_write_candidates.csv"
            ),
            "unresolved_csv": str(
                out / "unresolved_evidence_queue.csv"
            ),
            "rankings_json": str(
                out / "top_candidates_by_issue.json"
            ),
            "html": str(out / "index.html"),
        },
        "status": "pass",
    }
    atomic_json(out / "all_report.json", summary)

    shutil.rmtree(run_dir / "disc", ignore_errors=True)
    shutil.rmtree(run_dir / "system", ignore_errors=True)
    shutil.rmtree(run_dir / "start_runtime", ignore_errors=True)

    write_state(
        status,
        status="complete",
        progress=100,
        stage="완료",
        detail=(
            f"18개 오류 분석 · 완전 연결 {full_count}개 · "
            f"부분 연결 {partial_count}개 · "
            f"미해결 {unresolved_count}개"
        ),
        issue_count=18,
        full_links=full_count,
        partial_links=partial_count,
        unresolved_count=unresolved_count,
        expected_write_candidates=len(expected_writes),
        evidence_files=len(evidence_files),
        evidence_records=len(records),
        binary_targets=len(loaded_targets),
        report_html=str(out / "index.html"),
        report_json=str(out / "all_report.json"),
        links_csv=str(
            out / "prinny1_issue_evidence_links.csv"
        ),
        expected_write_csv=str(
            out / "expected_write_candidates.csv"
        ),
        unresolved_csv=str(
            out / "unresolved_evidence_queue.csv"
        ),
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
                    sys.argv[
                        sys.argv.index("--status-file") + 1
                    ]
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
