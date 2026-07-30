#!/usr/bin/env python3

import binascii
import struct
import zlib
from pathlib import Path


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

OUTPUT_PATH = Path(
    "workspace/reports/font_16x20_compare.png"
)

HEADER_SIZE = 0xA0

GLYPH_WIDTH = 16
GLYPH_HEIGHT = 20
BYTES_PER_GLYPH = (
    GLYPH_WIDTH
    * GLYPH_HEIGHT
    // 2
)

DISPLAY_GLYPHS = 512
COLUMNS = 32
ROWS = DISPLAY_GLYPHS // COLUMNS
SCALE = 2

PANEL_GAP = 16
BACKGROUND = 64
GRID = 38


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


def make_palette(
    data: bytes,
) -> list[int]:
    values = []

    # 0x10부터 16색 RGBA 팔레트
    for index in range(16):
        red, green, blue, alpha = (
            struct.unpack_from(
                "<BBBB",
                data,
                0x10 + index * 4,
            )
        )

        luminance = (
            red * 299
            + green * 587
            + blue * 114
        ) // 1000

        value = (
            luminance * alpha
            + BACKGROUND * (255 - alpha)
        ) // 255

        values.append(value)

    return values


def decode_glyph(
    packed: bytes,
    low_first: bool,
) -> list[int]:
    if len(packed) != BYTES_PER_GLYPH:
        raise ValueError(
            f"글리프 크기 오류: "
            f"{len(packed)}"
        )

    pixels = []

    for value in packed:
        low = value & 0x0F
        high = value >> 4

        if low_first:
            pixels.extend((low, high))
        else:
            pixels.extend((high, low))

    return pixels


def draw_panel(
    canvas: bytearray,
    canvas_width: int,
    panel_x: int,
    payload: bytes,
    palette: list[int],
    low_first: bool,
) -> None:
    cell_width = GLYPH_WIDTH * SCALE
    cell_height = GLYPH_HEIGHT * SCALE

    panel_width = COLUMNS * cell_width
    panel_height = ROWS * cell_height

    # 격자
    for column in range(COLUMNS + 1):
        x = min(
            panel_x + column * cell_width,
            panel_x + panel_width - 1,
        )

        for y in range(panel_height):
            canvas[
                y * canvas_width + x
            ] = GRID

    for row in range(ROWS + 1):
        y = min(
            row * cell_height,
            panel_height - 1,
        )

        for x in range(panel_width):
            canvas[
                y * canvas_width
                + panel_x
                + x
            ] = GRID

    for glyph_index in range(DISPLAY_GLYPHS):
        start = (
            glyph_index
            * BYTES_PER_GLYPH
        )

        end = start + BYTES_PER_GLYPH

        indices = decode_glyph(
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
                palette_index = indices[
                    source_y * GLYPH_WIDTH
                    + source_x
                ]

                value = palette[
                    palette_index
                ]

                for scale_y in range(SCALE):
                    for scale_x in range(SCALE):
                        x = (
                            target_x
                            + source_x * SCALE
                            + scale_x
                        )

                        y = (
                            target_y
                            + source_y * SCALE
                            + scale_y
                        )

                        canvas[
                            y * canvas_width + x
                        ] = value


def main() -> int:
    data = INPUT_PATH.read_bytes()
    payload = data[HEADER_SIZE:]

    glyph_count, remainder = divmod(
        len(payload),
        BYTES_PER_GLYPH,
    )

    print("FONT.FNT 16x20 TEST")
    print("===================")
    print("FILE SIZE       :", f"0x{len(data):X}")
    print("HEADER SIZE     :", f"0x{HEADER_SIZE:X}")
    print("PAYLOAD SIZE    :", f"0x{len(payload):X}")
    print(
        "BYTES PER GLYPH:",
        f"0x{BYTES_PER_GLYPH:X}",
    )
    print("GLYPH COUNT     :", glyph_count)
    print("REMAINDER       :", remainder)

    if remainder != 0:
        raise ValueError(
            "16×20 글리프 단위로 "
            "나누어지지 않습니다."
        )

    if glyph_count != 2054:
        raise ValueError(
            f"예상 글리프 수가 아닙니다: "
            f"{glyph_count}"
        )

    palette = make_palette(data)

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
        canvas=canvas,
        canvas_width=canvas_width,
        panel_x=0,
        payload=payload,
        palette=palette,
        low_first=True,
    )

    draw_panel(
        canvas=canvas,
        canvas_width=canvas_width,
        panel_x=panel_width + PANEL_GAP,
        payload=payload,
        palette=palette,
        low_first=False,
    )

    save_png(
        OUTPUT_PATH,
        canvas_width,
        panel_height,
        canvas,
    )

    print()
    print("LEFT : low nibble first")
    print("RIGHT: high nibble first")
    print("SAVED:", OUTPUT_PATH)
    print(
        "SIZE :",
        f"{canvas_width}x{panel_height}",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
