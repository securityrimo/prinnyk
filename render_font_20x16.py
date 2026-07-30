#!/usr/bin/env python3

import binascii
import struct
import zlib
from pathlib import Path


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

OUTPUT_PATH = Path(
    "workspace/reports/font_20x16_compare.png"
)

BITMAP_OFFSET = 0xA0

GLYPH_WIDTH = 20
GLYPH_HEIGHT = 16
ROW_BYTES = GLYPH_WIDTH // 2
BYTES_PER_GLYPH = ROW_BYTES * GLYPH_HEIGHT

EXPECTED_GLYPHS = 2054
DISPLAY_GLYPHS = 512

COLUMNS = 32
ROWS = DISPLAY_GLYPHS // COLUMNS
SCALE = 2

PANEL_GAP = 16
BACKGROUND = 18
GRID = 42


def png_chunk(
    chunk_type: bytes,
    payload: bytes,
) -> bytes:
    crc = binascii.crc32(chunk_type)
    crc = binascii.crc32(
        payload,
        crc,
    ) & 0xFFFFFFFF

    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", crc)
    )


def save_png(
    path: Path,
    width: int,
    height: int,
    pixels: bytearray,
) -> None:
    if len(pixels) != width * height:
        raise ValueError(
            f"픽셀 수 불일치: "
            f"{len(pixels)} != {width * height}"
        )

    scanlines = bytearray()

    for y in range(height):
        scanlines.append(0)

        start = y * width

        scanlines.extend(
            pixels[start:start + width]
        )

    output = bytearray(
        b"\x89PNG\r\n\x1a\n"
    )

    output.extend(
        png_chunk(
            b"IHDR",
            struct.pack(
                ">IIBBBBB",
                width,
                height,
                8,
                0,
                0,
                0,
                0,
            ),
        )
    )

    output.extend(
        png_chunk(
            b"IDAT",
            zlib.compress(
                bytes(scanlines),
                level=9,
            ),
        )
    )

    output.extend(
        png_chunk(
            b"IEND",
            b"",
        )
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_bytes(output)


def decode_glyph(
    packed: bytes,
    low_first: bool,
) -> bytearray:
    if len(packed) != BYTES_PER_GLYPH:
        raise ValueError(
            f"글리프 크기 오류: "
            f"{len(packed)} != {BYTES_PER_GLYPH}"
        )

    pixels = bytearray(
        GLYPH_WIDTH * GLYPH_HEIGHT
    )

    destination = 0

    for y in range(GLYPH_HEIGHT):
        row_start = y * ROW_BYTES

        for byte_x in range(ROW_BYTES):
            value = packed[
                row_start + byte_x
            ]

            low = value & 0x0F
            high = value >> 4

            if low_first:
                first, second = low, high
            else:
                first, second = high, low

            pixels[destination] = first
            pixels[destination + 1] = second
            destination += 2

    return pixels


def intensity(
    palette_index: int,
) -> int:
    # 실제 데이터에서 주로 사용하는 0~8 범위를
    # 화면 전체 명암으로 확대한다.
    if palette_index <= 8:
        return (
            BACKGROUND
            + palette_index
            * (255 - BACKGROUND)
            // 8
        )

    return 255


def set_pixel(
    canvas: bytearray,
    canvas_width: int,
    x: int,
    y: int,
    value: int,
) -> None:
    canvas[
        y * canvas_width + x
    ] = value


def draw_panel(
    canvas: bytearray,
    canvas_width: int,
    panel_x: int,
    payload: bytes,
    low_first: bool,
) -> None:
    cell_width = GLYPH_WIDTH * SCALE
    cell_height = GLYPH_HEIGHT * SCALE

    for glyph_index in range(DISPLAY_GLYPHS):
        start = (
            glyph_index
            * BYTES_PER_GLYPH
        )

        end = start + BYTES_PER_GLYPH

        glyph = decode_glyph(
            payload[start:end],
            low_first,
        )

        column = glyph_index % COLUMNS
        row = glyph_index // COLUMNS

        target_x = (
            panel_x
            + column * cell_width
        )

        target_y = row * cell_height

        for source_y in range(GLYPH_HEIGHT):
            for source_x in range(GLYPH_WIDTH):
                value = intensity(
                    glyph[
                        source_y * GLYPH_WIDTH
                        + source_x
                    ]
                )

                for scale_y in range(SCALE):
                    for scale_x in range(SCALE):
                        set_pixel(
                            canvas,
                            canvas_width,
                            target_x
                            + source_x * SCALE
                            + scale_x,
                            target_y
                            + source_y * SCALE
                            + scale_y,
                            value,
                        )

    panel_width = COLUMNS * cell_width
    panel_height = ROWS * cell_height

    for column in range(COLUMNS + 1):
        x = min(
            panel_x + column * cell_width,
            panel_x + panel_width - 1,
        )

        for y in range(panel_height):
            set_pixel(
                canvas,
                canvas_width,
                x,
                y,
                GRID,
            )

    for row in range(ROWS + 1):
        y = min(
            row * cell_height,
            panel_height - 1,
        )

        for x in range(
            panel_x,
            panel_x + panel_width,
        ):
            set_pixel(
                canvas,
                canvas_width,
                x,
                y,
                GRID,
            )


def main() -> int:
    data = INPUT_PATH.read_bytes()
    payload = data[BITMAP_OFFSET:]

    glyph_count, remainder = divmod(
        len(payload),
        BYTES_PER_GLYPH,
    )

    print("FONT.FNT 20x16 STRUCTURE")
    print("========================")
    print("FILE SIZE       :", f"0x{len(data):X}")
    print("BITMAP OFFSET   :", f"0x{BITMAP_OFFSET:X}")
    print("GLYPH WIDTH     :", GLYPH_WIDTH)
    print("GLYPH HEIGHT    :", GLYPH_HEIGHT)
    print("ROW BYTES       :", ROW_BYTES)
    print(
        "BYTES PER GLYPH:",
        f"0x{BYTES_PER_GLYPH:X}",
    )
    print("PAYLOAD SIZE    :", f"0x{len(payload):X}")
    print("GLYPH COUNT     :", glyph_count)
    print("REMAINDER       :", remainder)

    if glyph_count != EXPECTED_GLYPHS:
        raise ValueError(
            f"예상 글리프 수 불일치: "
            f"{glyph_count} != {EXPECTED_GLYPHS}"
        )

    if remainder:
        raise ValueError(
            f"글리프 나머지 발생: {remainder}"
        )

    panel_width = (
        COLUMNS
        * GLYPH_WIDTH
        * SCALE
    )

    panel_height = (
        ROWS
        * GLYPH_HEIGHT
        * SCALE
    )

    canvas_width = (
        panel_width * 2
        + PANEL_GAP
    )

    canvas = bytearray(
        [BACKGROUND]
        * canvas_width
        * panel_height
    )

    draw_panel(
        canvas,
        canvas_width,
        0,
        payload,
        low_first=True,
    )

    draw_panel(
        canvas,
        canvas_width,
        panel_width + PANEL_GAP,
        payload,
        low_first=False,
    )

    save_png(
        OUTPUT_PATH,
        canvas_width,
        panel_height,
        canvas,
    )

    print()
    print("LEFT : 20x16, low nibble first")
    print("RIGHT: 20x16, high nibble first")
    print("SAVED:", OUTPUT_PATH)
    print(
        "SIZE :",
        f"{canvas_width}x{panel_height}",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
