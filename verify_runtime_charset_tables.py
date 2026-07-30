#!/usr/bin/env python3

from pathlib import Path


JIS2UCS_PATH = Path(
    "workspace/unpack/START_runtime/jis2ucs.bin"
)

UCS2JIS_PATH = Path(
    "workspace/unpack/START_runtime/ucs2jis.bin"
)

REPORT_PATH = Path(
    "workspace/reports/runtime_charset_verify.txt"
)

KNOWN = [
    ("の", 0x244E),
    ("ウ", 0x2526),
    ("ワ", 0x256F),
    ("サ", 0x2535),
    ("命", 0x4C3F),
]


def lookup_u16_le(
    data: bytes,
    index: int,
) -> int | None:
    offset = index * 2

    if offset < 0 or offset + 2 > len(data):
        return None

    return int.from_bytes(
        data[offset:offset + 2],
        byteorder="little",
    )


def format_value(
    value: int | None,
) -> str:
    if value is None:
        return "OUT-OF-RANGE"

    return f"0x{value:04X}"


def main() -> int:
    jis2ucs = JIS2UCS_PATH.read_bytes()
    ucs2jis = UCS2JIS_PATH.read_bytes()

    lines = []

    lines.append(
        "RUNTIME CHARSET TABLE VERIFICATION"
    )
    lines.append(
        "=================================="
    )
    lines.append(
        f"JIS2UCS: {JIS2UCS_PATH}"
    )
    lines.append(
        f"  SIZE : 0x{len(jis2ucs):X}"
    )
    lines.append(
        f"UCS2JIS: {UCS2JIS_PATH}"
    )
    lines.append(
        f"  SIZE : 0x{len(ucs2jis):X}"
    )
    lines.append("")

    jis2ucs_matches = 0
    ucs2jis_matches = 0

    for character, jis_code in KNOWN:
        unicode_code = ord(character)

        decoded_unicode = lookup_u16_le(
            jis2ucs,
            jis_code,
        )

        encoded_jis = lookup_u16_le(
            ucs2jis,
            unicode_code,
        )

        decode_ok = (
            decoded_unicode == unicode_code
        )

        encode_ok = (
            encoded_jis == jis_code
        )

        jis2ucs_matches += int(decode_ok)
        ucs2jis_matches += int(encode_ok)

        lines.append(
            f"{character} "
            f"JIS=0x{jis_code:04X} "
            f"UNICODE=U+{unicode_code:04X}"
        )

        lines.append(
            "  JIS2UCS"
            f"[0x{jis_code:04X}]"
            f" = U+"
            f"{decoded_unicode:04X}"
            if decoded_unicode is not None
            else
            "  JIS2UCS = OUT-OF-RANGE"
        )

        lines[-1] += (
            "  MATCH"
            if decode_ok
            else "  MISMATCH"
        )

        lines.append(
            "  UCS2JIS"
            f"[U+{unicode_code:04X}]"
            f" = {format_value(encoded_jis)}"
            f"{'  MATCH' if encode_ok else '  MISMATCH'}"
        )

        lines.append("")

    lines.append("RESULT")
    lines.append("======")
    lines.append(
        f"JIS → Unicode: "
        f"{jis2ucs_matches}/{len(KNOWN)}"
    )
    lines.append(
        f"Unicode → JIS: "
        f"{ucs2jis_matches}/{len(KNOWN)}"
    )

    if (
        jis2ucs_matches == len(KNOWN)
        and ucs2jis_matches == len(KNOWN)
    ):
        lines.append("")
        lines.append(
            "CONFIRMED: 양방향 변환표가 정상입니다."
        )

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = "\n".join(lines) + "\n"

    REPORT_PATH.write_text(
        output,
        encoding="utf-8",
    )

    print(output, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
