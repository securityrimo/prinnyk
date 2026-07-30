#!/usr/bin/env python3

import binascii
import math
import struct
import zlib
from collections import Counter
from pathlib import Path


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

OUTPUT_DIRECTORY = Path(
    "workspace/reports"
)


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

        row_start = y * width

        scanlines.extend(
            pixels[
                row_start:
                row_start + width
            ]
        )

    png = bytearray(b"\x89PNG\r\n\x1a\n")

    png.extend(
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

    png.extend(
        png_chunk(
            b"IDAT",
            zlib.compress(
                bytes(scanlines),
                level=9,
            ),
        )
    )

    png.extend(
        png_chunk(
            b"IEND",
            b"",
        )
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_bytes(png)


def draw_hex_label(
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
                if bit != "1":
                    continue

                pixel_x = cursor_x + pattern_x
                pixel_y = y + pattern_y

                canvas[
                    pixel_y * canvas_width
                    + pixel_x
                ] = 225

        cursor_x += 4


def decode_glyph(
    packed: bytes,
    width: int,
    height: int,
    low_nibble_first: bool,
) -> list[int]:
    expected_bytes = width * height // 2

    if len(packed) != expected_bytes:
        raise ValueError(
            f"글리프 데이터 크기 불일치: "
            f"{len(packed)} != {expected_bytes}"
        )

    pixels = []

    for value in packed:
        low = value & 0x0F
        high = (value >> 4) & 0x0F

        if low_nibble_first:
            pixels.extend((low, high))
        else:
            pixels.extend((high, low))

    return pixels


def build_atlas(
    payload: bytes,
    palette: list[tuple[int, int, int, int]],
    glyph_width: int,
    glyph_height: int,
    glyph_count: int,
    bytes_per_glyph: int,
    low_nibble_first: bool,
    output_path: Path,
) -> None:
    columns = 48
    rows = math.ceil(glyph_count / columns)

    glyph_scale = 2
    cell_width = 40
    cell_height = 42

    atlas_width = columns * cell_width
    atlas_height = rows * cell_height

    background = 18
    grid_value = 35

    canvas = bytearray(
        [background]
        * (atlas_width * atlas_height)
    )

    palette_values = []

    for red, green, blue, alpha in palette:
        if alpha == 0:
            palette_values.append(background)
            continue

        luminance = (
            299 * red
            + 587 * green
            + 114 * blue
        ) // 1000

        palette_values.append(luminance)

    # 셀 경계
    for column in range(columns + 1):
        x = min(
            column * cell_width,
            atlas_width - 1,
        )

        for y in range(atlas_height):
            canvas[
                y * atlas_width + x
            ] = grid_value

    for row in range(rows + 1):
        y = min(
            row * cell_height,
            atlas_height - 1,
        )

        row_start = y * atlas_width

        for x in range(atlas_width):
            canvas[
                row_start + x
            ] = grid_value

    for glyph_index in range(glyph_count):
        column = glyph_index % columns
        row = glyph_index // columns

        cell_x = column * cell_width
        cell_y = row * cell_height

        glyph_x = cell_x + 4
        glyph_y = cell_y + 2

        start = glyph_index * bytes_per_glyph
        end = start + bytes_per_glyph

        indices = decode_glyph(
            payload[start:end],
            glyph_width,
            glyph_height,
            low_nibble_first,
        )

        for source_y in range(glyph_height):
            for source_x in range(glyph_width):
                palette_index = indices[
                    source_y * glyph_width
                    + source_x
                ]

                if palette_index >= len(palette_values):
                    value = 255
                else:
                    value = palette_values[
                        palette_index
                    ]

                for scale_y in range(glyph_scale):
                    for scale_x in range(glyph_scale):
                        target_x = (
                            glyph_x
                            + source_x * glyph_scale
                            + scale_x
                        )

                        target_y = (
                            glyph_y
                            + source_y * glyph_scale
                            + scale_y
                        )

                        canvas[
                            target_y * atlas_width
                            + target_x
                        ] = value

        label = f"{glyph_index:04X}"

        label_width = len(label) * 4 - 1

        label_x = (
            cell_x
            + (cell_width - label_width) // 2
        )

        label_y = cell_y + 35

        draw_hex_label(
            canvas,
            atlas_width,
            label_x,
            label_y,
            label,
        )

    save_grayscale_png(
        output_path,
        atlas_width,
        atlas_height,
        canvas,
    )

    print(
        "SAVED:",
        output_path,
        f"({atlas_width}x{atlas_height})",
    )


def main() -> int:
    if not INPUT_PATH.is_file():
        print(
            "ERROR: 파일이 없습니다:",
            INPUT_PATH,
        )
        return 1

    data = INPUT_PATH.read_bytes()

    if len(data) < 0x10:
        print("ERROR: font.fnt가 너무 작습니다.")
        return 1

    palette_count = struct.unpack_from(
        "<H",
        data,
        0x00,
    )[0]

    flags = struct.unpack_from(
        "<H",
        data,
        0x02,
    )[0]

    glyph_width = struct.unpack_from(
        "<I",
        data,
        0x04,
    )[0]

    packed_08 = struct.unpack_from(
        "<I",
        data,
        0x08,
    )[0]

    packed_0c = struct.unpack_from(
        "<I",
        data,
        0x0C,
    )[0]

    glyph_height = packed_08 & 0xFFFF
    value_08_high = packed_08 >> 16

    header_size = (
        0x10
        + palette_count * 4
    )

    palette = []

    for index in range(palette_count):
        offset = 0x10 + index * 4

        palette.append(
            struct.unpack_from(
                "<BBBB",
                data,
                offset,
            )
        )

    if (
        glyph_width <= 0
        or glyph_height <= 0
        or glyph_width * glyph_height % 2
    ):
        print(
            "ERROR: 4bpp 글리프 크기가 잘못됐습니다:",
            glyph_width,
            glyph_height,
        )
        return 1

    bytes_per_glyph = (
        glyph_width
        * glyph_height
        // 2
    )

    payload = data[header_size:]

    glyph_count, remainder = divmod(
        len(payload),
        bytes_per_glyph,
    )

    byte_histogram = Counter(payload)
    nibble_histogram = Counter()

    for value in payload:
        nibble_histogram[
            value & 0x0F
        ] += 1

        nibble_histogram[
            (value >> 4) & 0x0F
        ] += 1

    outside_palette = sum(
        count
        for value, count in nibble_histogram.items()
        if value >= palette_count
    )

    print("FONT.FNT STRUCTURE")
    print("==================")
    print(
        "FILE SIZE       :",
        f"0x{len(data):X}",
        len(data),
    )
    print(
        "PALETTE COUNT   :",
        palette_count,
    )
    print(
        "FLAGS           :",
        f"0x{flags:04X}",
    )
    print(
        "GLYPH WIDTH     :",
        glyph_width,
    )
    print(
        "GLYPH HEIGHT    :",
        glyph_height,
    )
    print(
        "VALUE 08 HIGH   :",
        value_08_high,
    )
    print(
        "VALUE 0C        :",
        f"0x{packed_0c:08X}",
    )
    print(
        "HEADER SIZE     :",
        f"0x{header_size:X}",
    )
    print(
        "PIXEL FORMAT    :",
        "4bpp packed",
    )
    print(
        "PAYLOAD SIZE    :",
        f"0x{len(payload):X}",
    )
    print(
        "BYTES PER GLYPH :",
        f"0x{bytes_per_glyph:X}",
    )
    print(
        "GLYPH COUNT     :",
        glyph_count,
        f"(0x{glyph_count:X})",
    )
    print(
        "REMAINDER       :",
        remainder,
    )
    print(
        "OUTSIDE PALETTE :",
        outside_palette,
    )

    print()
    print("PALETTE")
    print("=======")

    for index, rgba in enumerate(palette):
        print(
            f"[{index:02d}] "
            f"R={rgba[0]:3d} "
            f"G={rgba[1]:3d} "
            f"B={rgba[2]:3d} "
            f"A={rgba[3]:3d}"
        )

    print()
    print("NIBBLE HISTOGRAM")
    print("================")

    for value in sorted(nibble_histogram):
        print(
            f"{value:02X}: "
            f"{nibble_histogram[value]}"
        )

    print()
    print("PACKED BYTE RANGE")
    print("=================")
    print(
        "MIN:",
        f"0x{min(byte_histogram):02X}",
    )
    print(
        "MAX:",
        f"0x{max(byte_histogram):02X}",
    )

    if remainder != 0:
        print()
        print(
            "ERROR: 4bpp 글리프 크기로 "
            "정확히 나누어지지 않습니다."
        )
        return 1

    if outside_palette != 0:
        print()
        print(
            "ERROR: 실제 니블값이 팔레트 범위를 "
            "벗어납니다."
        )
        return 1

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    low_first_path = (
        OUTPUT_DIRECTORY
        / "font_fnt_atlas_low_first.png"
    )

    high_first_path = (
        OUTPUT_DIRECTORY
        / "font_fnt_atlas_high_first.png"
    )

    print()
    print("BUILDING ATLASES")
    print("================")

    build_atlas(
        payload=payload,
        palette=palette,
        glyph_width=glyph_width,
        glyph_height=glyph_height,
        glyph_count=glyph_count,
        bytes_per_glyph=bytes_per_glyph,
        low_nibble_first=True,
        output_path=low_first_path,
    )

    build_atlas(
        payload=payload,
        palette=palette,
        glyph_width=glyph_width,
        glyph_height=glyph_height,
        glyph_count=glyph_count,
        bytes_per_glyph=bytes_per_glyph,
        low_nibble_first=False,
        output_path=high_first_path,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
