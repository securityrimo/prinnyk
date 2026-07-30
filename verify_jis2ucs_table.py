#!/usr/bin/env python3

from pathlib import Path


TABLE_PATH = Path(
    "workspace/unpack/START_runtime/jis2ucs.bin"
)

KNOWN = [
    ("の", 0x244E),
    ("ウ", 0x2526),
    ("ワ", 0x256F),
    ("サ", 0x2535),
    ("命", 0x4C3F),
]


def main() -> int:
    data = TABLE_PATH.read_bytes()

    print("JIS2UCS TABLE VERIFICATION")
    print("==========================")
    print("FILE :", TABLE_PATH)
    print("SIZE :", len(data))
    print()

    matched_little = 0
    matched_big = 0

    for character, jis_code in KNOWN:
        offset = jis_code * 2
        expected = ord(character)

        if offset + 2 > len(data):
            print(
                f"{character} "
                f"JIS=0x{jis_code:04X} "
                f"OFFSET=0x{offset:X} "
                f"OUT OF RANGE"
            )
            continue

        raw = data[offset:offset + 2]

        little = int.from_bytes(
            raw,
            byteorder="little",
        )

        big = int.from_bytes(
            raw,
            byteorder="big",
        )

        little_ok = little == expected
        big_ok = big == expected

        matched_little += int(little_ok)
        matched_big += int(big_ok)

        print(
            f"{character}  "
            f"JIS=0x{jis_code:04X}  "
            f"OFFSET=0x{offset:05X}  "
            f"RAW={raw.hex(' ').upper()}  "
            f"LE=U+{little:04X}"
            f"{' MATCH' if little_ok else ''}  "
            f"BE=U+{big:04X}"
            f"{' MATCH' if big_ok else ''}"
        )

    print()
    print("RESULT")
    print("======")
    print(
        f"LITTLE-ENDIAN: "
        f"{matched_little}/{len(KNOWN)}"
    )
    print(
        f"BIG-ENDIAN   : "
        f"{matched_big}/{len(KNOWN)}"
    )

    if matched_little == len(KNOWN):
        print()
        print(
            "CONFIRMED: "
            "jis2ucs.bin[JIS] = UTF-16LE Unicode"
        )
    elif matched_big == len(KNOWN):
        print()
        print(
            "CONFIRMED: "
            "jis2ucs.bin[JIS] = UTF-16BE Unicode"
        )
    else:
        print()
        print(
            "DIRECT JIS INDEX DID NOT FULLY MATCH"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
