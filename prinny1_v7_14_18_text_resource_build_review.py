#!/usr/bin/env python3
from __future__ import annotations
import csv,hashlib,json
from datetime import datetime
from pathlib import Path
import core.font_builder as font_builder
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file,read_iso_file

ROOT=Path(__file__).resolve().parent
BASE_ISO=ROOT/"workspace/build/prinny1_v7_14_14_title_difficulty_repair/prinny_korean_v7_14_14_title_difficulty_repair_40.iso"
BUILD=ROOT/"workspace/build/prinny1_v7_14_18_text_resources";REPORT=ROOT/"workspace/reports/prinny1_v7_14_18_text_resource_build/all_report.json"
SEALED=ROOT/"workspace/reports/prinny1_v7_14_18_text_resource_build/sealed_expected_writes.csv";OUTPUT=ROOT/"workspace/reports/prinny1_v7_14_18_text_resource_build_review"
VERSION="v7_14_18";EXPECTED_WRITE_COUNT=71
def sha256_file(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def read_csv(p:Path):
    with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
def changed(a:bytes,b:bytes):return {i for i,p in enumerate(zip(a,b)) if p[0]!=p[1]}
def main()->int:
    names=("BOOT.BIN","start.dat","start.lzs","SYSTEM.DAT")
    for p in [BASE_ISO,REPORT,SEALED]+[BUILD/n for n in names]:
        if not p.is_file():raise FileNotFoundError(p)
    report=json.loads(REPORT.read_text(encoding="utf-8"))
    if report.get("status")!="pass_independent_resource_review_required":raise ValueError("빌드 상태 오류")
    for n in names:
        if sha256_file(BUILD/n)!=report["outputs"][n]["sha256"]:raise ValueError(f"출력 해시 오류: {n}")
    base_boot=read_iso_file(BASE_ISO,find_iso_file(BASE_ISO,["PSP_GAME","SYSDIR","BOOT.BIN"]));base_system=read_iso_file(BASE_ISO,find_iso_file(BASE_ISO,["PSP_GAME","USRDIR","SYSTEM.DAT"]))
    entry=font_builder.parse_nispack_start_entry(base_system);base_start,_=decompress_buffer(base_system[int(entry["data_offset"]):int(entry["data_offset"])+int(entry["size"])])
    archive=StartRuntimeArchive.from_bytes(base_start,source="v18-independent");records={r.output_name.casefold():r for r in archive.records}
    out_boot=(BUILD/"BOOT.BIN").read_bytes();out_start=(BUILD/"start.dat").read_bytes();sim_start=bytearray(base_start);sim_boot=bytearray(base_boot);ds=set();db=set();rows=read_csv(SEALED)
    if len(rows)!=EXPECTED_WRITE_COUNT:raise ValueError(f"봉인 {EXPECTED_WRITE_COUNT}건 아님")
    for row in rows:
        off=int(row["offset_hex"],0);before=bytes.fromhex(row["expected_before_hex"]);after=bytes.fromhex(row["write_after_hex"])
        if row["layer"].startswith("START.DAT/"):absolute=int(records[row["layer"].split("/",1)[1].casefold()].data_offset)+off;target=sim_start;declared=ds
        else:absolute=off;target=sim_boot;declared=db
        if target[absolute:absolute+len(before)]!=before:raise ValueError(f"독립 before 오류: {row['logical_id']}")
        target[absolute:absolute+len(after)]=after;declared.update(absolute+i for i,p in enumerate(zip(before,after)) if p[0]!=p[1])
    if bytes(sim_start)!=out_start or bytes(sim_boot)!=out_boot or changed(base_start,out_start)!=ds or changed(base_boot,out_boot)!=db:raise ValueError("독립 모의 적용 불일치")
    out_system=(BUILD/"SYSTEM.DAT").read_bytes();oe=font_builder.parse_nispack_start_entry(out_system);roundtrip,_=decompress_buffer(out_system[int(oe["data_offset"]):int(oe["data_offset"])+int(oe["size"])])
    packed=out_system[int(oe["data_offset"]):int(oe["data_offset"])+int(oe["size"])]
    if roundtrip!=out_start or packed!=(BUILD/"start.lzs").read_bytes():raise ValueError("SYSTEM START 왕복 오류")
    report2={"format":f"prinny1_{VERSION}_text_resource_build_review_v1","created_at":datetime.now().astimezone().isoformat(timespec="seconds"),"verified":{"expected_write_count":EXPECTED_WRITE_COUNT,"start_changed_bytes":len(ds),"boot_changed_bytes":len(db),"boot_sha256":sha256_file(BUILD/"BOOT.BIN")},"checks":{"fresh_base_iso_reextracted":True,"independent_simulation_equals_outputs":True,"actual_changes_equal_declared":True,"system_start_roundtrip":True,"translation_wording_changed":False,"candidate_wording_imported":False,"iso_created":False},"status":"pass_test_iso_build_ready_automatic_approval","final_verdict":"PASS"}
    OUTPUT.mkdir(parents=True,exist_ok=True);(OUTPUT/"all_report.json").write_text(json.dumps(report2,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"{VERSION} resource independent review: PASS");print("automatic ISO approval: active");print("FINAL_VERDICT: PASS");return 0
if __name__=="__main__":raise SystemExit(main())
