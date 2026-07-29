"""
core/nispack.py

NISPACK 고정 목차 파서.

확인된 SCRIPT.DAT 구조:

    0x00  NISPACK 헤더
    0x0C  파일 개수 u32
    0x10  목차 시작

각 목차 엔트리는 정확히 0x2C바이트다.

    +0x00  파일명 32바이트, NUL 패딩
    +0x20  파일 데이터 절대 오프셋 u32 LE
    +0x24  파일 크기 u32 LE
    +0x28  메타데이터 u32 LE

파일명 문자열을 전체 데이터에서 검색하지 않고,
헤더에 선언된 개수만큼 고정 엔트리를 읽는다.
"""

import struct
from pathlib import Path


MAGIC = b"NISPACK"
GLOBAL_HEADER_SIZE = 0x10
NAME_SIZE = 0x20
ENTRY_SIZE = 0x2C

OFFSET_FIELD = 0x20
SIZE_FIELD = 0x24
METADATA_FIELD = 0x28


class NISPack:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()

    def parse(self, verbose=True):
        if len(self.data) < GLOBAL_HEADER_SIZE:
            raise ValueError(
                f"NISPACK 헤더보다 파일이 작습니다: "
                f"size=0x{len(self.data):X}"
            )

        if self.data[:7] != MAGIC:
            raise ValueError(
                f"NISPACK 매직이 아닙니다: "
                f"{self.data[:7]!r}"
            )

        declared_count = struct.unpack_from(
            "<I",
            self.data,
            0x0C,
        )[0]

        if declared_count <= 0:
            raise ValueError(
                f"잘못된 파일 개수입니다: "
                f"{declared_count}"
            )

        table_offset = GLOBAL_HEADER_SIZE
        table_size = declared_count * ENTRY_SIZE
        table_end = table_offset + table_size

        if table_end > len(self.data):
            raise ValueError(
                f"목차가 파일 범위를 벗어납니다: "
                f"table_end=0x{table_end:X}, "
                f"file_size=0x{len(self.data):X}"
            )

        entries = []

        for index in range(declared_count):
            record_offset = (
                table_offset + index * ENTRY_SIZE
            )

            name_raw = self.data[
                record_offset:
                record_offset + NAME_SIZE
            ]

            name_bytes = name_raw.split(
                b"\x00",
                1,
            )[0]

            try:
                name = name_bytes.decode(
                    "ascii",
                    errors="strict",
                )
            except UnicodeDecodeError as error:
                raise ValueError(
                    f"엔트리 {index} 파일명이 ASCII가 아닙니다: "
                    f"{name_bytes.hex(' ')}"
                ) from error

            offset = struct.unpack_from(
                "<I",
                self.data,
                record_offset + OFFSET_FIELD,
            )[0]

            size = struct.unpack_from(
                "<I",
                self.data,
                record_offset + SIZE_FIELD,
            )[0]

            metadata = struct.unpack_from(
                "<I",
                self.data,
                record_offset + METADATA_FIELD,
            )[0]

            end = offset + size

            name_valid = bool(name)
            path_safe = (
                Path(name).name == name
                and "/" not in name
                and "\\" not in name
            )

            range_valid = (
                size > 0
                and offset >= table_end
                and end <= len(self.data)
            )

            plausible = (
                name_valid
                and path_safe
                and range_valid
            )

            entries.append(
                {
                    "index": index,
                    "name": name,
                    "record_at": record_offset,
                    "record_at_hex": (
                        f"0x{record_offset:X}"
                    ),
                    "offset": offset,
                    "offset_hex": f"0x{offset:X}",
                    "size": size,
                    "size_hex": f"0x{size:X}",
                    "end": end,
                    "end_hex": f"0x{end:X}",
                    "metadata": metadata,
                    "metadata_hex": (
                        f"0x{metadata:08X}"
                    ),
                    "metadata_low16": (
                        metadata & 0xFFFF
                    ),
                    "metadata_high16": (
                        metadata >> 16
                    ),
                    # 예전 코드 호환용
                    "flag": metadata & 0xFFFF,
                    "header_at": record_offset,
                    "name_valid": name_valid,
                    "path_safe": path_safe,
                    "range_valid": range_valid,
                    "plausible": plausible,
                }
            )

        if verbose:
            print(
                f"NISPACK 헤더상 파일 개수: "
                f"{declared_count}"
            )

            print(
                f"목차 범위: "
                f"0x{table_offset:X}~0x{table_end - 1:X}"
            )

            print()

            for entry in entries:
                warning = (
                    ""
                    if entry["plausible"]
                    else "  ⚠️ 유효성 검사 실패"
                )

                print(
                    f'[{entry["index"]}] '
                    f'{entry["name"]:<16} '
                    f'offset={entry["offset"]:06X} '
                    f'size={entry["size"]:06X} '
                    f'end={entry["end"]:06X} '
                    f'meta={entry["metadata"]:08X}'
                    f'{warning}'
                )

            plausible_count = sum(
                1
                for entry in entries
                if entry["plausible"]
            )

            print()

            if plausible_count == declared_count:
                print(
                    f"✅ {declared_count}개 엔트리가 "
                    f"모두 유효합니다."
                )
            else:
                print(
                    f"⚠️ 유효 엔트리: "
                    f"{plausible_count}/{declared_count}"
                )

            if entries:
                final_end = max(
                    entry["end"]
                    for entry in entries
                )

                print(
                    f"마지막 데이터 끝: "
                    f"0x{final_end:X}"
                )

                print(
                    f"컨테이너 크기: "
                    f"0x{len(self.data):X}"
                )

                if final_end == len(self.data):
                    print(
                        "✅ 마지막 데이터 끝과 "
                        "컨테이너 크기가 일치합니다."
                    )

        return entries

    def extract(
        self,
        output,
        only_plausible=True,
    ):
        output = Path(output)
        output.mkdir(
            parents=True,
            exist_ok=True,
        )

        entries = self.parse(verbose=False)

        for entry in entries:
            if (
                only_plausible
                and not entry["plausible"]
            ):
                print(
                    f'[SKIP] {entry["name"]} '
                    f'- 유효성 검사 실패'
                )
                continue

            name = entry["name"]

            if not name:
                print(
                    f'[SKIP] 엔트리 {entry["index"]} '
                    f'- 빈 파일명'
                )
                continue

            if (
                Path(name).name != name
                or "/" in name
                or "\\" in name
            ):
                print(
                    f"[SKIP] 위험한 파일명: "
                    f"{name!r}"
                )
                continue

            start = entry["offset"]
            end = entry["end"]

            if end > len(self.data):
                print(
                    f"[SKIP] {name} 범위 초과: "
                    f"offset=0x{start:X}, "
                    f"size=0x{entry['size']:X}"
                )
                continue

            outfile = output / name

            outfile.write_bytes(
                self.data[start:end]
            )

            print(
                f"EXTRACT {name} "
                f"{entry['size']} bytes "
                f"-> {outfile}"
            )


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="NISPACK 목차 분석 및 추출"
    )

    parser.add_argument(
        "archive",
        help="NISPACK 파일 경로",
    )

    parser.add_argument(
        "output",
        nargs="?",
        help="지정하면 해당 폴더에 파일을 추출",
    )

    args = parser.parse_args()

    pack = NISPack(args.archive)
    pack.parse(verbose=True)

    if args.output:
        print()
        pack.extract(args.output)


if __name__ == "__main__":
    main()
