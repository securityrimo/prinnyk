#!/usr/bin/env python3
from __future__ import annotations
import csv,hashlib,json,struct
from datetime import datetime
from pathlib import Path
import core.font_builder as font_builder
from core.lzs import compress_buffer,decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file,read_iso_file

ROOT=Path(__file__).resolve().parent
BASE_ISO=ROOT/"workspace/build/prinny1_v7_14_14_title_difficulty_repair/prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
PLAN=ROOT/"workspace/reports/prinny1_v7_14_18_candidate_native_plan/all_report.json"
REVIEW=ROOT/"workspace/reports/prinny1_v7_14_18_candidate_native_review/all_report.json"
WRITES=ROOT/"workspace/reports/prinny1_v7_14_18_candidate_native_plan/expected_write_confirmed.csv"
OUTPUT=ROOT/"workspace/build/prinny1_v7_14_18_text_resources";REPORT_DIR=ROOT/"workspace/reports/prinny1_v7_14_18_text_resource_build"
VERSION="v7_14_18";EXPECTED_WRITE_COUNT=71

def sha256_bytes(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def sha256_file(p:Path)->str:return sha256_bytes(p.read_bytes())
def read_csv(p:Path):
    with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
def changed(a:bytes,b:bytes):return {i for i,p in enumerate(zip(a,b)) if p[0]!=p[1]}

def main()->int:
    for p in (BASE_ISO,PLAN,REVIEW,WRITES):
        if not p.is_file():raise FileNotFoundError(p)
    plan=json.loads(PLAN.read_text(encoding="utf-8"));review=json.loads(REVIEW.read_text(encoding="utf-8"))
    if plan.get("final_verdict")!="PASS" or review.get("status")!="pass_resource_build_allowed":raise ValueError("계획·검토 PASS 아님")
    if sha256_file(WRITES)!=plan["artifacts"]["expected_writes_sha256"]:raise ValueError("Expected Write 해시 불일치")
    boot=read_iso_file(BASE_ISO,find_iso_file(BASE_ISO,["PSP_GAME","SYSDIR","BOOT.BIN"]));system=read_iso_file(BASE_ISO,find_iso_file(BASE_ISO,["PSP_GAME","USRDIR","SYSTEM.DAT"]))
    entry=font_builder.parse_nispack_start_entry(system);lo,old_size=int(entry["data_offset"]),int(entry["size"]);old_lzs=system[lo:lo+old_size];start,_=decompress_buffer(old_lzs)
    archive=StartRuntimeArchive.from_bytes(start,source="v18-build-base");records={r.output_name.casefold():r for r in archive.records}
    patched_start=bytearray(start);patched_boot=bytearray(boot);declared_start=set();declared_boot=set();rows=read_csv(WRITES)
    if len(rows)!=EXPECTED_WRITE_COUNT:raise ValueError(f"Expected Write {EXPECTED_WRITE_COUNT}건 아님")
    for row in rows:
        off=int(row["offset_hex"],0);before=bytes.fromhex(row["expected_before_hex"]);after=bytes.fromhex(row["write_after_hex"])
        if row["layer"].startswith("START.DAT/"):
            rec=records[row["layer"].split("/",1)[1].casefold()];absolute=int(rec.data_offset)+off;target=patched_start;declared=declared_start
        elif row["layer"]=="PSP_GAME/SYSDIR/BOOT.BIN":absolute=off;target=patched_boot;declared=declared_boot
        else:raise ValueError(f"계층 오류: {row['layer']}")
        if target[absolute:absolute+len(before)]!=before:raise ValueError(f"빌드 직전 before 불일치: {row['logical_id']}")
        target[absolute:absolute+len(after)]=after;declared.update(absolute+i for i,p in enumerate(zip(before,after)) if p[0]!=p[1])
    if changed(start,patched_start)!=declared_start or changed(boot,patched_boot)!=declared_boot:raise ValueError("실제 변경 집합 오류")
    new_lzs=compress_buffer(bytes(patched_start),old_lzs[:4]);roundtrip,_=decompress_buffer(new_lzs)
    if roundtrip!=bytes(patched_start) or len(new_lzs)>old_size:raise ValueError("START 압축 왕복/슬롯 오류")
    patched_system=bytearray(system);patched_system[lo:lo+old_size]=new_lzs+bytes(old_size-len(new_lzs));struct.pack_into("<I",patched_system,int(entry["entry_offset"])+0x24,len(new_lzs))
    OUTPUT.mkdir(parents=True,exist_ok=True)
    outputs={"BOOT.BIN":bytes(patched_boot),"start.dat":bytes(patched_start),"start.lzs":new_lzs,"SYSTEM.DAT":bytes(patched_system)}
    for name,blob in outputs.items():(OUTPUT/name).write_bytes(blob)
    REPORT_DIR.mkdir(parents=True,exist_ok=True);sealed=REPORT_DIR/"sealed_expected_writes.csv";sealed.write_bytes(WRITES.read_bytes())
    report={"format":f"prinny1_{VERSION}_text_resource_build_v1","created_at":datetime.now().astimezone().isoformat(timespec="seconds"),
            "inputs":{"base_iso_sha256":sha256_file(BASE_ISO),"plan_sha256":sha256_file(PLAN),"review_sha256":sha256_file(REVIEW),"writes_sha256":sha256_file(WRITES)},
            "outputs":{n:{"path":str(OUTPUT/n),"size":len(b),"sha256":sha256_bytes(b)} for n,b in outputs.items()},
            "verified":{"expected_write_count":EXPECTED_WRITE_COUNT,"start_changed_bytes":len(declared_start),"boot_changed_bytes":len(declared_boot),"lzs_size":len(new_lzs),"lzs_slot_size":old_size},
            "checks":{"all_before_bytes_rechecked":True,"actual_changes_equal_declared":True,"lzs_roundtrip":True,"translation_wording_changed":False,"candidate_wording_imported":False,"image_writes":0,"iso_created":False},
            "artifacts":{"sealed_expected_writes":str(sealed),"sealed_expected_writes_sha256":sha256_file(sealed)},"status":"pass_independent_resource_review_required","final_verdict":"PASS"}
    (REPORT_DIR/"all_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"{VERSION} resources built");print(f"START/BOOT changed bytes: {len(declared_start)}/{len(declared_boot)}");print("ISO created: no");print("FINAL_VERDICT: PASS");return 0
if __name__=="__main__":raise SystemExit(main())
