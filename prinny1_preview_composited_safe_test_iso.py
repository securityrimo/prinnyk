#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,os,shutil,struct,subprocess
from PIL import Image
from core.lzs import decompress_buffer,compress_buffer_runtime_safe
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_15_4_ui_image_export import system_records
from prinny1_v7_14_minimum_test_iso import find_iso_file,read_iso_file,SECTOR_SIZE
from scripts.prinny_anime_preview import parse_objects,find_texture_groups,swizzle_psp
ROOT=Path(__file__).resolve().parent; BASE=ROOT/'workspace/build/prinny1_v7_15_32_xdelta_title/prinny_korean_v7_15_32_xdelta_title.iso'; SRC=ROOT/'workspace/translations/generated_object017_tutorial_partial.png'; OUT=ROOT/'workspace/build/prinny1_v7_15_33_tutorial_partial/prinny_korean_v7_15_33_tutorial_partial.iso'; REP=ROOT/'workspace/reports/prinny1_v7_15_33_tutorial_partial'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def patch(data,tex):
 im=Image.open(SRC).convert('RGBA').resize((tex.width,tex.height),Image.Resampling.LANCZOS); pix=list(im.getdata()); opaque=[p for p in pix if p[3]>=128]; rgb=Image.new('RGB',(len(opaque),1)); rgb.putdata([(r,g,b) for r,g,b,a in opaque]); q=rgb.quantize(colors=15,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE).convert('RGB'); colors=[]
 for c in q.getdata():
  if c not in colors: colors.append(c)
 colors=colors[:15]; pal=[(0,0,0,0)]+[(r,g,b,255) for r,g,b in colors]; pal += [(0,0,0,0)]*(16-len(pal)); idx=[]
 for r,g,b,a in pix:
  if a<128: idx.append(0)
  else: idx.append(1+min(range(len(colors)),key=lambda i:sum((c-colors[i][j])**2 for j,c in enumerate((r,g,b)))))
 packed=bytes(idx[i]|(idx[i+1]<<4) for i in range(0,len(idx),2)); out=bytearray(data); out[tex.palette_offset:tex.palette_offset+64]=b''.join(bytes(c) for c in pal); out[tex.pixel_offset:tex.pixel_offset+len(packed)]=swizzle_psp(packed,tex.width//2,tex.height); return bytes(out)
def main():
 original=Image.open(ROOT/'workspace/translations/ui_images_v7_15_4_xdelta_authoritative/source_png/anime/anime00/object_017/group_00_page_00.png').convert('RGBA'); korean=Image.open('/home/hyuk/다운로드/textures/ULJS00150/08de41e046fe2552b6e0db29.png').convert('RGBA'); crop=korean.crop((232,208,256,256)); original.paste(crop,(232,208),crop); original.save(SRC)
 system=read_iso_file(BASE,find_iso_file(BASE,['PSP_GAME','USRDIR','SYSTEM.DAT'])); rows=system_records(system); sr=next(r for r in rows if r['name'].casefold()=='start.lzs'); lzs=system[sr['data_offset']:sr['data_offset']+sr['size']]; start=decompress_buffer(lzs)[0]; ar=next(r for r in StartRuntimeArchive.from_bytes(start).records if r.output_name.casefold()=='anime00.dat'); anime=bytes(start[ar.data_offset:ar.end_offset]); tex=next(t for o in parse_objects(anime) if o.index==17 for g in find_texture_groups(anime,o) for t in g if t.group_index==0 and t.page_index==0); final=bytearray(start); final[ar.data_offset:ar.end_offset]=patch(anime,tex); nlzs=compress_buffer_runtime_safe(bytes(final),lzs[:4],int(decompress_buffer(lzs)[1]['flag'])); cap=rows[sr['index']+1]['data_offset']-sr['data_offset']; nsys=bytearray(system); nsys[sr['data_offset']:sr['data_offset']+cap]=b'\0'*cap; nsys[sr['data_offset']:sr['data_offset']+len(nlzs)]=nlzs; struct.pack_into('<I',nsys,0x10+sr['index']*0x2C+0x24,len(nlzs)); sector=int(find_iso_file(BASE,['PSP_GAME','USRDIR','SYSTEM.DAT'])['extent_lba'])*SECTOR_SIZE; OUT.parent.mkdir(parents=True,exist_ok=True); REP.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.iso.tmp')
 with BASE.open('rb') as s,tmp.open('wb') as t: shutil.copyfileobj(s,t,1<<20)
 with tmp.open('r+b') as f: f.seek(sector); f.write(nsys); f.flush(); os.fsync(f.fileno())
 if subprocess.run(['7z','t',str(tmp)],capture_output=True,text=True).returncode: raise RuntimeError('7z test failed')
 os.replace(tmp,OUT); (REP/'all_report.json').write_text(json.dumps({'format':'prinny1_v7_15_29_preview_composited_test_v1','iso':{'path':str(OUT),'sha256':sha(OUT),'size':OUT.stat().st_size},'source':str(SRC),'normalization':'resize_to_512x512','palette':'transparent_slot_reserved','target':'anime00/object_078/group_00/page_00','checks':{'seven_zip_test':True,'external_textures':False},'status':'complete'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(OUT); print(sha(OUT))
if __name__=='__main__': main()
