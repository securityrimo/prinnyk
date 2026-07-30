#!/usr/bin/env python3

import binascii
import struct
import zlib
from pathlib import Path


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.txp"
)

OUTPUT_PATH = Path(
    "workspace/reports/font_txp_page_compare.png"
)


GRID_COLUMNS = 13
GRID_ROWS = 6

CELL_WIDTH = 92
CELL_HEIGHT = 100
PREVIEW_SIZE = 84
PANEL_HEADER = 18
PANEL_GAP = 20

CANVAS_BACKGROUND = 18
PANEL_BACKGROUND = 26
CELL_BORDER = 58


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


def save_rgb_png(
    path: Path,
    width: int,
    height: int,
    pixels: bytearray,
) -> None:
    if len(pixels) != width * height * 3:
        raise ValueError(
            f"RGB 크기 오류: {len(pixels)}"
        )

    scanlines = bytearray()

    row_size = width * 3

    for y in range(height):
        scanlines.append(0)

        start = y * row_size

        scanlines.extend(
            pixels[start:start + row_size]
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
                2,
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


def set_gray(
    canvas: bytearray,
    canvas_width: int,
    x: int,
    y: int,
    value: int,
) -> None:
    position = (
        y * canvas_width + x
    ) * 3

    canvas[position] = value
    canvas[position + 1] = value
    canvas[position + 2] = value


def fill_rectangle(
    canvas: bytearray,
    canvas_width: int,
    x: int,
    y: int,
    width: int,
    height: int,
    value: int,
) -> None:
    for target_y in range(y, y + height):
        row_position = (
            target_y * canvas_width + x
        ) * 3

        for _ in range(width):
            canvas[row_position] = value
            canvas[row_position + 1] = value
            canvas[row_position + 2] = value
            row_position += 3


def draw_hex(
    canvas: bytearray,
    canvas_width: int,
    x: int,
    y: int,
    text: str,
    scale: int = 2,
    value: int = 225,
) -> None:
    cursor_x = x

    for character in text:
        pattern = HEX_FONT[character]

        for pattern_y, row in enumerate(pattern):
            for pattern_x, bit in enumerate(row):
                if bit != "1":
                    continue

                for scale_y in range(scale):
                    for scale_x in range(scale):
                        set_gray(
                            canvas,
                            canvas_width,
                            cursor_x
                            + pattern_x * scale
                            + scale_x,
                            y
                            + pattern_y * scale
                            + scale_y,
                            value,
                        )

        cursor_x += 4 * scale


def unswizzle_psp(
    source: bytes,
    width_bytes: int,
    height: int,
) -> bytes:
    """
    PSP 기본 swizzle:
        블록 가로 16바이트
        블록 세로 8행
    """

    if (
        width_bytes < 16
        or height < 8
        or width_bytes % 16 != 0
        or height % 8 != 0
    ):
        return source

    expected_size = width_bytes * height

    if len(source) != expected_size:
        raise ValueError(
            f"swizzle 크기 오류: "
            f"{len(source)} != {expected_size}"
        )

    destination = bytearray(expected_size)

    blocks_x = width_bytes // 16
    blocks_y = height // 8

    source_position = 0

    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            for row in range(8):
                destination_position = (
                    (block_y * 8 + row)
                    * width_bytes
                    + block_x * 16
                )

                destination[
                    destination_position:
                    destination_position + 16
                ] = source[
                    source_position:
                    source_position + 16
                ]

                source_position += 16

    return bytes(destination)


def decode_indices(
    packed_pixels: bytes,
    width: int,
    height: int,
    bits_per_pixel: int,
    low_nibble_first: bool,
) -> list[int]:
    pixel_count = width * height

    if bits_per_pixel == 8:
        if len(packed_pixels) != pixel_count:
            raise ValueError(
                f"8bpp 크기 오류: "
                f"{len(packed_pixels)} != {pixel_count}"
            )

        return list(packed_pixels)

    expected_size = (pixel_count + 1) // 2

    if len(packed_pixels) != expected_size:
        raise ValueError(
            f"4bpp 크기 오류: "
            f"{len(packed_pixels)} != {expected_size}"
        )

    indices = []

    for value in packed_pixels:
        low = value & 0x0F
        high = (value >> 4) & 0x0F

        if low_nibble_first:
            indices.extend((low, high))
        else:
            indices.extend((high, low))

    return indices[:pixel_count]


def make_palette_values(
    palette_data: bytes,
    color_count: int,
    bank_count: int,
) -> list[int]:
    """
    채널 순서와 팔레트 뱅크가 아직 미확정이므로
    각 색상의 RGBA 네 바이트 중 최댓값을 밝기로 사용한다.

    여러 팔레트 뱅크가 있으면 동일 인덱스 중 가장 밝은 값을 사용한다.
    """

    banks = []

    for bank_index in range(bank_count):
        bank = []

        bank_start = (
            bank_index
            * color_count
            * 4
        )

        for color_index in range(color_count):
            offset = (
                bank_start
                + color_index * 4
            )

            color = palette_data[
                offset:
                offset + 4
            ]

            bank.append(max(color))

        banks.append(bank)

    values = []

    for color_index in range(color_count):
        values.append(
            max(
                bank[color_index]
                for bank in banks
            )
        )

    minimum = min(values)
    maximum = max(values)

    if maximum == minimum:
        return [20] * color_count

    return [
        20
        + (
            (value - minimum)
            * 235
            // (maximum - minimum)
        )
        for value in values
    ]


def decode_page(
    data: bytes,
    offset: int,
    unswizzle: bool,
    low_nibble_first: bool,
) -> dict:
    (
        declared_size,
        width,
        height,
        color_count,
        log2_width,
        log2_height,
        bank_count,
    ) = struct.unpack_from(
        "<IHHHBBI",
        data,
        offset,
    )

    if color_count == 16:
        bits_per_pixel = 4
    elif color_count == 256:
        bits_per_pixel = 8
    else:
        raise ValueError(
            f"지원하지 않는 색상 수: "
            f"{color_count}"
        )

    palette_size = (
        color_count
        * 4
        * bank_count
    )

    pixel_offset = (
        offset
        + 0x10
        + palette_size
    )

    pixel_size = (
        width
        * height
        * bits_per_pixel
        // 8
    )

    calculated_size = (
        0x10
        + palette_size
        + pixel_size
    )

    if declared_size != calculated_size:
        raise ValueError(
            f"페이지 크기 불일치: "
            f"0x{declared_size:X} != "
            f"0x{calculated_size:X}"
        )

    palette_data = data[
        offset + 0x10:
        offset + 0x10 + palette_size
    ]

    packed_pixels = data[
        pixel_offset:
        pixel_offset + pixel_size
    ]

    width_bytes = (
        width
        if bits_per_pixel == 8
        else width // 2
    )

    if unswizzle:
        packed_pixels = unswizzle_psp(
            packed_pixels,
            width_bytes,
            height,
        )

    indices = decode_indices(
        packed_pixels,
        width,
        height,
        bits_per_pixel,
        low_nibble_first,
    )

    palette_values = make_palette_values(
        palette_data,
        color_count,
        bank_count,
    )

    pixels = [
        palette_values[index]
        if index < len(palette_values)
        else 255
        for index in indices
    ]

    return {
        "width": width,
        "height": height,
        "pixels": pixels,
        "bits_per_pixel": bits_per_pixel,
        "color_count": color_count,
        "bank_count": bank_count,
        "log2_width": log2_width,
        "log2_height": log2_height,
    }


def draw_preview(
    canvas: bytearray,
    canvas_width: int,
    target_x: int,
    target_y: int,
    page: dict,
) -> None:
    source_width = page["width"]
    source_height = page["height"]
    source_pixels = page["pixels"]

    scale = min(
        PREVIEW_SIZE / source_width,
        PREVIEW_SIZE / source_height,
    )

    target_width = max(
        1,
        int(source_width * scale),
    )

    target_height = max(
        1,
        int(source_height * scale),
    )

    preview_x = (
        target_x
        + (PREVIEW_SIZE - target_width) // 2
    )

    preview_y = (
        target_y
        + (PREVIEW_SIZE - target_height) // 2
    )

    for y in range(target_height):
        source_y = min(
            source_height - 1,
            y * source_height // target_height,
        )

        for x in range(target_width):
            source_x = min(
                source_width - 1,
                x * source_width // target_width,
            )

            value = source_pixels[
                source_y * source_width
                + source_x
            ]

            set_gray(
                canvas,
                canvas_width,
                preview_x + x,
                preview_y + y,
                value,
            )


def draw_panel(
    canvas: bytearray,
    canvas_width: int,
    panel_x: int,
    panel_y: int,
    panel_letter: str,
    data: bytes,
    group_ids: list[int],
    page_offsets: list[int],
    unswizzle: bool,
    low_nibble_first: bool,
) -> None:
    panel_width = GRID_COLUMNS * CELL_WIDTH
    panel_height = (
        PANEL_HEADER
        + GRID_ROWS * CELL_HEIGHT
    )

    fill_rectangle(
        canvas,
        canvas_width,
        panel_x,
        panel_y,
        panel_width,
        panel_height,
        PANEL_BACKGROUND,
    )

    draw_hex(
        canvas,
        canvas_width,
        panel_x + 5,
        panel_y + 3,
        panel_letter,
        scale=3,
        value=245,
    )

    for page_index, (group_id, offset) in enumerate(
        zip(group_ids, page_offsets)
    ):
        column = page_index % GRID_COLUMNS
        row = page_index // GRID_COLUMNS

        cell_x = (
            panel_x
            + column * CELL_WIDTH
        )

        cell_y = (
            panel_y
            + PANEL_HEADER
            + row * CELL_HEIGHT
        )

        # 셀 테두리
        for x in range(CELL_WIDTH):
            set_gray(
                canvas,
                canvas_width,
                cell_x + x,
                cell_y,
                CELL_BORDER,
            )

            set_gray(
                canvas,
                canvas_width,
                cell_x + x,
                cell_y + CELL_HEIGHT - 1,
                CELL_BORDER,
            )

        for y in range(CELL_HEIGHT):
            set_gray(
                canvas,
                canvas_width,
                cell_x,
                cell_y + y,
                CELL_BORDER,
            )

            set_gray(
                canvas,
                canvas_width,
                cell_x + CELL_WIDTH - 1,
                cell_y + y,
                CELL_BORDER,
            )

        page = decode_page(
            data,
            offset,
            unswizzle,
            low_nibble_first,
        )

        draw_preview(
            canvas,
            canvas_width,
            cell_x + 4,
            cell_y + 3,
            page,
        )

        # 앞 두 자리: 페이지 번호
        # 뒤 두 자리: 그룹 ID
        label = (
            f"{page_index:02X}"
            f"{group_id:02X}"
        )

        draw_hex(
            canvas,
            canvas_width,
            cell_x + 30,
            cell_y + 88,
            label,
            scale=2,
            value=220,
        )


def main() -> int:
    if not INPUT_PATH.is_file():
        print(
            "ERROR: 파일이 없습니다:",
            INPUT_PATH,
        )
        return 1

    data = INPUT_PATH.read_bytes()

    group_count, record_count = struct.unpack_from(
        "<II",
        data,
        0x00,
    )

    group_ids_offset = 0x08

    record_offsets_offset = (
        group_ids_offset
        + group_count * 4
    )

    page_offsets_offset = (
        record_offsets_offset
        + record_count * 4
    )

    group_ids = list(
        struct.unpack_from(
            f"<{group_count}I",
            data,
            group_ids_offset,
        )
    )

    page_offsets = list(
        struct.unpack_from(
            f"<{group_count}I",
            data,
            page_offsets_offset,
        )
    )

    if group_count != GRID_COLUMNS * GRID_ROWS:
        raise ValueError(
            f"페이지 수가 예상과 다릅니다: "
            f"{group_count}"
        )

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
        [CANVAS_BACKGROUND]
        * canvas_width
        * canvas_height
        * 3
    )

    variants = [
        (
            0,
            0,
            "A",
            False,
            True,
        ),
        (
            panel_width + PANEL_GAP,
            0,
            "B",
            False,
            False,
        ),
        (
            0,
            panel_height + PANEL_GAP,
            "C",
            True,
            True,
        ),
        (
            panel_width + PANEL_GAP,
            panel_height + PANEL_GAP,
            "D",
            True,
            False,
        ),
    ]

    for (
        panel_x,
        panel_y,
        letter,
        unswizzle,
        low_first,
    ) in variants:
        print(
            f"{letter}: "
            f"{'PSP unswizzle' if unswizzle else 'linear'}, "
            f"{'low nibble first' if low_first else 'high nibble first'}"
        )

        draw_panel(
            canvas,
            canvas_width,
            panel_x,
            panel_y,
            letter,
            data,
            group_ids,
            page_offsets,
            unswizzle,
            low_first,
        )

    save_rgb_png(
        OUTPUT_PATH,
        canvas_width,
        canvas_height,
        canvas,
    )

    print()
    print("TXP PAGE SUMMARY")
    print("================")
    print("TOTAL PAGES:", group_count)
    print("4BPP PAGES  : 75")
    print("8BPP PAGES  : 3")
    print()
    print("LABEL FORMAT:")
    print("  앞 2자리 = 페이지 번호")
    print("  뒤 2자리 = 그룹 ID")
    print()
    print("SAVED:", OUTPUT_PATH)
    print(
        "SIZE :",
        f"{canvas_width}x{canvas_height}",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
