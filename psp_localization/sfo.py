from __future__ import annotations

import struct
from pathlib import Path
from typing import Any


class SFOError(ValueError):
    pass


def parse_sfo_bytes(data: bytes) -> dict[str, Any]:
    if len(data) < 0x14 or data[:4] != b"\x00PSF":
        raise SFOError("PARAM.SFO 매직이 아닙니다.")

    key_table_offset, data_table_offset, count = struct.unpack_from(
        "<III", data, 0x08
    )
    entry_offset = 0x14
    entry_size = 0x10
    if entry_offset + count * entry_size > len(data):
        raise SFOError("PARAM.SFO 색인이 파일 범위를 벗어납니다.")

    result: dict[str, Any] = {}
    for index in range(count):
        offset = entry_offset + index * entry_size
        key_offset, value_format, value_length, value_capacity, value_offset = (
            struct.unpack_from("<HHIII", data, offset)
        )
        key_start = key_table_offset + key_offset
        if key_start >= len(data):
            raise SFOError("PARAM.SFO 키 범위 오류")
        key_end = data.find(b"\x00", key_start)
        if key_end < 0:
            raise SFOError("PARAM.SFO 키 종료문자 누락")
        key = data[key_start:key_end].decode("utf-8", errors="replace")
        value_start = data_table_offset + value_offset
        value_end = value_start + value_length
        if value_end > len(data) or value_length > value_capacity:
            raise SFOError("PARAM.SFO 값 범위 오류")
        raw = data[value_start:value_end]

        if value_format == 0x0404 and len(raw) >= 4:
            value: Any = struct.unpack_from("<I", raw, 0)[0]
        elif value_format in {0x0004, 0x0204}:
            value = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        else:
            value = raw.hex(" ").upper()
        result[key] = value

    return result


def parse_sfo(path: Path) -> dict[str, Any]:
    return parse_sfo_bytes(path.read_bytes())
