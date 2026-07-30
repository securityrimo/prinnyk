#!/usr/bin/env python3

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

OUTPUT_PATH = Path(
    "workspace/reports/font_index_0000_01FF.png"
)

BITMAP_OFFSET = 0xA0

GLYPH_WIDTH = 20
GLYPH_HEIGHT = 16
ROW_BYTES = GLYPH_WIDTH // 2
BYTES_PER_GLYPH = ROW_BYTES * GLYPH_HEIGHT

EXPECTED_GLYPH_COUNT = 2054

DEFAULT_START = 0x0000
DEFAULT_COUNT = 0x0200

COLUMNS = 16
SCALE = 3

LABEL_HEIGHT = 14
CELL_PADDING = 3

BACKGROUND = 18
CELL_BACKGROUND = 26
BORDER = 70
LABEL_COLOR = 230


def decode_glyph(packed: bytes) -> Image.Image:
    if len(packed) != BYTES_PER_GLYPH:
        raise ValueError(
            f"글리프 데이터 크기 오류: "
            f"{len(packed)} != {BYTES_PER_GLYPH}"
        )

    pixels = bytearray(
        GLYPH_WIDTH * GLYPH_HEIGHT
    )

    destination = 0

    for y in range(GLYPH_HEIGHT):
        row_offset = y * ROW_BYTES

        for byte_x in range(ROW_BYTES):
            value = packed[row_offset + byte_x]

            # 확인된 순서:
            # 왼쪽 픽셀 = 하위 니블
            # 오른쪽 픽셀 = 상위 니블
            first = value & 0x0F
            second = value >> 4

            pixels[destination] = intensity(first)
            pixels[destination + 1] = intensity(second)

            destination += 2

    image = Image.frombytes(
        "L",
        (GLYPH_WIDTH, GLYPH_HEIGHT),
        bytes(pixels),
    )

    return image.resize(
        (
            GLYPH_WIDTH * SCALE,
            GLYPH_HEIGHT * SCALE,
        ),
        Image.Resampling.NEAREST,
    )


def intensity(value: int) -> int:
    # 실제 글꼴은 주로 0~8 단계의 명암을 사용한다.
    if value <= 8:
        return (
            BACKGROUND
            + value * (255 - BACKGROUND) // 8
        )

    return 255


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prinny font.fnt의 글리프를 "
            "인덱스가 표시된 표로 출력합니다."
        )
    )

    parser.add_argument(
        "--start",
        type=lambda value: int(value, 0),
        default=DEFAULT_START,
    )

    parser.add_argument(
        "--count",
        type=lambda value: int(value, 0),
        default=DEFAULT_COUNT,
    )

    parser.add_argument(
        "--out",
        type=Path,
        default=OUTPUT_PATH,
    )

    args = parser.parse_args()

    data = INPUT_PATH.read_bytes()
    payload = data[BITMAP_OFFSET:]

    glyph_count, remainder = divmod(
        len(payload),
        BYTES_PER_GLYPH,
    )

    print("FONT INDEX ATLAS")
    print("================")
    print("FILE SIZE       :", f"0x{len(data):X}")
    print("BITMAP OFFSET   :", f"0x{BITMAP_OFFSET:X}")
    print(
        "GLYPH SIZE      :",
        f"{GLYPH_WIDTH}x{GLYPH_HEIGHT}",
    )
    print(
        "BYTES PER GLYPH:",
        f"0x{BYTES_PER_GLYPH:X}",
    )
    print("GLYPH COUNT     :", glyph_count)
    print("REMAINDER       :", remainder)

    if remainder != 0:
        raise ValueError(
            f"글리프 데이터 나머지가 있습니다: {remainder}"
        )

    if glyph_count != EXPECTED_GLYPH_COUNT:
        raise ValueError(
            f"예상 글리프 수와 다릅니다: "
            f"{glyph_count} != {EXPECTED_GLYPH_COUNT}"
        )

    if args.start < 0:
        raise ValueError(
            "시작 인덱스는 0 이상이어야 합니다."
        )

    end = min(
        args.start + args.count,
        glyph_count,
    )

    if args.start >= end:
        raise ValueError(
            "출력할 글리프 범위가 없습니다."
        )

    output_count = end - args.start
    rows = (
        output_count + COLUMNS - 1
    ) // COLUMNS

    glyph_draw_width = GLYPH_WIDTH * SCALE
    glyph_draw_height = GLYPH_HEIGHT * SCALE

    cell_width = (
        glyph_draw_width
        + CELL_PADDING * 2
    )

    cell_height = (
        glyph_draw_height
        + LABEL_HEIGHT
        + CELL_PADDING * 2
    )

    canvas = Image.new(
        "L",
        (
            COLUMNS * cell_width,
            rows * cell_height,
        ),
        color=BACKGROUND,
    )

    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    for output_index, glyph_index in enumerate(
        range(args.start, end)
    ):
        column = output_index % COLUMNS
        row = output_index // COLUMNS

        cell_x = column * cell_width
        cell_y = row * cell_height

        draw.rectangle(
            (
                cell_x,
                cell_y,
                cell_x + cell_width - 1,
                cell_y + cell_height - 1,
            ),
            fill=CELL_BACKGROUND,
            outline=BORDER,
        )

        source_start = (
            glyph_index * BYTES_PER_GLYPH
        )

        source_end = (
            source_start + BYTES_PER_GLYPH
        )

        glyph = decode_glyph(
            payload[source_start:source_end]
        )

        canvas.paste(
            glyph,
            (
                cell_x + CELL_PADDING,
                cell_y + CELL_PADDING,
            ),
        )

        label = f"{glyph_index:04X}"

        label_box = draw.textbbox(
            (0, 0),
            label,
            font=font,
        )

        label_width = (
            label_box[2] - label_box[0]
        )

        label_x = (
            cell_x
            + (cell_width - label_width) // 2
        )

        label_y = (
            cell_y
            + CELL_PADDING
            + glyph_draw_height
        )

        draw.text(
            (label_x, label_y),
            label,
            fill=LABEL_COLOR,
            font=font,
        )

    args.out.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    canvas.save(args.out)

    print("INDEX RANGE     :", f"0x{args.start:04X}~0x{end - 1:04X}")
    print("SAVED           :", args.out)
    print("IMAGE SIZE      :", f"{canvas.width}x{canvas.height}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
