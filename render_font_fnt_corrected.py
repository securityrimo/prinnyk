#!/usr/bin/env python3

import binascii
import math
import struct
import zlib
from pathlib import Path


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

OUTPUT_LOW = Path(
    "workspace/reports/font_corrected_low.png"
)

OUTPUT_HIGH = Path(
    "workspace/reports/font_corrected_high.png"
)


HEADER_SIZE = 0x50
PALETTE_OFFSET = 0x10
PALETTE_COUNT = 16

OUTPUT_COLUMNS = 32
SCALE = 2
BACKGROUND = 72


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


def decode_4bpp(
    packed: bytes,
    low_first: bool,
) -> bytearray:
    pixels = bytearray(len(packed) * 2)

    destination = 0

    for value in packed:
        low = value & 0x0F
        high = value >> 4

        if low_first:
            pixels[destination] = low
            pixels[destination + 1] = high
        else:
            pixels[destination] = high
            pixels[destination + 1] = low

        destination += 2

    return pixels


def make_grayscale_palette(
    data: bytes,
) -> list[int]:
    values = []

    for index in range(PALETTE_COUNT):
        red, green, blue, alpha = struct.unpack_from(
            "<BBBB",
            data,
            PALETTE_OFFSET + index * 4,
        )

        luminance = (
            red * 299
            + green * 587
            + blue * 114
        ) // 1000

        composited = (
            luminance * alpha
            + BACKGROUND * (255 - alpha)
        ) // 255

        values.append(composited)

    return values


def build_atlas(
    source_pixels: bytearray,
    source_width: int,
    glyph_width: int,
    glyph_height: int,
    source_columns: int,
    glyph_count: int,
    palette: list[int],
    output_path: Path,
) -> None:
    output_rows = math.ceil(
        glyph_count / OUTPUT_COLUMNS
    )

    output_width = (
        OUTPUT_COLUMNS
        * glyph_width
        * SCALE
    )

    output_height = (
        output_rows
        * glyph_height
        * SCALE
    )

    canvas = bytearray(
        [BACKGROUND]
        * output_width
        * output_height
    )

    for glyph_index in range(glyph_count):
        source_column = (
            glyph_index % source_columns
        )

        source_row = (
            glyph_index // source_columns
        )

        source_x = (
            source_column * glyph_width
        )

        source_y = (
            source_row * glyph_height
        )

        output_column = (
            glyph_index % OUTPUT_COLUMNS
        )

        output_row = (
            glyph_index // OUTPUT_COLUMNS
        )

        output_x = (
            output_column
            * glyph_width
            * SCALE
        )

        output_y = (
            output_row
            * glyph_height
            * SCALE
        )

        for y in range(glyph_height):
            source_row_offset = (
                source_y + y
            ) * source_width

            for x in range(glyph_width):
                palette_index = source_pixels[
                    source_row_offset
                    + source_x
                    + x
                ]

                value = palette[
                    palette_index
                ]

                for scale_y in range(SCALE):
                    for scale_x in range(SCALE):
                        target_x = (
                            output_x
                            + x * SCALE
                            + scale_x
                        )

                        target_y = (
                            output_y
                            + y * SCALE
                            + scale_y
                        )

                        canvas[
                            target_y * output_width
                            + target_x
                        ] = value

    save_grayscale_png(
        output_path,
        output_width,
        output_height,
        canvas,
    )

    print(
        "SAVED:",
        output_path,
        f"({output_width}x{output_height})",
    )


def main() -> int:
    data = INPUT_PATH.read_bytes()

    glyph_height = struct.unpack_from(
        "<H",
        data,
        0x00,
    )[0]

    stride_and_flags = struct.unpack_from(
        "<H",
        data,
        0x02,
    )[0]

    glyph_width = struct.unpack_from(
        "<I",
        data,
        0x04,
    )[0]

    declared_colors = struct.unpack_from(
        "<H",
        data,
        0x08,
    )[0]

    row_bytes = (
        stride_and_flags
        & 0x7FFF
    )

    flags = (
        stride_and_flags
        & 0x8000
    )

    payload = data[HEADER_SIZE:]

    if row_bytes == 0:
        raise ValueError(
            "행 바이트 수가 0입니다."
        )

    if len(payload) % row_bytes:
        raise ValueError(
            f"픽셀 데이터가 행 크기로 나누어지지 않습니다: "
            f"0x{len(payload):X} / 0x{row_bytes:X}"
        )

    surface_width = row_bytes * 2
    surface_height = len(payload) // row_bytes

    if surface_width % glyph_width:
        raise ValueError(
            f"표면 폭이 글리프 폭으로 나누어지지 않습니다: "
            f"{surface_width} / {glyph_width}"
        )

    if surface_height % glyph_height:
        raise ValueError(
            f"표면 높이가 글리프 높이로 나누어지지 않습니다: "
            f"{surface_height} / {glyph_height}"
        )

    source_columns = (
        surface_width // glyph_width
    )

    source_rows = (
        surface_height // glyph_height
    )

    glyph_count = (
        source_columns * source_rows
    )

    palette = make_grayscale_palette(data)

    print("CORRECTED FONT.FNT STRUCTURE")
    print("============================")
    print("FILE SIZE        :", f"0x{len(data):X}")
    print("HEADER SIZE      :", f"0x{HEADER_SIZE:X}")
    print("GLYPH WIDTH      :", glyph_width)
    print("GLYPH HEIGHT     :", glyph_height)
    print("DECLARED COLORS  :", declared_colors)
    print("STRIDE RAW       :", f"0x{stride_and_flags:04X}")
    print("ROW BYTES        :", f"0x{row_bytes:X}", row_bytes)
    print("FLAGS            :", f"0x{flags:04X}")
    print("PIXEL FORMAT     :", "4bpp linear")
    print(
        "SURFACE SIZE     :",
        f"{surface_width}x{surface_height}",
    )
    print("SOURCE COLUMNS   :", source_columns)
    print("SOURCE ROWS      :", source_rows)
    print("GLYPH COUNT      :", glyph_count)
    print(
        "PAYLOAD CHECK    :",
        "OK"
        if row_bytes * surface_height == len(payload)
        else "FAILED",
    )

    low_pixels = decode_4bpp(
        payload,
        low_first=True,
    )

    high_pixels = decode_4bpp(
        payload,
        low_first=False,
    )

    build_atlas(
        source_pixels=low_pixels,
        source_width=surface_width,
        glyph_width=glyph_width,
        glyph_height=glyph_height,
        source_columns=source_columns,
        glyph_count=glyph_count,
        palette=palette,
        output_path=OUTPUT_LOW,
    )

    build_atlas(
        source_pixels=high_pixels,
        source_width=surface_width,
        glyph_width=glyph_width,
        glyph_height=glyph_height,
        source_columns=source_columns,
        glyph_count=glyph_count,
        palette=palette,
        output_path=OUTPUT_HIGH,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
