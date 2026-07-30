#!/usr/bin/env python3

import binascii
import struct
import zlib
from pathlib import Path


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

OUTPUT_PATH = Path(
    "workspace/reports/font_8x8_tile_compare.png"
)

PAYLOAD_OFFSET = 0x60
GLYPH_SIZE = 0x80
GLYPH_COUNT = 0x100

GLYPH_WIDTH = 16
GLYPH_HEIGHT = 16
TILE_WIDTH = 8
TILE_HEIGHT = 8
TILE_SIZE = 0x20

GRID_COLUMNS = 16
GRID_ROWS = 16

GLYPH_SCALE = 2
CELL_WIDTH = 38
CELL_HEIGHT = 40
PANEL_GAP = 18
PANEL_HEADER = 18

BACKGROUND = 26
GRID_VALUE = 48


HEX_FONT = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("111", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("111", "100", "100", "100", "111"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
}


def png_chunk(
    chunk_type: bytes,
    payload: bytes,
) -> bytes:
    crc = binascii.crc32(chunk_type)
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF

    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", crc)
    )


def save_grayscale_png(
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


def set_pixel(
    canvas: bytearray,
    width: int,
    x: int,
    y: int,
    value: int,
) -> None:
    canvas[y * width + x] = value


def draw_hex(
    canvas: bytearray,
    canvas_width: int,
    x: int,
    y: int,
    text: str,
    scale: int = 1,
    value: int = 225,
) -> None:
    cursor_x = x

    for character in text:
        pattern = HEX_FONT[character]

        for pattern_y, row in enumerate(pattern):
            for pattern_x, bit in enumerate(row):
                if bit != "1":
                    continue

                for sy in range(scale):
                    for sx in range(scale):
                        set_pixel(
                            canvas,
                            canvas_width,
                            cursor_x
                            + pattern_x * scale
                            + sx,
                            y
                            + pattern_y * scale
                            + sy,
                            value,
                        )

        cursor_x += 4 * scale


def unpack_tile(
    packed: bytes,
    low_nibble_first: bool,
) -> list[list[int]]:
    if len(packed) != TILE_SIZE:
        raise ValueError(
            f"타일 크기 오류: {len(packed)}"
        )

    tile = [
        [0] * TILE_WIDTH
        for _ in range(TILE_HEIGHT)
    ]

    position = 0

    for y in range(TILE_HEIGHT):
        for byte_x in range(4):
            value = packed[position]
            position += 1

            low = value & 0x0F
            high = value >> 4

            if low_nibble_first:
                first, second = low, high
            else:
                first, second = high, low

            x = byte_x * 2
            tile[y][x] = first
            tile[y][x + 1] = second

    return tile


def decode_glyph(
    packed: bytes,
    tile_order: str,
    low_nibble_first: bool,
) -> list[list[int]]:
    if len(packed) != GLYPH_SIZE:
        raise ValueError(
            f"글리프 크기 오류: {len(packed)}"
        )

    stored_tiles = [
        unpack_tile(
            packed[
                index * TILE_SIZE:
                (index + 1) * TILE_SIZE
            ],
            low_nibble_first,
        )
        for index in range(4)
    ]

    if tile_order == "row_major":
        # 저장 순서: 좌상, 우상, 좌하, 우하
        destinations = [
            (0, 0),
            (8, 0),
            (0, 8),
            (8, 8),
        ]

    elif tile_order == "column_major":
        # 저장 순서: 좌상, 좌하, 우상, 우하
        destinations = [
            (0, 0),
            (0, 8),
            (8, 0),
            (8, 8),
        ]

    else:
        raise ValueError(
            f"알 수 없는 타일 순서: {tile_order}"
        )

    image = [
        [0] * GLYPH_WIDTH
        for _ in range(GLYPH_HEIGHT)
    ]

    for tile, (target_x, target_y) in zip(
        stored_tiles,
        destinations,
    ):
        for y in range(TILE_HEIGHT):
            for x in range(TILE_WIDTH):
                image[target_y + y][target_x + x] = (
                    tile[y][x]
                )

    return image


def make_palette(
    data: bytes,
) -> list[int]:
    palette_count = struct.unpack_from(
        "<H",
        data,
        0x00,
    )[0]

    palette = []

    for index in range(palette_count):
        red, green, blue, alpha = struct.unpack_from(
            "<BBBB",
            data,
            0x10 + index * 4,
        )

        if alpha == 0:
            palette.append(BACKGROUND)
            continue

        luminance = (
            red * 299
            + green * 587
            + blue * 114
        ) // 1000

        palette.append(luminance)

    return palette


def draw_panel(
    canvas: bytearray,
    canvas_width: int,
    panel_x: int,
    panel_y: int,
    panel_label: str,
    payload: bytes,
    palette: list[int],
    tile_order: str,
    low_nibble_first: bool,
) -> None:
    panel_width = GRID_COLUMNS * CELL_WIDTH
    panel_height = (
        PANEL_HEADER
        + GRID_ROWS * CELL_HEIGHT
    )

    draw_hex(
        canvas,
        canvas_width,
        panel_x + 5,
        panel_y + 3,
        panel_label,
        scale=3,
        value=245,
    )

    for glyph_index in range(GLYPH_COUNT):
        column = glyph_index % GRID_COLUMNS
        row = glyph_index // GRID_COLUMNS

        cell_x = panel_x + column * CELL_WIDTH
        cell_y = (
            panel_y
            + PANEL_HEADER
            + row * CELL_HEIGHT
        )

        for x in range(CELL_WIDTH):
            set_pixel(
                canvas,
                canvas_width,
                cell_x + x,
                cell_y,
                GRID_VALUE,
            )

            set_pixel(
                canvas,
                canvas_width,
                cell_x + x,
                cell_y + CELL_HEIGHT - 1,
                GRID_VALUE,
            )

        for y in range(CELL_HEIGHT):
            set_pixel(
                canvas,
                canvas_width,
                cell_x,
                cell_y + y,
                GRID_VALUE,
            )

            set_pixel(
                canvas,
                canvas_width,
                cell_x + CELL_WIDTH - 1,
                cell_y + y,
                GRID_VALUE,
            )

        start = glyph_index * GLYPH_SIZE
        end = start + GLYPH_SIZE

        glyph = decode_glyph(
            payload[start:end],
            tile_order,
            low_nibble_first,
        )

        glyph_x = cell_x + 3
        glyph_y = cell_y + 2

        for source_y in range(GLYPH_HEIGHT):
            for source_x in range(GLYPH_WIDTH):
                palette_index = glyph[source_y][source_x]

                if palette_index < len(palette):
                    value = palette[palette_index]
                else:
                    value = 255

                for sy in range(GLYPH_SCALE):
                    for sx in range(GLYPH_SCALE):
                        set_pixel(
                            canvas,
                            canvas_width,
                            glyph_x
                            + source_x * GLYPH_SCALE
                            + sx,
                            glyph_y
                            + source_y * GLYPH_SCALE
                            + sy,
                            value,
                        )

        label = f"{glyph_index:04X}"

        draw_hex(
            canvas,
            canvas_width,
            cell_x + 11,
            cell_y + 34,
            label,
            scale=1,
        )


def main() -> int:
    data = INPUT_PATH.read_bytes()
    payload = data[PAYLOAD_OFFSET:]

    required = GLYPH_COUNT * GLYPH_SIZE

    if len(payload) < required:
        print(
            "ERROR: 글리프 데이터가 부족합니다:",
            len(payload),
            required,
        )
        return 1

    palette = make_palette(data)

    panel_width = GRID_COLUMNS * CELL_WIDTH
    panel_height = (
        PANEL_HEADER
        + GRID_ROWS * CELL_HEIGHT
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
            "A",
            "row_major",
            True,
        ),
        (
            panel_width + PANEL_GAP,
            0,
            "B",
            "row_major",
            False,
        ),
        (
            0,
            panel_height + PANEL_GAP,
            "C",
            "column_major",
            True,
        ),
        (
            panel_width + PANEL_GAP,
            panel_height + PANEL_GAP,
            "D",
            "column_major",
            False,
        ),
    ]

    for (
        panel_x,
        panel_y,
        label,
        tile_order,
        low_first,
    ) in variants:
        print(
            f"{label}: "
            f"{tile_order}, "
            f"{'low nibble first' if low_first else 'high nibble first'}"
        )

        draw_panel(
            canvas,
            canvas_width,
            panel_x,
            panel_y,
            label,
            payload,
            palette,
            tile_order,
            low_first,
        )

    save_grayscale_png(
        OUTPUT_PATH,
        canvas_width,
        canvas_height,
        canvas,
    )

    print()
    print("SAVED:", OUTPUT_PATH)
    print(
        "SIZE :",
        f"{canvas_width}x{canvas_height}",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
