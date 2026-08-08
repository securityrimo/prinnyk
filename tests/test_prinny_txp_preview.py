import struct
import tempfile
import unittest
from pathlib import Path

from scripts.prinny_txp_preview import (
    HEADER_SIZE,
    PALETTE_SIZE,
    decode_txp,
    swizzle_psp,
)


class PrinnyTxpPreviewTest(unittest.TestCase):
    def test_decodes_rgba_palette_and_pixels(self) -> None:
        data = bytearray(HEADER_SIZE + PALETTE_SIZE + 4)
        struct.pack_into("<HHH", data, 0, 2, 2, 256)
        data[HEADER_SIZE + 4:HEADER_SIZE + 8] = bytes((1, 2, 3, 4))
        data[-4:] = bytes((1, 0, 1, 0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txp"
            path.write_bytes(data)
            image = decode_txp(path)
        self.assertEqual(image.size, (2, 2))
        self.assertEqual(image.getpixel((0, 0)), (1, 2, 3, 4))
        self.assertEqual(image.getpixel((1, 0)), (0, 0, 0, 0))

    def test_rejects_unknown_layout(self) -> None:
        data = bytearray(HEADER_SIZE + PALETTE_SIZE + 3)
        struct.pack_into("<HHH", data, 0, 2, 2, 256)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.txp"
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                decode_txp(path)

    def test_decodes_4bpp_pixels(self) -> None:
        data = bytearray(HEADER_SIZE + 16 * 4 + 2)
        struct.pack_into("<HHH", data, 0, 2, 2, 16)
        data[HEADER_SIZE + 4:HEADER_SIZE + 8] = bytes((9, 8, 7, 6))
        data[-2:] = bytes((0x10, 0x01))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample4.txp"
            path.write_bytes(data)
            image = decode_txp(path)
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))
        self.assertEqual(image.getpixel((1, 0)), (9, 8, 7, 6))

    def test_decodes_4bpp_with_256_entry_palette_allocation(self) -> None:
        data = bytearray(HEADER_SIZE + PALETTE_SIZE + 2)
        struct.pack_into("<HHH", data, 0, 2, 2, 16)
        data[HEADER_SIZE + 4:HEADER_SIZE + 8] = bytes((9, 8, 7, 6))
        data[-2:] = bytes((0x10, 0x01))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "padded4.txp"
            path.write_bytes(data)
            image = decode_txp(path)
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))
        self.assertEqual(image.getpixel((1, 0)), (9, 8, 7, 6))

    def test_decodes_psp_swizzled_8bpp_pixels(self) -> None:
        width, height = 16, 8
        linear = bytes(range(width * height))
        data = bytearray(HEADER_SIZE + PALETTE_SIZE + len(linear))
        struct.pack_into("<HHH", data, 0, width, height, 256)
        struct.pack_into("<H", data, 0x0C, 1)
        for index in range(256):
            data[HEADER_SIZE + index * 4:HEADER_SIZE + index * 4 + 4] = bytes(
                (index, 0, 0, 255)
            )
        data[-len(linear):] = swizzle_psp(linear, width, height)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "swizzled.txp"
            path.write_bytes(data)
            image = decode_txp(path)
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 255))
        self.assertEqual(image.getpixel((15, 7)), (127, 0, 0, 255))


if __name__ == "__main__":
    unittest.main()
