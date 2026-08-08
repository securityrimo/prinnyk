#!/usr/bin/env python3
"""Independent pre-ISO review of the 프 sprite-geometry canary."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
from scripts.prinny_anime_preview import decode_texture, find_texture_groups, parse_objects


ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_11_pic0_title_style/prinny_korean_v7_15_11_pic0_title_style.iso"
BUILD = ROOT / "workspace/build/prinny1_v7_15_13_title_sprite_geometry_canary_resources"
PLAN = ROOT / "workspace/reports/prinny1_v7_15_13_title_sprite_geometry_canary_plan/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_13_title_sprite_geometry_canary_review"
PATCHES = (
    (0x23B4, (-63, -29, 32, 32), (-79, -45, 64, 64)),
    (0x23C4, (-63, -37, 32, 32), (-79, -53, 64, 64)),
)
GEOMETRY_POLICY = "center_preserved"


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status") != "canary_resources_sealed_independent_review_required":
        raise ValueError("카나리 계획 상태 불일치")
    for name, expected in plan["sealed"].items():
        if sha256_bytes((BUILD / name).read_bytes()) != expected:
            raise ValueError(f"카나리 봉인 해시 불일치: {name}")
    base_system = read_iso_file(BASE_ISO, find_iso_file(BASE_ISO, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    final_system = (BUILD / "SYSTEM.DAT").read_bytes()
    base_rows, final_rows = system_records(base_system), system_records(final_system)
    changed = []
    for old, new in zip(base_rows, final_rows):
        a = base_system[old["data_offset"]:old["data_offset"] + old["size"]]
        b = final_system[new["data_offset"]:new["data_offset"] + new["size"]]
        if a != b or old["size"] != new["size"]:
            changed.append(old["name"].casefold())
    if changed != ["start.lzs"]:
        raise ValueError(f"SYSTEM 변경 자원 불일치: {changed}")
    base_start = decompress_buffer(base_system[next(r for r in base_rows if r["name"].casefold() == "start.lzs")["data_offset"]:][:next(r for r in base_rows if r["name"].casefold() == "start.lzs")["size"]])[0]
    final_start = (BUILD / "start.dat").read_bytes()
    ba, fa = StartRuntimeArchive.from_bytes(base_start), StartRuntimeArchive.from_bytes(final_start)
    base_rec = next(r for r in ba.records if r.output_name.casefold() == "anime00.dat")
    final_rec = next(r for r in fa.records if r.output_name.casefold() == "anime00.dat")
    base_anime = base_start[base_rec.data_offset:base_rec.end_offset]
    final_anime = final_start[final_rec.data_offset:final_rec.end_offset]
    obj = parse_objects(base_anime)[78]
    allowed = set()
    for rel, before_tuple, after_tuple in PATCHES:
        off = obj.offset + rel
        before, after = struct.pack("<2h2H", *before_tuple), struct.pack("<2h2H", *after_tuple)
        if base_anime[off:off + 8] != before or final_anime[off:off + 8] != after:
            raise ValueError(f"transform row 검토 불일치: 0x{rel:X}")
        allowed.update(off + i for i, (a, b) in enumerate(zip(before, after)) if a != b)
    actual = {i for i, (a, b) in enumerate(zip(base_anime, final_anime)) if a != b}
    if actual != allowed:
        raise ValueError("anime 허용 범위 밖 변경")
    bt = find_texture_groups(base_anime, parse_objects(base_anime)[78])[0][0]
    ft = find_texture_groups(final_anime, parse_objects(final_anime)[78])[0][0]
    if bt != ft or decode_texture(base_anime, bt).tobytes() != decode_texture(final_anime, ft).tobytes():
        raise ValueError("카나리에서 타이틀 텍스처가 변경됨")
    report = {
        "format": "prinny1_v7_15_13_title_sprite_geometry_canary_review_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verified": {"changed_system_resources": changed, "anime_changed_bytes": len(actual), "texture_byte_identical": True},
        "checks": {"plan_seals_match": True, "only_two_pr_transform_rows_changed": True, "geometry_policy": GEOMETRY_POLICY, "title_texture_unchanged": True, "only_start_lzs_changed_in_system": True},
        "status": "pass_canary_iso_build_ready_automatic_approval",
        "final_verdict": "PASS",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"geometry rows {len(PATCHES)}/texture unchanged/SYSTEM bounded: PASS")
    print("FINAL_VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
