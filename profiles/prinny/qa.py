from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from core.translation_validator import CONTROL_PATTERN, control_tokens
from psp_localization.util import atomic_write_json


JAPANESE_RE = re.compile(
    r"[\u3040-\u30ff\uff61-\uff9f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
KANA_RE = re.compile(r"[\u3040-\u30ff\uff61-\uff9f]")
KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
PLACEHOLDER_RE = re.compile(r"[\ufffd□■◼◻]|(?:\?{3,})")
PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
SPACED_HANGUL_RE = re.compile(r"^(?:[가-힣]\s+){4,}[가-힣](?:[.!?…])?$")
FULLWIDTH_ALNUM_RE = re.compile(r"^[Ａ-Ｚａ-ｚ０-９\u3000【】！：，．・\-]+$")

DEFAULT_CSV = Path("workspace/translations/export/translation_master.csv")
DEFAULT_MASTER = Path("workspace/translations/export/translation_master.json")
DEFAULT_ALLOCATION = Path("workspace/font/audited_allocation_977/hangul_allocation.json")
DEFAULT_CATALOG = Path("workspace/translations/catalog/catalog.json")
DEFAULT_OUTPUT = Path("workspace/reports/prinny_qa")

RESOURCE_WIDTH_LIMITS = {
    "demo00.dat": 500,
    "picturebook.dat": 520,
    "stageinfo00.dat": 520,
    "collection.dat": 640,
    "honor.dat": 640,
    "musicshop.dat": 520,
    "luckydoll.dat": 600,
    "luckyitem.dat": 600,
    "cleartime00.dat": 520,
}
DEFAULT_WIDTH_LIMIT = 640


class TranslationQAError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TranslationQAError(f"JSON 최상위 값이 객체가 아닙니다: {path}")
    return value


def _load_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"id", "source_display", "translation", "status"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise TranslationQAError("CSV 필수 열 누락: " + ", ".join(sorted(missing)))
        return [
            {key: value or "" for key, value in row.items()}
            for row in reader
        ]


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        return default


def _allocation_map(document: dict[str, Any]) -> dict[str, bytes]:
    mapping = document.get("mapping", {})
    if not isinstance(mapping, dict):
        raise TranslationQAError("한글 배정표에 mapping 객체가 없습니다.")
    result: dict[str, bytes] = {}
    for character, item in mapping.items():
        if not isinstance(item, dict):
            continue
        encoded = str(item.get("sjis", "")).strip()
        if not encoded:
            continue
        try:
            result[str(character)] = bytes.fromhex(encoded)
        except ValueError:
            continue
    return result


def encode_text(text: str, mapping: dict[str, bytes]) -> tuple[bytes, list[str]]:
    output = bytearray()
    unsupported: list[str] = []
    for character in text:
        mapped = mapping.get(character)
        if mapped is not None:
            output.extend(mapped)
            continue
        try:
            output.extend(character.encode("shift_jis", errors="strict"))
        except UnicodeEncodeError:
            unsupported.append(character)
    return bytes(output), unsupported


def visual_width(text: str) -> tuple[int, int]:
    """20×14 고정폭 폰트 기준의 보수적 화면 폭 추정."""
    # 명시적 \n 토큰을 먼저 실제 줄바꿈으로 바꾼 뒤 나머지 제어 토큰만 제거한다.
    normalized = CONTROL_PATTERN.sub("", text.replace("\\n", "\n"))
    lines = normalized.splitlines() or [""]
    widths: list[int] = []
    for line in lines:
        width = 0
        for character in line:
            if character == "\t":
                width += 40
            elif character == " ":
                width += 10
            elif ord(character) < 0x80:
                width += 10
            elif unicodedata.east_asian_width(character) in {"W", "F", "A"}:
                width += 20
            else:
                width += 20
        widths.append(width)
    return max(widths, default=0), len(lines)


def _issue(
    code: str,
    severity: str,
    message: str,
) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _row_qa(
    row: dict[str, str],
    mapping: dict[str, bytes],
) -> dict[str, Any]:
    source = row.get("source_display", "")
    translation = row.get("translation", "")
    status = row.get("status", "").strip().casefold()
    resource = row.get("first_resource", "")
    capacity = _integer(row.get("translation_capacity_bytes"))
    encoded, unsupported = encode_text(translation, mapping)
    width, line_count = visual_width(translation)
    width_limit = RESOURCE_WIDTH_LIMITS.get(resource.casefold(), DEFAULT_WIDTH_LIMIT)
    issues: list[dict[str, str]] = []

    if not translation.strip():
        issues.append(_issue("untranslated", "error", "최종 번역문이 비어 있습니다."))
    elif source == translation and JAPANESE_RE.search(source):
        issues.append(_issue("source_copied", "error", "일본어 원문이 번역문에 그대로 복사되었습니다."))

    if translation and status in {"", "untranslated", "미번역"}:
        issues.append(_issue("status_mismatch", "warning", "번역문은 있으나 상태가 미번역입니다."))

    if unsupported:
        names = ", ".join(f"{char}(U+{ord(char):04X})" for char in dict.fromkeys(unsupported))
        issues.append(_issue("unsupported_character", "error", f"배정표/Shift-JIS에 없는 문자: {names}"))

    if capacity and len(encoded) > capacity:
        issues.append(_issue("byte_overflow", "error", f"번역 {len(encoded)}바이트 > 용량 {capacity}바이트"))

    if control_tokens(source) != control_tokens(translation):
        issues.append(_issue("control_mismatch", "error", "원문과 번역문의 제어 토큰 구성이 다릅니다."))

    if JAPANESE_RE.search(translation):
        residues = "".join(dict.fromkeys(JAPANESE_RE.findall(translation)))
        issues.append(_issue("japanese_residue", "warning", f"일본어/한자 잔존: {residues}"))

    if PLACEHOLDER_RE.search(translation) or PRIVATE_USE_RE.search(translation):
        issues.append(_issue("broken_glyph_marker", "error", "깨진 글리프 또는 플레이스홀더 문자가 의심됩니다."))

    if SPACED_HANGUL_RE.search(translation):
        issues.append(_issue("spaced_hangul", "warning", "한글 음절 사이에 반복 공백이 있습니다."))

    if width > width_limit:
        issues.append(_issue("visual_width", "warning", f"예상 한 줄 폭 {width}px > 권장 {width_limit}px"))

    if line_count > 3:
        issues.append(_issue("line_count", "warning", f"명시적 줄 수가 {line_count}줄입니다."))

    severity = "ok"
    if any(item["severity"] == "error" for item in issues):
        severity = "error"
    elif issues:
        severity = "warning"

    return {
        "id": row.get("id", ""),
        "resource": resource,
        "offset": row.get("first_offset_hex", ""),
        "source": source,
        "translation": translation,
        "status": row.get("status", ""),
        "capacity_bytes": capacity,
        "encoded_bytes": len(encoded),
        "remaining_bytes": capacity - len(encoded) if capacity else None,
        "visual_width_px": width,
        "width_limit_px": width_limit,
        "line_count": line_count,
        "severity": severity,
        "issues": issues,
    }


def _is_repeated_noise(text: str) -> bool:
    stripped = text.lstrip("ﾈﾉﾊ")
    if len(stripped) < 4 or len(set(stripped)) != 1:
        return False
    return KANJI_RE.fullmatch(stripped[0]) is not None


def uncovered_candidates(
    catalog: dict[str, Any],
    master: dict[str, Any],
) -> list[dict[str, Any]]:
    covered = {
        (str(occurrence.get("resource", "")), int(occurrence.get("offset", 0)))
        for entry in master.get("entries", [])
        for occurrence in entry.get("occurrences", [])
        if isinstance(occurrence, dict)
    }
    ignored_resources = {"anime00.dat", "effect00.gm3"}
    candidates: list[dict[str, Any]] = []

    for entry in catalog.get("entries", []):
        if not isinstance(entry, dict):
            continue
        resource = str(entry.get("resource", ""))
        offset = int(entry.get("offset", 0))
        text = str(entry.get("source", ""))
        confidence = str(entry.get("confidence", ""))
        if resource.casefold() in ignored_resources:
            continue
        if (resource, offset) in covered:
            continue
        if confidence not in {"high", "medium"}:
            continue
        if len(text) < 2 or not JAPANESE_RE.search(text):
            continue
        if _is_repeated_noise(text):
            continue
        if text.startswith(("ﾈ", "ﾉ", "ﾊ")) and set(text[1:]) <= {"？", "?"}:
            continue
        if FULLWIDTH_ALNUM_RE.fullmatch(text):
            continue
        # 단순 성우/음악명처럼 번역하지 않아도 되는 항목은 낮은 우선순위로 남긴다.
        japanese_count = int(entry.get("japanese_count", 0))
        score = japanese_count * 3 + len(text) + (12 if confidence == "high" else 4)
        if KANA_RE.search(text):
            score += 8
        if any(mark in text for mark in "。！？："):
            score += 6
        candidates.append(
            {
                "priority": score,
                "resource": resource,
                "offset": offset,
                "offset_hex": f"0x{offset:X}",
                "confidence": confidence,
                "source": text,
                "byte_length": int(entry.get("byte_length", 0)),
                "next_byte": entry.get("next_byte"),
                "reason": "번역 마스터 occurrence에 포함되지 않은 일본어 후보",
                "review_status": "todo",
                "translation": "",
            }
        )

    candidates.sort(key=lambda item: (-int(item["priority"]), item["resource"].casefold(), int(item["offset"])))
    return candidates


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            encoded = dict(row)
            if "issues" in encoded:
                encoded["issue_codes"] = ";".join(issue["code"] for issue in encoded["issues"])
                encoded["issue_messages"] = " | ".join(issue["message"] for issue in encoded["issues"])
            writer.writerow(encoded)


REVIEW_SUGGESTIONS = {
    "TXT-EE6E08FFA7E2": "돌려드림.",
    "TXT-65A9B2A7B100": "본명, 아사기리 아사기.",
}


def build_review_queue(
    results: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for result in results:
        if result["severity"] == "ok":
            continue
        queue.append(
            {
                "kind": "translation_qa",
                "priority": 100 if result["severity"] == "error" else 80,
                "id": result["id"],
                "resource": result["resource"],
                "offset_hex": result["offset"],
                "source": result["source"],
                "current_translation": result["translation"],
                "suggested_translation": REVIEW_SUGGESTIONS.get(result["id"], ""),
                "issue_codes": ";".join(issue["code"] for issue in result["issues"]),
                "notes": " | ".join(issue["message"] for issue in result["issues"]),
                "review_status": "todo",
            }
        )
    for candidate in candidates:
        queue.append(
            {
                "kind": "uncovered_candidate",
                "priority": candidate["priority"],
                "id": "",
                "resource": candidate["resource"],
                "offset_hex": candidate["offset_hex"],
                "source": candidate["source"],
                "current_translation": "",
                "suggested_translation": "",
                "issue_codes": "uncovered_candidate",
                "notes": candidate["reason"],
                "review_status": "todo",
            }
        )
    queue.sort(key=lambda row: (-int(row["priority"]), row["resource"].casefold(), row["offset_hex"]))
    return queue


def run_qa(
    *,
    csv_path: Path = DEFAULT_CSV,
    master_path: Path = DEFAULT_MASTER,
    allocation_path: Path = DEFAULT_ALLOCATION,
    catalog_path: Path = DEFAULT_CATALOG,
    output_directory: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    rows = _load_rows(csv_path)
    master = _load_json(master_path)
    allocation = _load_json(allocation_path)
    catalog = _load_json(catalog_path) if catalog_path.is_file() else {"entries": []}
    mapping = _allocation_map(allocation)

    results = [_row_qa(row, mapping) for row in rows]
    candidates = uncovered_candidates(catalog, master)
    issue_counts: Counter[str] = Counter(
        issue["code"] for result in results for issue in result["issues"]
    )
    error_rows = [result for result in results if result["severity"] == "error"]
    warning_rows = [result for result in results if result["severity"] == "warning"]
    review_queue = build_review_queue(results, candidates)

    report = {
        "format": "prinny_translation_qa_v1",
        "inputs": {
            "csv": str(csv_path),
            "master": str(master_path),
            "allocation": str(allocation_path),
            "catalog": str(catalog_path),
        },
        "summary": {
            "row_count": len(results),
            "ok_count": len(results) - len(error_rows) - len(warning_rows),
            "error_count": len(error_rows),
            "warning_count": len(warning_rows),
            "uncovered_candidate_count": len(candidates),
            "allocation_character_count": len(mapping),
            "issue_counts": dict(issue_counts),
        },
        "rows": results,
        "uncovered_candidates": candidates,
        "review_queue": review_queue,
        "status": "pass" if not error_rows else "needs-review",
    }

    output_directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_directory / "qa_report.json", report)
    _write_csv(
        output_directory / "qa_rows.csv",
        results,
        [
            "id", "resource", "offset", "source", "translation", "status",
            "capacity_bytes", "encoded_bytes", "remaining_bytes", "visual_width_px",
            "width_limit_px", "line_count", "severity", "issue_codes", "issue_messages",
        ],
    )
    _write_csv(
        output_directory / "uncovered_candidates.csv",
        candidates,
        [
            "priority", "resource", "offset", "offset_hex", "confidence", "source",
            "byte_length", "next_byte", "reason", "review_status", "translation",
        ],
    )
    _write_csv(
        output_directory / "review_queue.csv",
        review_queue,
        [
            "kind", "priority", "id", "resource", "offset_hex", "source",
            "current_translation", "suggested_translation", "issue_codes", "notes",
            "review_status",
        ],
    )
    summary_text = (
        "PRINNY QA\n"
        "=========\n"
        f"Rows: {len(results)}\n"
        f"Errors: {len(error_rows)}\n"
        f"Warnings: {len(warning_rows)}\n"
        f"Uncovered candidates: {len(candidates)}\n"
        f"Review queue: {len(review_queue)}\n"
    )
    (output_directory / "summary.txt").write_text(summary_text, encoding="utf-8")
    return report
