"""
Nippon Ichi Software LZS 압축 해제기.

확인된 헤더:
    +0x00  출력 확장자 4바이트
    +0x04  압축 해제 크기 u32 LE
    +0x08  압축 크기 필드 u32 LE
    +0x0C  제어 바이트 u32 LE
    +0x10  압축 데이터

압축 데이터 종료 위치는:
    compressed_size_field + 4
"""

import argparse
import struct
from array import array
from collections import Counter, deque
from pathlib import Path


HEADER_SIZE = 0x10


class NISLZSError(ValueError):
    pass


def compress_buffer(
    raw: bytes,
    extension: bytes = b"dat\x00",
    flag: int | None = None,
) -> bytes:
    """Encode NIS LZS with deterministic short-window backreferences."""
    if len(extension) != 4:
        raise NISLZSError("LZS 확장자 필드는 4바이트여야 합니다.")
    if flag is None:
        counts = Counter(raw)
        flag = min(range(256), key=lambda value: (counts[value], value))
    if not 0 <= flag <= 0xFF:
        raise NISLZSError(f"잘못된 LZS 플래그: 0x{flag:X}")

    encoded = bytearray()
    last_pair = array("i", [-1]) * 0x10000
    position = 0
    raw_size = len(raw)

    while position < raw_size:
        match_length = 0
        distance = 0

        if position + 1 < raw_size:
            key = (raw[position] << 8) | raw[position + 1]
            previous = last_pair[key]
            candidate_distance = position - previous
            if previous >= 0 and 1 <= candidate_distance <= 254:
                maximum = min(255, raw_size - position)
                length = 0
                while (
                    length < maximum
                    and raw[position + length]
                    == raw[position + length - candidate_distance]
                ):
                    length += 1
                if length >= 4:
                    match_length = length
                    distance = candidate_distance

        consumed = match_length if match_length else 1
        for update_position in range(position, position + consumed):
            if update_position + 1 >= raw_size:
                break
            key = (raw[update_position] << 8) | raw[update_position + 1]
            last_pair[key] = update_position

        if match_length:
            encoded_distance = distance if distance < flag else distance + 1
            if not 1 <= encoded_distance <= 0xFF or encoded_distance == flag:
                raise NISLZSError("LZS 역참조 거리를 표현할 수 없습니다.")
            encoded.extend((flag, encoded_distance, match_length))
            position += match_length
            continue

        value = raw[position]
        encoded.append(value)
        if value == flag:
            encoded.append(flag)
        position += 1

    total_size = HEADER_SIZE + len(encoded)
    header = bytearray(HEADER_SIZE)
    header[0:4] = extension
    struct.pack_into("<I", header, 0x04, raw_size)
    struct.pack_into("<I", header, 0x08, total_size - 4)
    struct.pack_into("<I", header, 0x0C, flag)
    return bytes(header + encoded)


def compress_buffer_best(
    raw: bytes,
    extension: bytes = b"dat\x00",
    flag: int | None = None,
    *,
    allow_overlap: bool = True,
) -> bytes:
    """Encode NIS LZS using the longest match in the 254-byte window.

    ``compress_buffer`` intentionally follows a fast last-pair strategy.  Some
    retail archives were packed more tightly, so a tiny edit can make that fast
    stream too large for its fixed NISPACK extent.  This variant evaluates all
    same-prefix candidates still representable by the format and remains fully
    deterministic.

    ``allow_overlap=True`` matches the Python decoder but is not safe for the
    Prinny PSP runtime: the retail/xdelta stream contains no command whose
    length exceeds its distance.  Use :func:`compress_buffer_runtime_safe` for
    game resources.
    """
    if len(extension) != 4:
        raise NISLZSError("LZS 확장자 필드는 4바이트여야 합니다.")
    if flag is None:
        counts = Counter(raw)
        flag = min(range(256), key=lambda value: (counts[value], value))
    if not 0 <= flag <= 0xFF:
        raise NISLZSError(f"잘못된 LZS 플래그: 0x{flag:X}")

    encoded = bytearray()
    pair_positions = [deque() for _ in range(0x10000)]
    position = 0
    raw_size = len(raw)

    while position < raw_size:
        match_length = 0
        distance = 0
        if position + 1 < raw_size:
            key = (raw[position] << 8) | raw[position + 1]
            candidates = pair_positions[key]
            minimum_position = position - 254
            while candidates and candidates[0] < minimum_position:
                candidates.popleft()
            absolute_maximum = min(255, raw_size - position)
            for previous in reversed(candidates):
                candidate_distance = position - previous
                maximum = (
                    absolute_maximum
                    if allow_overlap
                    else min(absolute_maximum, candidate_distance)
                )
                length = 2
                while (
                    length < maximum
                    and raw[position + length]
                    == raw[position + length - candidate_distance]
                ):
                    length += 1
                if length > match_length:
                    match_length = length
                    distance = candidate_distance
                    if match_length == absolute_maximum:
                        break

        consumed = match_length if match_length >= 4 else 1
        for update_position in range(position, position + consumed):
            if update_position + 1 >= raw_size:
                break
            key = (raw[update_position] << 8) | raw[update_position + 1]
            pair_positions[key].append(update_position)

        if match_length >= 4:
            encoded_distance = distance if distance < flag else distance + 1
            if not 1 <= encoded_distance <= 0xFF or encoded_distance == flag:
                raise NISLZSError("LZS 역참조 거리를 표현할 수 없습니다.")
            encoded.extend((flag, encoded_distance, match_length))
            position += match_length
        else:
            value = raw[position]
            encoded.append(value)
            if value == flag:
                encoded.append(flag)
            position += 1

    total_size = HEADER_SIZE + len(encoded)
    header = bytearray(HEADER_SIZE)
    header[0:4] = extension
    struct.pack_into("<I", header, 0x04, raw_size)
    struct.pack_into("<I", header, 0x08, total_size - 4)
    struct.pack_into("<I", header, 0x0C, flag)
    return bytes(header + encoded)


def compress_buffer_runtime_safe(
    raw: bytes,
    extension: bytes = b"dat\x00",
    flag: int | None = None,
) -> bytes:
    """Encode using longest matches without overlapping backreferences.

    The PSP game's decoder does not reproduce the overlapping-copy semantics
    accepted by :func:`decompress_buffer`.  Restricting every match to
    ``length <= distance`` matches all observed retail/xdelta START.LZS tokens.
    """
    return compress_buffer_best(
        raw,
        extension,
        flag,
        allow_overlap=False,
    )


def parse_header(data: bytes) -> dict:
    if len(data) < HEADER_SIZE:
        raise NISLZSError(
            f"LZS 헤더보다 파일이 작습니다: {len(data)}바이트"
        )

    extension_raw = data[0:4]
    decompressed_size = struct.unpack_from("<I", data, 0x04)[0]
    compressed_size = struct.unpack_from("<I", data, 0x08)[0]
    flag_u32 = struct.unpack_from("<I", data, 0x0C)[0]

    if flag_u32 > 0xFF:
        raise NISLZSError(
            f"제어 바이트가 1바이트 범위를 벗어납니다: "
            f"0x{flag_u32:08X}"
        )

    extension = (
        extension_raw
        .split(b"\x00", 1)[0]
        .decode("ascii", errors="replace")
    )

    compressed_end = compressed_size + 4

    if compressed_end < HEADER_SIZE:
        raise NISLZSError(
            f"잘못된 압축 종료 위치입니다: 0x{compressed_end:X}"
        )

    if compressed_end > len(data):
        raise NISLZSError(
            f"압축 데이터가 파일 범위를 벗어납니다: "
            f"end=0x{compressed_end:X}, "
            f"file=0x{len(data):X}"
        )

    return {
        "extension": extension,
        "decompressed_size": decompressed_size,
        "compressed_size": compressed_size,
        "compressed_end": compressed_end,
        "flag": flag_u32,
    }


def decompress_buffer(data: bytes) -> tuple[bytes, dict]:
    header = parse_header(data)

    expected_size = header["decompressed_size"]
    compressed_end = header["compressed_end"]
    flag = header["flag"]

    output = bytearray()
    position = HEADER_SIZE

    while position < compressed_end:
        token = data[position]

        # 일반 리터럴 바이트
        if token != flag:
            output.append(token)
            position += 1

        else:
            if position + 1 >= compressed_end:
                raise NISLZSError(
                    f"제어 바이트 뒤 데이터가 없습니다: "
                    f"0x{position:X}"
                )

            second = data[position + 1]

            # flag flag → flag 한 바이트
            if second == flag:
                output.append(flag)
                position += 2

            # flag distance length → 이전 데이터 복사
            else:
                if position + 2 >= compressed_end:
                    raise NISLZSError(
                        f"역참조 명령이 잘렸습니다: "
                        f"0x{position:X}"
                    )

                distance = second

                if distance > flag:
                    distance -= 1

                length = data[position + 2]

                if length > 0:
                    if distance == 0:
                        raise NISLZSError(
                            f"역참조 거리가 0입니다: "
                            f"0x{position:X}"
                        )

                    if distance > len(output):
                        raise NISLZSError(
                            f"역참조가 출력 시작 이전을 가리킵니다: "
                            f"command=0x{position:X}, "
                            f"distance={distance}, "
                            f"output={len(output)}"
                        )

                    # 겹치는 복사도 허용되어야 하므로 한 바이트씩 추가
                    for _ in range(length):
                        output.append(output[-distance])

                position += 3

        if len(output) > expected_size:
            raise NISLZSError(
                f"출력 크기가 헤더값을 초과했습니다: "
                f"actual={len(output)}, "
                f"expected={expected_size}"
            )

    if len(output) != expected_size:
        raise NISLZSError(
            f"압축 해제 크기가 일치하지 않습니다: "
            f"actual={len(output)}, "
            f"expected={expected_size}"
        )

    return bytes(output), header


def decompress_file(
    input_path: Path,
    output_path: Path | None = None,
) -> Path:
    data = input_path.read_bytes()
    result, header = decompress_buffer(data)

    if output_path is None:
        extension = header["extension"] or "dat"
        output_path = input_path.with_suffix(f".{extension}")

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_bytes(result)

    print("NIS LZS DECOMPRESS")
    print("==================")
    print("INPUT :", input_path)
    print("OUTPUT:", output_path)
    print("EXTENSION:", header["extension"])
    print(
        "COMPRESSED FILE:",
        f"{len(data)} bytes",
        f"(0x{len(data):X})",
    )
    print(
        "DECOMPRESSED:",
        f"{len(result)} bytes",
        f"(0x{len(result):X})",
    )
    print("FLAG:", f"0x{header['flag']:02X}")
    print(
        "SIZE CHECK:",
        "OK"
        if len(result) == header["decompressed_size"]
        else "FAILED",
    )

    print()
    print("OUTPUT HEAD")
    print("-----------")

    head = result[:64]

    print("HEX  :", head.hex(" ").upper())
    print(
        "ASCII:",
        "".join(
            chr(byte) if 32 <= byte <= 126 else "."
            for byte in head
        ),
    )

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="NIS LZS 압축 파일 해제"
    )

    parser.add_argument(
        "input",
        type=Path,
        help="입력 .lzs 파일",
    )

    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="출력 파일",
    )

    args = parser.parse_args()

    try:
        decompress_file(
            args.input,
            args.output,
        )
    except (OSError, NISLZSError) as error:
        print("ERROR:", error)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
