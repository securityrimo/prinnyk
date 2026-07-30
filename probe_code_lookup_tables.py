#!/usr/bin/env python3

from pathlib import Path


KNOWN = [
    ("の", 0x0043, 0x00F6),
    ("ウ", 0x0B43, 0x0119),
    ("ワ", 0x1E00, 0x015D),
    ("サ", 0x3200, 0x0128),
    ("命", 0x2200, 0x072E),
]

MAX_FILE_SIZE = 64 * 1024 * 1024

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".wav",
    ".ogg",
    ".at3",
    ".iso",
    ".cso",
}


def swap16(value: int) -> int:
    return (
        ((value & 0xFF) << 8)
        | ((value >> 8) & 0xFF)
    )


def encode_u16(
    value: int,
    endian: str,
) -> bytes:
    return value.to_bytes(
        2,
        byteorder=endian,
        signed=False,
    )


def get_jis_code(character: str) -> int:
    encoded = character.encode("iso2022_jp")

    marker = b"\x1b$B"
    position = encoded.find(marker)

    if position < 0:
        raise ValueError(
            f"JIS 변환 실패: {character}"
        )

    start = position + len(marker)

    return (
        encoded[start] << 8
        | encoded[start + 1]
    )


def find_all(
    data: bytes,
    needle: bytes,
):
    position = 0

    while True:
        position = data.find(
            needle,
            position,
        )

        if position < 0:
            return

        yield position
        position += 1


def collect_files() -> list[Path]:
    explicit_files = [
        Path(
            "workspace/iso/PSP_GAME/SYSDIR/"
            "EBOOT.BIN"
        ),
        Path(
            "workspace/iso/PSP_GAME/SYSDIR/"
            "BOOT.BIN"
        ),
        Path(
            "workspace/unpack/SYSTEM_fixed/"
            "start.dat"
        ),
    ]

    roots = [
        Path("workspace/unpack/START_runtime"),
        Path("workspace/unpack/SCRIPT_fixed"),
    ]

    files = []

    for path in explicit_files:
        if path.is_file():
            files.append(path)

    for root in roots:
        if not root.is_dir():
            continue

        for path in root.rglob("*"):
            if path.is_file():
                files.append(path)

    unique = {}

    for path in files:
        try:
            resolved = path.resolve()
            size = path.stat().st_size
        except OSError:
            continue

        if size > MAX_FILE_SIZE:
            continue

        if path.suffix.lower() in SKIP_SUFFIXES:
            continue

        unique[resolved] = path

    return sorted(
        unique.values(),
        key=lambda item: str(item),
    )


def verify_direct_array(
    data: bytes,
    indices: list[int],
    targets: list[int],
    target_endian: str,
    stride: int,
    field_offset: int,
):
    first_target = encode_u16(
        targets[0],
        target_endian,
    )

    matches = set()

    for position in find_all(
        data,
        first_target,
    ):
        base = (
            position
            - indices[0] * stride
            - field_offset
        )

        if base < 0:
            continue

        valid = True

        for index, target in zip(
            indices,
            targets,
        ):
            target_position = (
                base
                + index * stride
                + field_offset
            )

            if (
                target_position < 0
                or target_position + 2 > len(data)
            ):
                valid = False
                break

            actual = data[
                target_position:
                target_position + 2
            ]

            expected = encode_u16(
                target,
                target_endian,
            )

            if actual != expected:
                valid = False
                break

        if valid:
            matches.add(base)

    return sorted(matches)


def direct_array_probe(
    path: Path,
    data: bytes,
    target_name: str,
    targets: list[int],
):
    hits = []

    raw_codes = [
        code
        for _, code, _ in KNOWN
    ]

    code_modes = {
        "RAW": raw_codes,
        "BYTE_SWAPPED": [
            swap16(code)
            for code in raw_codes
        ],
    }

    for code_mode, indices in code_modes.items():
        for target_endian in (
            "little",
            "big",
        ):
            for stride in (2, 4):
                field_offsets = (
                    (0,)
                    if stride == 2
                    else (0, 2)
                )

                for field_offset in field_offsets:
                    bases = verify_direct_array(
                        data=data,
                        indices=indices,
                        targets=targets,
                        target_endian=target_endian,
                        stride=stride,
                        field_offset=field_offset,
                    )

                    for base in bases:
                        hits.append(
                            (
                                target_name,
                                code_mode,
                                target_endian,
                                stride,
                                field_offset,
                                base,
                            )
                        )

    return hits


def record_probe(
    data: bytes,
    target_name: str,
    targets: list[int],
):
    hits = []

    codes = [
        code
        for _, code, _ in KNOWN
    ]

    for code_endian in ("big", "little"):
        for target_endian in ("big", "little"):
            for order in (
                "CODE_TARGET",
                "TARGET_CODE",
            ):
                matched_pairs = []

                for (
                    character,
                    code,
                    _,
                ), target in zip(
                    KNOWN,
                    targets,
                ):
                    code_bytes = encode_u16(
                        code,
                        code_endian,
                    )

                    target_bytes = encode_u16(
                        target,
                        target_endian,
                    )

                    if order == "CODE_TARGET":
                        pattern = (
                            code_bytes
                            + target_bytes
                        )
                    else:
                        pattern = (
                            target_bytes
                            + code_bytes
                        )

                    positions = list(
                        find_all(
                            data,
                            pattern,
                        )
                    )

                    if positions:
                        matched_pairs.append(
                            (
                                character,
                                positions[:4],
                            )
                        )

                if len(matched_pairs) >= 3:
                    hits.append(
                        (
                            target_name,
                            code_endian,
                            target_endian,
                            order,
                            matched_pairs,
                        )
                    )

    return hits


def main() -> int:
    files = collect_files()

    print("KNOWN CODE → GLYPH PAIRS")
    print("========================")

    for character, code, glyph in KNOWN:
        jis = get_jis_code(character)

        print(
            f"{character}  "
            f"CODE=0x{code:04X}  "
            f"GLYPH=0x{glyph:04X}  "
            f"JIS=0x{jis:04X}  "
            f"UNICODE=U+{ord(character):04X}"
        )

    print()
    print("FILES TO SCAN")
    print("=============")
    print("COUNT:", len(files))

    for path in files:
        print(
            f"{path} "
            f"({path.stat().st_size} bytes)"
        )

    target_sets = {
        "GLYPH_INDEX": [
            glyph
            for _, _, glyph in KNOWN
        ],
        "JIS_CODE": [
            get_jis_code(character)
            for character, _, _ in KNOWN
        ],
        "UNICODE": [
            ord(character)
            for character, _, _ in KNOWN
        ],
    }

    direct_hits = []
    record_hits = []

    for path in files:
        try:
            data = path.read_bytes()
        except OSError as error:
            print(
                "READ ERROR:",
                path,
                error,
            )
            continue

        for target_name, targets in (
            target_sets.items()
        ):
            for hit in direct_array_probe(
                path,
                data,
                target_name,
                targets,
            ):
                direct_hits.append(
                    (path, *hit)
                )

            for hit in record_probe(
                data,
                target_name,
                targets,
            ):
                record_hits.append(
                    (path, *hit)
                )

    print()
    print("DIRECT LOOKUP ARRAY MATCHES")
    print("===========================")

    if not direct_hits:
        print("NONE")
    else:
        for (
            path,
            target_name,
            code_mode,
            target_endian,
            stride,
            field_offset,
            base,
        ) in direct_hits:
            print(
                f"{path}: "
                f"TARGET={target_name} "
                f"CODE_INDEX={code_mode} "
                f"VALUE_ENDIAN={target_endian.upper()} "
                f"STRIDE={stride} "
                f"FIELD=+0x{field_offset:X} "
                f"BASE=0x{base:X}"
            )

    print()
    print("FOUR-BYTE RECORD CANDIDATES")
    print("===========================")

    if not record_hits:
        print("NONE")
    else:
        for (
            path,
            target_name,
            code_endian,
            target_endian,
            order,
            matched_pairs,
        ) in record_hits:
            print()
            print("FILE          :", path)
            print("TARGET        :", target_name)
            print("CODE ENDIAN   :", code_endian.upper())
            print("TARGET ENDIAN :", target_endian.upper())
            print("ORDER         :", order)

            for character, positions in matched_pairs:
                offsets = ", ".join(
                    f"0x{position:X}"
                    for position in positions
                )

                print(
                    f"  {character}: {offsets}"
                )

    print()
    print("DONE")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
