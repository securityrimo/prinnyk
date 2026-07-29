from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from core.start_runtime import REQUIRED_RESOURCES, StartRuntimeArchive
from core.system_unpack import SystemUnpackError, unpack_system


def build_start_dat() -> bytes:
    names = sorted(REQUIRED_RESOURCES)
    count = len(names)
    table_size = count * 0x20
    table = bytearray(table_size)
    payload = bytearray()

    for index, name in enumerate(names):
        record_offset = index * 0x20
        data_offset = table_size + len(payload)
        struct.pack_into("<I", table, record_offset + 0x00, 0)
        struct.pack_into("<I", table, record_offset + 0x04, data_offset)
        encoded_name = name.encode("ascii")
        table[
            record_offset + 0x08:
            record_offset + 0x08 + len(encoded_name)
        ] = encoded_name
        payload.extend(bytes([index + 1]))

    struct.pack_into("<I", table, 0x00, count)
    return bytes(table + payload)


def build_lzs(raw: bytes, flag: int = 0xFE) -> bytes:
    encoded = bytearray()
    for byte in raw:
        encoded.append(byte)
        if byte == flag:
            encoded.append(flag)

    compressed_end = 0x10 + len(encoded)
    header = bytearray(0x10)
    header[0:4] = b"dat\x00"
    struct.pack_into("<I", header, 0x04, len(raw))
    struct.pack_into("<I", header, 0x08, compressed_end - 4)
    struct.pack_into("<I", header, 0x0C, flag)
    return bytes(header + encoded)


def build_nispack(name: str, blob: bytes) -> bytes:
    header = bytearray(0x10)
    header[0:7] = b"NISPACK"
    struct.pack_into("<I", header, 0x0C, 1)

    entry = bytearray(0x2C)
    encoded_name = name.encode("ascii")
    entry[0:len(encoded_name)] = encoded_name
    data_offset = 0x10 + 0x2C
    struct.pack_into("<I", entry, 0x20, data_offset)
    struct.pack_into("<I", entry, 0x24, len(blob))
    struct.pack_into("<I", entry, 0x28, 0)
    return bytes(header + entry + blob)


class SystemUnpackTest(unittest.TestCase):
    def test_unpack_and_idempotent_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            system_path = root / "SYSTEM.DAT"
            output = root / "SYSTEM_fixed"
            manifest_path = root / "system_unpack_manifest.json"

            start_dat = build_start_dat()
            start_lzs = build_lzs(start_dat)
            system_path.write_bytes(
                build_nispack("start.lzs", start_lzs)
            )

            first = unpack_system(
                system_path,
                output,
                manifest_path,
            )

            self.assertEqual(
                (output / "start.lzs").read_bytes(),
                start_lzs,
            )
            self.assertEqual(
                (output / "start.dat").read_bytes(),
                start_dat,
            )
            self.assertEqual(first["status"], "pass")
            self.assertEqual(
                first["outputs"]["start_dat"]["write_status"],
                "created",
            )

            archive = StartRuntimeArchive.load(
                output / "start.dat"
            )
            self.assertEqual(
                len(archive.records),
                len(REQUIRED_RESOURCES),
            )

            second = unpack_system(
                system_path,
                output,
                manifest_path,
            )
            self.assertEqual(
                second["outputs"]["start_lzs"]["write_status"],
                "unchanged",
            )
            self.assertEqual(
                second["outputs"]["start_dat"]["write_status"],
                "unchanged",
            )

            saved = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(saved["status"], "pass")

    def test_mismatched_existing_output_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            system_path = root / "SYSTEM.DAT"
            output = root / "SYSTEM_fixed"
            manifest_path = root / "system_unpack_manifest.json"

            start_dat = build_start_dat()
            system_path.write_bytes(
                build_nispack(
                    "start.lzs",
                    build_lzs(start_dat),
                )
            )
            output.mkdir(parents=True)
            (output / "start.dat").write_bytes(b"broken")

            with self.assertRaises(SystemUnpackError):
                unpack_system(
                    system_path,
                    output,
                    manifest_path,
                )

            result = unpack_system(
                system_path,
                output,
                manifest_path,
                force=True,
            )
            self.assertEqual(
                (output / "start.dat").read_bytes(),
                start_dat,
            )
            self.assertEqual(
                result["outputs"]["start_dat"]["write_status"],
                "overwritten",
            )


if __name__ == "__main__":
    unittest.main()
