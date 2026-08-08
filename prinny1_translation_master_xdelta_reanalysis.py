#!/usr/bin/env python3
"""Reconcile translation_master.csv against the authoritative xdelta payload."""
from __future__ import annotations
import csv, hashlib, json
from collections import Counter
from pathlib import Path
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_minimum_test_iso import find_iso_file, read_iso_file
from prinny1_v7_15_4_ui_image_export import system_records

ROOT=Path(__file__).resolve().parent
MASTER=ROOT/'workspace/translations/export/translation_master.csv'
ORIGINAL=ROOT/'game.iso'; XDELTA_CANDIDATE=Path('/tmp/prinny_xdelta_candidate.iso')
OUT=ROOT/'workspace/reports/prinny1_translation_master_xdelta_reanalysis'

def sha(p):
 d=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): d.update(b)
 return d.hexdigest()
def start_resources(iso):
 s=read_iso_file(iso,find_iso_file(iso,['PSP_GAME','USRDIR','SYSTEM.DAT']))
 rows=system_records(s); sr=next(r for r in rows if r['name'].casefold()=='start.lzs')
 start=decompress_buffer(s[sr['data_offset']:sr['data_offset']+sr['size']])[0]
 a=StartRuntimeArchive.from_bytes(start); return {r.output_name.casefold():start[r.data_offset:r.end_offset] for r in a.records}
def measure(t): return sum(2 if '가'<=c<='힣' else len(c.encode('cp932')) for c in t)
def main():
 if not XDELTA_CANDIDATE.exists(): raise FileNotFoundError(XDELTA_CANDIDATE)
 original=start_resources(ORIGINAL); candidate=start_resources(XDELTA_CANDIDATE)
 raw=list(csv.DictReader(MASTER.open(encoding='utf-8-sig'))); rows=[]; malformed=0; counts=Counter()
 for r in raw:
  # Two historical rows contain unquoted commas and are shifted by one field.
  if r['first_resource']=='True':
   malformed+=1; resource=r['first_offset_hex']; offset_hex=r['resources']; capacity=int(r['total_capacity_bytes'] or 0); issue='malformed_csv_row_normalized'
  else:
   resource=r['first_resource']; offset_hex=r['first_offset_hex']; capacity=int(r['translation_capacity_bytes'] or 0); issue=''
  key=resource.casefold(); offset=int(offset_hex,0) if offset_hex else -1
  blob_o=original.get(key); blob_x=candidate.get(key)
  if blob_o is None or blob_x is None: issue=(issue+';missing_start_resource').strip(';')
  if blob_x is not None and (offset<0 or offset+capacity>len(blob_x)): issue=(issue+';offset_out_of_range').strip(';')
  before=blob_o[offset:offset+capacity] if blob_o is not None and 0<=offset<=len(blob_o)-capacity else b''
  after=blob_x[offset:offset+capacity] if blob_x is not None and 0<=offset<=len(blob_x)-capacity else b''
  changed=bool(before!=after); user=r['translation']; source=r['source_display']; user_size=measure(user) if user else 0
  if user_size>capacity: decision='xdelta_overflow_fallback'
  elif 'ッス' in source or 'っス' in source: decision='user_translation_voice_review'
  else: decision='user_translation_primary'
  if issue: decision='hold_manual_review'
  counts[decision]+=1
  rows.append({'id':r['id'],'resource':resource,'offset_hex':offset_hex,'capacity_bytes':capacity,'source_display':source,'user_translation':user,'user_payload_measure':user_size,'xdelta_before_hex':before.hex().upper(),'xdelta_reference_after_hex':after.hex().upper(),'xdelta_changed':'yes' if changed else 'no','decision':decision,'issue':issue})
 OUT.mkdir(parents=True,exist_ok=True)
 with (OUT/'translation_master_xdelta_reanalysis.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
 report={'format':'prinny1_translation_master_xdelta_reanalysis_v1','inputs':{'translation_master.csv':sha(MASTER),'original_iso':sha(ORIGINAL),'xdelta_candidate_iso':sha(XDELTA_CANDIDATE)},'verified':{'master_rows':len(raw),'normalized_malformed_rows':malformed,'start_resources_original':len(original),'start_resources_xdelta':len(candidate),'xdelta_address_values_checked':len(rows),'out_of_range_or_missing':sum(bool(r['issue']) for r in rows),'decision_counts':dict(counts)},'policy':{'user_translation_primary':True,'xdelta_reference_for_addresses_and_payload':True,'overflow_fallback_to_xdelta':True,'character_voice_personality_review':True,'original_master_unchanged':True},'artifacts':{'reanalysis_csv':str(OUT/'translation_master_xdelta_reanalysis.csv'),'reanalysis_sha256':sha(OUT/'translation_master_xdelta_reanalysis.csv')},'status':'reanalysis_complete_manual_voice_review_required'}
 (OUT/'all_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(report['verified'],ensure_ascii=False))
if __name__=='__main__': raise SystemExit(main())
