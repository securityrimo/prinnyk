#!/usr/bin/env python3
from __future__ import annotations
import csv,hashlib,json
from datetime import datetime
from pathlib import Path
from core.start_runtime import StartRuntimeArchive
ROOT=Path(__file__).resolve().parent;PLAN_DIR=ROOT/"workspace/reports/prinny1_v7_14_19_candidate_glyph_plan";PLAN=PLAN_DIR/"all_report.json";WRITES=PLAN_DIR/"expected_write_confirmed.csv";SLOTS=PLAN_DIR/"candidate_glyph_slots.csv";BASE_START=ROOT/"workspace/build/prinny1_v7_14_14_title_difficulty_repair/start.dat";BASE_BOOT=ROOT/"workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN";ALLOCATION=ROOT/"workspace/font/audited_allocation_980/hangul_allocation.json";OUTPUT=ROOT/"workspace/reports/prinny1_v7_14_19_candidate_glyph_review"
VERSION="v7_14_19";EXPECTED_WRITE_COUNT=125;SLOT_COUNT=54
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rc(p):
    with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
def ch(a,b):return {i for i,p in enumerate(zip(a,b)) if p[0]!=p[1]}
def main():
    plan=json.loads(PLAN.read_text());rows=rc(WRITES);slots=rc(SLOTS);used={int(r["glyph_index"]) for r in json.loads(ALLOCATION.read_text())["allocations"]}
    if plan.get("status")!="expected_writes_confirmed_independent_review_required" or sh(WRITES)!=plan["artifacts"]["expected_writes_sha256"]:raise ValueError("계획 봉인 오류")
    targets=[int(r["target_glyph_index_hex"],0) for r in slots]
    if len(rows)!=EXPECTED_WRITE_COUNT or len(slots)!=SLOT_COUNT or len(set(targets))!=SLOT_COUNT or set(targets)&used:raise ValueError("안전 슬롯/행 수 오류")
    if any(int(r["trusted_text_hits"])!=0 for r in slots):raise ValueError("trusted hit 안전성 오류")
    a=StartRuntimeArchive.load(BASE_START);recs={r.output_name.casefold():r for r in a.records};bs=BASE_START.read_bytes();bb=BASE_BOOT.read_bytes();ps=bytearray(bs);pb=bytearray(bb);ds=set();db=set();ints={}
    for r in rows:
        off=int(r["offset_hex"],0);before=bytes.fromhex(r["expected_before_hex"]);after=bytes.fromhex(r["write_after_hex"]);layer=r["layer"]
        if layer.startswith("START.DAT/"):absolute=int(recs[layer.split('/',1)[1].casefold()].data_offset)+off;t=ps;d=ds
        else:absolute=off;t=pb;d=db
        key=layer
        if any(absolute<right and left<absolute+len(after) for left,right in ints.setdefault(key,[])):raise ValueError(f"겹침 {r['logical_id']}")
        ints[key].append((absolute,absolute+len(after)))
        if t[absolute:absolute+len(before)]!=before:raise ValueError(f"before 오류 {r['logical_id']}")
        t[absolute:absolute+len(after)]=after;d.update(absolute+i for i,p in enumerate(zip(before,after)) if p[0]!=p[1])
    if ch(bs,ps)!=ds or ch(bb,pb)!=db:raise ValueError("변경 집합 오류")
    report={"format":f"prinny1_{VERSION}_candidate_glyph_review_v1","created_at":datetime.now().astimezone().isoformat(timespec="seconds"),"verified":{"expected_write_count":len(rows),"candidate_glyph_count":SLOT_COUNT,"safe_slot_count":SLOT_COUNT,"start_changed_bytes":len(ds),"boot_changed_bytes":len(db)},"checks":{"fresh_sources_reopened":True,"all_before_bytes_match":True,"actual_changes_equal_declared":True,"no_overlap":True,"current_980_glyph_slots_preserved":True,"all_safe_slots_trusted_hits_zero":True,"translation_wording_changed":False,"iso_created":False},"status":"pass_resource_build_allowed","final_verdict":"PASS"};OUTPUT.mkdir(parents=True,exist_ok=True);(OUTPUT/"all_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n");print(f"{VERSION} candidate glyph review: PASS");print(f"Expected Writes: {EXPECTED_WRITE_COUNT}");print("FINAL_VERDICT: PASS");return 0
if __name__=="__main__":raise SystemExit(main())
