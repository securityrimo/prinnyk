#!/usr/bin/env python3
from __future__ import annotations

import json
import struct
from pathlib import Path


START_DIR = Path(
    "workspace/unpack/START_runtime"
)

FNT_PATH = START_DIR / "font.fnt"
TXP_PATH = START_DIR / "font.txp"
JIS2UCS_PATH = START_DIR / "jis2ucs.bin"
UCS2JIS_PATH = START_DIR / "ucs2jis.bin"

REPORT_PATH = Path(
    "workspace/reports/independent_hangul_probe.json"
)

TARGET_UNICODE = 0xAC00
TARGET_CHARACTER = "가"

KNOWN_CHARACTER = "の"
KNOWN_SJIS = bytes.fromhex("82 CC")
KNOWN_JIS = 0x244E
KNOWN_TABLE_INDEX = 0x01AB
KNOWN_GLYPH_INDEX = 0x011A

FNT_EXPECTED_COUNT = 11615
TXP_EXPECTED_WIDTH = 20
TXP_EXPECTED_HEIGHT = 32872
TXP_PIXEL_OFFSET = 0x50
GLYPH_HEIGHT = 14
BYTES_PER_GLYPH = 0x8C


def read_u16(
    data: bytes,
    offset: int,
) -> int:
    return struct.unpack_from(
        "<H",
        data,
        offset,
    )[0]


def jis_to_sjis(
    row: int,
    cell: int,
) -> bytes:
    if not (
        0x21 <= row <= 0x7E
        and 0x21 <= cell <= 0x7E
    ):
        raise ValueError(
            f"JIS 범위 오류: {row:02X}{cell:02X}"
        )

    row_index = row - 0x21
    lead = (row_index // 2) + 0x81

    if lead > 0x9F:
        lead += 0x40

    if row_index % 2 == 0:
        trail = cell + 0x1F

        if trail >= 0x7F:
            trail += 1
    else:
        trail = cell + 0x7E

    return bytes([lead, trail])


def jis_to_table_index(
    row: int,
    cell: int,
) -> int:
    # ASCII/반각문자 영역 100개 뒤에
    # 94×94 JIS 밀집 테이블이 이어지는 구조.
    return (
        100
        + (row - 0x21) * 94
        + (cell - 0x21)
    )


def decode_context(
    data: bytes,
    offset: int,
    radius: int = 32,
) -> dict[str, object]:
    start = max(0, offset - radius)
    end = min(
        len(data),
        offset + len(KNOWN_SJIS) + radius,
    )

    raw = data[start:end]

    return {
        "slice_start": start,
        "slice_end": end,
        "hex": raw.hex(" ").upper(),
        "shift_jis": raw.decode(
            "shift_jis",
            errors="replace",
        ),
    }


def find_all(
    data: bytes,
    needle: bytes,
) -> list[int]:
    offsets: list[int] = []
    position = 0

    while True:
        position = data.find(
            needle,
            position,
        )

        if position < 0:
            break

        offsets.append(position)
        position += 1

    return offsets


def scan_u16_offsets(
    data: bytes,
    value: int,
    limit: int,
) -> list[int]:
    encoded = struct.pack(
        "<H",
        value,
    )

    offsets: list[int] = []

    for offset in range(
        0,
        min(limit, len(data)) - 1,
    ):
        if data[
            offset:
            offset + 2
        ] == encoded:
            offsets.append(offset)

    return offsets


def candidate_rows() -> list[int]:
    # 표준 JIS의 후반 미할당 영역부터 조사한다.
    preferred = list(
        range(0x75, 0x7F)
    )

    remaining = [
        row
        for row in range(0x21, 0x7F)
        if row not in preferred
    ]

    return preferred + remaining


def main() -> int:
    required = [
        FNT_PATH,
        TXP_PATH,
        JIS2UCS_PATH,
        UCS2JIS_PATH,
    ]

    for path in required:
        if not path.is_file():
            raise FileNotFoundError(
                f"필수 파일 없음: {path}"
            )

    fnt = FNT_PATH.read_bytes()
    txp = TXP_PATH.read_bytes()
    jis2ucs = JIS2UCS_PATH.read_bytes()
    ucs2jis = UCS2JIS_PATH.read_bytes()

    fnt_count = read_u16(
        fnt,
        0,
    )

    if fnt_count != FNT_EXPECTED_COUNT:
        raise ValueError(
            "font.fnt 항목 수가 예상과 다릅니다: "
            f"{fnt_count}"
        )

    known_row = (
        KNOWN_JIS >> 8
    ) & 0xFF
    known_cell = (
        KNOWN_JIS
    ) & 0xFF

    calculated_sjis = jis_to_sjis(
        known_row,
        known_cell,
    )
    calculated_table_index = (
        jis_to_table_index(
            known_row,
            known_cell,
        )
    )

    known_glyph = read_u16(
        fnt,
        2 + calculated_table_index * 2,
    )

    if calculated_sjis != KNOWN_SJIS:
        raise ValueError(
            "JIS→Shift-JIS 계산 검증 실패: "
            f"{calculated_sjis.hex(' ')}"
        )

    if (
        calculated_table_index
        != KNOWN_TABLE_INDEX
    ):
        raise ValueError(
            "font.fnt 인덱스 계산 검증 실패: "
            f"0x{calculated_table_index:04X}"
        )

    if known_glyph != KNOWN_GLYPH_INDEX:
        raise ValueError(
            "の 글리프 검증 실패: "
            f"0x{known_glyph:04X}"
        )

    height_offsets = scan_u16_offsets(
        txp,
        TXP_EXPECTED_HEIGHT,
        TXP_PIXEL_OFFSET,
    )
    width_offsets = scan_u16_offsets(
        txp,
        TXP_EXPECTED_WIDTH,
        TXP_PIXEL_OFFSET,
    )

    expected_pixel_size = (
        TXP_EXPECTED_WIDTH
        * TXP_EXPECTED_HEIGHT
        // 2
    )

    if (
        len(txp) - TXP_PIXEL_OFFSET
        != expected_pixel_size
    ):
        raise ValueError(
            "TXP 픽셀 데이터 크기 검증 실패: "
            f"actual=0x{len(txp) - TXP_PIXEL_OFFSET:X}, "
            f"expected=0x{expected_pixel_size:X}"
        )

    target_ucs2jis = read_u16(
        ucs2jis,
        TARGET_UNICODE * 2,
    )

    candidates: list[dict[str, object]] = []

    for row in candidate_rows():
        for cell in range(0x21, 0x7F):
            jis = (
                row << 8
            ) | cell

            table_index = (
                jis_to_table_index(
                    row,
                    cell,
                )
            )

            if table_index >= fnt_count:
                continue

            unicode_value = read_u16(
                jis2ucs,
                jis * 2,
            )
            glyph_value = read_u16(
                fnt,
                2 + table_index * 2,
            )

            if unicode_value != 0:
                continue

            if glyph_value != 0:
                continue

            sjis = jis_to_sjis(
                row,
                cell,
            )

            candidates.append(
                {
                    "jis": jis,
                    "jis_hex": f"0x{jis:04X}",
                    "sjis_hex": (
                        sjis.hex(" ").upper()
                    ),
                    "sjis_bytes": list(sjis),
                    "table_index": table_index,
                    "table_index_hex": (
                        f"0x{table_index:04X}"
                    ),
                    "current_unicode": unicode_value,
                    "current_glyph": glyph_value,
                }
            )

            if len(candidates) >= 20:
                break

        if len(candidates) >= 20:
            break

    if not candidates:
        raise ValueError(
            "미할당 독립 코드 후보를 찾지 못했습니다."
        )

    selected = candidates[0]
    selected_bytes = bytes(
        selected["sjis_bytes"]
    )

    resource_names = [
        "Demo00.dat",
        "BaseTalk.dat",
        "PrinnyName.dat",
        "StageInfo00.dat",
        "Collection.dat",
        "Honor.dat",
        "LuckyDoll.dat",
        "LuckyItem.dat",
        "MusicShop.dat",
        "PictureBook.dat",
    ]

    occurrences: list[dict[str, object]] = []

    for name in resource_names:
        path = START_DIR / name

        if not path.is_file():
            continue

        data = path.read_bytes()
        offsets = find_all(
            data,
            KNOWN_SJIS,
        )

        item: dict[str, object] = {
            "path": str(path),
            "size": len(data),
            "no_count": len(offsets),
            "selected_code_count": len(
                find_all(
                    data,
                    selected_bytes,
                )
            ),
            "contexts": [],
        }

        for offset in offsets[:20]:
            context = decode_context(
                data,
                offset,
            )
            context["offset"] = offset
            context["offset_hex"] = (
                f"0x{offset:X}"
            )

            item["contexts"].append(
                context
            )

        occurrences.append(item)

    report = {
        "format": (
            "prinny_independent_hangul_probe_v1"
        ),
        "known_mapping": {
            "character": KNOWN_CHARACTER,
            "sjis_hex": (
                KNOWN_SJIS.hex(" ").upper()
            ),
            "jis_hex": (
                f"0x{KNOWN_JIS:04X}"
            ),
            "table_index_hex": (
                f"0x{calculated_table_index:04X}"
            ),
            "glyph_index_hex": (
                f"0x{known_glyph:04X}"
            ),
            "verified": True,
        },
        "txp": {
            "size": len(txp),
            "size_hex": f"0x{len(txp):X}",
            "pixel_offset": TXP_PIXEL_OFFSET,
            "pixel_offset_hex": (
                f"0x{TXP_PIXEL_OFFSET:X}"
            ),
            "width": TXP_EXPECTED_WIDTH,
            "height": TXP_EXPECTED_HEIGHT,
            "width_offsets": width_offsets,
            "width_offsets_hex": [
                f"0x{offset:X}"
                for offset in width_offsets
            ],
            "height_offsets": height_offsets,
            "height_offsets_hex": [
                f"0x{offset:X}"
                for offset in height_offsets
            ],
            "new_height_one_glyph": (
                TXP_EXPECTED_HEIGHT
                + GLYPH_HEIGHT
            ),
            "appended_bytes": (
                BYTES_PER_GLYPH
            ),
        },
        "target": {
            "character": TARGET_CHARACTER,
            "unicode": TARGET_UNICODE,
            "unicode_hex": (
                f"U+{TARGET_UNICODE:04X}"
            ),
            "current_ucs2jis": target_ucs2jis,
            "current_ucs2jis_hex": (
                f"0x{target_ucs2jis:04X}"
            ),
        },
        "selected_candidate": selected,
        "candidate_sample": candidates,
        "resource_occurrences": occurrences,
        "status": "pass",
    }

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("INDEPENDENT HANGUL PROBE")
    print("========================")
    print(
        "KNOWN MAPPING       : "
        f"{KNOWN_CHARACTER} "
        f"SJIS={KNOWN_SJIS.hex(' ').upper()} "
        f"JIS=0x{KNOWN_JIS:04X} "
        f"TABLE=0x{calculated_table_index:04X} "
        f"GLYPH=0x{known_glyph:04X}"
    )
    print()
    print(
        f"TXP SIZE            : "
        f"0x{len(txp):X}"
    )
    print(
        "WIDTH FIELD OFFSETS : "
        + ", ".join(
            f"0x{offset:X}"
            for offset in width_offsets
        )
    )
    print(
        "HEIGHT FIELD OFFSETS: "
        + ", ".join(
            f"0x{offset:X}"
            for offset in height_offsets
        )
    )
    print(
        f"CURRENT HEIGHT      : "
        f"{TXP_EXPECTED_HEIGHT}"
    )
    print(
        f"NEW HEIGHT          : "
        f"{TXP_EXPECTED_HEIGHT + GLYPH_HEIGHT}"
    )
    print()
    print(
        f"TARGET              : "
        f"{TARGET_CHARACTER} "
        f"U+{TARGET_UNICODE:04X}"
    )
    print(
        f"CURRENT UCS2JIS     : "
        f"0x{target_ucs2jis:04X}"
    )
    print()
    print(
        f"SELECTED JIS        : "
        f"{selected['jis_hex']}"
    )
    print(
        f"SELECTED SJIS       : "
        f"{selected['sjis_hex']}"
    )
    print(
        f"SELECTED TABLE      : "
        f"{selected['table_index_hex']}"
    )
    print(
        f"CURRENT UNICODE MAP : "
        f"0x{selected['current_unicode']:04X}"
    )
    print(
        f"CURRENT GLYPH MAP   : "
        f"0x{selected['current_glyph']:04X}"
    )
    print()
    print("RESOURCE OCCURRENCES")
    print("--------------------")

    for item in occurrences:
        print(
            f"{Path(item['path']).name:20s} "
            f"の={item['no_count']:4d} "
            f"CANDIDATE={item['selected_code_count']:4d}"
        )

        for context in item["contexts"][:5]:
            rendered = str(
                context["shift_jis"]
            ).replace(
                "\n",
                "\\n",
            ).replace(
                "\r",
                "\\r",
            )

            print(
                f"  {context['offset_hex']:>10s} "
                f"{rendered!r}"
            )

    print()
    print("REPORT:", REPORT_PATH)
    print("STATUS: PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
