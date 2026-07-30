from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any


class NSFStringExtractor:
    """Legacy NSF string-table reader kept for ad-hoc inspection.

    The format used by the original script stores ``count`` table records at
    0x20. Each record is two little-endian integers, with the second value
    pointing into a string blob that follows the table.
    """

    def __init__(self, filename: str | Path):
        self.filename = Path(filename)
        self.data = self.filename.read_bytes()
        self.count = 0
        self.blob_size = 0
        self.table_offset = 0x20
        self.blob_offset = 0

    def parse_header(self, *, verbose: bool = True) -> None:
        if len(self.data) < self.table_offset:
            raise ValueError(f"NSF 헤더가 너무 작습니다: {self.filename}")

        self.blob_size = struct.unpack_from("<I", self.data, 4)[0]
        self.count = struct.unpack_from("<I", self.data, 8)[0]
        self.blob_offset = self.table_offset + self.count * 8

        if self.blob_offset > len(self.data):
            raise ValueError(
                "NSF 문자열 테이블이 파일 범위를 벗어납니다: "
                f"count={self.count}, table_end=0x{self.blob_offset:X}, "
                f"size=0x{len(self.data):X}"
            )

        if verbose:
            print(f"NSF count : {self.count}")
            print(f"헤더 +0x04 blob size : {self.blob_size} bytes")
            print(f"문자열 테이블 위치 : 0x{self.table_offset:X}")
            print(f"문자열 blob 위치 : 0x{self.blob_offset:X}")
            print(f"예상 파일 크기 : {self.blob_offset + self.blob_size}")
            print(f"실제 파일 크기 : {len(self.data)}")
            print(f"차이 : {len(self.data) - (self.blob_offset + self.blob_size)}")

    @staticmethod
    def clean_text(raw: bytes) -> str:
        result = bytearray()
        index = 0

        while index < len(raw):
            byte = raw[index]

            # Legacy three-byte commands observed by the original probe.
            if byte in {0x43, 0x32, 0x44}:
                index += min(3, len(raw) - index)
                continue
            if byte == 0x00:
                break
            if byte < 0x20:
                index += 1
                continue

            result.append(byte)
            index += 1

        return result.decode("shift_jis", errors="replace")

    def extract(self, *, verbose: bool = True) -> list[dict[str, Any]]:
        if self.blob_offset == 0:
            self.parse_header(verbose=verbose)

        result: list[dict[str, Any]] = []
        blob_end = min(len(self.data), self.blob_offset + self.blob_size)

        for index in range(self.count):
            _pointer, offset = struct.unpack_from(
                "<II", self.data, self.table_offset + index * 8
            )
            position = self.blob_offset + offset
            if not (self.blob_offset <= position < blob_end):
                continue

            chunk = self.data[position:min(position + 128, blob_end)]
            text = self.clean_text(chunk)
            result.append({"id": index, "offset": offset, "text": text})

            if verbose and index < 20:
                print(f"[{index:03}] 0x{offset:04X}")
                print(text)

        return result

    def save_json(self, out: str | Path) -> None:
        output = Path(out)
        output.parent.mkdir(parents=True, exist_ok=True)
        items = self.extract()
        output.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nSaved : {output}")
