#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
P2 = Path('/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd/PSP_Localization_Work/prinny2')
RUNTIME = P2 / 'workspace/game2_start_runtime'
CATALOG = P2 / 'reports/game2_translation_catalog/catalog.json'
OUT = ROOT / 'workspace/reports/prinny2_font_fnt3_analysis'

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def ranges(values: list[int]) -> list[tuple[int, int]]:
    if not values: return []
    out=[]; start=prev=values[0]
    for value in values[1:]:
        if value != prev + 1:
            out.append((start, prev)); start=value
        prev=value
    out.append((start, prev)); return out

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    font = RUNTIME / 'Font.fnt3'; data = font.read_bytes()
    header, body = data[:16], data[16:]
    if len(body) != 0x10000 * 3: raise ValueError('Font.fnt3 body is not 65536 x 3 bytes')
    entries=[body[i*3:(i+1)*3] for i in range(0x10000)]
    mapped=[i for i,e in enumerate(entries) if e != b'\0\0\0']
    blocks={'ascii':(0x20,0x7e),'hiragana':(0x3040,0x309f),'katakana':(0x30a0,0x30ff),'cjk':(0x4e00,0x9fff),'hangul_syllables':(0xac00,0xd7a3),'hangul_jamo':(0x1100,0x11ff)}
    block_counts={k:sum(entries[i]!=b'\0\0\0' for i in range(a,b+1)) for k,(a,b) in blocks.items()}
    glyph_indices=[int.from_bytes(entries[i][:2],'little') for i in mapped]
    flag_values=Counter(entries[i][2] for i in mapped)
    with (OUT/'font_fnt3_nonzero_ranges.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f); w.writerow(['start_hex','end_hex','start_char','end_char','count'])
        for a,b in ranges(mapped): w.writerow([f'U+{a:04X}',f'U+{b:04X}',chr(a),chr(b),b-a+1])
    samples=[]
    for cp in [0x20,0x21,0x41,0x61,0x3042,0x30a2,0x4e00,0xac00,0xd7a3]:
        raw=entries[cp]; samples.append({'codepoint':f'U+{cp:04X}','character':chr(cp),'raw_hex':raw.hex(),'value_le24':int.from_bytes(raw,'little'),'mapped':raw!=b'\0\0\0'})
    (OUT/'font_fnt3_samples.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    catalog=json.loads(CATALOG.read_text(encoding='utf-8'))
    excluded={'effect00.GM3','Character00.dat'}
    rows=[e for e in catalog['entries'] if e['resource'] not in excluded and e['confidence'] in {'high','medium'} and int(e.get('japanese_count',0))>0]
    fields=['id','resource','offset_hex','byte_length','source','source_hex','confidence','translation','status','notes']
    with (OUT/'translation_required.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for e in rows:
            w.writerow({'id':e['id'],'resource':e['resource'],'offset_hex':f"0x{int(e['offset']):X}",'byte_length':e['byte_length'],'source':e['source'],'source_hex':e['source_hex'],'confidence':e['confidence'],'translation':'','status':'untranslated','notes':''})
    counts=Counter(e['resource'] for e in rows)
    report={'format':'prinny2_font_fnt3_analysis_v1','inputs':{'font':str(font),'font_size':len(data),'font_sha256':sha256(font),'catalog':str(CATALOG),'catalog_sha1':catalog['catalog_sha1'],'jis2ucs_sha256':sha256(RUNTIME/'jis2ucs.bin'),'ucs2jis_sha256':sha256(RUNTIME/'ucs2jis.bin')},'fnt3':{'header_hex':header.hex(),'header_observed_width':int.from_bytes(header[0:2],'big'),'header_observed_height':header[2],'body_size':len(body),'entry_size':3,'entry_count':len(entries),'mapped_entries':len(mapped),'zero_entries':len(entries)-len(mapped),'unique_entry_values':len(set(entries)),'glyph_index_min':min(glyph_indices),'glyph_index_max':max(glyph_indices),'glyph_indices_unique':len(set(glyph_indices)),'glyph_indices_contiguous':set(glyph_indices)==set(range(max(glyph_indices)+1)),'third_byte_counts':{f'0x{k:02X}':v for k,v in sorted(flag_values.items())},'block_mapped_counts':block_counts,'interpretation':'16-byte header followed by one 3-byte record per UCS-2 code point. First two bytes are a contiguous little-endian glyph index 0..2488; third byte is constant 0x8D for every mapped entry. Bitmap backing store still requires executable/resource-reference validation.'},'translation_extraction':{'rows':len(rows),'excluded_resources':sorted(excluded),'reason':'effect00.GM3 and Character00.dat contain high false-positive risk under generic scanning','by_resource':dict(sorted(counts.items())),'output':str(OUT/'translation_required.csv')},'status':'analysis_complete_bitmap_backing_store_pending'}
    (OUT/'all_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'summary.txt').write_text(f"Font.fnt3: {len(entries)} x 3-byte UCS-2 records\nMapped: {len(mapped)}\nHangul syllables mapped: {block_counts['hangul_syllables']}\nTranslation rows: {len(rows)}\n",encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == '__main__': main()
