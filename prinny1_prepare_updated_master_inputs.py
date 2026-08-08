#!/usr/bin/env python3
import csv, struct
from pathlib import Path
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records
ROOT=Path(__file__).resolve().parent
MASTER=ROOT/'workspace/translations/export/translation_master.csv'
ISO=Path('/tmp/prinny_xdelta_candidate.iso')
OUT=ROOT/'workspace/analysis/prinny1_xdelta_20260729/extracted/candidate'
QA=ROOT/'workspace/reports/prinny_qa/qa_rows.csv'
def main():
 system=read_iso_file(ISO,find_iso_file(ISO,['PSP_GAME','USRDIR','SYSTEM.DAT'])); sr=next(r for r in system_records(system) if r['name'].casefold()=='start.lzs'); start=decompress_buffer(system[sr['data_offset']:sr['data_offset']+sr['size']])[0]; archive=StartRuntimeArchive.from_bytes(start); OUT.mkdir(parents=True,exist_ok=True); (OUT/'start.dat').write_bytes(start); res=OUT/'start_resources'; res.mkdir(exist_ok=True)
 for r in archive.records:
  if r.output_name.casefold()=='font.fnt': (res/'font.fnt').write_bytes(start[r.data_offset:r.end_offset])
 rows=[]
 for r in csv.DictReader(MASTER.open(encoding='utf-8-sig')):
  if r['first_resource']=='True': resource=r['first_offset_hex']; off=r['resources']; cap=r['total_capacity_bytes']
  else: resource=r['first_resource']; off=r['first_offset_hex']; cap=r['translation_capacity_bytes']
  rows.append({'id':r['id'],'resource':resource,'offset':off,'capacity_bytes':cap,'translation':r['translation']})
 QA.parent.mkdir(parents=True,exist_ok=True)
 with QA.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
 print(len(rows))
if __name__=='__main__': main()
