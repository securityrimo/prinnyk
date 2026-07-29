"""
core/nispack.py — NISPACK 컨테이너 파서 (앵커 기반, 정렬/스트라이드 추측 없음)
--------------------------------------------------------------------------
기존 방식의 문제:
    엔트리를 앞에서부터 순서대로 훑으면서 pos += 0x30 (또는 이름 끝 기준 정렬)
    으로 "다음 엔트리 위치"를 추측했다. 이름 길이가 다르면 정렬 규칙이 깨지고,
    한 번 어긋나면 그 뒤 모든 엔트리가 연쇄적으로 깨진다 (지금까지의 로그가
    정확히 이 증상: 엔트리 0/1은 우연히 맞고, 2부터 깨짐).

이 버전의 접근:
    "다음 엔트리가 어디 있는지"를 계산하지 않는다. 대신 파일명 문자열
    (".nsf" 등으로 끝나는 읽을 수 있는 ASCII + NUL) 자체를 정규식으로 파일
    전체에서 찾아내고, 각 이름의 위치에서 '고정 10바이트'만큼 거꾸로 가서
    offset/size/flag를 읽는다. 이러면 엔트리 사이의 패딩/정렬을 몰라도 된다 —
    이름이 어디 있든, 그 이름의 헤더는 항상 이름 시작 지점 - 10에 있기 때문.

확인된 구조 (엔트리 0, 1에서 실측):
    +0x00  offset : uint32 LE   (파일 전체 기준 절대 오프셋)
    +0x04  size   : uint32 LE
    +0x08  flag   : uint16 LE   (지금까지 관측된 값은 항상 0x03E8 = 1000 —
                                 의미는 아직 불명, 아마 고정 상수/블록크기 필드)
    +0x0A  name   : NUL로 끝나는 ASCII 문자열
"""

import re
import struct
from pathlib import Path

HEADER_LEN = 10  # offset(4) + size(4) + flag(2)

# 확인된 확장자는 .nsf뿐이지만, 다른 NISPACK 아카이브에 다른 확장자가 있을 수
# 있으니 일반적인 "짧은 확장자"까지 넓게 잡아둔다. 오탐이 있으면 아래
# scan_nispack()의 sanity check(오버플로/개수불일치)에서 걸러진다.
NAME_PATTERN = re.compile(rb"[ -~]{2,40}\.[A-Za-z0-9]{2,4}\x00")


class NISPack:

    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()

    # --------------------------------------------------------------
    def parse(self, verbose=True):
        if self.data[:7] != b"NISPACK":
            raise ValueError(f"NISPACK 매직이 아닙니다: {self.data[:7]!r}")

        declared_count = struct.unpack("<I", self.data[12:16])[0]
        if verbose:
            print(f"NISPACK 헤더상 파일 개수: {declared_count}")

        entries = []
        seen_headers = set()  # 같은 헤더 위치를 중복으로 잡지 않기 위함

        for m in NAME_PATTERN.finditer(self.data):
            name_start = m.start()
            header_start = name_start - HEADER_LEN
            if header_start < 0x30:  # 헤더 테이블 시작(0x30) 이전이면 이름 후보가 아님
                continue
            if header_start in seen_headers:
                continue
            seen_headers.add(header_start)

            offset, size, flag = struct.unpack(
                "<IIH", self.data[header_start:header_start + HEADER_LEN]
            )
            name = m.group()[:-1].decode("ascii", errors="ignore")  # 끝 NUL 제거

            # sanity check: offset/size가 파일 범위를 벗어나면 이 이름은
            # 진짜 엔트리가 아니라 데이터 안에서 우연히 매칭된 문자열일 확률이 높음
            plausible = (offset + size) <= len(self.data) and size > 0

            entries.append({
                "name": name,
                "offset": offset,
                "size": size,
                "flag": flag,
                "header_at": header_start,
                "plausible": plausible,
            })

        # 파일 안에 나온 순서(= header_at 오름차순)로 정렬
        entries.sort(key=lambda e: e["header_at"])

        if verbose:
            for i, e in enumerate(entries):
                tag = "" if e["plausible"] else "  ⚠️ 범위초과(오탐 의심)"
                print(f"[{i}] {e['name']:<20} offset={e['offset']:X} "
                      f"size={e['size']:X} flag={e['flag']:X} "
                      f"@header=0x{e['header_at']:X}{tag}")

            plausible_count = sum(1 for e in entries if e["plausible"])
            if plausible_count == declared_count:
                print(f"✅ 헤더 개수({declared_count})와 정확히 일치합니다. 구조 확정으로 봐도 됩니다.")
            else:
                print(f"⚠️ 헤더 개수({declared_count})와 실제 그럴듯한 엔트리 수"
                      f"({plausible_count})가 다릅니다.")
                print("   ↳ NAME_PATTERN이 이름을 놓쳤거나(확장자가 .nsf가 아닌 다른 것),")
                print("     혹은 반대로 데이터 안의 우연한 문자열을 이름으로 잘못 잡았을 수 있습니다.")

        return entries

    # --------------------------------------------------------------
    def extract(self, output, only_plausible=True):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)

        for e in self.parse(verbose=False):
            if not e["name"]:
                continue
            if only_plausible and not e["plausible"]:
                print(f"[SKIP] {e['name']} - 범위초과/오탐 의심이라 건너뜀 "
                      f"(강제로 뽑으려면 only_plausible=False)")
                continue

            start, end = e["offset"], e["offset"] + e["size"]
            if end > len(self.data):
                print(f"[SKIP] {e['name']} overflow (offset={start:X}, size={e['size']:X}, "
                      f"파일크기={len(self.data):X})")
                continue

            outfile = output / e["name"]
            outfile.write_bytes(self.data[start:end])
            print(f"EXTRACT {e['name']} {e['size']} bytes -> {outfile}")


    # --------------------------------------------------------------
    def debug_dump_near(self, keyword: bytes, context=24):
        """keyword가 파일 어디에 나오는지 전부 찾아서 앞뒤 context바이트를
        hex+ascii로 보여준다. 이름 인식이 깨지는 특정 엔트리를 눈으로 직접
        확인할 때 쓴다 (예: b"effect")."""
        positions = [m.start() for m in re.finditer(re.escape(keyword), self.data)]
        if not positions:
            print(f"'{keyword}'를 찾지 못했습니다.")
            return []

        for pos in positions:
            start = max(0, pos - context)
            end = min(len(self.data), pos + len(keyword) + context)
            chunk = self.data[start:end]
            print(f"--- 위치 0x{pos:X} 근처 (0x{start:X}~0x{end:X}) ---")
            print("hex  :", chunk.hex(" "))
            print("ascii:", "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk))
        return positions


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("사용법: python3 nispack.py <SCRIPT.DAT 경로> [출력폴더]")
        sys.exit(1)

    pack = NISPack(sys.argv[1])
    pack.parse(verbose=True)

    if len(sys.argv) >= 3:
        pack.extract(sys.argv[2])
