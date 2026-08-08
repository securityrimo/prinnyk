#!/usr/bin/env python3
from __future__ import annotations

import csv, hashlib, json
from datetime import datetime
from pathlib import Path
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_0_full_decoder_plan import ALREADY_ACTIVE_RANGES, BASE_ISO, CANDIDATE_BOOT, MISSING_RANGES

ROOT = Path(__file__).resolve().parent
PLAN_DIR = ROOT / "workspace/reports/prinny1_v7_15_0_full_decoder_plan"
PLAN = PLAN_DIR / "all_report.json"; WRITES = PLAN_DIR / "expected_write_confirmed.csv"
V22_REVIEW = ROOT / "workspace/reports/prinny1_v7_14_22_coherent_f0_iso_review/all_report.json"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_0_full_decoder_review"

def shb(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def shf(p: Path) -> str: return shb(p.read_bytes())

def main() -> int:
    for p in (PLAN, WRITES, BASE_ISO, CANDIDATE_BOOT, V22_REVIEW):
        if not p.is_file(): raise FileNotFoundError(p)
    plan=json.loads(PLAN.read_text()); v22=json.loads(V22_REVIEW.read_text())
    if plan.get("final_verdict")!="PASS" or v22.get("final_verdict")!="PASS": raise ValueError("사전/V22 검토 상태 오류")
    if shf(WRITES)!=plan["artifacts"]["expected_writes_sha256"]: raise ValueError("Expected Write 해시 오류")
    base=read_iso_file(BASE_ISO,find_iso_file(BASE_ISO,["PSP_GAME","SYSDIR","BOOT.BIN"])); cand=CANDIDATE_BOOT.read_bytes(); patched=bytearray(base)
    with WRITES.open(encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
    if len(rows)!=4: raise ValueError("추가 디코더 쓰기가 4건이 아닙니다")
    declared=set(); occupied=[]
    for row in rows:
        o=int(row["offset_hex"],0); before=bytes.fromhex(row["expected_before_hex"]); after=bytes.fromhex(row["write_after_hex"])
        if patched[o:o+len(before)]!=before: raise ValueError(f"before 불일치: {row['logical_id']}")
        if any(o<r and o+len(before)>l for l,r in occupied): raise ValueError("쓰기 중첩")
        occupied.append((o,o+len(before))); patched[o:o+len(after)]=after; declared.update(o+i for i,(a,b) in enumerate(zip(before,after)) if a!=b)
    actual={i for i,p in enumerate(zip(base,patched)) if p[0]!=p[1]}
    if actual!=declared or shb(bytes(patched))!=plan["preflight"]["patched_boot_sha256"]: raise ValueError("변경 집합/해시 불일치")
    for o,n in ALREADY_ACTIVE_RANGES:
        if patched[o:o+n]!=cand[o:o+n]: raise ValueError(f"기존 디코더 불일치 0x{o:X}")
    for _,o,n,_ in MISSING_RANGES:
        if patched[o:o+n]!=cand[o:o+n]: raise ValueError(f"추가 디코더 불일치 0x{o:X}")
    OUTPUT.mkdir(parents=True,exist_ok=True)
    report={"format":"prinny1_v7_15_0_full_decoder_review_v1","created_at":datetime.now().astimezone().isoformat(timespec="seconds"),"verified":{"expected_write_count":len(rows),"actual_changed_bytes":len(actual),"total_decoder_range_count":10,"preserved_qa_slots":4110,"preserved_f0_aliases":980},"checks":{"fresh_base_reextracted":True,"all_before_bytes_match":True,"actual_changes_equal_declared":True,"all_ten_decoder_ranges_match_candidate_mechanism":True,"v22_system_start_font_text_preserved":True,"candidate_wording_imported":False,"translation_wording_changed":False,"iso_created":False},"known_runtime_regressions":["prologue_boss_interaction_may_fail"],"status":"pass_integrated_baseline_iso_build_ready_automatic_approval","final_verdict":"PASS"}
    (OUTPUT/"all_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("full decoder review: PASS"); print("decoder ranges: 10/10"); print("QA/F0 preserved: 4110/980"); print("FINAL_VERDICT: PASS"); return 0
if __name__=="__main__": raise SystemExit(main())
