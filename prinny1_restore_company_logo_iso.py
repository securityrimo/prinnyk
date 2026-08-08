#!/usr/bin/env python3
"""Restore anime00/object_079 (company logo) from the original ISO."""
from pathlib import Path
import hashlib, os, shutil, struct, subprocess, json
from core.lzs import decompress_buffer, compress_buffer_runtime_safe
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file, SECTOR_SIZE

ROOT = Path(__file__).resolve().parent
ORIG = ROOT / "game.iso"
BASE = ROOT / "workspace/build/prinny1_v7_15_24_final_intro_spacing/prinny_korean_v7_15_24_final_intro_spacing.iso"
OUT = ROOT / "workspace/build/prinny1_v7_15_25_company_logo_restored/prinny_korean_v7_15_25_company_logo_restored.iso"
REP = ROOT / "workspace/reports/prinny1_v7_15_25_company_logo_restored"

def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def system_start(iso):
    data = read_iso_file(iso, find_iso_file(iso, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"]))
    rows = system_records(data)
    sr = next(r for r in rows if r["name"].casefold() == "start.lzs")
    raw = data[sr["data_offset"]:sr["data_offset"] + sr["size"]]
    return data, rows, sr, raw, decompress_buffer(raw)[0]

def anime_record(start):
    a = StartRuntimeArchive.from_bytes(start)
    return next(r for r in a.records if r.output_name.casefold() == "anime00.dat")

def main():
    base_system, base_rows, base_sr, base_lzs, base_start = system_start(BASE)
    _, _, _, orig_lzs, orig_start = system_start(ORIG)
    ba, oa = anime_record(base_start), anime_record(orig_start)
    # object 079 is fixed-layout in both archives; copy only this object.
    def object_span(anime, index):
        from scripts.prinny_anime_preview import parse_objects
        o = next(o for o in parse_objects(anime) if o.index == index)
        return o.offset, o.end
    base_anime = bytearray(base_start[ba.data_offset:ba.end_offset])
    orig_anime = orig_start[oa.data_offset:oa.end_offset]
    b0, b1 = object_span(base_anime, 79); o0, o1 = object_span(orig_anime, 79)
    if (b1-b0) != (o1-o0): raise RuntimeError("object_079 크기가 원본과 다릅니다")
    base_anime[b0:b1] = orig_anime[o0:o1]
    new_start = bytearray(base_start)
    new_start[ba.data_offset:ba.end_offset] = base_anime
    flag = int(decompress_buffer(base_lzs)[1]["flag"])
    new_lzs = compress_buffer_runtime_safe(bytes(new_start), base_lzs[:4], flag)
    capacity = base_rows[base_sr["index"] + 1]["data_offset"] - base_sr["data_offset"]
    if len(new_lzs) > capacity: raise RuntimeError("새 start.lzs가 SYSTEM.DAT 영역을 초과합니다")
    new_system = bytearray(base_system)
    new_system[base_sr["data_offset"]:base_sr["data_offset"] + capacity] = b"\0" * capacity
    new_system[base_sr["data_offset"]:base_sr["data_offset"] + len(new_lzs)] = new_lzs
    struct.pack_into("<I", new_system, 0x10 + base_sr["index"] * 0x2C + 0x24, len(new_lzs))
    br = find_iso_file(BASE, ["PSP_GAME", "USRDIR", "SYSTEM.DAT"])
    sector = int(br["extent_lba"]) * SECTOR_SIZE
    OUT.parent.mkdir(parents=True, exist_ok=True); REP.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".iso.tmp")
    with BASE.open("rb") as s, tmp.open("wb") as t: shutil.copyfileobj(s, t, 1 << 20)
    with tmp.open("r+b") as f: f.seek(sector); f.write(new_system); f.flush(); os.fsync(f.fileno())
    if subprocess.run(["7z", "t", str(tmp)], capture_output=True, text=True).returncode: raise RuntimeError("7z 검증 실패")
    os.replace(tmp, OUT)
    (REP / "all_report.json").write_text(json.dumps({
        "format":"prinny1_v7_15_25_company_logo_restored_v1", "base_iso":str(BASE), "original_iso":str(ORIG),
        "iso":{"path":str(OUT),"sha256":sha(OUT),"size":OUT.stat().st_size},
        "restored_resource":"SYSTEM.DAT/start.lzs/START/anime00.dat/object_079", "preserved":"all other final resources",
        "checks":{"object_079_size_equal":True,"seven_zip_test":True,"external_textures":False}, "status":"complete"
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT); print(sha(OUT))
if __name__ == "__main__": main()
