from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

from core.text_catalog import scan_runs
from psp_localization.util import atomic_write_json, sha1_file


KANA_RE = re.compile(r"[\u3040-\u30ff\uff61-\uff9f]")
KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
REPEATED_RE = re.compile(r"^(.)\1{3,}$")


class StringScanError(RuntimeError):
    pass


def _candidate_score(item: dict[str, Any], *, boundary_bonus: bool) -> int:
    text = str(item.get("source", ""))
    kana = int(item.get("kana_count", 0))
    kanji = int(item.get("kanji_count", 0))
    score = kana * 5 + kanji * 2 + min(len(text), 80)
    if boundary_bonus:
        score += 20
    if any(mark in text for mark in "。！？：…【】"):
        score += 8
    if "%" in text:
        score += 3
    return score


def scan_sjis_candidates(
    data: bytes,
    *,
    source_name: str = "",
    require_terminator: bool = True,
    minimum_score: int = 18,
) -> list[dict[str, Any]]:
    """Find review-worthy Shift-JIS strings without modifying the source.

    The generic scanner is intentionally conservative for executables: a run
    normally has to end at NUL and contain kana.  This removes most accidental
    decodes from MIPS code while preserving menu/help/dialogue strings.
    """

    candidates: list[dict[str, Any]] = []
    for item in scan_runs(data):
        start = int(item["offset"])
        end = int(item["end"])
        text = str(item["source"]).strip()
        if not text or REPEATED_RE.fullmatch(text):
            continue
        has_kana = KANA_RE.search(text) is not None
        has_kanji = KANJI_RE.search(text) is not None
        if not has_kana and not (has_kanji and any(mark in text for mark in "。！？：")):
            continue
        previous_nul = start == 0 or data[start - 1] == 0
        next_nul = end >= len(data) or data[end] == 0
        boundary_ok = previous_nul or next_nul
        if require_terminator and not next_nul:
            continue
        score = _candidate_score(item, boundary_bonus=boundary_ok)
        if score < minimum_score:
            continue
        candidates.append(
            {
                "source_file": source_name,
                "offset": start,
                "offset_hex": f"0x{start:X}",
                "end": end,
                "byte_length": int(item["byte_length"]),
                "character_length": int(item["character_length"]),
                "text": text,
                "confidence": item.get("confidence", ""),
                "score": score,
                "previous_nul": previous_nul,
                "next_nul": next_nul,
                "source_hex": item.get("source_hex", ""),
                "translation": "",
                "review_status": "todo",
            }
        )

    # The same string can appear at multiple offsets; preserve occurrences but
    # sort the most useful review targets first.
    candidates.sort(key=lambda row: (-int(row["score"]), int(row["offset"])))
    return candidates


def scan_file(path: Path, *, require_terminator: bool = True) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    data = path.read_bytes()
    candidates = scan_sjis_candidates(
        data,
        source_name=path.name,
        require_terminator=require_terminator,
    )
    return {
        "format": "psp_sjis_string_scan_v1",
        "source": str(path),
        "source_size": len(data),
        "source_sha1": sha1_file(path),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "status": "pass",
    }


def candidates_from_legacy_json(path: Path) -> dict[str, Any]:
    """Convert the project's old strings JSON into the new review schema."""
    path = path.expanduser().resolve()
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, list):
        raise StringScanError(f"문자열 JSON이 목록이 아닙니다: {path}")
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not KANA_RE.search(text):
            continue
        offset = int(item.get("offset", 0))
        score = len(text) + len(KANA_RE.findall(text)) * 5
        if any(mark in text for mark in "。！？：…【】"):
            score += 8
        candidates.append(
            {
                "source_file": path.stem,
                "offset": offset,
                "offset_hex": f"0x{offset:X}",
                "end": offset + int(item.get("length", 0)),
                "byte_length": int(item.get("length", 0)),
                "character_length": len(text),
                "text": text,
                "confidence": "legacy-scan",
                "score": score,
                "previous_nul": None,
                "next_nul": None,
                "source_hex": "",
                "translation": str(item.get("translated", "")),
                "review_status": "todo" if not item.get("translated") else "translated",
            }
        )
    candidates.sort(key=lambda row: (-int(row["score"]), int(row["offset"])))
    return {
        "format": "psp_legacy_string_scan_import_v1",
        "source": str(path),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "status": "pass",
    }


def write_scan_report(report: dict[str, Any], output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_directory / "strings.json", report)
    fields = [
        "source_file", "offset", "offset_hex", "end", "byte_length",
        "character_length", "text", "confidence", "score", "previous_nul",
        "next_nul", "translation", "review_status",
    ]
    with (output_directory / "strings.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report.get("candidates", []))
