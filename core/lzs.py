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
from pathlib import Path


HEADER_SIZE = 0x10


class NISLZSError(ValueError):
    pass


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
