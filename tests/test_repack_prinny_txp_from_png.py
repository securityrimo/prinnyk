import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.prinny_txp_preview import HEADER_SIZE, decode_txp
from scripts.repack_prinny_txp_from_png import repack


class RepackPrinnyTxpTest(unittest.TestCase):
    def make_txp(self, colors: int, pixels: bytes) -> bytes:
        data = bytearray(HEADER_SIZE + colors * 4 + len(pixels))
        struct.pack_into("<HHH", data, 0, 2, 2, colors)
        data[HEADER_SIZE:HEADER_SIZE + 4] = bytes((0, 0, 0, 0))
        data[HEADER_SIZE + 4:HEADER_SIZE + 8] = bytes((10, 20, 30, 40))
        data[-len(pixels):] = pixels
        return bytes(data)

    def test_unchanged_png_roundtrips_byte_exact_8bpp(self) -> None:
        original = self.make_txp(256, bytes((0, 1, 0, 1)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            txp = root / "original.txp"
            png = root / "edited.png"
            txp.write_bytes(original)
            decode_txp(txp).save(png)
            self.assertEqual(repack(txp, png), original)

    def test_rejects_color_outside_original_palette(self) -> None:
        original = self.make_txp(16, bytes((0x10, 0x10)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            txp = root / "original.txp"
            png = root / "edited.png"
            txp.write_bytes(original)
            image = decode_txp(txp)
            image.putpixel((0, 0), (255, 1, 2, 3))
            image.save(png)
            with self.assertRaisesRegex(ValueError, "팔레트에 없는 색"):
                repack(txp, png)

    def test_modified_existing_palette_color_repacks(self) -> None:
        original = self.make_txp(16, bytes((0x10, 0x10)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            txp = root / "original.txp"
            png = root / "edited.png"
            txp.write_bytes(original)
            image = decode_txp(txp)
            image.putpixel((0, 0), (10, 20, 30, 40))
            image.save(png)
            result = repack(txp, png)
        self.assertEqual(result[-2:], bytes((0x11, 0x10)))

    def test_padded_4bpp_unchanged_png_roundtrips_byte_exact(self) -> None:
        original = bytearray(HEADER_SIZE + 256 * 4 + 2)
        struct.pack_into("<HHH", original, 0, 2, 2, 16)
        original[HEADER_SIZE + 4:HEADER_SIZE + 8] = bytes((10, 20, 30, 40))
        original[-2:] = bytes((0x10, 0x10))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            txp = root / "padded4.txp"
            png = root / "unchanged.png"
            txp.write_bytes(original)
            decode_txp(txp).save(png)
            result = repack(txp, png)
        self.assertEqual(result, bytes(original))

    def test_swizzled_4bpp_unchanged_png_roundtrips_byte_exact(self) -> None:
        width, height = 32, 8
        original = bytearray(HEADER_SIZE + 256 * 4 + width * height // 2)
        struct.pack_into("<HHH", original, 0, width, height, 16)
        struct.pack_into("<H", original, 0x0C, 1)
        original[HEADER_SIZE + 4:HEADER_SIZE + 8] = bytes((10, 20, 30, 40))
        original[-(width * height // 2):] = bytes((0x10,)) * (width * height // 2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            txp = root / "swizzled4.txp"
            png = root / "unchanged.png"
            txp.write_bytes(original)
            decode_txp(txp).save(png)
            result = repack(txp, png)
        self.assertEqual(result, bytes(original))


if __name__ == "__main__":
    unittest.main()
