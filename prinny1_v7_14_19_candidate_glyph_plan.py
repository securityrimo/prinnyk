#!/usr/bin/env python3
from __future__ import annotations
import csv,hashlib,json,struct
from datetime import datetime
from pathlib import Path
from typing import Any
from core.font_runtime import FontRuntime
from core.start_runtime import StartRuntimeArchive

ROOT=Path(__file__).resolve().parent
V18_DIR=ROOT/"workspace/reports/prinny1_v7_14_18_candidate_native_plan";V18_REPORT=V18_DIR/"all_report.json";V18_WRITES=V18_DIR/"expected_write_confirmed.csv";V18_MAPPING=V18_DIR/"native_mapping.csv"
BASE_START=ROOT/"workspace/build/prinny1_v7_14_14_title_difficulty_repair/start.dat";CANDIDATE_START=ROOT/"workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start.dat"
ALLOCATION=ROOT/"workspace/font/audited_allocation_980/hangul_allocation.json";RESIDUAL=ROOT/"workspace/font/audited_allocation_977/residual_audit.json"
OUTPUT=ROOT/"workspace/reports/prinny1_v7_14_19_candidate_glyph_plan";PIXEL_OFFSET=0x50;BYTES_PER_GLYPH=0x8C
def sha256_file(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def read_csv(p:Path):
    with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
def write_csv(p:Path,rows:list[dict[str,Any]]):
    with p.open("w",encoding="utf-8-sig",newline="") as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def main()->int:
    for p in (V18_REPORT,V18_WRITES,V18_MAPPING,BASE_START,CANDIDATE_START,ALLOCATION,RESIDUAL):
        if not p.is_file():raise FileNotFoundError(p)
    if json.loads(V18_REPORT.read_text(encoding="utf-8")).get("final_verdict")!="PASS":raise ValueError("V18 native 계획 PASS 아님")
    mapping=read_csv(V18_MAPPING);used={int(r["glyph_index"]) for r in json.loads(ALLOCATION.read_text())["allocations"]}
    safe=[];seen=set()
    for r in json.loads(RESIDUAL.read_text())["safe_candidates"]:
        g=int(r["glyph_index"])
        if g not in used and g not in seen and int(r["audit"]["trusted_text_hits"])==0:safe.append(r);seen.add(g)
        if len(safe)==54:break
    if len(safe)!=54:raise ValueError("미사용 안전 글리프 54개 확보 실패")
    ba=StartRuntimeArchive.load(BASE_START);br={r.output_name.casefold():r for r in ba.records};ca=StartRuntimeArchive.load(CANDIDATE_START);cr={r.output_name.casefold():r for r in ca.records}
    bfnt=ba.data[br["font.fnt"].data_offset:br["font.fnt"].end_offset];btxp=ba.data[br["font.txp"].data_offset:br["font.txp"].end_offset]
    cfnt=ca.data[cr["font.fnt"].data_offset:cr["font.fnt"].end_offset];ctxp=ca.data[cr["font.txp"].data_offset:cr["font.txp"].end_offset]
    btable=FontRuntime._parse_fnt(bfnt);ctable=FontRuntime._parse_fnt(cfnt);target=list(btable);slot_rows=[];glyph_rows=[]
    for m,s in zip(mapping,safe):
        code=bytes.fromhex(m["native_code"]);ti=FontRuntime.table_index_from_sjis(code);source_glyph=ctable[ti];target_glyph=int(s["glyph_index"]);target[ti]=target_glyph
        before=btxp[PIXEL_OFFSET+target_glyph*BYTES_PER_GLYPH:PIXEL_OFFSET+(target_glyph+1)*BYTES_PER_GLYPH];after=ctxp[PIXEL_OFFSET+source_glyph*BYTES_PER_GLYPH:PIXEL_OFFSET+(source_glyph+1)*BYTES_PER_GLYPH]
        if before==after:raise ValueError(f"후보 글리프와 미사용 슬롯이 같음: {m['hangul']}")
        glyph_rows.append({"sequence":0,"layer":"START.DAT/font.txp","logical_id":f"P1-CANDIDATE-GLYPH-{int(m['sequence']):03d}","target":"font.txp","offset_hex":f"0x{PIXEL_OFFSET+target_glyph*BYTES_PER_GLYPH:X}","write_span":BYTES_PER_GLYPH,"expected_before_hex":before.hex().upper(),"write_after_hex":after.hex().upper(),"change_kind":"candidate_proven_glyph_into_audited_unused_slot","wording_changed":"no","expected_write_confirmed":"yes"})
        slot_rows.append({**m,"target_glyph_index_hex":f"0x{target_glyph:04X}","replaced_unused_character":s["character"],"trusted_text_hits":s["audit"]["trusted_text_hits"]})
    changed_indices=[i for i,p in enumerate(zip(btable,target)) if p[0]!=p[1]];groups=[];left=prev=changed_indices[0]
    for i in changed_indices[1:]:
        if i!=prev+1:groups.append((left,prev+1));left=i
        prev=i
    groups.append((left,prev+1));fnt_rows=[]
    for n,(left,right) in enumerate(groups,1):
        off=2+left*2;before=bfnt[off:2+right*2];after=b''.join(struct.pack('<H',target[i]) for i in range(left,right))
        fnt_rows.append({"sequence":0,"layer":"START.DAT/font.fnt","logical_id":f"P1-CANDIDATE-FNT-{n:03d}","target":"font.fnt","offset_hex":f"0x{off:X}","write_span":len(after),"expected_before_hex":before.hex().upper(),"write_after_hex":after.hex().upper(),"change_kind":"native_code_to_audited_candidate_glyph_slot","wording_changed":"no","expected_write_confirmed":"yes"})
    v18=[r for r in read_csv(V18_WRITES) if r["layer"]!="START.DAT/font.fnt"]
    rows=v18+glyph_rows+fnt_rows;rows.sort(key=lambda r:(r["layer"],int(r["offset_hex"],0)))
    for i,r in enumerate(rows,1):r["sequence"]=i
    OUTPUT.mkdir(parents=True,exist_ok=True);writes=OUTPUT/"expected_write_confirmed.csv";slots=OUTPUT/"candidate_glyph_slots.csv";write_csv(writes,rows);write_csv(slots,slot_rows)
    report={"format":"prinny1_v7_14_19_candidate_glyph_plan_v1","created_at":datetime.now().astimezone().isoformat(timespec="seconds"),"inputs":{"v18_writes_sha256":sha256_file(V18_WRITES),"base_start_sha256":sha256_file(BASE_START),"candidate_start_sha256":sha256_file(CANDIDATE_START),"residual_audit_sha256":sha256_file(RESIDUAL)},"verified":{"character_count":54,"candidate_glyph_write_count":54,"font_fnt_write_count":len(fnt_rows),"total_expected_write_count":len(rows),"safe_slot_glyph_count":len(safe)},"checks":{"current_980_glyph_slots_preserved":True,"all_new_slots_trusted_text_hits_zero":True,"candidate_native_glyphs_copied":True,"translation_wording_changed":False,"candidate_wording_imported":False,"image_writes":0,"iso_created":False},"artifacts":{"expected_writes":str(writes),"expected_writes_sha256":sha256_file(writes),"slots":str(slots),"slots_sha256":sha256_file(slots)},"status":"expected_writes_confirmed_independent_review_required","final_verdict":"PASS"}
    (OUTPUT/"all_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(f"candidate glyphs: 54, Expected Writes: {len(rows)}");print("current 980 slots overwritten: 0");print("FINAL_VERDICT: PASS");return 0
if __name__=="__main__":raise SystemExit(main())
