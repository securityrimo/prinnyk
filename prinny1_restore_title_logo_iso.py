#!/usr/bin/env python3
"""Restore anime00 title/logo object_078 while retaining all other final edits."""
from pathlib import Path
import hashlib, os, shutil, struct, subprocess, json
from core.lzs import decompress_buffer, compress_buffer_runtime_safe
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file, SECTOR_SIZE
from scripts.prinny_anime_preview import parse_objects
ROOT=Path(__file__).resolve().parent
ORIG=ROOT/'game.iso'; BASE=ROOT/'workspace/build/prinny1_v7_15_25_company_logo_restored/prinny_korean_v7_15_25_company_logo_restored.iso'
OUT=ROOT/'workspace/build/prinny1_v7_15_26_original_title_logo/prinny_korean_v7_15_26_original_title_logo.iso'; REP=ROOT/'workspace/reports/prinny1_v7_15_26_original_title_logo'
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def unpack(iso):
 s=read_iso_file(iso,find_iso_file(iso,['PSP_GAME','USRDIR','SYSTEM.DAT'])); rows=system_records(s); sr=next(r for r in rows if r['name'].casefold()=='start.lzs'); lzs=s[sr['data_offset']:sr['data_offset']+sr['size']]; return s,rows,sr,lzs,decompress_buffer(lzs)[0]
def rec(st): return next(r for r in StartRuntimeArchive.from_bytes(st).records if r.output_name.casefold()=='anime00.dat')
def span(an,index):
 o=next(o for o in parse_objects(an) if o.index==index); return o.offset,o.end
def main():
 bs,rows,sr,lzs,st=unpack(BASE); _,_,_,_,ost=unpack(ORIG); br,orr=rec(st),rec(ost); ba=bytearray(st[br.data_offset:br.end_offset]); oa=ost[orr.data_offset:orr.end_offset]
 for idx in (78,79):
  b0,b1=span(ba,idx); o0,o1=span(oa,idx)
  if b1-b0!=o1-o0: raise RuntimeError(f'object_{idx} size mismatch')
  ba[b0:b1]=oa[o0:o1]
 ns=bytearray(st); ns[br.data_offset:br.end_offset]=ba; flag=int(decompress_buffer(lzs)[1]['flag']); nlzs=compress_buffer_runtime_safe(bytes(ns),lzs[:4],flag); cap=rows[sr['index']+1]['data_offset']-sr['data_offset']
 if len(nlzs)>cap: raise RuntimeError('start.lzs overflow')
 nsys=bytearray(bs); nsys[sr['data_offset']:sr['data_offset']+cap]=b'\0'*cap; nsys[sr['data_offset']:sr['data_offset']+len(nlzs)]=nlzs; struct.pack_into('<I',nsys,0x10+sr['index']*0x2C+0x24,len(nlzs))
 sector=int(find_iso_file(BASE,['PSP_GAME','USRDIR','SYSTEM.DAT'])['extent_lba'])*SECTOR_SIZE; OUT.parent.mkdir(parents=True,exist_ok=True); REP.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.iso.tmp')
 with BASE.open('rb') as s,tmp.open('wb') as t: shutil.copyfileobj(s,t,1<<20)
 with tmp.open('r+b') as f: f.seek(sector); f.write(nsys); f.flush(); os.fsync(f.fileno())
 if subprocess.run(['7z','t',str(tmp)],capture_output=True,text=True).returncode: raise RuntimeError('7z test failed')
 os.replace(tmp,OUT); (REP/'all_report.json').write_text(json.dumps({'format':'prinny1_v7_15_26_original_title_logo_v1','iso':{'path':str(OUT),'sha256':sha(OUT),'size':OUT.stat().st_size},'restored_resources':['anime00/object_078','anime00/object_079'],'preserved':['dialogue','sign-only textures','intro spacing'],'checks':{'seven_zip_test':True,'external_textures':False},'status':'complete'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(OUT); print(sha(OUT))
if __name__=='__main__': main()
