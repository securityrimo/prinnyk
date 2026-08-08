#!/usr/bin/env python3
"""Build the isolated V7.15.21 voice-first dialogue test ISO."""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess
from datetime import datetime
from pathlib import Path
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE, find_iso_file, read_iso_file
from prinny1_v7_14_15_text_test_iso import hash_range, merge_intervals
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_15_4_ui_image_export import system_records

ROOT=Path(__file__).resolve().parent
BASE=ROOT/"workspace/build/prinny1_v7_15_15_user_dialogue/prinny_korean_v7_15_15_user_dialogue.iso"
SYSTEM=ROOT/"workspace/build/prinny1_v7_15_21_dialogue_voice_first_resources/SYSTEM.DAT"
REPORT=ROOT/"workspace/reports/prinny1_v7_15_21_dialogue_voice_first"
OUT=ROOT/"workspace/build/prinny1_v7_15_21_dialogue_voice_first/prinny_korean_v7_15_21_dialogue_voice_first.iso"
def sha(p):
 d=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): d.update(b)
 return d.hexdigest()
def main():
 if OUT.exists(): raise ValueError('출력 ISO가 이미 존재합니다. 덮어쓰지 않습니다.')
 br=find_iso_file(BASE,['PSP_GAME','USRDIR','SYSTEM.DAT']); final=SYSTEM.read_bytes()
 if len(final)!=int(br['data_length']): raise ValueError('SYSTEM.DAT 크기 불일치')
 OUT.parent.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.iso.tmp')
 with BASE.open('rb') as s,tmp.open('wb') as t: shutil.copyfileobj(s,t,1<<20)
 so=int(br['extent_lba'])*SECTOR_SIZE
 with tmp.open('r+b') as f: f.seek(so); f.write(final); f.flush(); os.fsync(f.fileno())
 if tmp.stat().st_size!=BASE.stat().st_size: raise ValueError('ISO 크기 변경')
 cur=0
 for l,r in merge_intervals([(so,so+len(final))]):
  if hash_range(BASE,cur,l)!=hash_range(tmp,cur,l): raise ValueError('SYSTEM.DAT 앞 데이터 변경')
  cur=r
 if hash_range(BASE,cur,BASE.stat().st_size)!=hash_range(tmp,cur,tmp.stat().st_size): raise ValueError('SYSTEM.DAT 뒤 데이터 변경')
 z=subprocess.run(['7z','t',str(tmp)],capture_output=True,text=True,check=False)
 if z.returncode or 'Everything is Ok' not in z.stdout: raise ValueError('7z 구조 검사 실패')
 os.replace(tmp,OUT)
 extracted=read_iso_file(OUT,find_iso_file(OUT,['PSP_GAME','USRDIR','SYSTEM.DAT']))
 if extracted!=final: raise ValueError('SYSTEM.DAT 재추출 불일치')
 rows=system_records(extracted); sr=next(r for r in rows if r['name'].casefold()=='start.lzs')
 start=decompress_buffer(extracted[sr['data_offset']:sr['data_offset']+sr['size']])[0]; a=StartRuntimeArchive.from_bytes(start); rec={r.output_name.casefold():r for r in a.records}
 demo=(ROOT/'workspace/build/prinny1_v7_15_21_dialogue_voice_first_resources/Demo00.dat').read_bytes()
 dr=rec['demo00.dat']
 if start[dr.data_offset:dr.end_offset]!=demo: raise ValueError('Demo00.dat 재추출 불일치')
 report=json.loads((REPORT/'all_report.json').read_text(encoding='utf-8')); report.update({'iso':{'path':str(OUT),'sha256':sha(OUT),'size':OUT.stat().st_size},'checks':{'only_system_extent_changed':True,'seven_zip_structure_test':True,'system_reextracted_exactly':True,'demo_reextracted_exactly':True,'base_iso_not_overwritten':True},'status':'pass_v7_15_21_test_iso_built_runtime_pending','created_at':datetime.now().astimezone().isoformat(timespec='seconds')}); (REPORT/'all_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(OUT); print(sha(OUT))
if __name__=='__main__': raise SystemExit(main())
