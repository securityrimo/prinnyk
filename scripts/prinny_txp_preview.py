#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from PIL import Image


HEADER_SIZE = 0x10
PALETTE_COLORS = 256
PALETTE_SIZE = PALETTE_COLORS * 4
PIXEL_OFFSET = HEADER_SIZE + PALETTE_SIZE


def txp_layout(data: bytes) -> tuple[int, int, int, int, int, bool]:
    """Return dimensions, palette/layout sizes, and the PSP swizzle flag.

    Prinny stores some 4bpp textures in a 256-entry palette-sized allocation even
    though only the first 16 entries are addressable.  Both the compact and padded
    variants are observed in the game; no other trailing data is accepted here.
    """
    if len(data) < HEADER_SIZE + 16 * 4:
        raise ValueError("TXP가 헤더보다 작습니다.")
    width, height, palette_colors = struct.unpack_from("<HHH", data, 0)
    if width <= 0 or height <= 0:
        raise ValueError(f"잘못된 TXP 크기: {width}x{height}")
    if palette_colors not in {16, 256}:
        raise ValueError(f"지원하지 않는 팔레트 크기: {palette_colors}")
    pixel_bytes = width * height if palette_colors == 256 else width * height // 2
    compact_offset = HEADER_SIZE + palette_colors * 4
    padded_offset = HEADER_SIZE + PALETTE_SIZE
    matching_offsets = [
        offset
        for offset in dict.fromkeys((compact_offset, padded_offset))
        if len(data) == offset + pixel_bytes
    ]
    if len(matching_offsets) != 1:
        expected_sizes = sorted(
            {compact_offset + pixel_bytes, padded_offset + pixel_bytes}
        )
        raise ValueError(
            "지원하지 않는 TXP 레이아웃: "
            f"size={len(data)}, expected={expected_sizes}"
        )
    swizzled = struct.unpack_from("<H", data, 0x0C)[0] != 0
    return width, height, palette_colors, matching_offsets[0], pixel_bytes, swizzled


def unswizzle_psp(data: bytes, row_bytes: int, height: int) -> bytes:
    if row_bytes % 16 or height % 8 or len(data) != row_bytes * height:
        raise ValueError(
            f"지원하지 않는 PSP 스위즐 크기: row_bytes={row_bytes}, height={height}"
        )
    output = bytearray(len(data))
    blocks_per_row = row_bytes // 16
    for y in range(height):
        for x in range(row_bytes):
            block = (y // 8) * blocks_per_row + (x // 16)
            source = block * 128 + (y % 8) * 16 + (x % 16)
            output[y * row_bytes + x] = data[source]
    return bytes(output)


def swizzle_psp(data: bytes, row_bytes: int, height: int) -> bytes:
    if row_bytes % 16 or height % 8 or len(data) != row_bytes * height:
        raise ValueError(
            f"지원하지 않는 PSP 스위즐 크기: row_bytes={row_bytes}, height={height}"
        )
    output = bytearray(len(data))
    blocks_per_row = row_bytes // 16
    for y in range(height):
        for x in range(row_bytes):
            block = (y // 8) * blocks_per_row + (x // 16)
            target = block * 128 + (y % 8) * 16 + (x % 16)
            output[target] = data[y * row_bytes + x]
    return bytes(output)


def decode_txp(path: Path) -> Image.Image:
    data = path.read_bytes()
    try:
        width, height, palette_colors, pixel_offset, pixel_bytes, swizzled = txp_layout(data)
    except ValueError as error:
        raise ValueError(f"{error}: {path}") from error

    palette = [
        tuple(data[HEADER_SIZE + index * 4:HEADER_SIZE + index * 4 + 4])
        for index in range(palette_colors)
    ]
    packed_pixels = data[pixel_offset:pixel_offset + pixel_bytes]
    if swizzled:
        row_bytes = width if palette_colors == 256 else width // 2
        packed_pixels = unswizzle_psp(packed_pixels, row_bytes, height)
    if palette_colors == 256:
        pixels = packed_pixels
    else:
        pixels = bytes(
            nibble
            for value in packed_pixels
            for nibble in (value & 0x0F, value >> 4)
        )
    rgba = bytearray(width * height * 4)
    for index, palette_index in enumerate(pixels):
        rgba[index * 4:index * 4 + 4] = bytes(palette[palette_index])
    return Image.frombytes("RGBA", (width, height), bytes(rgba))


def main() -> int:
    parser = argparse.ArgumentParser(description="Prinny 8bpp TXP PNG 미리보기")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    for source in args.inputs:
        image = decode_txp(source)
        target = args.output / f"{source.stem}.png"
        image.save(target)
        print(f"{source.name}: {image.width}x{image.height} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
