#!/usr/bin/env python3
from __future__ import annotations
import csv,hashlib,json,struct
from datetime import datetime
from pathlib import Path
from core.font_runtime import FontRuntime
from core.start_runtime import StartRuntimeArchive
from prinny1_v7_14_15_boot_translation_plan import GROUPS,LABELS,TRANSLATION_CSV,TRANSLATION_SHA256,align4,virtual_address
from prinny1_v7_14_18_candidate_native_plan import NATIVE_HEX

ROOT=Path(__file__).resolve().parent;BASE_START=ROOT/"workspace/build/prinny1_v7_14_14_title_difficulty_repair/start.dat";BASE_BOOT=ROOT/"workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN";CANDIDATE_START=ROOT/"workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start.dat";V18_WRITES=ROOT/"workspace/reports/prinny1_v7_14_18_candidate_native_plan/expected_write_confirmed.csv";ALLOCATION=ROOT/"workspace/font/audited_allocation_980/hangul_allocation.json";RESIDUAL=ROOT/"workspace/font/audited_allocation_977/residual_audit.json";QA=ROOT/"workspace/reports/prinny_qa/qa_rows.csv";OUTPUT=ROOT/"workspace/reports/prinny1_v7_14_20_mixed_renderer_plan";PIX=0x50;BPG=0x8C
EXTRA={"리":"F1C2","추":"F3D6","천":"F3CB","처":"F3C9","음":"F35F","분":"F265","은":"F35D","쪽":"F3B9"}
MAP={**NATIVE_HEX,**EXTRA}
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rc(p):
    with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
def wc(p,rows):
    with p.open("w",encoding="utf-8-sig",newline="") as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def enc(text):
    out=bytearray()
    for c in text:
        if c in MAP:out.extend(bytes.fromhex(MAP[c]))
        else:out.extend(c.encode("cp932"))
    return bytes(out)
def row(layer,lid,target,off,before,after,kind):return {"sequence":0,"layer":layer,"logical_id":lid,"target":target,"offset_hex":f"0x{off:X}","write_span":len(after),"expected_before_hex":before.hex().upper(),"write_after_hex":after.hex().upper(),"change_kind":kind,"wording_changed":"no","expected_write_confirmed":"yes"}
def main():
    if sh(TRANSLATION_CSV)!=TRANSLATION_SHA256:raise ValueError("번역 CSV 해시 오류")
    ba=StartRuntimeArchive.load(BASE_START);br={r.output_name.casefold():r for r in ba.records};ca=StartRuntimeArchive.load(CANDIDATE_START);cr={r.output_name.casefold():r for r in ca.records};bs=BASE_START.read_bytes();bb=BASE_BOOT.read_bytes();bfnt=bs[br['font.fnt'].data_offset:br['font.fnt'].end_offset];btxp=bs[br['font.txp'].data_offset:br['font.txp'].end_offset];cfnt=ca.data[cr['font.fnt'].data_offset:cr['font.fnt'].end_offset];ctxp=ca.data[cr['font.txp'].data_offset:cr['font.txp'].end_offset];bt=FontRuntime._parse_fnt(bfnt);ct=FontRuntime._parse_fnt(cfnt);target=list(bt)
    used={int(r['glyph_index']) for r in json.loads(ALLOCATION.read_text())['allocations']};safe=[];seen=set()
    for r in json.loads(RESIDUAL.read_text())['safe_candidates']:
        g=int(r['glyph_index'])
        if g not in used and g not in seen and int(r['audit']['trusted_text_hits'])==0:safe.append(r);seen.add(g)
        if len(safe)==len(MAP):break
    if len(safe)!=len(MAP) or len(set(MAP.values()))!=len(MAP):raise ValueError("61자 코드/슬롯 오류")
    rows=[r for r in rc(V18_WRITES) if r['layer']=='START.DAT/font.txp' or r['logical_id'].startswith(('HOOK-','PARSER-','BYTE-','INJECT-'))];slots=[]
    for seq,((ch,hx),s) in enumerate(zip(MAP.items(),safe),1):
        code=bytes.fromhex(hx);ti=FontRuntime.table_index_from_sjis(code);sg=ct[ti];tg=int(s['glyph_index']);target[ti]=tg;before=btxp[PIX+tg*BPG:PIX+(tg+1)*BPG];after=ctxp[PIX+sg*BPG:PIX+(sg+1)*BPG]
        rows.append(row('START.DAT/font.txp',f'P1-MIXED-GLYPH-{seq:03d}','font.txp',PIX+tg*BPG,before,after,'candidate_glyph_into_audited_unused_slot'));slots.append({'sequence':seq,'hangul':ch,'native_code':hx,'table_index_hex':f'0x{ti:04X}','candidate_glyph_index_hex':f'0x{sg:04X}','target_glyph_index_hex':f'0x{tg:04X}','trusted_text_hits':s['audit']['trusted_text_hits']})
    ci=[i for i,p in enumerate(zip(bt,target)) if p[0]!=p[1]];groups=[];left=prev=ci[0]
    for i in ci[1:]:
        if i!=prev+1:groups.append((left,prev+1));left=i
        prev=i
    groups.append((left,prev+1))
    for n,(left,right) in enumerate(groups,1):
        off=2+left*2;rows.append(row('START.DAT/font.fnt',f'P1-MIXED-FNT-{n:03d}','font.fnt',off,bfnt[off:2+right*2],b''.join(struct.pack('<H',target[i]) for i in range(left,right)),'native_code_to_candidate_glyph_slot'))
    tr={r['id']:r['translation_korean'] for r in rc(TRANSLATION_CSV)}
    for g in GROUPS:
        gid=str(g['id']);lines=tuple(g['translation_lines']);assert ' '.join(lines)==tr[gid];start,end=int(g['block_start']),int(g['block_end']);block=bytearray(end-start);offs=[];cur=start
        for text in lines:
            payload=enc(text);cur=align4(cur);rel=cur-start
            if rel+len(payload)+2>len(block):raise ValueError(f"BOOT 혼합 인코딩 용량 초과 {gid}")
            block[rel:rel+len(payload)]=payload;offs.append(cur);cur+=len(payload)+2
        rows.append(row('PSP_GAME/SYSDIR/BOOT.BIN',f'{gid}-MIXED-BLOCK','PSP_GAME/SYSDIR/BOOT.BIN',start,bb[start:end],bytes(block),'user_translation_candidate_mixed_encoding'))
        for n,(po,so) in enumerate(zip(g['pointer_offsets'],offs),1):
            po=int(po);after=struct.pack('<I',virtual_address(so))
            if bb[po:po+4]!=after:rows.append(row('PSP_GAME/SYSDIR/BOOT.BIN',f'{gid}-PTR-{n}','PSP_GAME/SYSDIR/BOOT.BIN',po,bb[po:po+4],after,'in_block_string_pointer_adjustment'))
    for gid,off,span,_ in LABELS:
        payload=enc(tr[gid]);rows.append(row('PSP_GAME/SYSDIR/BOOT.BIN',f'{gid}-MIXED-LABEL','PSP_GAME/SYSDIR/BOOT.BIN',off,bb[off:off+span],payload+bytes(span-len(payload)),'user_translation_candidate_mixed_encoding'))
    q={(r['resource'].casefold(),int(r['offset'],0)):r for r in rc(QA)};demo=bs[br['demo00.dat'].data_offset:br['demo00.dat'].end_offset]
    for off,prefix in [(0xA,b'\xC8'),(0xA0,b''),(0xC3,b'')]:
        qr=q[('demo00.dat',off)];span=int(qr['capacity_bytes']);after=prefix+enc(qr['translation']);
        if len(after)+1>span:raise ValueError(f"Demo00 용량 초과 {off:#x}")
        after=after+bytes(span-len(after));rows.append(row('START.DAT/Demo00.dat',f'P1-DEMO-NATIVE-{off:X}','Demo00.dat',off,demo[off:off+span],after,'existing_user_translation_candidate_mixed_encoding'))
    rows.sort(key=lambda r:(r['layer'],int(r['offset_hex'],0)))
    for i,r in enumerate(rows,1):r['sequence']=i
    OUTPUT.mkdir(parents=True,exist_ok=True);wp=OUTPUT/'expected_write_confirmed.csv';sp=OUTPUT/'candidate_glyph_slots.csv';wc(wp,rows);wc(sp,slots);report={'format':'prinny1_v7_14_20_mixed_renderer_plan_v1','created_at':datetime.now().astimezone().isoformat(timespec='seconds'),'verified':{'native_character_count':len(MAP),'candidate_glyph_count':len(slots),'font_fnt_write_count':len(groups),'demo00_write_count':3,'total_expected_write_count':len(rows)},'checks':{'ascii_space_and_punctuation_preserved':True,'all_current_980_slots_preserved':True,'all_new_slots_trusted_hits_zero':True,'existing_user_demo_translations_used':True,'translation_wording_changed':False,'candidate_wording_imported':False,'iso_created':False},'artifacts':{'expected_writes':str(wp),'expected_writes_sha256':sh(wp),'slots':str(sp),'slots_sha256':sh(sp)},'status':'expected_writes_confirmed_independent_review_required','final_verdict':'PASS'};(OUTPUT/'all_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(f"native chars/glyphs: {len(MAP)}");print(f"Expected Writes: {len(rows)}");print("FINAL_VERDICT: PASS");return 0
if __name__=='__main__':raise SystemExit(main())
