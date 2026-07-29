#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from build_font_canary import (
    BYTES_PER_GLYPH,
    SOURCE_START,
    TXP_PIXEL_OFFSET,
    encode_4bpp,
    parse_nispack_start_entry,
    parse_start_records,
)
from build_hangul_canary import (
    find_korean_font,
    render_hangul,
)
from build_independent_hangul_test import resource_blob
from core.lzs import decompress_buffer


PATCHED_START = Path(
    "workspace/test/reclaimed_hangul/"
    "start_reclaimed_hangul.dat"
)
PATCHED_SYSTEM = Path(
    "workspace/test/reclaimed_hangul/"
    "SYSTEM_reclaimed_hangul.DAT"
)
TEST_ISO = Path(
    "workspace/test/reclaimed_hangul.iso"
)

REPORT_IMAGE = Path(
    "workspace/reports/"
    "reclaimed_hangul_artifact_check.png"
)

DEMO_RESOURCE = "Demo00.dat"
DEMO_OFFSET = 0x2E
EXPECTED_DEMO = bytes.fromhex("8B E3")

GLYPH_INDEX = 0x0334
GLYPH_WIDTH = 20
GLYPH_HEIGHT = 14


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def get_resource(
    start_data: bytes,
    name: str,
) -> bytes:
    records = parse_start_records(start_data)

    matches = [
        record
        for record in records
        if str(record["name"]).casefold()
        == name.casefold()
    ]

    if len(matches) != 1:
        raise ValueError(
            f"{name} 레코드 수가 {len(matches)}개입니다."
        )

    return resource_blob(
        start_data,
        matches[0],
    )


def extract_start_from_system(
    system_data: bytes,
) -> bytes:
    entry = parse_nispack_start_entry(
        system_data
    )

    offset = int(entry["data_offset"])
    size = int(entry["size"])

    lzs = system_data[
        offset:
        offset + size
    ]

    start_data, _ = decompress_buffer(lzs)
    return start_data


def extract_system_from_iso(
    iso_path: Path,
) -> bytes:
    result = subprocess.run(
        [
            "7z",
            "x",
            "-so",
            str(iso_path),
            "PSP_GAME/USRDIR/SYSTEM.DAT",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "ISO의 SYSTEM.DAT 추출 실패:\n"
            + result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

    if not result.stdout:
        raise RuntimeError(
            "ISO에서 추출한 SYSTEM.DAT가 비어 있습니다."
        )

    return result.stdout


def glyph_bytes(
    txp: bytes,
    glyph_index: int,
) -> bytes:
    offset = (
        TXP_PIXEL_OFFSET
        + glyph_index * BYTES_PER_GLYPH
    )

    result = txp[
        offset:
        offset + BYTES_PER_GLYPH
    ]

    if len(result) != BYTES_PER_GLYPH:
        raise ValueError(
            "글리프 범위가 font.txp를 벗어났습니다."
        )

    return result


def decode_glyph(raw: bytes) -> Image.Image:
    if len(raw) != BYTES_PER_GLYPH:
        raise ValueError(
            "글리프 크기가 잘못됐습니다."
        )

    image = Image.new(
        "L",
        (GLYPH_WIDTH, GLYPH_HEIGHT),
        0,
    )

    position = 0

    for y in range(GLYPH_HEIGHT):
        for x in range(0, GLYPH_WIDTH, 2):
            value = raw[position]
            position += 1

            image.putpixel(
                (x, y),
                (value & 0x0F) * 17,
            )
            image.putpixel(
                (x + 1, y),
                ((value >> 4) & 0x0F) * 17,
            )

    return image


def save_comparison(
    original: bytes,
    expected: bytes,
    patched: bytes,
) -> None:
    scale = 12
    label_height = 22
    gap = 12

    sources = [
        ("ORIGINAL", original),
        ("EXPECTED GA", expected),
        ("PATCHED ISO", patched),
    ]

    cell_width = GLYPH_WIDTH * scale
    cell_height = (
        label_height
        + GLYPH_HEIGHT * scale
    )

    canvas = Image.new(
        "L",
        (
            len(sources) * cell_width
            + (len(sources) - 1) * gap,
            cell_height,
        ),
        0,
    )
    draw = ImageDraw.Draw(canvas)

    for index, (label, raw) in enumerate(
        sources
    ):
        x = index * (cell_width + gap)

        draw.text(
            (x + 4, 4),
            label,
            fill=255,
        )

        glyph = decode_glyph(raw).resize(
            (
                GLYPH_WIDTH * scale,
                GLYPH_HEIGHT * scale,
            ),
            Image.Resampling.NEAREST,
        )

        canvas.paste(
            glyph,
            (x, label_height),
        )

    REPORT_IMAGE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    canvas.save(REPORT_IMAGE)


def main() -> int:
    required = [
        SOURCE_START,
        PATCHED_START,
        PATCHED_SYSTEM,
        TEST_ISO,
    ]

    for path in required:
        if not path.is_file():
            raise FileNotFoundError(
                f"필수 파일 없음: {path}"
            )

    original_start = SOURCE_START.read_bytes()
    patched_start = PATCHED_START.read_bytes()
    patched_system = PATCHED_SYSTEM.read_bytes()

    system_embedded_start = (
        extract_start_from_system(
            patched_system
        )
    )

    iso_system = extract_system_from_iso(
        TEST_ISO
    )
    iso_embedded_start = (
        extract_start_from_system(
            iso_system
        )
    )

    original_txp = get_resource(
        original_start,
        "font.txp",
    )
    patched_txp = get_resource(
        patched_start,
        "font.txp",
    )
    system_txp = get_resource(
        system_embedded_start,
        "font.txp",
    )
    iso_txp = get_resource(
        iso_embedded_start,
        "font.txp",
    )

    patched_demo = get_resource(
        patched_start,
        DEMO_RESOURCE,
    )
    iso_demo = get_resource(
        iso_embedded_start,
        DEMO_RESOURCE,
    )

    original_glyph = glyph_bytes(
        original_txp,
        GLYPH_INDEX,
    )
    patched_glyph = glyph_bytes(
        patched_txp,
        GLYPH_INDEX,
    )
    system_glyph = glyph_bytes(
        system_txp,
        GLYPH_INDEX,
    )
    iso_glyph = glyph_bytes(
        iso_txp,
        GLYPH_INDEX,
    )

    font_path = find_korean_font()
    pixels, _ = render_hangul(
        font_path
    )
    expected_glyph = encode_4bpp(
        pixels
    )

    save_comparison(
        original_glyph,
        expected_glyph,
        iso_glyph,
    )

    changed_bytes = sum(
        before != after
        for before, after in zip(
            original_glyph,
            patched_glyph,
        )
    )

    checks = {
        "patched_start_differs":
            patched_start != original_start,

        "patched_glyph_changed":
            changed_bytes > 0,

        "patched_glyph_is_expected_ga":
            patched_glyph == expected_glyph,

        "system_embeds_patched_start":
            system_embedded_start
            == patched_start,

        "iso_system_matches_generated_system":
            iso_system == patched_system,

        "iso_embeds_patched_start":
            iso_embedded_start
            == patched_start,

        "iso_glyph_matches_patched_glyph":
            iso_glyph == patched_glyph,

        "system_glyph_matches_patched_glyph":
            system_glyph == patched_glyph,

        "patched_demo_is_8be3":
            patched_demo[
                DEMO_OFFSET:
                DEMO_OFFSET + 2
            ] == EXPECTED_DEMO,

        "iso_demo_is_8be3":
            iso_demo[
                DEMO_OFFSET:
                DEMO_OFFSET + 2
            ] == EXPECTED_DEMO,
    }

    print("RECLAIMED HANGUL ARTIFACT CHECK")
    print("===============================")
    print(
        f"GLYPH INDEX          : "
        f"0x{GLYPH_INDEX:04X}"
    )
    print(
        f"GLYPH BYTE OFFSET    : "
        f"0x{TXP_PIXEL_OFFSET + GLYPH_INDEX * BYTES_PER_GLYPH:X}"
    )
    print(
        f"CHANGED GLYPH BYTES  : "
        f"{changed_bytes}"
    )
    print(
        f"ORIGINAL GLYPH SHA1  : "
        f"{sha1(original_glyph)}"
    )
    print(
        f"EXPECTED 가 SHA1     : "
        f"{sha1(expected_glyph)}"
    )
    print(
        f"PATCHED GLYPH SHA1   : "
        f"{sha1(patched_glyph)}"
    )
    print(
        f"ISO GLYPH SHA1       : "
        f"{sha1(iso_glyph)}"
    )
    print()

    for name, passed in checks.items():
        print(
            f"{name:36s}: {passed}"
        )

    print()
    print("COMPARISON IMAGE:", REPORT_IMAGE)

    if all(checks.values()):
        print("ARTIFACT STATUS : PASS")
        print(
            "판정: ISO 안에는 가 글리프가 정확히 들어 있습니다."
        )
        print(
            "게임 런타임이 한자 九에 다른 글리프 경로를 사용합니다."
        )
    else:
        print("ARTIFACT STATUS : FAIL")
        print(
            "판정: 생성 또는 ISO 삽입 단계에 불일치가 있습니다."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
