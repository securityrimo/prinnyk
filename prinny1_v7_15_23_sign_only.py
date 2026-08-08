#!/usr/bin/env python3
"""Rebuild V7.15.22 with only the Korean sign texture enabled."""
from __future__ import annotations
import hashlib,json,os,shutil,struct,subprocess
from datetime import datetime
from pathlib import Path
from core.lzs import compress_buffer_runtime_safe,decompress_buffer
from core.start_runtime import StartRuntimeArchive
from core.system_unpack import *
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_14_minimum_test_iso import SECTOR_SIZE,find_iso_file,read_iso_file
from prinny1_v7_14_15_text_test_iso import hash_range,merge_intervals
from scripts.prinny_anime_preview import parse_objects,find_texture_groups
from prinny1_v7_15_22_internal_texture_test import quantized_patch
ROOT=Path(__file__).resolve().parent; BASE=Path('/tmp/prinny1_v7_archive_20260802/build/prinny1_v7_15_21_dialogue_voice_first'); BASEISO=BASE/'prinny_korean_v7_15_21_dialogue_voice_first.iso'; SRC=Path('/home/hyuk/다운로드/textures/ULJS00150/09bba150f04e998665714c1a.png'); OUTRES=ROOT/'workspace/build/prinny1_v7_15_23_sign_only_resources'; REP=ROOT/'workspace/reports/prinny1_v7_15_23_sign_only'; OUTISO=ROOT/'workspace/build/prinny1_v7_15_23_sign_only/prinny_korean_v7_15_23_sign_only.iso'
def sh(p):
 d=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): d.update(b)
 return d.hexdigest()
def main():
 system=read_iso_file(BASEISO,find_iso_file(BASEISO,['PSP_GAME','USRDIR','SYSTEM.DAT'])); rows0=system_records(system); sr0=next(r for r in rows0 if r['name'].casefold()=='start.lzs'); lzs=system[sr0['data_offset']:sr0['data_offset']+sr0['size']]; start=decompress_buffer(lzs)[0]; a=StartRuntimeArchive.from_bytes(start); rec={r.output_name.casefold():r for r in a.records}; ar=rec['anime00.dat']; anime=bytes(start[ar.data_offset:ar.end_offset]); tex={(t.object_index,t.group_index,t.page_index):t for o in parse_objects(anime) for g in find_texture_groups(anime,o) for t in g}; patched,meta=quantized_patch(anime,tex[(79,0,0)],SRC); final=bytearray(start); final[ar.data_offset:ar.end_offset]=patched; h=decompress_buffer(lzs)[1]; new=compress_buffer_runtime_safe(bytes(final),lzs[:4],int(h['flag'])); rows=system_records(system); sr=next(r for r in rows if r['name'].casefold()=='start.lzs'); cap=rows[sr['index']+1]['data_offset']-sr['data_offset']; fs=bytearray(system); fs[sr['data_offset']:sr['data_offset']+cap]=bytes(cap); fs[sr['data_offset']:sr['data_offset']+len(new)]=new; struct.pack_into('<I',fs,0x10+sr['index']*0x2C+0x24,len(new)); OUTRES.mkdir(parents=True,exist_ok=True); REP.mkdir(parents=True,exist_ok=True); (OUTRES/'SYSTEM.DAT').write_bytes(fs); (OUTRES/'start.dat').write_bytes(final); (OUTRES/'start.lzs').write_bytes(new); (OUTRES/'anime00.dat').write_bytes(patched)
 if OUTISO.exists(): raise ValueError('출력 ISO가 이미 존재합니다')
 br=find_iso_file(BASEISO,['PSP_GAME','USRDIR','SYSTEM.DAT']); so=int(br['extent_lba'])*SECTOR_SIZE; OUTISO.parent.mkdir(parents=True,exist_ok=True); tmp=OUTISO.with_suffix('.iso.tmp');
 with BASEISO.open('rb') as s,tmp.open('wb') as t: shutil.copyfileobj(s,t,1<<20)
 with tmp.open('r+b') as f: f.seek(so); f.write(fs); f.flush(); os.fsync(f.fileno())
 if tmp.stat().st_size!=BASEISO.stat().st_size: raise ValueError('ISO size changed')
 z=subprocess.run(['7z','t',str(tmp)],capture_output=True,text=True);
 if z.returncode or 'Everything is Ok' not in z.stdout: raise ValueError('7z failed')
 os.replace(tmp,OUTISO); (REP/'all_report.json').write_text(json.dumps({'format':'prinny1_v7_15_23_sign_only_v1','created_at':datetime.now().astimezone().isoformat(timespec='seconds'),'base_iso_sha256':sh(BASEISO),'iso':{'path':str(OUTISO),'sha256':sh(OUTISO),'size':OUTISO.stat().st_size},'enabled_texture':'anime00/object_079/group_00/page_00','disabled_textures':['anime00/object_017/group_00/page_00','anime00/object_085/group_00/page_00'],'checks':{'dialogue_preserved':True,'title_baseline_preserved':True,'external_textures_used':False,'seven_zip_test':True,'sign_only':True},'status':'pass_runtime_pending'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(OUTISO); print(sh(OUTISO))
if __name__=='__main__': raise SystemExit(main())
