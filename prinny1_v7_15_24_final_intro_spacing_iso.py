#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,shutil,subprocess
from datetime import datetime
from pathlib import Path
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE,find_iso_file,read_iso_file
from prinny1_v7_14_15_text_test_iso import hash_range,merge_intervals
ROOT=Path(__file__).resolve().parent; BASE=ROOT/'workspace/build/prinny1_v7_15_23_sign_only/prinny_korean_v7_15_23_sign_only.iso'; ANIME=Path('/tmp/prinny1_v7_archive_20260802/build/prinny1_v7_15_16_intro_spacing_resources/ANIME.DAT'); OUT=ROOT/'workspace/build/prinny1_v7_15_24_final_intro_spacing/prinny_korean_v7_15_24_final_intro_spacing.iso'; REP=ROOT/'workspace/reports/prinny1_v7_15_24_final_intro_spacing'
def sh(p):
 d=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): d.update(b)
 return d.hexdigest()
def main():
 if OUT.exists(): raise ValueError('출력 ISO가 이미 존재합니다')
 rec=find_iso_file(BASE,['PSP_GAME','USRDIR','ANIME.DAT']); blob=ANIME.read_bytes(); cap=int(rec['data_length']);
 if len(blob)!=cap: raise ValueError('ANIME.DAT 크기 불일치')
 off=int(rec['extent_lba'])*SECTOR_SIZE; OUT.parent.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.iso.tmp')
 with BASE.open('rb') as s,tmp.open('wb') as t: shutil.copyfileobj(s,t,1<<20)
 with tmp.open('r+b') as f: f.seek(off); f.write(blob); f.flush(); os.fsync(f.fileno())
 if tmp.stat().st_size!=BASE.stat().st_size: raise ValueError('ISO 크기 변경')
 cur=0
 for l,r in merge_intervals([(off,off+cap)]):
  if hash_range(BASE,cur,l)!=hash_range(tmp,cur,l): raise ValueError('앞 데이터 변경')
  cur=r
 if hash_range(BASE,cur,BASE.stat().st_size)!=hash_range(tmp,cur,tmp.stat().st_size): raise ValueError('뒤 데이터 변경')
 z=subprocess.run(['7z','t',str(tmp)],capture_output=True,text=True);
 if z.returncode or 'Everything is Ok' not in z.stdout: raise ValueError('7z 실패')
 os.replace(tmp,OUT); ex=read_iso_file(OUT,find_iso_file(OUT,['PSP_GAME','USRDIR','ANIME.DAT']))
 if ex!=blob: raise ValueError('ANIME.DAT 재추출 불일치')
 REP.mkdir(parents=True,exist_ok=True); (REP/'all_report.json').write_text(json.dumps({'format':'prinny1_v7_15_24_final_intro_spacing_v1','created_at':datetime.now().astimezone().isoformat(timespec='seconds'),'base_iso_sha256':sh(BASE),'iso':{'path':str(OUT),'sha256':sh(OUT),'size':OUT.stat().st_size},'policy':{'user_translation_primary':True,'overflow_xdelta_fallback':True,'character_voice_personality_selection':True,'external_textures':False},'textures':{'sign_only':True,'npc_textures_reverted':True,'photo_reviewed':['다음스테이지 간판.png','마왕 간판.png','마을 미번역 마계시.png','인트로데모.png','푯말.png']},'intro_spacing':{'resource':'ANIME.DAT/anime94.dat','horizontal_shift_pixels':-24,'source':'V7.15.16 verified spacing patch'},'checks':{'dialogue_preserved':True,'sign_only_preserved':True,'title_baseline_preserved':True,'intro_spacing_applied':True,'anime_reextracted_exactly':True,'seven_zip_test':True},'status':'pass_runtime_pending'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(OUT); print(sh(OUT))
if __name__=='__main__': raise SystemExit(main())
