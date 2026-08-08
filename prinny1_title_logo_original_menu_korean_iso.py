#!/usr/bin/env python3
"""Keep the original PRINNY logo while using the Korean title-menu texture."""
from pathlib import Path
import hashlib, json, os, shutil, struct, subprocess
from core.lzs import decompress_buffer, compress_buffer_runtime_safe
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file, SECTOR_SIZE
from scripts.prinny_anime_preview import parse_objects, find_texture_groups
from prinny1_v7_15_22_internal_texture_test import quantized_patch
ROOT=Path(__file__).resolve().parent
BASE=ROOT/'workspace/build/prinny1_v7_15_26_original_title_logo/prinny_korean_v7_15_26_original_title_logo.iso'
SRC=ROOT/'workspace/translations/ui_images_v7_15_4_xdelta_authoritative/translated/resized_v7_15_19/anime/anime00/object_078/group_00_page_00.png'
OUT=ROOT/'workspace/build/prinny1_v7_15_27_original_logo_korean_menu/prinny_korean_v7_15_27_original_logo_korean_menu.iso'
REP=ROOT/'workspace/reports/prinny1_v7_15_27_original_logo_korean_menu'
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def main():
 system=read_iso_file(BASE,find_iso_file(BASE,['PSP_GAME','USRDIR','SYSTEM.DAT'])); rows=system_records(system); sr=next(r for r in rows if r['name'].casefold()=='start.lzs'); lzs=system[sr['data_offset']:sr['data_offset']+sr['size']]; start=decompress_buffer(lzs)[0]; ar=next(r for r in StartRuntimeArchive.from_bytes(start).records if r.output_name.casefold()=='anime00.dat'); anime=bytes(start[ar.data_offset:ar.end_offset]); tex=next(t for o in parse_objects(anime) if o.index==78 for g in find_texture_groups(anime,o) for t in g if t.group_index==0 and t.page_index==0); patched,meta=quantized_patch(anime,tex,SRC); final=bytearray(start); final[ar.data_offset:ar.end_offset]=patched; nlzs=compress_buffer_runtime_safe(bytes(final),lzs[:4],int(decompress_buffer(lzs)[1]['flag'])); cap=rows[sr['index']+1]['data_offset']-sr['data_offset']; nsys=bytearray(system); nsys[sr['data_offset']:sr['data_offset']+cap]=b'\0'*cap; nsys[sr['data_offset']:sr['data_offset']+len(nlzs)]=nlzs; struct.pack_into('<I',nsys,0x10+sr['index']*0x2C+0x24,len(nlzs)); sector=int(find_iso_file(BASE,['PSP_GAME','USRDIR','SYSTEM.DAT'])['extent_lba'])*SECTOR_SIZE; OUT.parent.mkdir(parents=True,exist_ok=True); REP.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.iso.tmp')
 with BASE.open('rb') as s,tmp.open('wb') as t: shutil.copyfileobj(s,t,1<<20)
 with tmp.open('r+b') as f: f.seek(sector); f.write(nsys); f.flush(); os.fsync(f.fileno())
 if subprocess.run(['7z','t',str(tmp)],capture_output=True,text=True).returncode: raise RuntimeError('7z test failed')
 os.replace(tmp,OUT); (REP/'all_report.json').write_text(json.dumps({'format':'prinny1_v7_15_27_original_logo_korean_menu_v1','iso':{'path':str(OUT),'sha256':sha(OUT),'size':OUT.stat().st_size},'source_menu_texture':str(SRC),'restored_logo':'original PRINNY pixels in object_078','preserved':['Korean first/continue menu','company logo original','dialogue','sign-only textures','intro spacing'],'checks':{'seven_zip_test':True,'external_textures':False},'status':'complete'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(OUT); print(sha(OUT))
if __name__=='__main__': main()
