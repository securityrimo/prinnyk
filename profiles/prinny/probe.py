from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from core.font_runtime import FontRuntime, FontRuntimeError
from core.lzs import NISLZSError, decompress_buffer
from core.nispack import NISPack
from psp_localization.iso import find_disc_root
from psp_localization.util import sha1_bytes, sha1_file


class PrinnyProbeError(RuntimeError):
    pass


START_RECORD_SIZE = 0x20
START_OFFSET_FIELD = 0x04
START_NAME_FIELD = 0x08
START_NAME_SIZE = 0x18
REQUIRED_START_RESOURCES = {"font.fnt", "font.txp", "jis2ucs.bin", "ucs2jis.bin"}


def _start_records(data: bytes) -> list[dict[str, Any]]:
    if len(data) < START_RECORD_SIZE:
        raise PrinnyProbeError("start.dat이 너무 작습니다.")
    count = struct.unpack_from("<I", data, 0)[0]
    table_end = count * START_RECORD_SIZE
    if count <= 0 or table_end > len(data):
        raise PrinnyProbeError("start.dat 레코드 테이블이 유효하지 않습니다.")

    raw: list[dict[str, Any]] = []
    for index in range(count):
        base = index * START_RECORD_SIZE
        offset = struct.unpack_from("<I", data, base + START_OFFSET_FIELD)[0]
        name = data[
            base + START_NAME_FIELD:base + START_NAME_FIELD + START_NAME_SIZE
        ].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        raw.append({"index": index, "name": name, "offset": offset})

    records: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        end = raw[index + 1]["offset"] if index + 1 < len(raw) else len(data)
        start = int(item["offset"])
        if not (table_end <= start <= end <= len(data)):
            raise PrinnyProbeError(f"start.dat 자원 범위 오류: {item['name']}")
        blob = data[start:end]
        records.append(
            {
                **item,
                "end": end,
                "size": len(blob),
                "sha1": sha1_bytes(blob),
                "blob": blob,
            }
        )
    return records


def _pack_entries(path: Path) -> list[dict[str, Any]]:
    pack = NISPack(path)
    return pack.parse(verbose=False)


def _entry_summary(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": int(entry["index"]),
            "name": str(entry["name"]),
            "offset": int(entry["offset"]),
            "size": int(entry["size"]),
            "metadata": int(entry["metadata"]),
            "plausible": bool(entry.get("plausible", False)),
        }
        for entry in entries
    ]


def probe_prinny_disc(disc_root: Path) -> dict[str, Any]:
    disc_root = find_disc_root(disc_root)
    usrdir = disc_root / "PSP_GAME" / "USRDIR"
    system = usrdir / "SYSTEM.DAT"
    script = usrdir / "SCRIPT.DAT"
    if not system.is_file():
        raise PrinnyProbeError(f"SYSTEM.DAT 없음: {system}")

    system_entries = _pack_entries(system)
    start_matches = [
        entry for entry in system_entries
        if str(entry.get("name", "")).casefold() == "start.lzs"
    ]
    if len(start_matches) != 1:
        raise PrinnyProbeError(f"start.lzs 엔트리 수가 {len(start_matches)}개입니다.")
    start_entry = start_matches[0]
    system_data = system.read_bytes()
    start_lzs = system_data[int(start_entry["offset"]):int(start_entry["end"])]
    try:
        start_dat, lzs_header = decompress_buffer(start_lzs)
    except NISLZSError as error:
        raise PrinnyProbeError(f"start.lzs 해제 실패: {error}") from error

    records = _start_records(start_dat)
    by_name = {str(record["name"]).casefold(): record for record in records}
    missing = sorted(name for name in REQUIRED_START_RESOURCES if name not in by_name)
    font: dict[str, Any] = {"status": "missing", "missing": missing}
    if not missing:
        try:
            table = FontRuntime._parse_fnt(by_name["font.fnt"]["blob"])
            txp = FontRuntime._parse_txp(by_name["font.txp"]["blob"])
        except FontRuntimeError as error:
            font = {"status": "error", "error": str(error)}
        else:
            font = {
                "status": "pass",
                "table_entries": len(table),
                "txp": txp,
                "font_fnt_size": by_name["font.fnt"]["size"],
                "font_txp_size": by_name["font.txp"]["size"],
            }

    script_entries: list[dict[str, Any]] = []
    script_error = ""
    if script.is_file():
        try:
            script_entries = _pack_entries(script)
        except (OSError, ValueError) as error:
            script_error = str(error)

    return {
        "format": "prinny_profile_probe_v1",
        "disc_root": str(disc_root),
        "system": {
            "path": str(system),
            "size": system.stat().st_size,
            "sha1": sha1_file(system),
            "entries": _entry_summary(system_entries),
        },
        "start": {
            "lzs_size": len(start_lzs),
            "lzs_sha1": sha1_bytes(start_lzs),
            "lzs_header": lzs_header,
            "dat_size": len(start_dat),
            "dat_sha1": sha1_bytes(start_dat),
            "record_count": len(records),
            "resources": [
                {
                    "index": record["index"],
                    "name": record["name"],
                    "offset": record["offset"],
                    "size": record["size"],
                    "sha1": record["sha1"],
                }
                for record in records
            ],
        },
        "font": font,
        "script": {
            "present": script.is_file(),
            "path": str(script),
            "size": script.stat().st_size if script.is_file() else 0,
            "sha1": sha1_file(script) if script.is_file() else "",
            "entries": _entry_summary(script_entries),
            "error": script_error,
        },
        "status": "pass",
    }


def compare_prinny_profiles(
    game1: dict[str, Any],
    game2: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    a_resources = {item["name"] for item in game1["start"]["resources"]}
    b_resources = {item["name"] for item in game2["start"]["resources"]}
    union = a_resources | b_resources
    overlap = len(a_resources & b_resources) / max(1, len(union))

    a_system_names = [item["name"] for item in game1["system"]["entries"]]
    b_system_names = [item["name"] for item in game2["system"]["entries"]]
    system_layout_same = a_system_names == b_system_names
    if system_layout_same:
        reasons.append("SYSTEM.DAT NISPACK 엔트리 이름과 순서가 같습니다.")
    else:
        reasons.append("SYSTEM.DAT NISPACK 엔트리 구성이 다릅니다.")

    a_font = game1.get("font", {})
    b_font = game2.get("font", {})
    font_same = (
        a_font.get("status") == "pass"
        and b_font.get("status") == "pass"
        and a_font.get("table_entries") == b_font.get("table_entries")
        and a_font.get("txp", {}).get("width") == b_font.get("txp", {}).get("width")
        and a_font.get("txp", {}).get("glyph_height") == b_font.get("txp", {}).get("glyph_height")
        and a_font.get("txp", {}).get("pixel_format") == b_font.get("txp", {}).get("pixel_format")
    )
    reasons.append(
        "런타임 폰트 구조가 같습니다." if font_same else "런타임 폰트 구조 또는 글리프 테이블이 다릅니다."
    )
    reasons.append(f"START 자원 이름 겹침 비율은 {overlap:.1%}입니다.")

    script_a = {item["name"] for item in game1.get("script", {}).get("entries", [])}
    script_b = {item["name"] for item in game2.get("script", {}).get("entries", [])}
    script_overlap = len(script_a & script_b) / max(1, len(script_a | script_b))
    reasons.append(f"SCRIPT.DAT 자원 이름 겹침 비율은 {script_overlap:.1%}입니다.")

    if system_layout_same and font_same and overlap >= 0.9 and script_overlap >= 0.75:
        grade = "A"
        verdict = "프리니 1 프로필 엔진을 그대로 사용할 가능성이 높습니다. 번역 데이터와 오프셋은 프리니 2에서 별도로 추출해야 합니다."
    elif overlap >= 0.65 and (font_same or system_layout_same):
        grade = "B"
        verdict = "공통 엔진은 재사용할 수 있지만 프리니 2용 자원 설정과 일부 파서 조정이 필요합니다."
    else:
        grade = "C"
        verdict = "프리니 2 전용 프로필/플러그인이 필요합니다."

    return {
        "format": "prinny1_prinny2_compatibility_v1",
        "grade": grade,
        "verdict": verdict,
        "resource_overlap_ratio": round(overlap, 6),
        "script_overlap_ratio": round(script_overlap, 6),
        "system_layout_same": system_layout_same,
        "font_structure_same": font_same,
        "reasons": reasons,
        "important_note": "A 등급이어도 프리니 1 번역문이나 고정 오프셋을 프리니 2 ISO에 직접 복사하면 안 됩니다.",
        "status": "pass",
    }
