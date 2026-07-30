#!/usr/bin/env python3

import struct
from pathlib import Path

from probe_font_fnt import (
    draw_hex_label,
    save_grayscale_png,
)


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

OUTPUT_LOW = Path(
    "workspace/reports/font_unswizzle_24_low.png"
)

OUTPUT_HIGH = Path(
    "workspace/reports/font_unswizzle_24_high.png"
)


GLYPH_WIDTH = 16
GLYPH_HEIGHT = 16
GLYPH_COLUMNS = 24

SHEET_COLUMNS = 48
CELL_WIDTH = 40
CELL_HEIGHT = 42
GLYPH_SCALE = 2


def unswizzle_psp(
    source: bytes,
    width_bytes: int,
    height: int,
) -> bytes:
    """
    PSP block swizzle 해제.

    저장 블록:
        가로 16바이트
        세로 8행
        블록당 0x80바이트
    """

    if width_bytes % 16 != 0:
        raise ValueError(
            f"텍스처 바이트 폭이 16의 배수가 아닙니다: "
            f"{width_bytes}"
        )

    if height % 8 != 0:
        raise ValueError(
            f"텍스처 높이가 8의 배수가 아닙니다: "
            f"{height}"
        )

    expected_size = width_bytes * height

    if len(source) != expected_size:
        raise ValueError(
            f"텍스처 크기 불일치: "
            f"{len(source)} != {expected_size}"
        )

    destination = bytearray(expected_size)

    blocks_per_row = width_bytes // 16
    block_rows = height // 8

    source_offset = 0

    for block_y in range(block_rows):
        for block_x in range(blocks_per_row):
            for row_in_block in range(8):
                destination_offset = (
                    (block_y * 8 + row_in_block)
                    * width_bytes
                    + block_x * 16
                )

                destination[
                    destination_offset:
                    destination_offset + 16
                ] = source[
                    source_offset:
                    source_offset + 16
                ]

                source_offset += 16

    if source_offset != len(source):
        raise ValueError(
            f"swizzle 입력을 전부 소비하지 못했습니다: "
            f"{source_offset}/{len(source)}"
        )

    return bytes(destination)


def unpack_4bpp(
    packed: bytes,
    low_nibble_first: bool,
) -> bytearray:
    pixels = bytearray(len(packed) * 2)
    output_position = 0

    for value in packed:
        low = value & 0x0F
        high = (value >> 4) & 0x0F

        if low_nibble_first:
            pixels[output_position] = low
            pixels[output_position + 1] = high
        else:
            pixels[output_position] = high
            pixels[output_position + 1] = low

        output_position += 2

    return pixels


def make_palette_values(
    palette: list[tuple[int, int, int, int]],
    background: int,
) -> list[int]:
    values = []

    for red, green, blue, alpha in palette:
        luminance = (
            red * 299
            + green * 587
            + blue * 114
        ) // 1000

        composited = (
            luminance * alpha
            + background * (255 - alpha)
        ) // 255

        values.append(composited)

    return values


def build_atlas(
    texture_pixels: bytearray,
    texture_width: int,
    glyph_count: int,
    palette_values: list[int],
    output_path: Path,
) -> None:
    sheet_rows = (
        glyph_count
        + SHEET_COLUMNS
        - 1
    ) // SHEET_COLUMNS

    sheet_width = (
        SHEET_COLUMNS
        * CELL_WIDTH
    )

    sheet_height = (
        sheet_rows
        * CELL_HEIGHT
    )

    background = 96
    grid_value = 55

    canvas = bytearray(
        [background]
        * (sheet_width * sheet_height)
    )

    # 세로 격자
    for column in range(SHEET_COLUMNS + 1):
        x = min(
            column * CELL_WIDTH,
            sheet_width - 1,
        )

        for y in range(sheet_height):
            canvas[
                y * sheet_width + x
            ] = grid_value

    # 가로 격자
    for row in range(sheet_rows + 1):
        y = min(
            row * CELL_HEIGHT,
            sheet_height - 1,
        )

        row_offset = y * sheet_width

        for x in range(sheet_width):
            canvas[
                row_offset + x
            ] = grid_value

    for glyph_index in range(glyph_count):
        source_glyph_x = (
            glyph_index % GLYPH_COLUMNS
        ) * GLYPH_WIDTH

        source_glyph_y = (
            glyph_index // GLYPH_COLUMNS
        ) * GLYPH_HEIGHT

        sheet_column = (
            glyph_index % SHEET_COLUMNS
        )

        sheet_row = (
            glyph_index // SHEET_COLUMNS
        )

        cell_x = sheet_column * CELL_WIDTH
        cell_y = sheet_row * CELL_HEIGHT

        target_glyph_x = cell_x + 4
        target_glyph_y = cell_y + 2

        for source_y in range(GLYPH_HEIGHT):
            texture_row = (
                source_glyph_y + source_y
            ) * texture_width

            for source_x in range(GLYPH_WIDTH):
                palette_index = texture_pixels[
                    texture_row
                    + source_glyph_x
                    + source_x
                ]

                if palette_index >= len(palette_values):
                    pixel_value = 255
                else:
                    pixel_value = palette_values[
                        palette_index
                    ]

                for scale_y in range(GLYPH_SCALE):
                    for scale_x in range(GLYPH_SCALE):
                        target_x = (
                            target_glyph_x
                            + source_x * GLYPH_SCALE
                            + scale_x
                        )

                        target_y = (
                            target_glyph_y
                            + source_y * GLYPH_SCALE
                            + scale_y
                        )

                        canvas[
                            target_y * sheet_width
                            + target_x
                        ] = pixel_value

        label = f"{glyph_index:04X}"
        label_width = len(label) * 4 - 1

        label_x = (
            cell_x
            + (CELL_WIDTH - label_width) // 2
        )

        label_y = cell_y + 35

        draw_hex_label(
            canvas,
            sheet_width,
            label_x,
            label_y,
            label,
        )

    save_grayscale_png(
        output_path,
        sheet_width,
        sheet_height,
        canvas,
    )

    print(
        "SAVED:",
        output_path,
        f"({sheet_width}x{sheet_height})",
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

    bytes_per_glyph = (
        GLYPH_WIDTH
        * GLYPH_HEIGHT
        // 2
    )

    glyph_count, remainder = divmod(
        len(payload),
        bytes_per_glyph,
    )

    if remainder:
        raise ValueError(
            f"글리프 데이터 나머지가 있습니다: "
            f"{remainder}"
        )

    if glyph_count % GLYPH_COLUMNS:
        raise ValueError(
            f"글리프 수 {glyph_count}가 "
            f"{GLYPH_COLUMNS}열로 나누어지지 않습니다."
        )

    glyph_rows = (
        glyph_count
        // GLYPH_COLUMNS
    )

    texture_width = (
        GLYPH_COLUMNS
        * GLYPH_WIDTH
    )

    texture_height = (
        glyph_rows
        * GLYPH_HEIGHT
    )

    texture_width_bytes = (
        texture_width // 2
    )

    print("FONT UNSWIZZLE")
    print("==============")
    print("GLYPH COUNT       :", glyph_count)
    print("GLYPH COLUMNS     :", GLYPH_COLUMNS)
    print("GLYPH ROWS        :", glyph_rows)
    print(
        "TEXTURE SIZE      :",
        f"{texture_width}x{texture_height}",
    )
    print(
        "TEXTURE BYTE WIDTH:",
        texture_width_bytes,
    )
    print(
        "PAYLOAD SIZE      :",
        f"0x{len(payload):X}",
    )

    linear_packed = unswizzle_psp(
        payload,
        texture_width_bytes,
        texture_height,
    )

    palette_values = make_palette_values(
        palette,
        background=96,
    )

    low_pixels = unpack_4bpp(
        linear_packed,
        low_nibble_first=True,
    )

    high_pixels = unpack_4bpp(
        linear_packed,
        low_nibble_first=False,
    )

    OUTPUT_LOW.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    build_atlas(
        texture_pixels=low_pixels,
        texture_width=texture_width,
        glyph_count=glyph_count,
        palette_values=palette_values,
        output_path=OUTPUT_LOW,
    )

    build_atlas(
        texture_pixels=high_pixels,
        texture_width=texture_width,
        glyph_count=glyph_count,
        palette_values=palette_values,
        output_path=OUTPUT_HIGH,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
