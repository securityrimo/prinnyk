#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from core.font_runtime import FontRuntime
from core.start_runtime import StartRuntimeArchive


ROOT=Path(__file__).resolve().parent
PLAN_DIR=ROOT/"workspace/reports/prinny1_v7_14_18_candidate_native_plan"
PLAN=PLAN_DIR/"all_report.json"; WRITES=PLAN_DIR/"expected_write_confirmed.csv"; MAPPING=PLAN_DIR/"native_mapping.csv"
BASE_START=ROOT/"workspace/build/prinny1_v7_14_14_title_difficulty_repair/start.dat"
BASE_BOOT=ROOT/"workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN"
CANDIDATE_START=ROOT/"workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start.dat"
OLD_ALIASES=ROOT/"workspace/reports/prinny1_v7_14_16_boot_alias_plan/alias_mapping.csv"
OUTPUT=ROOT/"workspace/reports/prinny1_v7_14_18_candidate_native_review"


def sha256_file(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def read_csv(path:Path)->list[dict[str,str]]:
    with path.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
def changed(a:bytes,b:bytes)->set[int]: return {i for i,p in enumerate(zip(a,b)) if p[0]!=p[1]}


def main()->int:
    for p in (PLAN,WRITES,MAPPING,BASE_START,BASE_BOOT,CANDIDATE_START,OLD_ALIASES):
        if not p.is_file():raise FileNotFoundError(p)
    plan=json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("status")!="expected_writes_confirmed_independent_review_required":raise ValueError("계획 상태 오류")
    if sha256_file(WRITES)!=plan["artifacts"]["expected_writes_sha256"] or sha256_file(MAPPING)!=plan["artifacts"]["mapping_sha256"]:
        raise ValueError("봉인 산출물 해시 불일치")
    mapping_rows=read_csv(MAPPING); old_rows=read_csv(OLD_ALIASES)
    if len(mapping_rows)!=54 or {r["hangul"] for r in mapping_rows}!={r["hangul"] for r in old_rows}:raise ValueError("54자 집합 오류")
    codes=[bytes.fromhex(r["native_code"]) for r in mapping_rows]
    if len(set(codes))!=54 or any(not 0xF0<=c[0]<=0xF5 or c[1]==0x7F for c in codes):raise ValueError("native 코드 범위/중복 오류")

    base_archive=StartRuntimeArchive.load(BASE_START); records={r.output_name.casefold():r for r in base_archive.records}
    candidate_archive=StartRuntimeArchive.load(CANDIDATE_START); crecords={r.output_name.casefold():r for r in candidate_archive.records}
    base_start=BASE_START.read_bytes(); base_boot=BASE_BOOT.read_bytes(); patched_start=bytearray(base_start); patched_boot=bytearray(base_boot)
    candidate_fnt=candidate_archive.data[crecords["font.fnt"].data_offset:crecords["font.fnt"].end_offset]
    candidate_table=FontRuntime._parse_fnt(candidate_fnt)
    for row,code in zip(mapping_rows,codes):
        ti=FontRuntime.table_index_from_sjis(code)
        if ti!=int(row["table_index_hex"],0) or candidate_table[ti]!=int(row["candidate_glyph_index_hex"],0) or candidate_table[ti]==0:
            raise ValueError(f"후보 native 연결 오류: {row['hangul']}")

    declared_start:set[int]=set();declared_boot:set[int]=set();intervals:dict[str,list[tuple[int,int]]]={}
    rows=read_csv(WRITES)
    if len(rows)!=71:raise ValueError(f"Expected Write 수 오류: {len(rows)}")
    for row in rows:
        offset=int(row["offset_hex"],0);before=bytes.fromhex(row["expected_before_hex"]);after=bytes.fromhex(row["write_after_hex"])
        if len(before)!=len(after) or len(after)!=int(row["write_span"]):raise ValueError(f"길이 오류: {row['logical_id']}")
        layer=row["layer"]
        if layer.startswith("START.DAT/"):
            resource=layer.split("/",1)[1].casefold();absolute=int(records[resource].data_offset)+offset;target=patched_start;declared=declared_start
        elif layer=="PSP_GAME/SYSDIR/BOOT.BIN":absolute=offset;target=patched_boot;declared=declared_boot
        else:raise ValueError(f"계층 오류: {layer}")
        for left,right in intervals.setdefault(layer,[]):
            if absolute<right and left<absolute+len(after):raise ValueError(f"겹침: {row['logical_id']}")
        intervals[layer].append((absolute,absolute+len(after)))
        if target[absolute:absolute+len(before)]!=before:raise ValueError(f"before 불일치: {row['logical_id']}")
        target[absolute:absolute+len(after)]=after
        declared.update(absolute+i for i,p in enumerate(zip(before,after)) if p[0]!=p[1])
    if changed(base_start,patched_start)!=declared_start or changed(base_boot,patched_boot)!=declared_boot:raise ValueError("실제 변경 집합 오류")

    fnt_record=records["font.fnt"];patched_fnt=patched_start[fnt_record.data_offset:fnt_record.end_offset];table=FontRuntime._parse_fnt(patched_fnt)
    reverse={bytes.fromhex(r["native_code"]):r["hangul"] for r in mapping_rows}
    for row in mapping_rows:
        code=bytes.fromhex(row["native_code"]);ti=FontRuntime.table_index_from_sjis(code)
        if table[ti]!=int(row["current_glyph_index_hex"],0):raise ValueError(f"최종 글리프 연결 오류: {row['hangul']}")
    native_boot_rows=[r for r in rows if "NATIVE" in r["logical_id"] and r["layer"].endswith("BOOT.BIN")]
    decoded_characters=set()
    for row in native_boot_rows:
        payload=bytes.fromhex(row["write_after_hex"])
        for i in range(len(payload)-1):
            pair=payload[i:i+2]
            if pair in reverse:decoded_characters.add(reverse[pair])
    if decoded_characters!={r["hangul"] for r in mapping_rows}:raise ValueError("BOOT에서 54자 native 코드 사용 확인 실패")
    if patched_boot[0x613F4:0x613F8]!=bytes.fromhex("7343230E") or patched_boot[0xCCE20:0xCCF74]==bytes(0x154):raise ValueError("디코더 후킹 최종 상태 오류")
    report={"format":"prinny1_v7_14_18_candidate_native_review_v1","created_at":datetime.now().astimezone().isoformat(timespec="seconds"),
            "inputs":{"plan_sha256":sha256_file(PLAN),"writes_sha256":sha256_file(WRITES),"mapping_sha256":sha256_file(MAPPING)},
            "verified":{"native_character_count":54,"expected_write_count":len(rows),"start_changed_bytes":len(declared_start),"boot_changed_bytes":len(declared_boot)},
            "checks":{"fresh_inputs_reopened":True,"all_before_bytes_match":True,"actual_changes_equal_declared":True,
                      "all_candidate_native_entries_nonzero":True,"all_54_native_codes_present_in_boot":True,"decoder_hooks_present":True,
                      "translation_wording_changed":False,"candidate_wording_imported":False,"iso_created":False},
            "status":"pass_resource_build_allowed","final_verdict":"PASS"}
    OUTPUT.mkdir(parents=True,exist_ok=True);path=OUTPUT/"all_report.json";path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("native mapping 54: PASS");print("Expected Writes 71: PASS");print(f"START/BOOT changed bytes: {len(declared_start)}/{len(declared_boot)}");print("FINAL_VERDICT: PASS")
    return 0


if __name__=="__main__":raise SystemExit(main())
