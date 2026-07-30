#!/usr/bin/env python3

import probe_code_lookup_tables as probe


# 대사에서 확인된 코드 → 실제 font.fnt 글리프 인덱스
probe.KNOWN = [
    ("の", 0x0043, 0x00D0),
    ("ウ", 0x0B43, 0x0118),
    ("ワ", 0x1E00, 0x0161),
    ("サ", 0x3200, 0x0127),
    ("命", 0x2200, 0x072E),
]


if __name__ == "__main__":
    raise SystemExit(probe.main())
