#!/usr/bin/env python3
"""Apply voice-first dialogue corrections on the sealed V7.15.15 user baseline.

Addresses and field capacities remain those declared by the forced-xdelta map;
wording remains the user's wording except for the reviewed character-voice rows.
"""
from __future__ import annotations

import csv, hashlib, json, os, shutil, struct, subprocess
from datetime import datetime
from pathlib import Path

from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_14_15_text_test_iso import hash_range, merge_intervals
from prinny1_v7_15_3_xdelta_translation_select import load_codebook
from prinny1_v7_15_4_ui_image_export import system_records

ROOT = Path(__file__).resolve().parent
BASE_ISO = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue/prinny_korean_v7_15_15_user_dialogue.iso"
BASE_RES = ROOT / "workspace/build/prinny1_v7_15_15_user_dialogue_resources"
PARALLEL = ROOT / "workspace/reports/prinny1_xdelta_codebook_recovery/parallel_slots.csv"
EXT = ROOT / "workspace/reports/prinny1_v7_15_15_user_dialogue_plan/font_extension_slots.csv"
OUT_RES = ROOT / "workspace/build/prinny1_v7_15_21_dialogue_voice_first_resources"
OUT_ISO = ROOT / "workspace/build/prinny1_v7_15_21_dialogue_voice_first/prinny_korean_v7_15_21_dialogue_voice_first.iso"
REPORT = ROOT / "workspace/reports/prinny1_v7_15_21_dialogue_voice_first"

REVISIONS = (
    (291, 0x1C, "프리니", "우왓, 지각임다!!", "프리니식 군대 존대와 감탄 유지"),
    (326, 0x3F, "프리니 부대", "다녀오겠슴다~.", "프리니 부대 1인칭 말투 유지"),
    (329, 0x1C, "프리니", "부탁임다.", "프리니식 요청 말투 유지"),
    (329, 0x3F, "프리니", "순서 좀 양보해 주십쇼.", "프리니식 요청·존대 유지"),
    (479, 0x1C, "프리니", "알겠슴다!", "프리니식 응답 어미 유지"),
    (479, 0x3F, "프리니", "더 부르겠슴다!", "행동 주체와 프리니식 어미 복원"),
    (501, 0x1C, "프리니", "……수고하셨슴다.", "명령형이 아닌 감사·인사 기능 유지"),
    (1306, 0x1C, "프리니", "궁극의 스위츠 돌려드림다.", "행동 방향과 프리니식 군대 존대 유지"),
    (1314, 0x3F, "프리니", "돌려드림.", "슬롯 용량 안에서 행동 방향 유지"),
    (1500, 0x1C, "아사기", "그 죽은 생선 눈인가요!?", "아사기 일반 존댓말 유지"),
    (1501, 0x3F, "아사기", "펭귄 모습 그대로인가요!?", "아사기 일반 존댓말 유지"),
)

def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()

def file_sha(path: Path) -> str:
    return sha256(path.read_bytes())

def decode(payload: bytes, mapping: dict[str, str]) -> str:
    payload = payload.split(b"\0", 1)[0]; out=[]; i=0
    while i < len(payload):
        if i+1 < len(payload) and payload[i:i+2].hex().upper() in mapping:
            out.append(mapping[payload[i:i+2].hex().upper()]); i += 2; continue
        b=payload[i]
        if (0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF) and i+1 < len(payload):
            out.append(payload[i:i+2].decode("cp932", errors="replace")); i += 2
        elif b < 0x80: out.append(chr(b)); i += 1
        elif 0xA1 <= b <= 0xDF: out.append(bytes((b,)).decode("cp932")); i += 1
        else: out.append(f"□{b:02X}"); i += 1
    return "".join(out)

def encode(text: str, reverse: dict[str, str], ext: dict[str, str]) -> bytes:
    out=bytearray()
    for c in text:
        if "가" <= c <= "힣":
            code = reverse.get(c) or ext.get(c)
            if not code: raise ValueError(f"코드북에 없는 글자: {c}")
            out.extend(bytes.fromhex(code))
        else: out.extend(c.encode("cp932"))
    return bytes(out)

def main() -> int:
    mapping, _ = load_codebook(); reverse={v:k for k,v in mapping.items()}
    ext_rows=list(csv.DictReader(EXT.open(encoding="utf-8-sig")))
    ext={r["character"]: r["encoded_code"].replace(" ","").upper() for r in ext_rows}
    parallel={int(r["offset"],0):r for r in csv.DictReader(PARALLEL.open(encoding="utf-8-sig"))}
    # The sealed V7.15.15 resource is byte-identical to SYSTEM.DAT in its test
    # ISO; use the extracted resource here to avoid loading a 500 MB ISO.
    system=(BASE_RES/"SYSTEM.DAT").read_bytes()
    rows=system_records(system); sr=next(r for r in rows if r["name"].casefold()=="start.lzs")
    old_lzs=system[sr["data_offset"]:sr["data_offset"]+sr["size"]]; start=decompress_buffer(old_lzs)[0]
    archive=StartRuntimeArchive.from_bytes(start); rec={r.output_name.casefold():r for r in archive.records}; demo_rec=rec["demo00.dat"]
    demo=bytearray(start[demo_rec.data_offset:demo_rec.end_offset]); writes=[]
    for idx,field,speaker,text,reason in REVISIONS:
        off=idx*0x84+field; q=parallel[off]; cap=int(q["capacity_bytes"]); end=idx*0x84+(0x3F if field==0x1C else 0x84)
        nul=demo.find(b"\0",off,end)
        if nul < 0 or len(encode(text,reverse,ext)) > cap: raise ValueError(f"슬롯 검증 실패: 0x{off:X}")
        span=max(cap,nul-off); before=bytes(demo[off:off+span]); payload=encode(text,reverse,ext); after=payload+bytes(span-len(payload));
        if decode(after,mapping|{v:k for k,v in ext.items()}) != text: raise ValueError(f"왕복 실패: 0x{off:X}")
        if after == before:
            continue
        demo[off:off+span]=after
        writes.append({"record_index":idx,"field_offset_hex":hex(field),"resource_offset_hex":hex(off),"speaker":speaker,"selected_translation":text,"reason":reason,"capacity_bytes":cap,"write_span":span,"expected_before_hex":before.hex().upper(),"write_after_hex":after.hex().upper(),"address_basis":"forced_xdelta_parallel_slots.csv","decision":"voice_first_over_user_baseline"})
    final_start=bytearray(start); final_start[demo_rec.data_offset:demo_rec.end_offset]=demo
    new_lzs=compress_buffer_runtime_safe(bytes(final_start),old_lzs[:4],int(decompress_buffer(old_lzs)[1]["flag"]))
    if decompress_buffer(new_lzs)[0] != bytes(final_start): raise ValueError("START.LZS 왕복 실패")
    next_off=rows[sr["index"]+1]["data_offset"]; capacity=next_off-sr["data_offset"]
    if len(new_lzs)>capacity: raise ValueError("START.LZS 슬롯 초과")
    final_system=bytearray(system); final_system[sr["data_offset"]:next_off]=bytes(capacity); final_system[sr["data_offset"]:sr["data_offset"]+len(new_lzs)]=new_lzs
    struct.pack_into("<I",final_system,0x10+sr["index"]*0x2C+0x24,len(new_lzs))
    OUT_RES.mkdir(parents=True,exist_ok=True); REPORT.mkdir(parents=True,exist_ok=True)
    (OUT_RES/"SYSTEM.DAT").write_bytes(final_system); (OUT_RES/"start.lzs").write_bytes(new_lzs); (OUT_RES/"start.dat").write_bytes(final_start); (OUT_RES/"Demo00.dat").write_bytes(demo)
    with (REPORT/"expected_dialogue_writes.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(writes[0])); w.writeheader(); w.writerows(writes)
    prior={}
    if (REPORT/"all_report.json").exists():
        prior=json.loads((REPORT/"all_report.json").read_text(encoding="utf-8"))
    report={"format":"prinny1_v7_15_21_dialogue_voice_first_v1","created_at":datetime.now().astimezone().isoformat(timespec="seconds"),"base_iso":file_sha(BASE_ISO),"policy":{"user_translation_baseline":True,"xdelta_address_authority":True,"character_voice_priority":True},"verified":{"rows":len(writes),"all_xdelta_offsets":True,"slot_capacity_and_roundtrip":True,"lzs_roundtrip":True,"start_lzs_margin":capacity-len(new_lzs)},"sealed":{"SYSTEM.DAT":sha256(final_system),"start.lzs":sha256(new_lzs),"Demo00.dat":sha256(demo),"expected_dialogue_writes.csv":file_sha(REPORT/"expected_dialogue_writes.csv")},"status":"resources_sealed_iso_build_pending"}
    if prior.get("iso"): report["iso"]=prior["iso"]; report["checks"]=prior.get("checks",{}); report["status"]=prior.get("status",report["status"])
    (REPORT/"all_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"voice-first rows: {len(writes)}; START.LZS {len(new_lzs)}/{capacity}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
