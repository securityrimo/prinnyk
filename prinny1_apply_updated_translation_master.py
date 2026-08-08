#!/usr/bin/env python3
import csv,hashlib,json,os,shutil,struct,subprocess
from pathlib import Path
from core.lzs import decompress_buffer,compress_buffer_runtime_safe
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file,read_iso_file,SECTOR_SIZE
from prinny1_v7_15_4_ui_image_export import system_records
ROOT=Path(__file__).resolve().parent; BASE=ROOT/'workspace/build/prinny1_final_dialogue_user_priority/prinny_korean_final_dialogue_user_priority.iso'; XD=Path('/tmp/prinny_xdelta_candidate.iso'); MASTER=ROOT/'workspace/translations/export/translation_master.csv'; META=ROOT/'workspace/translations/export/translation_master_merged.json'; CODEBOOK=ROOT/'workspace/reports/prinny1_xdelta_codebook_recovery/candidate_codebook_partial.csv'; OUT=ROOT/'workspace/build/prinny1_final_updated_master/prinny_korean_final_updated_master.iso'; REP=ROOT/'workspace/reports/prinny1_final_updated_master'
def sh(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def extract(iso):
 s=read_iso_file(iso,find_iso_file(iso,['PSP_GAME','USRDIR','SYSTEM.DAT'])); rows=system_records(s); sr=next(r for r in rows if r['name'].casefold()=='start.lzs'); l=s[sr['data_offset']:sr['data_offset']+sr['size']]; st=decompress_buffer(l)[0]; a=StartRuntimeArchive.from_bytes(st); return s,rows,sr,l,bytearray(st),{r.output_name.casefold():r for r in a.records}
def main():
 system,rows,sr,lzs,start,recs=extract(BASE); _,_,_,_,xst,xrecs=extract(XD); csvrows={r['id']:r for r in csv.DictReader(MASTER.open(encoding='utf-8-sig'))}; entries=json.load(META.open())['entries']; codes={r['unicode_character']:bytes.fromhex(r['candidate_code']) for r in csv.DictReader(CODEBOOK.open(encoding='utf-8-sig')) if r['unicode_character']}; counts={'user':0,'xdelta_overflow':0,'xdelta_missing_glyph':0,'unchanged':0}; writes=[]
 for e in entries:
  r=csvrows[e['id']]; text=r['translation']; prefix=bytes.fromhex(r['prefix_hex']) if r['prefix_hex'] else b''
  try:
   body=b''.join(codes[c] if '가'<=c<='힣' else c.encode('cp932') for c in text); missing=False
  except (KeyError,UnicodeEncodeError): body=b''; missing=True
  for o in e['occurrences']:
   key=o['resource'].casefold(); off=int(o['offset']); cap=int(o['byte_length']); xr=xrecs[key]; fallback=bytes(xst[xr.data_offset+off:xr.data_offset+off+cap])
   if missing: payload=fallback; source='xdelta_missing_glyph'
   elif len(prefix)+len(body)>cap: payload=fallback; source='xdelta_overflow'
   else: payload=prefix+body+b'\0'*(cap-len(prefix)-len(body)); source='user'
   rr=recs[key]; pos=rr.data_offset+off; before=bytes(start[pos:pos+cap]); start[pos:pos+cap]=payload; counts['unchanged' if before==payload else source]+=1; writes.append({'id':e['id'],'resource':o['resource'],'offset_hex':hex(off),'capacity':cap,'source':source,'before_hex':before.hex().upper(),'after_hex':payload.hex().upper()})
 nlzs=compress_buffer_runtime_safe(bytes(start),lzs[:4],int(decompress_buffer(lzs)[1]['flag'])); capsys=rows[sr['index']+1]['data_offset']-sr['data_offset'];
 if len(nlzs)>capsys: raise RuntimeError('START.LZS overflow')
 nsys=bytearray(system); nsys[sr['data_offset']:sr['data_offset']+capsys]=b'\0'*capsys; nsys[sr['data_offset']:sr['data_offset']+len(nlzs)]=nlzs; struct.pack_into('<I',nsys,0x10+sr['index']*0x2C+0x24,len(nlzs)); sector=int(find_iso_file(BASE,['PSP_GAME','USRDIR','SYSTEM.DAT'])['extent_lba'])*SECTOR_SIZE; OUT.parent.mkdir(parents=True,exist_ok=True); REP.mkdir(parents=True,exist_ok=True); tmp=OUT.with_suffix('.tmp')
 with BASE.open('rb') as a,tmp.open('wb') as b: shutil.copyfileobj(a,b,1<<20)
 with tmp.open('r+b') as f: f.seek(sector); f.write(nsys); f.flush(); os.fsync(f.fileno())
 if subprocess.run(['7z','t',str(tmp)],capture_output=True).returncode: raise RuntimeError('7z failed')
 os.replace(tmp,OUT)
 with (REP/'expected_writes.csv').open('w',encoding='utf-8-sig',newline='') as f: w=csv.DictWriter(f,fieldnames=list(writes[0])); w.writeheader(); w.writerows(writes)
 report={'format':'prinny1_updated_master_apply_v1','master_sha256':sh(MASTER),'base_sha256':sh(BASE),'iso':{'path':str(OUT),'sha256':sh(OUT)},'occurrences':len(writes),'counts':counts,'lzs_roundtrip':decompress_buffer(nlzs)[0]==bytes(start),'seven_zip_test':True,'status':'complete'}; (REP/'all_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__': main()
