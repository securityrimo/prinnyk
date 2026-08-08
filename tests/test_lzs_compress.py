import unittest

from core.lzs import (
    compress_buffer,
    compress_buffer_best,
    compress_buffer_runtime_safe,
    decompress_buffer,
)


class LZSCompressTest(unittest.TestCase):
    def test_roundtrip_mixed_and_overlapping_runs(self) -> None:
        raw = (
            bytes(range(256))
            + b"A" * 600
            + (b"ABCD" * 300)
            + bytes(range(255, -1, -1))
        )
        encoded = compress_buffer(raw, b"dat\x00")
        decoded, header = decompress_buffer(encoded)
        self.assertEqual(decoded, raw)
        self.assertEqual(header["decompressed_size"], len(raw))
        self.assertLess(len(encoded), len(raw))

    def test_deterministic_output(self) -> None:
        raw = (b"\x00\x01\x02\x03" * 1024) + b"tail"
        self.assertEqual(
            compress_buffer(raw, b"bin\x00"),
            compress_buffer(raw, b"bin\x00"),
        )

    def test_explicit_flag_roundtrip(self) -> None:
        raw = bytes([0x7F]) * 1024 + b"literal"
        encoded = compress_buffer(raw, b"bin\x00", flag=0x7F)
        decoded, header = decompress_buffer(encoded)
        self.assertEqual(decoded, raw)

    def test_best_window_roundtrip_and_determinism(self) -> None:
        raw = (b"ABCD" * 300) + bytes(range(256)) + (b"ABCD" * 300)
        first = compress_buffer_best(raw, b"bin\x00", flag=0x7F)
        second = compress_buffer_best(raw, b"bin\x00", flag=0x7F)
        decoded, header = decompress_buffer(first)
        self.assertEqual(first, second)
        self.assertEqual(decoded, raw)
        self.assertEqual(header["flag"], 0x7F)

    def test_runtime_safe_stream_has_no_overlapping_backreferences(self) -> None:
        raw = (b"A" * 600) + (b"ABCD" * 300) + bytes(range(256))
        encoded = compress_buffer_runtime_safe(raw, b"bin\x00", flag=0x7F)
        decoded, header = decompress_buffer(encoded)
        self.assertEqual(decoded, raw)
        self.assertEqual(header["flag"], 0x7F)

        position = 0x10
        end = header["compressed_end"]
        while position < end:
            token = encoded[position]
            position += 1
            if token != header["flag"]:
                continue
            second = encoded[position]
            position += 1
            if second == header["flag"]:
                continue
            length = encoded[position]
            position += 1
            distance = second if second < header["flag"] else second - 1
            self.assertLessEqual(length, distance)


if __name__ == "__main__":
    unittest.main()
