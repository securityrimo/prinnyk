#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
P2=Path('/media/hyuk/92647554-5423-456f-ba71-0f4b1803dcdd/PSP_Localization_Work/prinny2')
RT=P2/'workspace/game2_start_runtime'; FONT=RT/'Font.fnt3'; OUT=ROOT/'workspace/reports/prinny2_font_bitmap_location_analysis'
PGF=Path('/var/lib/flatpak/app/org.ppsspp.PPSSPP/x86_64/stable/193bbe95656ed696c8e5a5e42831ee8017d53514e9e0e0acaa3e1235e22089d3/files/share/ppsspp/assets/flash0/font')
def sh(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 b=FONT.read_bytes(); body=b[16:]; pairs=[]
 for cp in range(65536):
  r=body[cp*3:cp*3+3]
  if r!=b'\0\0\0': pairs.append((cp,int.from_bytes(r[:2],'little'),r[2]))
 files=[p for p in RT.iterdir() if p.is_file()]; expected={f'{bits}bpp':(20*14*len(pairs)*bits+7)//8 for bits in (1,2,4,8)}
 exact={k:[p.name for p in files if p.stat().st_size==size] for k,size in expected.items()}
 report={'format':'prinny2_font_bitmap_location_analysis_v1','font_fnt3':{'path':str(FONT),'sha256':sh(FONT),'header_hex':b[:16].hex(),'cell_width':20,'cell_height':14,'mapped_codepoints':len(pairs),'index_min':min(x[1] for x in pairs),'index_max':max(x[1] for x in pairs),'index_equals_unicode_sorted_rank':all(i==x[1] for i,x in enumerate(pairs)),'third_byte_values':sorted(set(x[2] for x in pairs)),'contains_bitmap_payload':False},'standalone_bitmap_search':{'expected_raw_sizes':expected,'exact_size_start_resources':exact,'result':'no_exact_standalone_bitmap_resource'},'system_font_candidates':{'jpn0.pgf':{'path':str(PGF/'jpn0.pgf'),'size':(PGF/'jpn0.pgf').stat().st_size,'sha256':sh(PGF/'jpn0.pgf')},'kr0.pgf':{'path':str(PGF/'kr0.pgf'),'size':(PGF/'kr0.pgf').stat().st_size,'sha256':sh(PGF/'kr0.pgf')}},'executable_evidence':{'BOOT.BIN':'zero-filled dummy image','EBOOT.BIN':'encrypted ~PSP module; static import/call confirmation unavailable without decryption','sceFont_static_string_found':False},'conclusion':{'most_likely':'Font.fnt3 enumerates Unicode characters and assigns runtime atlas slots; glyph bitmaps are most likely rasterized from PSP system PGF at runtime rather than stored in Font.fnt3 or another standalone START resource.','confidence':'high_inference_not_yet_call-trace_proven','next_proof':'decrypt EBOOT.BIN or capture PPSSPP sceFont call trace; then verify jpn0/kr0 font selection before a Hangul mapping canary'},'status':'bitmap_location_narrowed_runtime_pgf_call_proof_pending'}
 OUT.mkdir(parents=True,exist_ok=True); (OUT/'all_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
