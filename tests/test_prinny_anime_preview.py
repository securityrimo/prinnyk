import struct
import tempfile
import unittest
from pathlib import Path

from scripts.prinny_anime_preview import (
    CONTAINER_HEADER_SIZE,
    PALETTE_SIZE,
    TEXTURE_DESCRIPTOR_TAIL,
    decode_texture,
    find_texture_groups,
    parse_objects,
    repack_texture,
)
from scripts.prinny_txp_preview import swizzle_psp


class PrinnyAnimePreviewTest(unittest.TestCase):
    def make_anime(self) -> bytes:
        width, height = 32, 8
        object_offset = CONTAINER_HEADER_SIZE
        descriptor = object_offset + 0x20
        pixel_relative = 0x80
        pixel_offset = object_offset + pixel_relative
        pixel_size = width * height // 2
        end = pixel_offset + pixel_size
        data = bytearray(end)
        struct.pack_into("<I", data, 0, 1)
        struct.pack_into("<I", data, object_offset, end - object_offset)
        struct.pack_into("<IHH", data, descriptor, pixel_relative, width, height)
        data[descriptor + 8:descriptor + 12] = TEXTURE_DESCRIPTOR_TAIL
        palette_offset = pixel_offset - PALETTE_SIZE
        data[palette_offset + 4:palette_offset + 8] = bytes((10, 20, 30, 40))
        linear = bytes((0x10,)) * pixel_size
        data[pixel_offset:end] = swizzle_psp(linear, width // 2, height)
        return bytes(data)

    def test_parses_and_decodes_texture(self) -> None:
        data = self.make_anime()
        objects = parse_objects(data)
        groups = find_texture_groups(data, objects[0])
        self.assertEqual(len(objects), 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 1)
        image = decode_texture(data, groups[0][0])
        self.assertEqual(image.size, (32, 8))
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))
        self.assertEqual(image.getpixel((1, 0)), (10, 20, 30, 40))

    def test_rejects_trailing_bytes_outside_objects(self) -> None:
        with self.assertRaisesRegex(ValueError, "끝 불일치"):
            parse_objects(self.make_anime() + b"\x00")

    def test_repack_unchanged_is_byte_exact_and_edit_uses_palette(self) -> None:
        data = self.make_anime()
        texture = find_texture_groups(data, parse_objects(data)[0])[0][0]
        image = decode_texture(data, texture)
        self.assertEqual(repack_texture(data, texture, image), data)
        image.putpixel((0, 0), (10, 20, 30, 40))
        changed = repack_texture(data, texture, image)
        self.assertEqual(changed[:texture.pixel_offset], data[:texture.pixel_offset])
        self.assertNotEqual(changed, data)
        self.assertEqual(decode_texture(changed, texture).getpixel((0, 0)), (10, 20, 30, 40))


if __name__ == "__main__":
    unittest.main()
