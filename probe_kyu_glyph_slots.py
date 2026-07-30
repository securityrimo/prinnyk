#!/usr/bin/env python3
from pathlib import Path
from PIL import Image

TXP = Path("workspace/unpack/START_runtime/font.txp")
OUT = Path("workspace/reports/kyu_glyph_candidates.png")

PIXEL_OFFSET = 0x50
GLYPH_WIDTH = 20
GLYPH_HEIGHT = 14
BYTES_PER_GLYPH = 140

# font.fnt 값 주변과, 런타임 변환 가능성이 있는 범위를 우선 확인
CANDIDATES = list(range(0x0300, 0x0341))

data = TXP.read_bytes()


def decode_glyph(index: int) -> Image.Image:
    start = PIXEL_OFFSET + index * BYTES_PER_GLYPH
    raw = data[start:start + BYTES_PER_GLYPH]

    if len(raw) != BYTES_PER_GLYPH:
        raise ValueError(f"슬롯 범위 오류: 0x{index:04X}")

    image = Image.new("L", (GLYPH_WIDTH, GLYPH_HEIGHT), 0)
    position = 0

    for y in range(GLYPH_HEIGHT):
        for x in range(0, GLYPH_WIDTH, 2):
            value = raw[position]
            position += 1

            image.putpixel((x, y), (value & 0x0F) * 17)
            image.putpixel((x + 1, y), ((value >> 4) & 0x0F) * 17)

    return image


scale = 6
cell_width = GLYPH_WIDTH * scale + 24
cell_height = GLYPH_HEIGHT * scale + 24
columns = 8
rows = (len(CANDIDATES) + columns - 1) // columns

sheet = Image.new(
    "L",
    (columns * cell_width, rows * cell_height),
    32,
)

for number, index in enumerate(CANDIDATES):
    glyph = decode_glyph(index).resize(
        (GLYPH_WIDTH * scale, GLYPH_HEIGHT * scale),
        Image.Resampling.NEAREST,
    )

    x = number % columns * cell_width
    y = number // columns * cell_height

    sheet.paste(glyph, (x, y))

    # 숫자는 터미널 출력 순서와 대조
    print(
        f"{number + 1:2d}: "
        f"slot=0x{index:04X} "
        f"offset=0x{PIXEL_OFFSET + index * BYTES_PER_GLYPH:X}"
    )

OUT.parent.mkdir(parents=True, exist_ok=True)
sheet.save(OUT)

print()
print("OUTPUT:", OUT)
