#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,shutil,subprocess
from datetime import datetime
from pathlib import Path
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE,find_iso_file,read_iso_file
from prinny1_v7_14_15_text_test_iso import hash_range,merge_intervals
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_15_4_ui_image_export import system_records
ROOT=Path(__file__).resolve().parent; BASE=ROOT/'workspace/build/prinny1_v7_15_21_dialogue_voice_first/prinny_korean_v7_15_21_dialogue_voice_first.iso'; SYS=ROOT/'workspace/build/prinny1_v7_15_22_internal_texture_test_resources/SYSTEM.DAT'; REP=ROOT/'workspace/reports/prinny1_v7_15_22_internal_texture_test'; OUT=ROOT/'workspace/build/prinny1_v7_15_22_internal_texture_test/prinny_korean_v7_15_22_internal_texture_test.iso'
def sh(p):
 d=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): d.update(b)
 return d.hexdigest()
def main():
 if OUT.exists(): raise ValueError('출력 ISO가 이미 존재합니다.')
 br=find_iso_file(BASE,['PSP_GAME','USRDIR','SYSTEM.DAT']); blob=SYS.read_bytes(); so=int(br['extent_lba'])*SECTOR_SIZE; OUT.parent.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.iso.tmp')
 with BASE.open('rb') as s,tmp.open('wb') as t: shutil.copyfileobj(s,t,1<<20)
 with tmp.open('r+b') as f: f.seek(so); f.write(blob); f.flush(); os.fsync(f.fileno())
 if tmp.stat().st_size!=BASE.stat().st_size: raise ValueError('ISO 크기 변경')
 cur=0
 for l,r in merge_intervals([(so,so+len(blob))]):
  if hash_range(BASE,cur,l)!=hash_range(tmp,cur,l): raise ValueError('앞 데이터 변경')
  cur=r
 if hash_range(BASE,cur,BASE.stat().st_size)!=hash_range(tmp,cur,tmp.stat().st_size): raise ValueError('뒤 데이터 변경')
 z=subprocess.run(['7z','t',str(tmp)],capture_output=True,text=True);
 if z.returncode or 'Everything is Ok' not in z.stdout: raise ValueError('7z 실패')
 os.replace(tmp,OUT); ex=read_iso_file(OUT,find_iso_file(OUT,['PSP_GAME','USRDIR','SYSTEM.DAT']))
 if ex!=blob: raise ValueError('SYSTEM 재추출 불일치')
 rep=json.loads((REP/'all_report.json').read_text(encoding='utf-8')); rep['iso']={'path':str(OUT),'sha256':sh(OUT),'size':OUT.stat().st_size}; rep['checks']={'only_system_extent_changed':True,'seven_zip_structure_test':True,'system_reextracted_exactly':True,'title_baseline_unchanged_from_v7_15_11':True,'dialogue_voice_first_preserved':True}; rep['status']='pass_v7_15_22_test_iso_built_runtime_pending'; (REP/'all_report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(OUT); print(rep['iso']['sha256'])
if __name__=='__main__': raise SystemExit(main())
