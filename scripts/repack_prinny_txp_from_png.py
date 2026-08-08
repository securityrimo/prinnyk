#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from PIL import Image

try:
    from scripts.prinny_txp_preview import swizzle_psp, txp_layout, unswizzle_psp
except ModuleNotFoundError:  # 직접 `python scripts/...py` 실행 경로
    from prinny_txp_preview import swizzle_psp, txp_layout, unswizzle_psp


HEADER_SIZE = 0x10


def unpack_indices(data: bytes, colors: int, pixel_count: int) -> list[int]:
    if colors == 256:
        return list(data[:pixel_count])
    if colors == 16:
        result = []
        for value in data:
            result.extend((value & 0x0F, value >> 4))
        return result[:pixel_count]
    raise ValueError(f"지원하지 않는 팔레트 크기: {colors}")


def pack_indices(indices: list[int], colors: int) -> bytes:
    if colors == 256:
        return bytes(indices)
    if colors == 16:
        if len(indices) % 2:
            raise ValueError("4bpp 픽셀 수가 홀수입니다.")
        return bytes(
            indices[offset] | (indices[offset + 1] << 4)
            for offset in range(0, len(indices), 2)
        )
    raise ValueError(f"지원하지 않는 팔레트 크기: {colors}")


def repack(original_txp: Path, edited_png: Path) -> bytes:
    original = original_txp.read_bytes()
    width, height, colors, pixel_offset, pixel_bytes, swizzled = txp_layout(original)
    active_palette_end = HEADER_SIZE + colors * 4
    pixel_count = width * height

    palette = [
        tuple(original[offset:offset + 4])
        for offset in range(HEADER_SIZE, active_palette_end, 4)
    ]
    original_pixels = original[pixel_offset:pixel_offset + pixel_bytes]
    row_bytes = width if colors == 256 else width // 2
    if swizzled:
        original_pixels = unswizzle_psp(original_pixels, row_bytes, height)
    original_indices = unpack_indices(original_pixels, colors, pixel_count)
    with Image.open(edited_png) as image:
        rgba = image.convert("RGBA")
    if rgba.size != (width, height):
        raise ValueError(
            f"PNG 크기가 원본과 다릅니다: {rgba.size} != {(width, height)}"
        )

    color_to_indices: dict[tuple[int, int, int, int], list[int]] = {}
    for index, color in enumerate(palette):
        color_to_indices.setdefault(color, []).append(index)
    edited_pixels = list(rgba.getdata())
    output_indices: list[int] = []
    for position, edited_color in enumerate(edited_pixels):
        old_index = original_indices[position]
        if edited_color == palette[old_index]:
            output_indices.append(old_index)
            continue
        candidates = color_to_indices.get(edited_color)
        if not candidates:
            x = position % width
            y = position // width
            raise ValueError(
                f"원본 팔레트에 없는 색입니다: ({x},{y}) RGBA={edited_color}"
            )
        output_indices.append(candidates[0])

    packed = pack_indices(output_indices, colors)
    if swizzled:
        packed = swizzle_psp(packed, row_bytes, height)
    result = original[:pixel_offset] + packed
    if len(result) != len(original) or result[:pixel_offset] != original[:pixel_offset]:
        raise ValueError("TXP 헤더·팔레트 또는 파일 크기가 변경됐습니다.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="편집 PNG를 동일 팔레트의 Prinny TXP로 내부 재삽입용 변환"
    )
    parser.add_argument("original_txp", type=Path)
    parser.add_argument("edited_png", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = repack(arguments.original_txp, arguments.edited_png)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(result)
    print(f"TXP: {len(result)} bytes -> {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
