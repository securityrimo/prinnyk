#!/usr/bin/env python3

import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_MAP_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

FONT_TEXTURE_PATH = Path(
    "workspace/unpack/START_runtime/font.txp"
)

REPORT_PATH = Path(
    "workspace/reports/exact_font_runtime_map.txt"
)

IMAGE_PATH = Path(
    "workspace/reports/exact_font_runtime_map.png"
)

TXP_HEADER_SIZE = 0x10
GLYPH_HEIGHT = 14
SCALE = 8

CHARACTERS = [
    "の",
    "ウ",
    "サ",
    "ワ",
    "命",
]


def read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(
        "<H",
        data,
        offset,
    )[0]


def parse_font_table(data: bytes) -> list[int]:
    if len(data) < 2:
        raise ValueError(
            "font.fnt가 너무 작습니다."
        )

    count = read_u16(data, 0)

    expected_size = (
        2 + count * 2
    )

    if len(data) != expected_size:
        raise ValueError(
            "font.fnt 크기가 헤더와 다릅니다: "
            f"actual=0x{len(data):X}, "
            f"expected=0x{expected_size:X}"
        )

    return list(
        struct.unpack_from(
            f"<{count}H",
            data,
            2,
        )
    )


def lead_slot(lead: int) -> int:
    if 0x81 <= lead <= 0x9F:
        return lead - 0x81

    if 0xE0 <= lead <= 0xFC:
        return lead - 0xC1

    raise ValueError(
        f"지원하지 않는 리드 바이트: "
        f"0x{lead:02X}"
    )


def font_table_index(encoded: bytes) -> int:
    if len(encoded) == 1:
        value = encoded[0]

        if value < 0x20:
            raise ValueError(
                f"지원하지 않는 단일 바이트: "
                f"0x{value:02X}"
            )

        return value - 0x20

    if len(encoded) != 2:
        raise ValueError(
            "1바이트 또는 2바이트 "
            "Shift-JIS만 지원합니다."
        )

    lead = encoded[0]
    trail = encoded[1]

    if not 0x40 <= trail <= 0xFF:
        raise ValueError(
            f"지원하지 않는 트레일 바이트: "
            f"0x{trail:02X}"
        )

    return (
        0x5F
        + lead_slot(lead) * 0xC0
        + (trail - 0x40)
    )


def parse_txp(data: bytes) -> dict:
    if len(data) < TXP_HEADER_SIZE:
        raise ValueError(
            "font.txp가 너무 작습니다."
        )

    width = read_u16(data, 0x00)
    height = read_u16(data, 0x02)
    pixel_format = read_u16(data, 0x04)

    palette_width = read_u16(data, 0x08)
    palette_height = read_u16(data, 0x0A)

    palette_size = (
        palette_width
        * palette_height
        * 4
    )

    pixel_offset = (
        TXP_HEADER_SIZE
        + palette_size
    )

    if width <= 0 or height <= 0:
        raise ValueError(
            "TXP 폭 또는 높이가 잘못됐습니다."
        )

    bytes_per_row = (
        (width + 1) // 2
    )

    expected_pixel_size = (
        bytes_per_row * height
    )

    actual_pixel_size = (
        len(data) - pixel_offset
    )

    if actual_pixel_size != expected_pixel_size:
        raise ValueError(
            "TXP 픽셀 데이터 크기가 일치하지 않습니다: "
            f"actual=0x{actual_pixel_size:X}, "
            f"expected=0x{expected_pixel_size:X}"
        )

    if height % GLYPH_HEIGHT:
        raise ValueError(
            "TXP 높이가 글리프 높이 14의 "
            "배수가 아닙니다."
        )

    bytes_per_glyph = (
        bytes_per_row * GLYPH_HEIGHT
    )

    glyph_count = (
        height // GLYPH_HEIGHT
    )

    return {
        "width": width,
        "height": height,
        "pixel_format": pixel_format,
        "palette_width": palette_width,
        "palette_height": palette_height,
        "palette_size": palette_size,
        "pixel_offset": pixel_offset,
        "bytes_per_row": bytes_per_row,
        "bytes_per_glyph": bytes_per_glyph,
        "glyph_count": glyph_count,
    }


def decode_glyph(
    texture_data: bytes,
    txp: dict,
    glyph_index: int,
) -> Image.Image:
    if not 0 <= glyph_index < txp["glyph_count"]:
        raise ValueError(
            f"글리프 0x{glyph_index:04X}가 "
            f"범위 0x0000~"
            f"0x{txp['glyph_count'] - 1:04X}를 "
            "벗어납니다."
        )

    start = (
        txp["pixel_offset"]
        + glyph_index
        * txp["bytes_per_glyph"]
    )

    end = (
        start
        + txp["bytes_per_glyph"]
    )

    blob = texture_data[start:end]

    image = Image.new(
        "L",
        (
            txp["width"],
            GLYPH_HEIGHT,
        ),
        0,
    )

    pixels = image.load()

    for y in range(GLYPH_HEIGHT):
        row_offset = (
            y * txp["bytes_per_row"]
        )

        for byte_index in range(
            txp["bytes_per_row"]
        ):
            value = blob[
                row_offset + byte_index
            ]

            # 실제 TXP 픽셀 순서:
            # 왼쪽 = low nibble
            # 오른쪽 = high nibble
            left = value & 0x0F
            right = (
                value >> 4
            ) & 0x0F

            x = byte_index * 2

            if x < txp["width"]:
                pixels[x, y] = left * 17

            if x + 1 < txp["width"]:
                pixels[x + 1, y] = right * 17

    return image


def main() -> int:
    font_data = FONT_MAP_PATH.read_bytes()
    texture_data = FONT_TEXTURE_PATH.read_bytes()

    table = parse_font_table(
        font_data
    )

    txp = parse_txp(
        texture_data
    )

    mapped_max = max(table)

    invalid_values = [
        value
        for value in table
        if value >= txp["glyph_count"]
    ]

    lines = []

    lines.append(
        "EXACT FONT RUNTIME MAP"
    )
    lines.append(
        "======================"
    )
    lines.append(
        f"FONT TABLE ENTRIES : "
        f"0x{len(table):X} ({len(table)})"
    )
    lines.append(
        f"TABLE VALUE MAX    : "
        f"0x{mapped_max:04X}"
    )
    lines.append(
        f"INVALID MAP VALUES : "
        f"{len(invalid_values)}"
    )
    lines.append("")
    lines.append(
        f"TXP WIDTH          : "
        f"{txp['width']}"
    )
    lines.append(
        f"TXP HEIGHT         : "
        f"0x{txp['height']:X} "
        f"({txp['height']})"
    )
    lines.append(
        f"TXP PIXEL FORMAT   : "
        f"0x{txp['pixel_format']:04X}"
    )
    lines.append(
        f"PALETTE            : "
        f"{txp['palette_width']}×"
        f"{txp['palette_height']}"
    )
    lines.append(
        f"PIXEL OFFSET       : "
        f"0x{txp['pixel_offset']:X}"
    )
    lines.append(
        f"BYTES PER ROW      : "
        f"0x{txp['bytes_per_row']:X}"
    )
    lines.append(
        f"GLYPH SIZE         : "
        f"{txp['width']}×{GLYPH_HEIGHT}"
    )
    lines.append(
        f"BYTES PER GLYPH    : "
        f"0x{txp['bytes_per_glyph']:X}"
    )
    lines.append(
        f"GLYPH COUNT        : "
        f"0x{txp['glyph_count']:X} "
        f"({txp['glyph_count']})"
    )
    lines.append("")

    results = []

    for character in CHARACTERS:
        encoded = character.encode(
            "shift_jis"
        )

        table_index = font_table_index(
            encoded
        )

        if table_index >= len(table):
            raise ValueError(
                f"{character}: 테이블 인덱스가 "
                "범위를 벗어났습니다."
            )

        glyph_index = table[
            table_index
        ]

        glyph_offset = (
            txp["pixel_offset"]
            + glyph_index
            * txp["bytes_per_glyph"]
        )

        results.append(
            {
                "character": character,
                "encoded": encoded,
                "table_index": table_index,
                "glyph_index": glyph_index,
                "glyph_offset": glyph_offset,
            }
        )

        lines.append(
            f"{character} "
            f"UNICODE=U+{ord(character):04X}"
        )
        lines.append(
            f"  SHIFT-JIS     : "
            f"{encoded.hex(' ').upper()}"
        )
        lines.append(
            f"  TABLE INDEX   : "
            f"0x{table_index:04X}"
        )
        lines.append(
            f"  TABLE OFFSET  : "
            f"0x{2 + table_index * 2:05X}"
        )
        lines.append(
            f"  GLYPH INDEX   : "
            f"0x{glyph_index:04X}"
        )
        lines.append(
            f"  PIXEL OFFSET  : "
            f"0x{glyph_offset:05X}"
        )
        lines.append("")

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report = "\n".join(lines) + "\n"

    REPORT_PATH.write_text(
        report,
        encoding="utf-8",
    )

    print(report, end="")

    cell_width = 190
    cell_height = 155

    sheet = Image.new(
        "RGB",
        (
            cell_width * len(results),
            cell_height,
        ),
        "black",
    )

    draw = ImageDraw.Draw(sheet)
    label_font = ImageFont.load_default()

    for column, result in enumerate(results):
        glyph = decode_glyph(
            texture_data,
            txp,
            result["glyph_index"],
        )

        glyph = glyph.resize(
            (
                txp["width"] * SCALE,
                GLYPH_HEIGHT * SCALE,
            ),
            Image.Resampling.NEAREST,
        ).convert("RGB")

        cell_x = (
            column * cell_width
        )

        glyph_x = (
            cell_x
            + (cell_width - glyph.width) // 2
        )

        sheet.paste(
            glyph,
            (
                glyph_x,
                4,
            ),
        )

        labels = [
            f"U+{ord(result['character']):04X}",
            (
                f"SJIS "
                f"{result['encoded'].hex().upper()}"
            ),
            (
                f"T={result['table_index']:04X} "
                f"G={result['glyph_index']:04X}"
            ),
        ]

        for row, label in enumerate(labels):
            draw.text(
                (
                    cell_x + 5,
                    118 + row * 11,
                ),
                label,
                fill="white",
                font=label_font,
            )

        draw.rectangle(
            (
                cell_x,
                0,
                cell_x + cell_width - 1,
                cell_height - 1,
            ),
            outline="white",
        )

    sheet.save(
        IMAGE_PATH
    )

    print(
        "IMAGE:",
        IMAGE_PATH,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
