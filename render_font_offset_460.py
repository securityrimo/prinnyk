#!/usr/bin/env python3

import binascii
import struct
import zlib
from pathlib import Path


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

OUTPUT_PATH = Path(
    "workspace/reports/font_offset_460_compare.png"
)

BITMAP_OFFSET = 0x460

GLYPH_WIDTH = 16
GLYPH_HEIGHT = 20
BYTES_PER_GLYPH = (
    GLYPH_WIDTH * GLYPH_HEIGHT // 2
)

EXPECTED_GLYPHS = 2048
DISPLAY_GLYPHS = 512

DISPLAY_COLUMNS = 32
DISPLAY_ROWS = DISPLAY_GLYPHS // DISPLAY_COLUMNS

SOURCE_WIDTH = 256
SOURCE_COLUMNS = SOURCE_WIDTH // GLYPH_WIDTH

SCALE = 2
PANEL_GAP = 16
BACKGROUND = 20
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
            f"픽셀 크기 불일치: "
            f"{len(pixels)} != {width * height}"
        )

    scanlines = bytearray()

    for y in range(height):
        scanlines.append(0)

        start = y * width

        scanlines.extend(
            pixels[start:start + width]
        )

    output = bytearray(b"\x89PNG\r\n\x1a\n")

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


def unpack_4bpp(
    packed: bytes,
    low_first: bool,
) -> bytearray:
    result = bytearray(len(packed) * 2)

    destination = 0

    for value in packed:
        low = value & 0x0F
        high = value >> 4

        if low_first:
            result[destination] = low
            result[destination + 1] = high
        else:
            result[destination] = high
            result[destination + 1] = low

        destination += 2

    return result


def intensity(index: int) -> int:
    return (
        BACKGROUND
        + index * (255 - BACKGROUND) // 15
    )


def set_pixel(
    canvas: bytearray,
    canvas_width: int,
    x: int,
    y: int,
    value: int,
) -> None:
    canvas[y * canvas_width + x] = value


def draw_grid(
    canvas: bytearray,
    canvas_width: int,
    panel_x: int,
    panel_y: int,
    panel_width: int,
    panel_height: int,
) -> None:
    cell_width = GLYPH_WIDTH * SCALE
    cell_height = GLYPH_HEIGHT * SCALE

    for column in range(DISPLAY_COLUMNS + 1):
        x = min(
            panel_x + column * cell_width,
            panel_x + panel_width - 1,
        )

        for y in range(panel_y, panel_y + panel_height):
            set_pixel(
                canvas,
                canvas_width,
                x,
                y,
                GRID,
            )

    for row in range(DISPLAY_ROWS + 1):
        y = min(
            panel_y + row * cell_height,
            panel_y + panel_height - 1,
        )

        for x in range(panel_x, panel_x + panel_width):
            set_pixel(
                canvas,
                canvas_width,
                x,
                y,
                GRID,
            )


def draw_glyph(
    canvas: bytearray,
    canvas_width: int,
    target_x: int,
    target_y: int,
    glyph: list[int] | bytearray,
) -> None:
    for source_y in range(GLYPH_HEIGHT):
        for source_x in range(GLYPH_WIDTH):
            index = glyph[
                source_y * GLYPH_WIDTH
                + source_x
            ]

            value = intensity(index)

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


def draw_glyph_major_panel(
    canvas: bytearray,
    canvas_width: int,
    panel_x: int,
    panel_y: int,
    payload: bytes,
    low_first: bool,
) -> None:
    for glyph_index in range(DISPLAY_GLYPHS):
        source_start = (
            glyph_index * BYTES_PER_GLYPH
        )

        packed = payload[
            source_start:
            source_start + BYTES_PER_GLYPH
        ]

        glyph = unpack_4bpp(
            packed,
            low_first,
        )

        column = glyph_index % DISPLAY_COLUMNS
        row = glyph_index // DISPLAY_COLUMNS

        target_x = (
            panel_x
            + column * GLYPH_WIDTH * SCALE
        )

        target_y = (
            panel_y
            + row * GLYPH_HEIGHT * SCALE
        )

        draw_glyph(
            canvas,
            canvas_width,
            target_x,
            target_y,
            glyph,
        )


def draw_surface_panel(
    canvas: bytearray,
    canvas_width: int,
    panel_x: int,
    panel_y: int,
    payload: bytes,
    low_first: bool,
) -> None:
    source_pixels = unpack_4bpp(
        payload,
        low_first,
    )

    source_height, remainder = divmod(
        len(source_pixels),
        SOURCE_WIDTH,
    )

    if remainder:
        raise ValueError(
            "256픽셀 폭으로 나누어지지 않습니다."
        )

    expected_height = (
        EXPECTED_GLYPHS
        // SOURCE_COLUMNS
        * GLYPH_HEIGHT
    )

    if source_height != expected_height:
        raise ValueError(
            f"표면 높이 불일치: "
            f"{source_height} != {expected_height}"
        )

    for glyph_index in range(DISPLAY_GLYPHS):
        source_column = (
            glyph_index % SOURCE_COLUMNS
        )

        source_row = (
            glyph_index // SOURCE_COLUMNS
        )

        source_x = (
            source_column * GLYPH_WIDTH
        )

        source_y = (
            source_row * GLYPH_HEIGHT
        )

        glyph = bytearray(
            GLYPH_WIDTH * GLYPH_HEIGHT
        )

        for y in range(GLYPH_HEIGHT):
            source_offset = (
                (source_y + y) * SOURCE_WIDTH
                + source_x
            )

            destination_offset = (
                y * GLYPH_WIDTH
            )

            glyph[
                destination_offset:
                destination_offset + GLYPH_WIDTH
            ] = source_pixels[
                source_offset:
                source_offset + GLYPH_WIDTH
            ]

        output_column = (
            glyph_index % DISPLAY_COLUMNS
        )

        output_row = (
            glyph_index // DISPLAY_COLUMNS
        )

        target_x = (
            panel_x
            + output_column * GLYPH_WIDTH * SCALE
        )

        target_y = (
            panel_y
            + output_row * GLYPH_HEIGHT * SCALE
        )

        draw_glyph(
            canvas,
            canvas_width,
            target_x,
            target_y,
            glyph,
        )


def main() -> int:
    data = INPUT_PATH.read_bytes()
    payload = data[BITMAP_OFFSET:]

    glyph_count, remainder = divmod(
        len(payload),
        BYTES_PER_GLYPH,
    )

    print("FONT.FNT OFFSET 0x460 TEST")
    print("==========================")
    print("FILE SIZE       :", f"0x{len(data):X}")
    print("BITMAP OFFSET   :", f"0x{BITMAP_OFFSET:X}")
    print("PREFIX SIZE     :", f"0x{BITMAP_OFFSET:X}")
    print("TABLE AFTER 60  :", f"0x{BITMAP_OFFSET - 0x60:X}")
    print("PAYLOAD SIZE    :", f"0x{len(payload):X}")
    print(
        "BYTES PER GLYPH:",
        f"0x{BYTES_PER_GLYPH:X}",
    )
    print("GLYPH COUNT     :", glyph_count)
    print("REMAINDER       :", remainder)

    if glyph_count != EXPECTED_GLYPHS:
        raise ValueError(
            f"예상 글리프 수가 아닙니다: "
            f"{glyph_count}"
        )

    if remainder:
        raise ValueError(
            f"글리프 나머지가 있습니다: "
            f"{remainder}"
        )

    panel_width = (
        DISPLAY_COLUMNS
        * GLYPH_WIDTH
        * SCALE
    )

    panel_height = (
        DISPLAY_ROWS
        * GLYPH_HEIGHT
        * SCALE
    )

    canvas_width = (
        panel_width * 2
        + PANEL_GAP
    )

    canvas_height = (
        panel_height * 2
        + PANEL_GAP
    )

    canvas = bytearray(
        [BACKGROUND]
        * canvas_width
        * canvas_height
    )

    variants = [
        (
            0,
            0,
            "GLYPH-MAJOR LOW",
            "glyph",
            True,
        ),
        (
            panel_width + PANEL_GAP,
            0,
            "GLYPH-MAJOR HIGH",
            "glyph",
            False,
        ),
        (
            0,
            panel_height + PANEL_GAP,
            "SURFACE LOW",
            "surface",
            True,
        ),
        (
            panel_width + PANEL_GAP,
            panel_height + PANEL_GAP,
            "SURFACE HIGH",
            "surface",
            False,
        ),
    ]

    for (
        panel_x,
        panel_y,
        label,
        mode,
        low_first,
    ) in variants:
        print(label)

        if mode == "glyph":
            draw_glyph_major_panel(
                canvas,
                canvas_width,
                panel_x,
                panel_y,
                payload,
                low_first,
            )
        else:
            draw_surface_panel(
                canvas,
                canvas_width,
                panel_x,
                panel_y,
                payload,
                low_first,
            )

        draw_grid(
            canvas,
            canvas_width,
            panel_x,
            panel_y,
            panel_width,
            panel_height,
        )

    save_png(
        OUTPUT_PATH,
        canvas_width,
        canvas_height,
        canvas,
    )

    print()
    print("LAYOUT")
    print("======")
    print("TOP LEFT     : glyph-major, low nibble")
    print("TOP RIGHT    : glyph-major, high nibble")
    print("BOTTOM LEFT  : 256px surface, low nibble")
    print("BOTTOM RIGHT : 256px surface, high nibble")
    print()
    print("SAVED:", OUTPUT_PATH)
    print(
        "SIZE :",
        f"{canvas_width}x{canvas_height}",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
