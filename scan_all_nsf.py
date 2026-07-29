"""
scan_all_nsf.py — 언패킹된 모든 .nsf 파일을 훑어서, 실제 SJIS 대사 텍스트가
얼마나 들어있는지 순위를 매긴다. G9system.nsf가 순수 이벤트 스크립트(바이너리
오프코드)로 확인됐으니, 어떤 파일이 진짜 대사를 담고 있는지 한 번에 찾기 위함.
"""

import sys
from pathlib import Path
from core.nsf import NSFParser


def _is_sjis_lead(b):
    return (0x81 <= b <= 0x9F) or (0xE0 <= b <= 0xEF)


def _is_sjis_trail(b):
    return (0x40 <= b <= 0x7E) or (0x80 <= b <= 0xFC)


def sjis_char_count(raw: bytes) -> int:
    """raw 바이트열 안에서 유효한 SJIS 2바이트 문자가 몇 개나 디코딩되는지 센다."""
    count = 0
    i, n = 0, len(raw)
    while i < n - 1:
        if _is_sjis_lead(raw[i]) and _is_sjis_trail(raw[i + 1]):
            count += 1
            i += 2
        else:
            i += 1
    return count


def scan_folder(folder="workspace/unpack/SCRIPT"):
    folder = Path(folder)
    nsf_files = sorted(folder.glob("*.nsf"))

    if not nsf_files:
        print(f"⚠️ {folder} 안에 .nsf 파일이 없습니다.")
        return []

    report = []
    for f in nsf_files:
        try:
            parser = NSFParser(f)
            entries = parser.extract_strings(verbose=False, raw_mode=True)
        except Exception as ex:
            print(f"❌ {f.name}: 파싱 실패 ({ex})")
            continue

        if not entries and f.stat().st_size > 0:
            # 구조 가정이 안 맞아서 parse()가 빈 결과를 반환한 경우
            report.append({
                "file": f.name, "entries": 0, "total_bytes": 0,
                "sjis_chars": 0, "sjis_ratio": 0.0, "structure_ok": False,
            })
            continue

        total_bytes = sum(e["length"] for e in entries)
        total_sjis_chars = sum(sjis_char_count(bytes.fromhex(e["hex"])) for e in entries)
        sjis_byte_ratio = (total_sjis_chars * 2 / total_bytes) if total_bytes else 0

        report.append({
            "file": f.name,
            "entries": len(entries),
            "total_bytes": total_bytes,
            "sjis_chars": total_sjis_chars,
            "sjis_ratio": round(sjis_byte_ratio, 3),
            "structure_ok": True,
        })

    report.sort(key=lambda r: -r["sjis_ratio"])

    print(f"{'파일':<20} {'엔트리':>6} {'총바이트':>8} {'SJIS문자수':>10} {'SJIS비율':>8}")
    for r in report:
        if not r["structure_ok"]:
            print(f"{r['file']:<20}   ❌ 구조 불일치 (header 해석이 이 파일엔 안 맞음 — 별도 분석 필요)")
            continue
        tag = "  ⭐ 대사 후보" if r["sjis_ratio"] >= 0.15 else ""
        print(f"{r['file']:<20} {r['entries']:>6} {r['total_bytes']:>8} "
              f"{r['sjis_chars']:>10} {r['sjis_ratio']:>8.1%}{tag}")

    print("\n💡 SJIS비율이 높은 파일부터 실제 대사일 확률이 높습니다.")
    print("   전부 0%에 가깝다면, 이 SCRIPT.DAT 안의 nsf들은 전부 로직/이벤트")
    print("   스크립트고, 실제 화면에 뜨는 텍스트는 다른 컨테이너(다른 .DAT 파일)에")
    print("   있을 가능성을 봐야 합니다 — inventory_all_files()로 다시 후보를 넓혀보세요.")
    return report


def preview_text_entries(nsf_path, min_sjis_chars=1, limit=20):
    """SJIS 문자가 실제로 포함된 엔트리만 골라서 디코딩된 텍스트를 보여준다.
    (진짜 대사 후보를 눈으로 직접 확인하는 용도)"""
    parser = NSFParser(nsf_path)
    entries = parser.extract_strings(verbose=False, raw_mode=True)

    hits = []
    for e in entries:
        raw = bytes.fromhex(e["hex"])
        n = sjis_char_count(raw)
        if n >= min_sjis_chars:
            hits.append((n, e))

    hits.sort(key=lambda x: -x[0])
    print(f"{nsf_path}: SJIS 포함 엔트리 {len(hits)}개 (상위 {min(limit, len(hits))}개 표시)")
    for n, e in hits[:limit]:
        print(f"  [{e['index']}] @0x{e['offset']:X} SJIS문자{n}개")
        print(f"       hex : {e['hex']}")
        print(f"       text: {e['text']!r}")
    return hits


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "workspace/unpack/SCRIPT"
    scan_folder(folder)
