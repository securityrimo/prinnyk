#!/usr/bin/env python3
"""Import selected dumped Korean textures into internal anime00 pages.

Only one mutually-exclusive color variant per source family is selected.
"""
from __future__ import annotations
import csv, hashlib, json, struct
from datetime import datetime
from pathlib import Path
from PIL import Image
from core.lzs import compress_buffer_runtime_safe, decompress_buffer
from core.start_runtime import StartRuntimeArchive
from scripts.prinny_anime_preview import parse_objects, find_texture_groups, decode_texture, swizzle_psp
from prinny1_v7_15_4_ui_image_export import system_records

ROOT=Path(__file__).resolve().parent
BASE=ROOT/"workspace/build/prinny1_v7_15_21_dialogue_voice_first_resources"
OUT=ROOT/"workspace/build/prinny1_v7_15_22_internal_texture_test_resources"
REPORT=ROOT/"workspace/reports/prinny1_v7_15_22_internal_texture_test"
SRC=Path('/home/hyuk/다운로드/textures/ULJS00150')
SELECTED={
    'object_017_g00_p00':SRC/'08de41e046fe2552b6e0db29.png',
    'object_079_g00_p00':SRC/'09bba150f04e998665714c1a.png',
    'object_085_g00_p00':SRC/'09596a50a8d5f299b5a34886.png',
}
ALTERNATES={
    '08de_family':[SRC/x for x in ['08de41e0a43c0364b6e0db29.png','08de41e02d08ded3b6e0db29.png','08de41e0742b67e5b6e0db29.png','08de41e05976a553b6e0db29.png']],
    '09596_family':[SRC/x for x in ['09596a50862c2386b5a34886.png','09596a50564378d0b5a34886.png','09596a50982610dbb5a34886.png']],
}
def sha(b): return hashlib.sha256(b).hexdigest()
def quantized_patch(data:bytes, tex, source:Path)->tuple[bytes,dict]:
    im=Image.open(source).convert('RGBA')
    if im.size!=(tex.width,tex.height): raise ValueError(f'{source.name}: size {im.size}!={(tex.width,tex.height)}')
    q=im.quantize(colors=16,method=Image.Quantize.FASTOCTREE,dither=Image.Dither.NONE)
    rgba=q.convert('RGBA'); colors=[]; indices=[]
    for c in rgba.getdata():
        if c not in colors: colors.append(c)
    colors += [(0,0,0,0)]*(16-len(colors)); cmap={c:i for i,c in enumerate(colors)}
    indices=[cmap[c] for c in rgba.getdata()]
    packed=bytes(indices[i] | (indices[i+1]<<4) for i in range(0,len(indices),2))
    packed=swizzle_psp(packed,tex.width//2,tex.height)
    out=bytearray(data); out[tex.palette_offset:tex.palette_offset+64]=b''.join(bytes(c) for c in colors); out[tex.pixel_offset:tex.pixel_offset+len(packed)]=packed
    return bytes(out),{'source':str(source),'size':[tex.width,tex.height],'palette_colors':len(set(colors)),'source_sha256':sha(source.read_bytes())}
def main():
    start=(BASE/'start.dat').read_bytes(); system=(BASE/'SYSTEM.DAT').read_bytes(); lzs=(BASE/'start.lzs').read_bytes(); archive=StartRuntimeArchive.from_bytes(start); rec={r.output_name.casefold():r for r in archive.records}; ar=rec['anime00.dat']; anime=bytes(start[ar.data_offset:ar.end_offset]); texmap={(t.object_index,t.group_index,t.page_index):t for o in parse_objects(anime) for g in find_texture_groups(anime,o) for t in g}
    keys={'object_017_g00_p00':(17,0,0),'object_079_g00_p00':(79,0,0),'object_085_g00_p00':(85,0,0)}; patched=anime; rows=[]
    for name,path in SELECTED.items():
        tex=texmap[keys[name]]; before=patched; patched,meta=quantized_patch(patched,tex,path); rows.append({'target':name,'object':tex.object_index,'group':tex.group_index,'page':tex.page_index,'source':path.name,'changed_bytes':sum(a!=b for a,b in zip(before,patched)),**meta})
    if patched==anime: raise ValueError('anime00 변경 없음')
    final=bytearray(start); final[ar.data_offset:ar.end_offset]=patched; header=decompress_buffer(lzs)[1]; new=compress_buffer_runtime_safe(bytes(final),lzs[:4],int(header['flag']));
    if decompress_buffer(new)[0]!=bytes(final): raise ValueError('LZS roundtrip failed')
    sr=next(r for r in system_records(system) if r['name'].casefold()=='start.lzs'); nextoff=system_records(system)[sr['index']+1]['data_offset']; cap=nextoff-sr['data_offset'];
    if len(new)>cap: raise ValueError('START.LZS overflow')
    fs=bytearray(system); fs[sr['data_offset']:nextoff]=bytes(cap); fs[sr['data_offset']:sr['data_offset']+len(new)]=new; struct.pack_into('<I',fs,0x10+sr['index']*0x2C+0x24,len(new))
    OUT.mkdir(parents=True,exist_ok=True); REPORT.mkdir(parents=True,exist_ok=True); (OUT/'SYSTEM.DAT').write_bytes(fs); (OUT/'start.dat').write_bytes(final); (OUT/'start.lzs').write_bytes(new); (OUT/'anime00.dat').write_bytes(patched)
    with (REPORT/'selection.csv').open('w',encoding='utf-8-sig',newline='') as f: w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    report={'format':'prinny1_v7_15_22_internal_texture_test_v1','created_at':datetime.now().astimezone().isoformat(timespec='seconds'),'base_resources':str(BASE),'selection':rows,'alternates_held':{k:[p.name for p in v] for k,v in ALTERNATES.items()},'verified':{'internal_anime_targets':3,'palette_repacked_to_16':True,'anime_size_preserved':len(patched)==len(anime),'lzs_roundtrip':True,'start_lzs_margin':cap-len(new)},'status':'resources_sealed_iso_build_pending'}; (REPORT/'all_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print('anime00 targets:',len(rows),'LZS:',len(new), '/',cap)
if __name__=='__main__': raise SystemExit(main())
