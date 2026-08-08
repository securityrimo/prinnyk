#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

try:
    from scripts.prinny_txp_preview import swizzle_psp, unswizzle_psp
except ModuleNotFoundError:  # 직접 `python scripts/...py` 실행 경로
    from prinny_txp_preview import swizzle_psp, unswizzle_psp


CONTAINER_HEADER_SIZE = 0x10
TEXTURE_DESCRIPTOR_TAIL = bytes.fromhex("04 10 10 01")
TEXTURE_DESCRIPTOR_SIZE = 0x0C
PALETTE_SIZE = 16 * 4


@dataclass(frozen=True)
class AnimeObject:
    index: int
    offset: int
    size: int
    end: int


@dataclass(frozen=True)
class AnimeTexture:
    object_index: int
    group_index: int
    page_index: int
    descriptor_offset: int
    pixel_offset: int
    width: int
    height: int
    palette_offset: int


def parse_objects(data: bytes) -> list[AnimeObject]:
    if len(data) < CONTAINER_HEADER_SIZE:
        raise ValueError("anime 컨테이너가 헤더보다 작습니다.")
    count = struct.unpack_from("<I", data, 0)[0]
    if count <= 0 or count > 4096:
        raise ValueError(f"잘못된 anime 오브젝트 수: {count}")
    objects: list[AnimeObject] = []
    offset = CONTAINER_HEADER_SIZE
    for index in range(count):
        if offset + 4 > len(data):
            raise ValueError(f"anime 오브젝트 {index} 크기 필드가 범위를 벗어납니다.")
        size = struct.unpack_from("<I", data, offset)[0]
        end = offset + size
        if size < 0x20 or end > len(data):
            raise ValueError(
                f"anime 오브젝트 {index} 범위 오류: offset=0x{offset:X}, size=0x{size:X}"
            )
        objects.append(AnimeObject(index, offset, size, end))
        offset = end
    if offset != len(data):
        raise ValueError(
            f"anime 오브젝트 끝 불일치: parsed=0x{offset:X}, file=0x{len(data):X}"
        )
    return objects


def find_texture_groups(data: bytes, obj: AnimeObject) -> list[list[AnimeTexture]]:
    candidates: list[tuple[int, int, int, int]] = []
    at = obj.offset
    while True:
        tail = data.find(TEXTURE_DESCRIPTOR_TAIL, at, obj.end)
        if tail < 0:
            break
        descriptor = tail - 8
        at = tail + 1
        if descriptor < obj.offset or descriptor + TEXTURE_DESCRIPTOR_SIZE > obj.end:
            continue
        relative_pixel = struct.unpack_from("<I", data, descriptor)[0]
        width, height = struct.unpack_from("<HH", data, descriptor + 4)
        pixel_offset = obj.offset + relative_pixel
        pixel_size = width * height // 2
        if (
            width <= 0
            or height <= 0
            or width > 2048
            or height > 2048
            or width % 32
            or height % 8
            or pixel_offset < obj.offset
            or pixel_offset + pixel_size > obj.end
            or descriptor >= pixel_offset
        ):
            continue
        candidates.append((descriptor, pixel_offset, width, height))

    raw_groups: list[list[tuple[int, int, int, int]]] = []
    for candidate in candidates:
        if raw_groups and candidate[0] == raw_groups[-1][-1][0] + TEXTURE_DESCRIPTOR_SIZE:
            raw_groups[-1].append(candidate)
        else:
            raw_groups.append([candidate])

    groups: list[list[AnimeTexture]] = []
    for group_index, raw_group in enumerate(raw_groups):
        palette_offset = min(row[1] for row in raw_group) - PALETTE_SIZE
        if palette_offset < obj.offset:
            continue
        group = [
            AnimeTexture(
                object_index=obj.index,
                group_index=group_index,
                page_index=page_index,
                descriptor_offset=descriptor,
                pixel_offset=pixel_offset,
                width=width,
                height=height,
                palette_offset=palette_offset,
            )
            for page_index, (descriptor, pixel_offset, width, height) in enumerate(raw_group)
        ]
        groups.append(group)
    return groups


def decode_texture(data: bytes, texture: AnimeTexture) -> Image.Image:
    palette = [
        tuple(data[offset:offset + 4])
        for offset in range(
            texture.palette_offset,
            texture.palette_offset + PALETTE_SIZE,
            4,
        )
    ]
    pixel_size = texture.width * texture.height // 2
    packed = data[texture.pixel_offset:texture.pixel_offset + pixel_size]
    linear = unswizzle_psp(packed, texture.width // 2, texture.height)
    indices = [
        nibble
        for value in linear
        for nibble in (value & 0x0F, value >> 4)
    ]
    rgba = bytearray(texture.width * texture.height * 4)
    for index, palette_index in enumerate(indices):
        rgba[index * 4:index * 4 + 4] = bytes(palette[palette_index])
    return Image.frombytes("RGBA", (texture.width, texture.height), bytes(rgba))


def repack_texture(data: bytes, texture: AnimeTexture, edited: Image.Image) -> bytes:
    rgba = edited.convert("RGBA")
    if rgba.size != (texture.width, texture.height):
        raise ValueError(
            f"anime PNG 크기가 다릅니다: {rgba.size} != "
            f"{(texture.width, texture.height)}"
        )
    palette = [
        tuple(data[offset:offset + 4])
        for offset in range(
            texture.palette_offset,
            texture.palette_offset + PALETTE_SIZE,
            4,
        )
    ]
    color_to_indices: dict[tuple[int, int, int, int], list[int]] = {}
    for index, color in enumerate(palette):
        color_to_indices.setdefault(color, []).append(index)

    original = decode_texture(data, texture)
    pixel_size = texture.width * texture.height // 2
    source_packed = data[texture.pixel_offset:texture.pixel_offset + pixel_size]
    source_linear = unswizzle_psp(source_packed, texture.width // 2, texture.height)
    source_indices = [
        nibble
        for value in source_linear
        for nibble in (value & 0x0F, value >> 4)
    ]
    output_indices: list[int] = []
    for position, color in enumerate(rgba.getdata()):
        x = position % texture.width
        y = position // texture.width
        if color == original.getpixel((x, y)):
            output_indices.append(source_indices[position])
            continue
        candidates = color_to_indices.get(color)
        if not candidates:
            raise ValueError(
                f"anime 팔레트에 없는 색입니다: ({x},{y}) RGBA={color}"
            )
        output_indices.append(candidates[0])
    linear = bytes(
        output_indices[offset] | (output_indices[offset + 1] << 4)
        for offset in range(0, len(output_indices), 2)
    )
    packed = swizzle_psp(linear, texture.width // 2, texture.height)
    result = bytearray(data)
    result[texture.pixel_offset:texture.pixel_offset + pixel_size] = packed
    return bytes(result)


def export_anime(source: Path, output: Path) -> dict[str, object]:
    data = source.read_bytes()
    objects = parse_objects(data)
    rows: list[dict[str, int | str]] = []
    for obj in objects:
        for group in find_texture_groups(data, obj):
            for texture in group:
                relative = Path(f"object_{obj.index:03d}") / (
                    f"group_{texture.group_index:02d}_page_{texture.page_index:02d}.png"
                )
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                decode_texture(data, texture).save(target)
                row = asdict(texture)
                row["png"] = str(target)
                rows.append(row)
    report: dict[str, object] = {
        "format": "prinny_anime_preview_v1",
        "source": str(source),
        "source_size": len(data),
        "object_count": len(objects),
        "texture_page_count": len(rows),
        "textures": rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Prinny anime*.dat 내부 텍스처 PNG 추출")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = export_anime(args.source, args.output)
    print(f"objects: {report['object_count']}")
    print(f"texture pages: {report['texture_page_count']}")
    print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
