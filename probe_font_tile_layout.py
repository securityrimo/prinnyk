#!/usr/bin/env python3

import binascii
import struct
import zlib
from pathlib import Path


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

OUTPUT_PATH = Path(
    "workspace/reports/font_tile_layout_compare.png"
)

GLYPH_COUNT = 256
GLYPH_WIDTH = 16
GLYPH_HEIGHT = 16
BYTES_PER_GLYPH = 0x80

GRID_COLUMNS = 16
GRID_ROWS = 16

GLYPH_SCALE = 3
CELL_WIDTH = 52
CELL_HEIGHT = 58

PANEL_GAP = 16
BACKGROUND = 70
GRID_VALUE = 38


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


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(chunk_type)
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF

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

        row_start = y * width

        scanlines.extend(
            pixels[row_start:row_start + width]
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


def draw_hex(
    canvas: bytearray,
    canvas_width: int,
    x: int,
    y: int,
    text: str,
) -> None:
    cursor_x = x

    for character in text:
        pattern = HEX_FONT[character]

        for pattern_y, row in enumerate(pattern):
            for pattern_x, bit in enumerate(row):
                if bit == "0":
                    continue

                canvas[
                    (y + pattern_y) * canvas_width
                    + cursor_x
                    + pattern_x
                ] = 230

        cursor_x += 4


def rearrange_rows(
    glyph: bytes,
    layout: str,
) -> bytes:
    """
    입력 글리프는 16바이트 × 8개의 저장 행이다.

    row_pair:
        각 저장 행의 왼쪽 8바이트와 오른쪽 8바이트를
        연속된 두 출력 행으로 배치한다.

    vertical_halves:
        왼쪽 8바이트는 위쪽 8개 행,
        오른쪽 8바이트는 아래쪽 8개 행으로 배치한다.
    """

    if len(glyph) != BYTES_PER_GLYPH:
        raise ValueError(
            f"글리프 크기 오류: {len(glyph)}"
        )

    output = bytearray(BYTES_PER_GLYPH)

    for stored_y in range(8):
        stored_row = glyph[
            stored_y * 16:
            stored_y * 16 + 16
        ]

        left = stored_row[:8]
        right = stored_row[8:]

        if layout == "row_pair":
            first_y = stored_y * 2
            second_y = first_y + 1

        elif layout == "vertical_halves":
            first_y = stored_y
            second_y = stored_y + 8

        else:
            raise ValueError(
                f"알 수 없는 행 배열: {layout}"
            )

        output[
            first_y * 8:
            first_y * 8 + 8
        ] = left

        output[
            second_y * 8:
            second_y * 8 + 8
        ] = right

    return bytes(output)


def unpack_pixels(
    packed: bytes,
    low_first: bool,
) -> list[int]:
    pixels = []

    for value in packed:
        low = value & 0x0F
        high = (value >> 4) & 0x0F

        if low_first:
            pixels.extend((low, high))
        else:
            pixels.extend((high, low))

    if len(pixels) != GLYPH_WIDTH * GLYPH_HEIGHT:
        raise ValueError(
            f"픽셀 수 오류: {len(pixels)}"
        )

    return pixels


def palette_to_grayscale(
    palette: list[tuple[int, int, int, int]],
) -> list[int]:
    result = []

    for red, green, blue, alpha in palette:
        luminance = (
            red * 299
            + green * 587
            + blue * 114
        ) // 1000

        value = (
            luminance * alpha
            + BACKGROUND * (255 - alpha)
        ) // 255

        result.append(value)

    return result


def draw_panel(
    canvas: bytearray,
    canvas_width: int,
    panel_x: int,
    panel_y: int,
    payload: bytes,
    palette_values: list[int],
    layout: str,
    low_first: bool,
) -> None:
    panel_width = GRID_COLUMNS * CELL_WIDTH
    panel_height = GRID_ROWS * CELL_HEIGHT

    # 패널 외곽선
    for x in range(panel_width):
        canvas[
            panel_y * canvas_width
            + panel_x
            + x
        ] = 245

        canvas[
            (panel_y + panel_height - 1)
            * canvas_width
            + panel_x
            + x
        ] = 245

    for y in range(panel_height):
        canvas[
            (panel_y + y) * canvas_width
            + panel_x
        ] = 245

        canvas[
            (panel_y + y) * canvas_width
            + panel_x
            + panel_width - 1
        ] = 245

    # 셀 격자
    for column in range(GRID_COLUMNS + 1):
        x = min(
            column * CELL_WIDTH,
            panel_width - 1,
        )

        for y in range(panel_height):
            canvas[
                (panel_y + y) * canvas_width
                + panel_x
                + x
            ] = GRID_VALUE

    for row in range(GRID_ROWS + 1):
        y = min(
            row * CELL_HEIGHT,
            panel_height - 1,
        )

        for x in range(panel_width):
            canvas[
                (panel_y + y) * canvas_width
                + panel_x
                + x
            ] = GRID_VALUE

    for glyph_index in range(GLYPH_COUNT):
        start = glyph_index * BYTES_PER_GLYPH
        end = start + BYTES_PER_GLYPH

        stored_glyph = payload[start:end]

        linear_glyph = rearrange_rows(
            stored_glyph,
            layout,
        )

        pixels = unpack_pixels(
            linear_glyph,
            low_first,
        )

        column = glyph_index % GRID_COLUMNS
        row = glyph_index // GRID_COLUMNS

        cell_x = (
            panel_x
            + column * CELL_WIDTH
        )

        cell_y = (
            panel_y
            + row * CELL_HEIGHT
        )

        glyph_x = cell_x + 2
        glyph_y = cell_y + 1

        for source_y in range(GLYPH_HEIGHT):
            for source_x in range(GLYPH_WIDTH):
                palette_index = pixels[
                    source_y * GLYPH_WIDTH
                    + source_x
                ]

                value = palette_values[
                    palette_index
                ]

                for scale_y in range(GLYPH_SCALE):
                    for scale_x in range(GLYPH_SCALE):
                        target_x = (
                            glyph_x
                            + source_x * GLYPH_SCALE
                            + scale_x
                        )

                        target_y = (
                            glyph_y
                            + source_y * GLYPH_SCALE
                            + scale_y
                        )

                        canvas[
                            target_y * canvas_width
                            + target_x
                        ] = value

        label = f"{glyph_index:04X}"
        label_width = len(label) * 4 - 1

        draw_hex(
            canvas,
            canvas_width,
            cell_x + (
                CELL_WIDTH - label_width
            ) // 2,
            cell_y + 51,
            label,
        )


def main() -> int:
    data = INPUT_PATH.read_bytes()

    palette_count = struct.unpack_from(
        "<H",
        data,
        0x00,
    )[0]

    header_size = (
        0x10
        + palette_count * 4
    )

    palette = [
        struct.unpack_from(
            "<BBBB",
            data,
            0x10 + index * 4,
        )
        for index in range(palette_count)
    ]

    payload = data[header_size:]

    required_size = (
        GLYPH_COUNT
        * BYTES_PER_GLYPH
    )

    if len(payload) < required_size:
        raise ValueError(
            f"글리프 데이터 부족: "
            f"{len(payload)} < {required_size}"
        )

    palette_values = palette_to_grayscale(
        palette
    )

    panel_width = GRID_COLUMNS * CELL_WIDTH
    panel_height = GRID_ROWS * CELL_HEIGHT

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
        * (canvas_width * canvas_height)
    )

    variants = [
        (
            0,
            0,
            "row_pair",
            True,
            "TOP LEFT",
        ),
        (
            panel_width + PANEL_GAP,
            0,
            "row_pair",
            False,
            "TOP RIGHT",
        ),
        (
            0,
            panel_height + PANEL_GAP,
            "vertical_halves",
            True,
            "BOTTOM LEFT",
        ),
        (
            panel_width + PANEL_GAP,
            panel_height + PANEL_GAP,
            "vertical_halves",
            False,
            "BOTTOM RIGHT",
        ),
    ]

    for (
        panel_x,
        panel_y,
        layout,
        low_first,
        label,
    ) in variants:
        print(
            f"{label:<12}: "
            f"{layout}, "
            f"{'low nibble first' if low_first else 'high nibble first'}"
        )

        draw_panel(
            canvas=canvas,
            canvas_width=canvas_width,
            panel_x=panel_x,
            panel_y=panel_y,
            payload=payload,
            palette_values=palette_values,
            layout=layout,
            low_first=low_first,
        )

    save_png(
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
