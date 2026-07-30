#!/usr/bin/env python3

import json
from pathlib import Path


NSF_PATH = Path(
    "workspace/unpack/SCRIPT_fixed/enemy.nsf"
)

ANALYSIS_PATH = Path(
    "workspace/analysis/enemy.nsf.json"
)

ANCHOR = bytes.fromhex(
    "00 A1 "
    "0B 43 "
    "1E 00 "
    "32 00 "
    "00 43 "
    "22 00 "
    "32 0B "
    "9F 0B"
)

CODE_COUNT = 23

FONT_TABLE = {
    0x0B43: "ウ",
    0x1E00: "ワ",
    0x3200: "サ",
    0x0043: "の",
    0x2200: "命",
    0x320B: "が",
    0x9F0B: "け",
    0x0D01: "ス",
    0x0023: "イ",
    0x0501: "ー",
    0x00A2: "ツ",
    0x0B0C: "ッ",
    0x0028: "か",
    0x0401: "！",
    0x00A4: "？",
}


def decode_code(code: int) -> str:
    character = FONT_TABLE.get(code)

    if character is not None:
        return character

    return f"[{code:04X}]"


def main() -> int:
    if not NSF_PATH.is_file():
        print("ERROR: NSF 파일이 없습니다:", NSF_PATH)
        return 1

    if not ANALYSIS_PATH.is_file():
        print("ERROR: 분석 JSON이 없습니다:", ANALYSIS_PATH)
        return 1

    with ANALYSIS_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        analysis = json.load(file)

    data = NSF_PATH.read_bytes()

    blob_offset = analysis["layout"]["blob_offset"]
    blob_size = analysis["layout"]["blob_size"]

    blob = data[
        blob_offset:
        blob_offset + blob_size
    ]

    anchor_offset = blob.find(ANCHOR)

    if anchor_offset < 0:
        print("ERROR: 대사 앵커를 찾지 못했습니다.")
        return 1

    byte_length = CODE_COUNT * 2

    raw = blob[
        anchor_offset:
        anchor_offset + byte_length
    ]

    if len(raw) != byte_length:
        print("ERROR: 앵커 뒤 데이터가 부족합니다.")
        return 1

    codes = [
        int.from_bytes(
            raw[position:position + 2],
            byteorder="big",
            signed=False,
        )
        for position in range(0, len(raw), 2)
    ]

    decoded = "".join(
        decode_code(code)
        for code in codes
    )

    print("FILE:", NSF_PATH.name)
    print("BYTE ORDER: big-endian")
    print("BLOB OFFSET:", f"0x{blob_offset:X}")
    print("ANCHOR IN BLOB:", f"0x{anchor_offset:X}")
    print(
        "ANCHOR IN FILE:",
        f"0x{blob_offset + anchor_offset:X}",
    )

    print()
    print("CODES")
    print("-----")
    print(
        " ".join(
            f"{code:04X}"
            for code in codes
        )
    )

    print()
    print("DECODED")
    print("-------")
    print(decoded)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
