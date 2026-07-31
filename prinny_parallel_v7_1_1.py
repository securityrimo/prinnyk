#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from core.lzs import decompress_buffer
from core.nispack import NISPack
from core.start_runtime import REQUIRED_RESOURCES, StartRuntimeArchive
from core.text_catalog import build_catalog, save_catalog
from psp_localization.iso import prepare_disc
from psp_localization.util import atomic_write_json


PROJECT = Path(__file__).resolve().parent
START_RECORD_SIZE = 0x20


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


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
        except (OSError, json.JSONDecodeError):
            old = {}
    atomic_write_json(
        path,
        {
            **old,
            "format": "prinny_v7_1_2_state_v1",
            "status": status,
            "progress": int(progress),
            "stage": stage,
            "detail": detail,
            "updated_at": now(),
            "pid": os.getpid(),
            **extra,
        },
    )


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"객체 JSON이 아닙니다: {path}")
    return value


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_minimal(source: Path, output: Path) -> tuple[Path, dict[str, Any]]:
    try:
        return prepare_disc(
            source,
            output,
            force=True,
            extraction_mode="minimal",
        )
    except TypeError:
        return prepare_disc(source, output, force=True)


def locate_system_dat(disc_root: Path) -> Path:
    """prepare_disc가 반환한 실제 루트에서 SYSTEM.DAT을 안전하게 확정한다."""
    disc_root = Path(disc_root).expanduser().resolve()

    direct = disc_root / "PSP_GAME" / "USRDIR" / "SYSTEM.DAT"
    if direct.is_file():
        return direct

    # 일부 7z/파일시스템 조합의 대소문자 차이를 허용하되,
    # 후보가 둘 이상이면 임의 선택하지 않는다.
    candidates = sorted(
        path
        for path in disc_root.rglob("*")
        if (
            path.is_file()
            and path.name.casefold() == "system.dat"
            and path.parent.name.casefold() == "usrdir"
            and path.parent.parent.name.casefold() == "psp_game"
        )
    )

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(
            "prepare_disc가 반환한 디스크 루트에서 SYSTEM.DAT을 "
            f"찾지 못했습니다: root={disc_root}"
        )
    raise RuntimeError(
        "SYSTEM.DAT 후보가 여러 개라 자동 선택을 중단합니다: "
        + ", ".join(str(item) for item in candidates)
    )


def find_unique_entry(entries: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [
        item
        for item in entries
        if str(item.get("name", "")).casefold() == name.casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"{name} 엔트리 수가 1개가 아닙니다: {len(matches)}")
    entry = matches[0]
    if not entry.get("plausible", False):
        raise ValueError(f"{name} 엔트리 범위 검증 실패")
    return entry


def inventory_archive(archive: StartRuntimeArchive) -> list[dict[str, Any]]:
    return [
        {
            "index": record.index,
            "name": record.name,
            "output_name": record.output_name,
            "offset": record.data_offset,
            "offset_hex": f"0x{record.data_offset:X}",
            "size": record.size,
            "size_hex": f"0x{record.size:X}",
            "sha1": record.sha1,
        }
        for record in archive.records
    ]


def permissive_unpack_system(
    system_path: Path,
    output_dir: Path,
    manifest_path: Path,
) -> tuple[StartRuntimeArchive, dict[str, Any]]:
    """SYSTEM.DAT을 풀되 Prinny 1의 폰트 위치를 강제하지 않는다."""
    pack = NISPack(system_path)
    entries = pack.parse(verbose=False)
    start_entry = find_unique_entry(entries, "start.lzs")

    start = int(start_entry["offset"])
    end = int(start_entry["end"])
    start_lzs = pack.data[start:end]
    start_dat, header = decompress_buffer(start_lzs)

    if str(header.get("extension", "")).casefold() != "dat":
        raise ValueError(
            f"start.lzs 출력 확장자가 dat이 아닙니다: {header.get('extension')!r}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    start_lzs_path = output_dir / "start.lzs"
    start_dat_path = output_dir / "start.dat"
    write_bytes(start_lzs_path, start_lzs)
    write_bytes(start_dat_path, start_dat)

    archive = StartRuntimeArchive.load(start_dat_path)
    names = {record.name.casefold() for record in archive.records}
    required = {
        name: name.casefold() in names
        for name in sorted(REQUIRED_RESOURCES)
    }

    manifest = {
        "format": "prinny_system_discovery_unpack_v1",
        "pipeline": "SYSTEM.DAT -> start.lzs -> start.dat",
        "mode": "discovery_non_strict",
        "source": {
            "path": str(system_path),
            "size": len(pack.data),
            "sha1": sha1_bytes(pack.data),
        },
        "nispack": {
            "entry_count": len(entries),
            "entries": [
                {
                    "index": int(item["index"]),
                    "name": str(item["name"]),
                    "offset": int(item["offset"]),
                    "size": int(item["size"]),
                    "metadata": int(item["metadata"]),
                    "plausible": bool(item["plausible"]),
                }
                for item in entries
            ],
            "start_entry": {
                "index": int(start_entry["index"]),
                "name": str(start_entry["name"]),
                "offset": start,
                "size": int(start_entry["size"]),
                "sha1": sha1_bytes(start_lzs),
            },
        },
        "lzs": {
            "extension": header["extension"],
            "decompressed_size": int(header["decompressed_size"]),
            "compressed_size_field": int(header["compressed_size"]),
            "compressed_end": int(header["compressed_end"]),
            "flag": int(header["flag"]),
        },
        "start_archive": {
            "record_count": len(archive.records),
            "table_end": archive.table_end,
            "resources": inventory_archive(archive),
            "prinny1_expected_resources": required,
            "missing_prinny1_expected_resources": [
                name for name, present in required.items() if not present
            ],
        },
        "validation": {
            "archive_structure": "pass",
            "prinny1_font_location_match": (
                "pass"
                if required.get("font.fnt") and required.get("font.txp")
                else "not_applicable_for_prinny2_discovery"
            ),
            "status": "pass",
        },
    }
    atomic_write_json(manifest_path, manifest)
    return archive, manifest


def resource_candidates(
    system_manifest: dict[str, Any],
    archive: StartRuntimeArchive,
) -> dict[str, Any]:
    keywords = (
        "font",
        "fnt",
        "txp",
        "glyph",
        "char",
        "jis",
        "ucs",
        "moji",
        "text",
    )

    def candidate(name: str) -> bool:
        lowered = name.casefold()
        return (
            any(word in lowered for word in keywords)
            or Path(lowered).suffix in {".fnt", ".txp", ".gim", ".tm2"}
        )

    start_items = [
        item
        for item in inventory_archive(archive)
        if candidate(str(item["name"]))
    ]
    system_items = [
        item
        for item in system_manifest["nispack"]["entries"]
        if candidate(str(item["name"]))
    ]

    exact = {
        "font.fnt": archive.find_record("font.fnt") is not None,
        "font.txp": archive.find_record("font.txp") is not None,
        "jis2ucs.bin": archive.find_record("jis2ucs.bin") is not None,
        "ucs2jis.bin": archive.find_record("ucs2jis.bin") is not None,
    }

    if exact["font.fnt"] and exact["font.txp"]:
        location_status = "prinny1_compatible_start_location"
    elif start_items:
        location_status = "nonstandard_start_candidates_found"
    elif system_items:
        location_status = "system_container_candidates_found"
    else:
        location_status = "font_location_unresolved"

    return {
        "format": "prinny2_font_discovery_v1",
        "location_status": location_status,
        "exact_prinny1_names": exact,
        "start_candidates": start_items,
        "system_candidates": system_items,
        "search_keywords": list(keywords),
        "blocking": False,
        "next_action": (
            "후보 자원의 헤더·크기·실행 파일 참조를 대조해 실제 폰트와 코드맵 위치를 확정합니다."
        ),
        "created_at": now(),
    }


def build_prinny1_queue(v7: dict[str, Any], output: Path) -> dict[str, Any]:
    old_report_path = output.parent / "prinny1_runtime_repair_queue.json"
    if old_report_path.is_file():
        try:
            old = load_json(old_report_path)
            if Path(str(old.get("queue_csv", ""))).is_file():
                return old
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "issue_id",
        "group",
        "observation",
        "source_link_status",
        "translation_change_allowed",
        "status",
    ]
    rows = [
        {
            "issue_id": "P1-GLYPH",
            "group": "runtime_glyph_or_boundary",
            "observation": "■·엉뚱한 한자/영문 글리프 잔존",
            "source_link_status": "unlinked",
            "translation_change_allowed": "no",
            "status": "todo",
        },
        {
            "issue_id": "P1-LAYOUT",
            "group": "capacity_or_layout",
            "observation": "문장 중간 또는 끝 잘림",
            "source_link_status": "unlinked",
            "translation_change_allowed": "no",
            "status": "todo",
        },
        {
            "issue_id": "P1-UI",
            "group": "boot_eboot_ui",
            "observation": "난이도·튜토리얼·HUD·결과 화면 미번역",
            "source_link_status": "unlinked",
            "translation_change_allowed": "no",
            "status": "todo",
        },
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return {
        "format": "prinny1_runtime_repair_queue_v1",
        "queue_csv": str(output),
        "issue_count": len(rows),
        "boot_ui_candidate_count": int(
            v7.get("executable_scans", {})
            .get("game1", {})
            .get("candidate_count", 0)
        ),
        "translation_policy": "대사 문구와 캐릭터 말투 변경 금지",
    }


def create_profile(
    v7: dict[str, Any],
    manifest: dict[str, Any],
    font: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    game = v7.get("analyses", {}).get("game2", {}).get("game", {})
    return {
        "format": "psp_localization_game_profile_v1",
        "profile_id": "prinny2_jp_discovery",
        "display_name": "Prinny 2 Japanese discovery profile",
        "game": {
            "disc_id": game.get("disc_id", ""),
            "title": game.get("title", ""),
            "disc_version": game.get("disc_version", ""),
        },
        "containers": {
            "system": {
                "path": "PSP_GAME/USRDIR/SYSTEM.DAT",
                "format": "nispack",
                "entry_count": manifest["nispack"]["entry_count"],
            },
            "start": {
                "entry": "start.lzs",
                "compression": "nis_lzs",
                "record_count": manifest["start_archive"]["record_count"],
            },
        },
        "font": {
            "status": font["location_status"],
            "discovery_file": "font_discovery.json",
            "required_before_patch_build": True,
        },
        "translation_catalog": {
            "entry_count": catalog["entry_count"],
            "resource_count": catalog["resource_count"],
            "catalog_sha1": catalog["catalog_sha1"],
            "auto_copy_from_prinny1": False,
        },
        "translation_policy": {
            "character_voice": "translator_declared",
            "auto_rewrite_dialogue": False,
            "machine_safe_fixes_only": True,
        },
        "patch_policy": {
            "source_hash_required": True,
            "expected_write_required": True,
            "zero_actual_change_is_failure": True,
            "output_iso_must_be_separate": True,
        },
        "status": "translation_catalog_ready_font_location_pending",
        "created_at": now(),
    }


def write_dashboard(
    path: Path,
    *,
    v7: dict[str, Any],
    queue: dict[str, Any],
    catalog: dict[str, Any],
    font: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    compatibility = v7.get("compatibility", {})
    candidates = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('name', '')))}</td>"
        f"<td>{int(item.get('size', 0))}</td>"
        f"<td>{html.escape(str(item.get('sha1', '')))}</td>"
        "</tr>"
        for item in font.get("start_candidates", [])[:30]
    ) or '<tr><td colspan="3">START 내부에서 이름 기반 후보 없음</td></tr>'

    document = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSP Localization Studio V7.1.2</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--ok:#3fb950;--warn:#d29922}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,"Noto Sans KR",sans-serif}}
header{{padding:20px 24px;border-bottom:1px solid var(--line);background:var(--panel)}}
main{{max-width:1280px;margin:auto;padding:18px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:17px}}
.wide{{grid-column:1/-1}}h1,h2{{margin:0 0 10px}}.metric{{font-size:36px;font-weight:900;color:var(--accent)}}
.ok{{color:var(--ok)}}.warn{{color:var(--warn)}}.muted{{color:var(--muted)}}table{{width:100%;border-collapse:collapse}}
th,td{{border-bottom:1px solid var(--line);padding:8px;text-align:left}}code{{color:#79c0ff}}
@media(max-width:800px){{main{{grid-template-columns:1fr}}.wide{{grid-column:auto}}}}
</style></head>
<body>
<header><h1>PSP Localization Studio · V7.1.2</h1>
<p class="muted">프리니 2 폰트 위치 차이를 오류가 아닌 전용 프로필 발견 항목으로 처리</p></header>
<main>
<section class="card"><h2>V7.0 호환성</h2>
<div class="metric">{html.escape(str(compatibility.get("grade", "")))}</div>
<p>{html.escape(str(compatibility.get("verdict", "")))}</p></section>
<section class="card"><h2>프리니 2 START</h2>
<div class="metric ok">{manifest["start_archive"]["record_count"]}</div>
<p>구조 파싱 및 자원 추출 통과</p></section>
<section class="card"><h2>프리니 2 번역 후보</h2>
<div class="metric">{catalog["entry_count"]}</div>
<p>{catalog["resource_count"]}개 자원에서 추출</p></section>
<section class="card"><h2>폰트 위치</h2>
<div class="warn">{html.escape(font["location_status"])}</div>
<p>번역 후보 추출은 계속 가능하지만 실제 폰트 패치는 위치 확정 후 진행합니다.</p></section>
<section class="card"><h2>프리니 1 수정 트랙</h2>
<p>오류 큐: <b>{queue["issue_count"]}</b></p>
<p>BOOT/UI 후보: <b>{queue["boot_ui_candidate_count"]}</b></p>
<p>대사 문구·캐릭터 말투: <b>잠금</b></p></section>
<section class="card"><h2>프리니 2 번역 정책</h2>
<p>프리니 1 번역 자동 복사: <b>금지</b></p>
<p>Expected Write 없는 패치: <b>금지</b></p></section>
<section class="card wide"><h2>START 이름 기반 폰트 후보</h2>
<table><thead><tr><th>이름</th><th>크기</th><th>SHA-1</th></tr></thead>
<tbody>{candidates}</tbody></table></section>
</main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="prinny_v711_") as tmp:
        path = Path(tmp) / "start.dat"
        names_and_data = [
            ("jis2ucs.bin", b"A" * 16),
            ("ucs2jis.bin", b"B" * 16),
            ("Demo00.dat", b"\x82\xa0\x82\xa2\x82\xa4\x00"),
        ]
        count = len(names_and_data)
        table_end = count * START_RECORD_SIZE
        table = bytearray(table_end)
        blobs = bytearray()
        cursor = table_end
        for index, (name, blob) in enumerate(names_and_data):
            at = index * START_RECORD_SIZE
            struct.pack_into("<I", table, at, count)
            struct.pack_into("<I", table, at + 4, cursor)
            encoded = name.encode("ascii")[:0x17]
            table[at + 8:at + 8 + len(encoded)] = encoded
            blobs.extend(blob)
            cursor += len(blob)
        struct.pack_into("<I", table, 0, count)
        path.write_bytes(bytes(table + blobs))
        archive = StartRuntimeArchive.load(path)
        exact = {
            name: archive.find_record(name) is not None
            for name in REQUIRED_RESOURCES
        }
        if exact["font.fnt"] or exact["font.txp"]:
            raise AssertionError("합성 START에 폰트가 잘못 탐지됐습니다.")
        if len(archive.records) != 3:
            raise AssertionError("합성 START 레코드 수 불일치")
        print("SELF TEST PASS: 폰트 없는 START를 발견 모드에서 정상 처리")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v7-report", type=Path)
    parser.add_argument("--game2", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    required_args = (
        args.v7_report,
        args.game2,
        args.run_dir,
        args.report_dir,
        args.status_file,
    )
    if any(value is None for value in required_args):
        parser.error("실행 인자가 부족합니다.")

    v7_path = args.v7_report.expanduser().resolve()
    game2 = args.game2.expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    report_dir = args.report_dir.expanduser().resolve()
    status_file = args.status_file.expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_state(
        status_file,
        status="running",
        progress=3,
        stage="이전 오류 복구",
        detail="프리니 1 전용 폰트 위치 검사를 프리니 2 발견 단계에서 분리합니다.",
    )
    v7 = load_json(v7_path)

    queue = build_prinny1_queue(
        v7,
        report_dir / "prinny1_runtime_repair_queue.csv",
    )

    system_dir = run_dir / "game2_system"
    start_dat = system_dir / "start.dat"
    system_manifest_path = report_dir / "game2_system_discovery_unpack.json"

    write_state(
        status_file,
        status="running",
        progress=15,
        stage="프리니 2 START 확보",
        detail="이전 실행의 start.dat을 재사용하거나 game2.iso에서 다시 추출합니다.",
        prinny1_issue_queue=queue["issue_count"],
    )

    manifest: dict[str, Any]
    if start_dat.is_file():
        archive = StartRuntimeArchive.load(start_dat)
        old_manifest = None
        for candidate in (
            report_dir / "game2_system_unpack.json",
            system_dir / "manifest.json",
        ):
            if candidate.is_file():
                try:
                    old_manifest = load_json(candidate)
                    break
                except Exception:
                    old_manifest = None

        # SYSTEM 목차 후보를 얻기 위해 최소 추출본이 있으면 읽고, 없으면 다시 준비한다.
        extract_workspace = run_dir / "game2_disc"
        try:
            system_path = locate_system_dat(extract_workspace)
        except FileNotFoundError:
            disc_root, extract_manifest = prepare_minimal(
                game2,
                extract_workspace,
            )
            atomic_write_json(
                report_dir / "game2_extract_manifest_v7_1_2.json",
                extract_manifest,
            )
            # 중요: prepare_disc의 반환 루트는 보통 extract_workspace/iso이다.
            system_path = locate_system_dat(disc_root)

        pack = NISPack(system_path)
        entries = pack.parse(verbose=False)
        manifest = {
            "format": "prinny_system_discovery_unpack_v1",
            "mode": "reused_decompressed_start_after_strict_failure",
            "source": {
                "path": str(system_path),
                "size": len(pack.data),
                "sha1": sha1_bytes(pack.data),
            },
            "nispack": {
                "entry_count": len(entries),
                "entries": [
                    {
                        "index": int(item["index"]),
                        "name": str(item["name"]),
                        "offset": int(item["offset"]),
                        "size": int(item["size"]),
                        "metadata": int(item["metadata"]),
                        "plausible": bool(item["plausible"]),
                    }
                    for item in entries
                ],
            },
            "start_archive": {
                "record_count": len(archive.records),
                "table_end": archive.table_end,
                "resources": inventory_archive(archive),
                "prinny1_expected_resources": {
                    name: archive.find_record(name) is not None
                    for name in sorted(REQUIRED_RESOURCES)
                },
            },
            "validation": {
                "archive_structure": "pass",
                "prinny1_font_location_match": "not_applicable_for_prinny2_discovery",
                "previous_strict_manifest": old_manifest,
                "status": "pass",
            },
        }
        manifest["start_archive"]["missing_prinny1_expected_resources"] = [
            name
            for name, present in manifest["start_archive"][
                "prinny1_expected_resources"
            ].items()
            if not present
        ]
        atomic_write_json(system_manifest_path, manifest)
    else:
        extract_workspace = run_dir / "game2_disc"
        try:
            system_path = locate_system_dat(extract_workspace)
        except FileNotFoundError:
            disc_root, extract_manifest = prepare_minimal(
                game2,
                extract_workspace,
            )
            atomic_write_json(
                report_dir / "game2_extract_manifest_v7_1_2.json",
                extract_manifest,
            )
            # 추출 전 작업 폴더가 아니라 prepare_disc 반환 루트에서 다시 계산한다.
            system_path = locate_system_dat(disc_root)

        archive, manifest = permissive_unpack_system(
            system_path,
            system_dir,
            system_manifest_path,
        )

    write_state(
        status_file,
        status="running",
        progress=35,
        stage="프리니 2 자원 인벤토리",
        detail="START와 SYSTEM에서 폰트·코드맵 후보를 탐색합니다.",
        start_resources=len(archive.records),
    )
    font = resource_candidates(manifest, archive)
    atomic_write_json(report_dir / "prinny2_font_discovery.json", font)
    atomic_write_json(
        PROJECT / "profiles" / "prinny2" / "font_discovery.json",
        font,
    )

    runtime_dir = run_dir / "game2_start_runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    archive.extract(runtime_dir)

    write_state(
        status_file,
        status="running",
        progress=56,
        stage="프리니 2 번역 후보 추출",
        detail="폰트 위치 미확정과 무관하게 대사·UI 후보 카탈로그를 생성합니다.",
        font_location=font["location_status"],
    )
    catalog = build_catalog(runtime_dir)
    catalog_dir = report_dir / "game2_translation_catalog"
    save_catalog(catalog, catalog_dir)

    write_state(
        status_file,
        status="running",
        progress=75,
        stage="프리니 2 전용 프로필 갱신",
        detail="폰트 위치를 보류 항목으로 기록하고 번역 준비 상태를 저장합니다.",
        prinny2_catalog_entries=catalog["entry_count"],
        prinny2_catalog_resources=catalog["resource_count"],
    )
    profile = create_profile(v7, manifest, font, catalog)
    atomic_write_json(PROJECT / "profiles" / "prinny2" / "profile.json", profile)
    atomic_write_json(report_dir / "prinny2_profile_discovery.json", profile)

    write_state(
        status_file,
        status="running",
        progress=88,
        stage="PSP 종합툴 현황 갱신",
        detail="프리니 1 수정 트랙과 프리니 2 전용 프로필 현황을 통합합니다.",
    )
    dashboard = report_dir / "index.html"
    write_dashboard(
        dashboard,
        v7=v7,
        queue=queue,
        catalog=catalog,
        font=font,
        manifest=manifest,
    )
    shutil.copy2(
        dashboard,
        PROJECT / "studio" / "psp_localization_studio_v7_1.html",
    )

    combined = {
        "format": "prinny_v7_1_2_parallel_report_v1",
        "created_at": now(),
        "previous_error": (
            "프리니 1 전용 system_unpack이 프리니 2 START에서 "
            "font.fnt/font.txp를 필수로 요구함"
        ),
        "resolution": (
            "프리니 2 발견 모드에서는 START 구조와 번역 카탈로그를 먼저 확정하고, "
            "폰트 위치는 SYSTEM/START 후보 탐색 항목으로 분리"
        ),
        "prinny1": queue,
        "prinny2": {
            "system_manifest": str(system_manifest_path),
            "font_discovery": font,
            "profile": profile,
            "translation_catalog": {
                "entry_count": catalog["entry_count"],
                "resource_count": catalog["resource_count"],
                "catalog_sha1": catalog["catalog_sha1"],
                "csv": str(catalog_dir / "catalog.csv"),
                "json": str(catalog_dir / "catalog.json"),
                "template": str(catalog_dir / "translation_template.json"),
            },
        },
        "parallel_development_possible": True,
        "parallel_condition": (
            "공통 압축·START·문자열 엔진을 재사용하되 "
            "프리니 2 폰트 및 실행 파일 패치는 전용 프로필로 구현"
        ),
        "github_checkpoint": {
            "status": "not_due",
            "reason": "V7.1.1은 0.5 단위가 아니며 다음 체크포인트는 V7.5",
        },
        "status": "pass",
    }
    atomic_write_json(report_dir / "all_report.json", combined)

    # 재생성 가능한 대형 추출물만 제거한다. 카탈로그와 인벤토리는 유지한다.
    shutil.rmtree(runtime_dir, ignore_errors=True)
    shutil.rmtree(run_dir / "game2_disc", ignore_errors=True)
    shutil.rmtree(system_dir, ignore_errors=True)

    write_state(
        status_file,
        status="complete",
        progress=100,
        stage="완료",
        detail=(
            f"프리니 2 START {manifest['start_archive']['record_count']}개 · "
            f"번역 후보 {catalog['entry_count']}개 · "
            f"폰트 위치 {font['location_status']} · 병행 진행 가능"
        ),
        parallel_development_possible=True,
        start_resources=manifest["start_archive"]["record_count"],
        prinny2_catalog_entries=catalog["entry_count"],
        prinny2_catalog_resources=catalog["resource_count"],
        prinny1_issue_queue=queue["issue_count"],
        font_location=font["location_status"],
        report_html=str(dashboard),
        report_json=str(report_dir / "all_report.json"),
        catalog_csv=str(catalog_dir / "catalog.csv"),
        profile_json=str(PROJECT / "profiles" / "prinny2" / "profile.json"),
        font_discovery_json=str(
            PROJECT / "profiles" / "prinny2" / "font_discovery.json"
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
