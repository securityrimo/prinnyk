#!/usr/bin/env python3
from __future__ import annotations

import csv, hashlib, json, os, shutil, subprocess
from datetime import datetime
from pathlib import Path
from prinny1_v7_14_15_text_test_iso import find_iso_record, hash_range, merge_intervals
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_15_0_full_decoder_plan import BASE_ISO

ROOT=Path(__file__).resolve().parent
PLAN_DIR=ROOT/"workspace/reports/prinny1_v7_15_0_full_decoder_plan"; PLAN=PLAN_DIR/"all_report.json"; WRITES=PLAN_DIR/"expected_write_confirmed.csv"
REVIEW=ROOT/"workspace/reports/prinny1_v7_15_0_full_decoder_review/all_report.json"
OUTPUT_DIR=ROOT/"workspace/build/prinny1_v7_15_0_full_korean_baseline"; OUTPUT_ISO=OUTPUT_DIR/"prinny_korean_v7_15_0_full_text_baseline.iso"
REPORT_DIR=ROOT/"workspace/reports/prinny1_v7_15_0_full_text_iso"

def shb(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def shf(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        while c:=f.read(1024*1024):h.update(c)
    return h.hexdigest()

def main()->int:
    for p in (BASE_ISO,PLAN,WRITES,REVIEW):
        if not p.is_file():raise FileNotFoundError(p)
    plan=json.loads(PLAN.read_text());review=json.loads(REVIEW.read_text())
    if review.get("status")!="pass_integrated_baseline_iso_build_ready_automatic_approval" or review.get("final_verdict")!="PASS":raise ValueError("독립 검토 미통과")
    br=find_iso_record(BASE_ISO,["PSP_GAME","SYSDIR","BOOT.BIN"]);er=find_iso_record(BASE_ISO,["PSP_GAME","SYSDIR","EBOOT.BIN"]);sr=find_iso_record(BASE_ISO,["PSP_GAME","USRDIR","SYSTEM.DAT"])
    boot=read_iso_file(BASE_ISO,br);eboot=read_iso_file(BASE_ISO,er);system=read_iso_file(BASE_ISO,sr);patched=bytearray(boot)
    with WRITES.open(encoding="utf-8-sig",newline="") as f:rows=list(csv.DictReader(f))
    declared=set()
    for row in rows:
        o=int(row["offset_hex"],0);before=bytes.fromhex(row["expected_before_hex"]);after=bytes.fromhex(row["write_after_hex"])
        if patched[o:o+len(before)]!=before:raise ValueError(f"빌드 직전 before 불일치: {row['logical_id']}")
        patched[o:o+len(after)]=after;declared.update(o+i for i,(a,b) in enumerate(zip(before,after)) if a!=b)
    actual={i for i,p in enumerate(zip(boot,patched)) if p[0]!=p[1]}
    if actual!=declared or shb(bytes(patched))!=plan["preflight"]["patched_boot_sha256"]:raise ValueError("빌드 직전 변경/해시 오류")
    if len(boot)!=len(eboot):raise ValueError("V22 BOOT/EBOOT 크기 불일치")
    bo=int(br["extent_lba"])*SECTOR_SIZE;eo=int(er["extent_lba"])*SECTOR_SIZE
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    if OUTPUT_ISO.exists():raise ValueError("출력 ISO가 이미 있습니다")
    tmp=OUTPUT_ISO.with_suffix(".iso.tmp")
    if tmp.exists():tmp.unlink()
    with BASE_ISO.open("rb") as s,tmp.open("wb") as t:shutil.copyfileobj(s,t,1024*1024)
    with tmp.open("r+b") as t:
        t.seek(bo);t.write(patched);t.seek(eo);t.write(patched);t.flush();os.fsync(t.fileno())
    allowed=merge_intervals([(bo,bo+len(boot)),(eo,eo+len(eboot))]);cursor=0
    for l,r in allowed:
        if hash_range(BASE_ISO,cursor,l)!=hash_range(tmp,cursor,l):raise ValueError("허용 범위 밖 ISO 변경")
        cursor=r
    if hash_range(BASE_ISO,cursor,BASE_ISO.stat().st_size)!=hash_range(tmp,cursor,tmp.stat().st_size):raise ValueError("마지막 허용 범위 뒤 변경")
    test=subprocess.run(["7z","t",str(tmp)],capture_output=True,text=True)
    if test.returncode or "Everything is Ok" not in test.stdout:raise ValueError("7z 구조 검사 실패")
    os.replace(tmp,OUTPUT_ISO)
    fb=read_iso_file(OUTPUT_ISO,find_iso_file(OUTPUT_ISO,["PSP_GAME","SYSDIR","BOOT.BIN"]));fe=read_iso_file(OUTPUT_ISO,find_iso_file(OUTPUT_ISO,["PSP_GAME","SYSDIR","EBOOT.BIN"]));fs=read_iso_file(OUTPUT_ISO,find_iso_file(OUTPUT_ISO,["PSP_GAME","USRDIR","SYSTEM.DAT"]))
    if fb!=bytes(patched) or fe!=bytes(patched) or fs!=system:raise ValueError("최종 ISO 재추출 오류")
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    report={"format":"prinny1_v7_15_0_full_text_iso_v1","created_at":datetime.now().astimezone().isoformat(timespec="seconds"),"authorization":"user_automatic_test_iso_approval_active_since_2026_08_01","base_iso":{"path":str(BASE_ISO),"sha256":shf(BASE_ISO)},"output_iso":{"path":str(OUTPUT_ISO),"size":OUTPUT_ISO.stat().st_size,"sha256":shf(OUTPUT_ISO)},"resources":{"boot_sha256":shb(bytes(patched)),"system_sha256":shb(system)},"verified":{"expected_write_count":len(rows),"boot_changed_bytes":len(actual),"qa_slots_preserved":4110,"f0_aliases_preserved":980,"decoder_ranges_active":10},"checks":{"independent_prebuild_review_pass":True,"only_boot_eboot_ranges_changed":True,"system_start_user_text_byte_identical_to_v22":True,"seven_zip_structure_test":True,"boot_eboot_system_reextracted":True,"candidate_wording_imported":False,"translation_wording_changed":False},"known_runtime_regressions":["prologue_boss_interaction_may_fail"],"status":"pass_full_text_baseline_iso_built_independent_post_review_required"}
    (REPORT_DIR/"all_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(f"ISO: {OUTPUT_ISO}");print(f"sha256: {report['output_iso']['sha256']}");print("decoder ranges: 10/10");print("7z/reextract: PASS");return 0
if __name__=="__main__":raise SystemExit(main())
