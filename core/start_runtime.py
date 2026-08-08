#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from core.font_runtime import (
    FontRuntime,
    FontRuntimeError,
)


DEFAULT_START = Path(
    "workspace/unpack/SYSTEM_fixed/start.dat"
)

DEFAULT_OUTPUT = Path(
    "workspace/unpack/START_runtime"
)

DEFAULT_MANIFEST = Path(
    "workspace/reports/start_runtime_manifest.json"
)

RECORD_SIZE = 0x20
OFFSET_FIELD = 0x04
NAME_FIELD = 0x08
NAME_SIZE = 0x18

REQUIRED_RESOURCES = {
    "font.fnt",
    "font.txp",
    "jis2ucs.bin",
    "ucs2jis.bin",
}


class StartRuntimeError(RuntimeError):
    """start.dat 구조가 예상과 다를 때 발생한다."""


@dataclass
class StartRecord:
    index: int
    name: str
    output_name: str
    record_offset: int
    data_offset: int
    end_offset: int
    size: int
    sha1: str


def read_u32(
    data: bytes,
    offset: int,
) -> int:
    if (
        offset < 0
        or offset + 4 > len(data)
    ):
        raise StartRuntimeError(
            f"uint32 범위 초과: 0x{offset:X}"
        )

    return struct.unpack_from(
        "<I",
        data,
        offset,
    )[0]


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def clean_resource_name(
    raw_name: bytes,
    index: int,
) -> str:
    raw_name = raw_name.split(
        b"\x00",
        1,
    )[0]

    name = raw_name.decode(
        "ascii",
        errors="replace",
    ).strip()

    # 경로 이동을 막고 파일명만 유지한다.
    name = Path(name).name

    if not name:
        name = f"resource_{index:03d}.bin"

    safe_characters = []

    for character in name:
        if (
            character.isalnum()
            or character in "._-"
        ):
            safe_characters.append(
                character
            )
        else:
            safe_characters.append("_")

    safe_name = "".join(
        safe_characters
    ).strip(".")

    if not safe_name:
        safe_name = (
            f"resource_{index:03d}.bin"
        )

    return safe_name


class StartRuntimeArchive:
    """
    Prinny start.dat 런타임 자원 아카이브.

    레코드 구조:
        +0x00  미확인 uint32
        +0x04  자원 데이터 오프셋
        +0x08  이름[0x18]
    """

    def __init__(
        self,
        path: Path,
        data: bytes,
        records: list[StartRecord],
        table_end: int,
    ) -> None:
        self.path = path
        self.data = data
        self.records = records
        self.table_end = table_end

    @classmethod
    def load(
        cls,
        path: Path | str = DEFAULT_START,
    ) -> "StartRuntimeArchive":
        path = Path(path)

        if not path.is_file():
            raise FileNotFoundError(
                f"start.dat 없음: {path}"
            )

        data = path.read_bytes()

        return cls.from_bytes(
            data,
            source=path,
        )

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        source: Path | str = "<memory>",
    ) -> "StartRuntimeArchive":
        path = Path(source)

        if len(data) < RECORD_SIZE:
            raise StartRuntimeError(
                "start.dat이 너무 작습니다."
            )

        count = read_u32(
            data,
            0x00,
        )

        if count <= 0:
            raise StartRuntimeError(
                f"잘못된 레코드 수: {count}"
            )

        table_end = (
            count * RECORD_SIZE
        )

        if table_end > len(data):
            raise StartRuntimeError(
                "레코드 테이블이 파일 범위를 "
                "벗어납니다: "
                f"0x{table_end:X}"
            )

        raw_records = []

        for index in range(count):
            record_offset = (
                index * RECORD_SIZE
            )

            data_offset = read_u32(
                data,
                record_offset
                + OFFSET_FIELD,
            )

            raw_name = data[
                record_offset + NAME_FIELD:
                record_offset
                + NAME_FIELD
                + NAME_SIZE
            ]

            name = clean_resource_name(
                raw_name,
                index,
            )

            raw_records.append(
                {
                    "index": index,
                    "name": name,
                    "record_offset":
                        record_offset,
                    "data_offset":
                        data_offset,
                }
            )

        if (
            raw_records[0]["data_offset"]
            < table_end
        ):
            raise StartRuntimeError(
                "첫 자원 오프셋이 레코드 "
                "테이블 안에 있습니다: "
                f"0x{raw_records[0]['data_offset']:X}"
            )

        used_names: set[str] = set()
        records: list[StartRecord] = []

        for index, raw_record in enumerate(
            raw_records
        ):
            data_offset = raw_record[
                "data_offset"
            ]

            if index + 1 < count:
                end_offset = raw_records[
                    index + 1
                ]["data_offset"]
            else:
                end_offset = len(data)

            if not (
                table_end
                <= data_offset
                <= end_offset
                <= len(data)
            ):
                raise StartRuntimeError(
                    "잘못된 자원 범위: "
                    f"index={index}, "
                    f"start=0x{data_offset:X}, "
                    f"end=0x{end_offset:X}"
                )

            output_name = raw_record[
                "name"
            ]

            if output_name in used_names:
                output_path = Path(
                    output_name
                )

                output_name = (
                    f"{output_path.stem}_"
                    f"{index:03d}"
                    f"{output_path.suffix}"
                )

            used_names.add(
                output_name
            )

            blob = data[
                data_offset:end_offset
            ]

            records.append(
                StartRecord(
                    index=index,
                    name=raw_record["name"],
                    output_name=output_name,
                    record_offset=raw_record[
                        "record_offset"
                    ],
                    data_offset=data_offset,
                    end_offset=end_offset,
                    size=len(blob),
                    sha1=sha1_bytes(blob),
                )
            )

        return cls(
            path=path,
            data=data,
            records=records,
            table_end=table_end,
        )

    def extract(
        self,
        output_directory: Path | str,
    ) -> dict[str, Path]:
        output_directory = Path(
            output_directory
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        extracted: dict[str, Path] = {}

        for record in self.records:
            blob = self.data[
                record.data_offset:
                record.end_offset
            ]

            output_path = (
                output_directory
                / record.output_name
            )

            output_path.write_bytes(
                blob
            )

            extracted[
                record.output_name
            ] = output_path

        return extracted

    def find_record(
        self,
        name: str,
    ) -> StartRecord | None:
        for record in self.records:
            if record.name == name:
                return record

        return None


def verify_charset_table(
    path: Path,
) -> dict:
    data = path.read_bytes()

    size_match = (
        len(data) == 0x20000
    )

    identity_match = True

    if len(data) < 0x100:
        identity_match = False
    else:
        for index in range(0x7F):
            value = struct.unpack_from(
                "<H",
                data,
                index * 2,
            )[0]

            if value != index:
                identity_match = False
                break

    return {
        "path": str(path),
        "size": len(data),
        "size_match": size_match,
        "ascii_identity_match":
            identity_match,
        "ok": (
            size_match
            and identity_match
        ),
    }


def verify_extraction(
    archive: StartRuntimeArchive,
    output_directory: Path,
) -> dict:
    checks = []

    for name in sorted(
        REQUIRED_RESOURCES
    ):
        record = archive.find_record(
            name
        )

        path = (
            output_directory / name
        )

        exists = (
            record is not None
            and path.is_file()
        )

        checks.append(
            {
                "name": name,
                "exists": exists,
                "size": (
                    path.stat().st_size
                    if exists
                    else None
                ),
                "ok": exists,
            }
        )

    font_result = {
        "ok": False,
    }

    try:
        runtime = FontRuntime.load(
            output_directory / "font.fnt",
            output_directory / "font.txp",
        )

        verification = runtime.verify()

        font_result = {
            "table_entries":
                len(runtime.table),
            "table_count_match":
                verification[
                    "table_count_match"
                ],
            "glyph_count":
                runtime.txp[
                    "glyph_count"
                ],
            "glyph_count_match":
                verification[
                    "glyph_count_match"
                ],
            "invalid_table_values":
                verification[
                    "invalid_table_values"
                ],
            "known_character_matches":
                verification["matched"],
            "known_character_total":
                verification["total"],
            "ok": (
                verification[
                    "table_count_match"
                ]
                and verification[
                    "glyph_count_match"
                ]
                and verification[
                    "invalid_table_values"
                ] == 0
                and verification["matched"]
                == verification["total"]
            ),
        }

    except (
        FileNotFoundError,
        FontRuntimeError,
        ValueError,
        OSError,
    ) as error:
        font_result = {
            "ok": False,
            "error": str(error),
        }

    charset_results = {
        "jis2ucs.bin":
            verify_charset_table(
                output_directory
                / "jis2ucs.bin"
            ),
        "ucs2jis.bin":
            verify_charset_table(
                output_directory
                / "ucs2jis.bin"
            ),
    }

    all_ok = (
        all(
            check["ok"]
            for check in checks
        )
        and font_result["ok"]
        and all(
            result["ok"]
            for result
            in charset_results.values()
        )
    )

    return {
        "required_resources": checks,
        "font_runtime": font_result,
        "charset_tables":
            charset_results,
        "ok": all_ok,
    }


def build_manifest(
    archive: StartRuntimeArchive,
    output_directory: Path,
    verification: dict,
) -> dict:
    return {
        "source": str(
            archive.path
        ),
        "source_size":
            len(archive.data),
        "source_sha1":
            sha1_bytes(archive.data),
        "record_size":
            RECORD_SIZE,
        "record_count":
            len(archive.records),
        "table_end":
            archive.table_end,
        "first_data_offset":
            archive.records[
                0
            ].data_offset,
        "output_directory":
            str(output_directory),
        "records": [
            asdict(record)
            for record in archive.records
        ],
        "verification":
            verification,
    }


def run_extract(
    args: argparse.Namespace,
) -> int:
    archive = StartRuntimeArchive.load(
        args.start
    )

    output_directory = Path(
        args.output
    )

    archive.extract(
        output_directory
    )

    verification = verify_extraction(
        archive,
        output_directory,
    )

    manifest = build_manifest(
        archive,
        output_directory,
        verification,
    )

    manifest_path = Path(
        args.manifest
    )

    manifest_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "START.DAT RUNTIME EXTRACTION"
    )
    print(
        "============================"
    )
    print(
        "SOURCE       :",
        archive.path,
    )
    print(
        "SOURCE SIZE  :",
        f"0x{len(archive.data):X}",
    )
    print(
        "RECORD COUNT :",
        len(archive.records),
    )
    print(
        "TABLE END    :",
        f"0x{archive.table_end:X}",
    )
    print(
        "FIRST DATA   :",
        f"0x{archive.records[0].data_offset:X}",
    )
    print(
        "OUTPUT       :",
        output_directory,
    )
    print()

    print(
        "REQUIRED RESOURCES"
    )
    print(
        "=================="
    )

    for name in sorted(
        REQUIRED_RESOURCES
    ):
        record = archive.find_record(
            name
        )

        if record is None:
            print(
                f"{name}: NOT FOUND"
            )
            continue

        print(
            f"{name}: "
            f"INDEX={record.index} "
            f"OFFSET=0x{record.data_offset:X} "
            f"SIZE=0x{record.size:X}"
        )

    print()
    print(
        "FONT VERIFICATION"
    )
    print(
        "================="
    )

    font = verification[
        "font_runtime"
    ]

    if font.get("ok"):
        print(
            "TABLE ENTRIES :",
            f"0x{font['table_entries']:X}",
        )
        print(
            "GLYPH COUNT   :",
            f"0x{font['glyph_count']:X}",
        )
        print(
            "INVALID VALUES:",
            font[
                "invalid_table_values"
            ],
        )
        print(
            "KNOWN CHARS   :",
            f"{font['known_character_matches']}/"
            f"{font['known_character_total']}",
        )
    else:
        print(
            "FAILED:",
            font.get(
                "error",
                "폰트 검증 실패",
            ),
        )

    print()
    print(
        "CHARSET VERIFICATION"
    )
    print(
        "===================="
    )

    for name, result in (
        verification[
            "charset_tables"
        ].items()
    ):
        print(
            f"{name}: "
            f"SIZE=0x{result['size']:X} "
            f"ASCII_IDENTITY="
            f"{result['ascii_identity_match']} "
            f"{'MATCH' if result['ok'] else 'MISMATCH'}"
        )

    print()
    print(
        "SELF TEST:",
        "PASS"
        if verification["ok"]
        else "FAIL",
    )
    print(
        "MANIFEST :",
        manifest_path,
    )

    return (
        0
        if verification["ok"]
        else 1
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prinny start.dat 런타임 "
            "자원 추출기"
        )
    )

    parser.add_argument(
        "command",
        choices=["extract"],
    )

    parser.add_argument(
        "--start",
        type=Path,
        default=DEFAULT_START,
        help=(
            "start.dat 경로 "
            f"(기본값: {DEFAULT_START})"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "출력 디렉터리 "
            f"(기본값: {DEFAULT_OUTPUT})"
        ),
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=(
            "manifest JSON 경로 "
            f"(기본값: {DEFAULT_MANIFEST})"
        ),
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return run_extract(
            args
        )

    except (
        FileNotFoundError,
        StartRuntimeError,
        FontRuntimeError,
        ValueError,
        OSError,
    ) as error:
        print(
            f"ERROR: {error}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
