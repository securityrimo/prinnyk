#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import struct
from pathlib import Path

from PIL import Image

import build_hangul_canary as hangul_canary

from build_font_canary import (
    BYTES_PER_GLYPH,
    SOURCE_START,
    SOURCE_SYSTEM,
    TXP_PIXEL_OFFSET,
    align_up,
    build_literal_lzs,
    encode_4bpp,
    parse_nispack_start_entry,
    parse_start_records,
    read_u32,
)
from build_independent_hangul_test import (
    rebuild_start_archive,
    resource_blob,
)
from core.lzs import decompress_buffer
from core.start_runtime import StartRuntimeArchive


ALLOCATION_PATH = Path(
    "workspace/font/hangul_map.json"
)

OUTPUT_DIR = Path(
    "workspace/test/multihangul"
)
OUTPUT_START = OUTPUT_DIR / "start_multihangul.dat"
OUTPUT_LZS = OUTPUT_DIR / "start_multihangul.lzs"
OUTPUT_SYSTEM = OUTPUT_DIR / "SYSTEM_multihangul.DAT"
OUTPUT_PREVIEW = OUTPUT_DIR / "multihangul_preview.png"
OUTPUT_MANIFEST = OUTPUT_DIR / "manifest.json"

DEMO_RESOURCE = "Demo00.dat"

# 마지막 の가 0x2E에서 시작하므로
# 10문자 전체의 시작은 0x1C이다.
DEMO_OFFSET = 0x1C

ORIGINAL_TEXT = "やりごたえバッチリの"
EXPECTED_HANGUL = "가나다라마바사아자차"


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def load_allocation() -> dict:
    if not ALLOCATION_PATH.is_file():
        raise FileNotFoundError(
            f"배정표가 없습니다: {ALLOCATION_PATH}"
        )

    data = json.loads(
        ALLOCATION_PATH.read_text(
            encoding="utf-8",
        )
    )

    if data.get("status") != "pass":
        raise ValueError(
            "배정표 상태가 pass가 아닙니다."
        )

    allocations = data.get(
        "allocations",
        [],
    )

    if len(allocations) != 10:
        raise ValueError(
            "이번 테스트는 정확히 10개 배정이 필요합니다: "
            f"actual={len(allocations)}"
        )

    text = "".join(
        str(item["hangul"])
        for item in allocations
    )

    if text != EXPECTED_HANGUL:
        raise ValueError(
            "배정된 한글 순서가 예상과 다릅니다: "
            f"{text!r}"
        )

    glyph_indices = [
        int(item["glyph_index"])
        for item in allocations
    ]

    if len(set(glyph_indices)) != len(glyph_indices):
        raise ValueError(
            "중복 글리프 슬롯이 있습니다."
        )

    sjis_codes = [
        str(item["sjis"]).upper()
        for item in allocations
    ]

    if len(set(sjis_codes)) != len(sjis_codes):
        raise ValueError(
            "중복 Shift-JIS 코드가 있습니다."
        )

    return data


def render_character(
    font_path: Path,
    character: str,
):
    """
    성공했던 build_hangul_canary.py의 렌더링 설정을
    그대로 재사용한다.

    함수가 문자 인자를 지원하면 직접 넘기고,
    기존 1문자 버전이면 모듈의 '가' 전역값을
    현재 문자로 임시 변경한다.
    """
    function = hangul_canary.render_hangul
    parameters = list(
        inspect.signature(function).parameters
    )

    if len(parameters) >= 2:
        return function(
            font_path,
            character,
        )

    changed_names: list[str] = []

    preferred_names = (
        "CHARACTER",
        "HANGUL_CHARACTER",
        "CANARY_CHARACTER",
        "TARGET_CHARACTER",
    )

    for name in preferred_names:
        if not hasattr(
            hangul_canary,
            name,
        ):
            continue

        setattr(
            hangul_canary,
            name,
            character,
        )
        changed_names.append(name)

    if not changed_names:
        for name, value in list(
            vars(hangul_canary).items()
        ):
            if value != "가":
                continue

            setattr(
                hangul_canary,
                name,
                character,
            )
            changed_names.append(name)

    if not changed_names:
        raise RuntimeError(
            "render_hangul의 대상 문자 전역값을 "
            "찾지 못했습니다."
        )

    return function(font_path)


def save_preview_sheet(
    previews: list[Image.Image],
) -> None:
    if not previews:
        return

    scale = 6
    gap = 8

    resized: list[Image.Image] = []

    for preview in previews:
        converted = preview.convert("L")
        resized.append(
            converted.resize(
                (
                    converted.width * scale,
                    converted.height * scale,
                ),
                Image.Resampling.NEAREST,
            )
        )

    width = (
        sum(image.width for image in resized)
        + gap * (len(resized) - 1)
    )
    height = max(
        image.height
        for image in resized
    )

    sheet = Image.new(
        "L",
        (width, height),
        0,
    )

    x = 0

    for image in resized:
        sheet.paste(
            image,
            (x, 0),
        )
        x += image.width + gap

    sheet.save(
        OUTPUT_PREVIEW
    )


def get_resource(
    start_data: bytes,
    records: list[dict],
    name: str,
) -> bytes:
    for record in records:
        if (
            str(record["name"]).casefold()
            == name.casefold()
        ):
            return resource_blob(
                start_data,
                record,
            )

    raise ValueError(
        f"START 리소스를 찾지 못했습니다: {name}"
    )


def main() -> int:
    allocation = load_allocation()
    allocations = allocation["allocations"]

    if OUTPUT_DIR.exists():
        shutil.rmtree(
            OUTPUT_DIR
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    font_path = (
        hangul_canary.find_korean_font()
    )

    original_start = SOURCE_START.read_bytes()
    original_system = SOURCE_SYSTEM.read_bytes()

    records = parse_start_records(
        original_start
    )

    original_txp = get_resource(
        original_start,
        records,
        "font.txp",
    )
    original_demo = get_resource(
        original_start,
        records,
        DEMO_RESOURCE,
    )

    patched_txp = bytearray(
        original_txp
    )
    patched_demo = bytearray(
        original_demo
    )

    width = struct.unpack_from(
        "<H",
        original_txp,
        0x00,
    )[0]
    height = struct.unpack_from(
        "<H",
        original_txp,
        0x02,
    )[0]

    if width != 20:
        raise ValueError(
            f"예상하지 못한 TXP 너비: {width}"
        )

    if height != 32872:
        raise ValueError(
            f"예상하지 못한 TXP 높이: {height}"
        )

    previews: list[Image.Image] = []
    glyph_results: list[dict] = []

    for item in allocations:
        character = str(
            item["hangul"]
        )
        glyph_index = int(
            item["glyph_index"]
        )

        glyph_offset = (
            TXP_PIXEL_OFFSET
            + glyph_index
            * BYTES_PER_GLYPH
        )
        glyph_end = (
            glyph_offset
            + BYTES_PER_GLYPH
        )

        if glyph_end > len(patched_txp):
            raise ValueError(
                f"{character} 글리프가 "
                "TXP 범위를 벗어났습니다: "
                f"0x{glyph_index:04X}"
            )

        pixels, preview = render_character(
            font_path,
            character,
        )
        encoded = encode_4bpp(
            pixels
        )

        if len(encoded) != BYTES_PER_GLYPH:
            raise ValueError(
                f"{character} 인코딩 크기 오류: "
                f"{len(encoded)}"
            )

        original_glyph = bytes(
            patched_txp[
                glyph_offset:
                glyph_end
            ]
        )

        changed_bytes = sum(
            before != after
            for before, after in zip(
                original_glyph,
                encoded,
            )
        )

        if changed_bytes == 0:
            raise ValueError(
                f"{character} 글리프가 기존 슬롯과 "
                "동일합니다: "
                f"0x{glyph_index:04X}"
            )

        patched_txp[
            glyph_offset:
            glyph_end
        ] = encoded

        previews.append(
            preview
        )

        glyph_results.append(
            {
                "hangul": character,
                "sjis": str(
                    item["sjis"]
                ).upper(),
                "replaced_character": str(
                    item["replaced_character"]
                ),
                "table_index": int(
                    item["table_index"]
                ),
                "table_index_hex": (
                    f"0x{int(item['table_index']):04X}"
                ),
                "glyph_index": glyph_index,
                "glyph_index_hex": (
                    f"0x{glyph_index:04X}"
                ),
                "glyph_offset": glyph_offset,
                "glyph_offset_hex": (
                    f"0x{glyph_offset:X}"
                ),
                "changed_bytes": changed_bytes,
                "encoded_sha1": sha1(
                    encoded
                ),
            }
        )

    if len(patched_txp) != len(original_txp):
        raise ValueError(
            "font.txp 크기가 변경됐습니다."
        )

    if struct.unpack_from(
        "<H",
        patched_txp,
        0x02,
    )[0] != height:
        raise ValueError(
            "font.txp 높이가 변경됐습니다."
        )

    original_text_bytes = (
        ORIGINAL_TEXT.encode(
            "shift_jis"
        )
    )

    new_text_bytes = b"".join(
        bytes.fromhex(
            str(item["sjis"])
        )
        for item in allocations
    )

    if len(original_text_bytes) != 20:
        raise ValueError(
            "원본 문자열 크기가 20바이트가 아닙니다: "
            f"{len(original_text_bytes)}"
        )

    if len(new_text_bytes) != len(
        original_text_bytes
    ):
        raise ValueError(
            "새 문자열의 바이트 길이가 다릅니다: "
            f"old={len(original_text_bytes)}, "
            f"new={len(new_text_bytes)}"
        )

    actual_original = bytes(
        patched_demo[
            DEMO_OFFSET:
            DEMO_OFFSET
            + len(original_text_bytes)
        ]
    )

    if actual_original != original_text_bytes:
        raise ValueError(
            "Demo00.dat 원본 문구가 예상과 다릅니다:\n"
            f"actual  : "
            f"{actual_original.hex(' ').upper()}\n"
            f"expected: "
            f"{original_text_bytes.hex(' ').upper()}"
        )

    patched_demo[
        DEMO_OFFSET:
        DEMO_OFFSET
        + len(new_text_bytes)
    ] = new_text_bytes

    replacements = {
        "font.txp": bytes(
            patched_txp
        ),
        DEMO_RESOURCE.casefold(): bytes(
            patched_demo
        ),
    }

    rebuilt_start = rebuild_start_archive(
        original_start,
        records,
        replacements,
    )

    if len(rebuilt_start) != len(original_start):
        raise ValueError(
            "start.dat 크기가 변경됐습니다: "
            f"0x{len(original_start):X} -> "
            f"0x{len(rebuilt_start):X}"
        )

    OUTPUT_START.write_bytes(
        rebuilt_start
    )

    rebuilt_records = parse_start_records(
        rebuilt_start
    )

    rebuilt_txp = get_resource(
        rebuilt_start,
        rebuilt_records,
        "font.txp",
    )
    rebuilt_demo = get_resource(
        rebuilt_start,
        rebuilt_records,
        DEMO_RESOURCE,
    )

    if rebuilt_txp != bytes(patched_txp):
        raise ValueError(
            "재구성된 font.txp가 패치 결과와 다릅니다."
        )

    if (
        rebuilt_demo[
            DEMO_OFFSET:
            DEMO_OFFSET + len(new_text_bytes)
        ]
        != new_text_bytes
    ):
        raise ValueError(
            "재구성 후 한글 코드 검증 실패"
        )

    StartRuntimeArchive.load(
        OUTPUT_START
    )

    start_entry = parse_nispack_start_entry(
        original_system
    )

    old_lzs_offset = int(
        start_entry["data_offset"]
    )
    old_lzs_size = int(
        start_entry["size"]
    )

    old_lzs = original_system[
        old_lzs_offset:
        old_lzs_offset + old_lzs_size
    ]

    extension = old_lzs[0:4]
    flag = read_u32(
        old_lzs,
        0x0C,
    ) & 0xFF

    new_lzs = build_literal_lzs(
        rebuilt_start,
        extension,
        flag,
    )

    OUTPUT_LZS.write_bytes(
        new_lzs
    )

    decoded_start, decoded_header = (
        decompress_buffer(
            new_lzs
        )
    )

    if decoded_start != rebuilt_start:
        raise ValueError(
            "LZS 왕복 검증 실패"
        )

    patched_system = bytearray(
        original_system
    )

    new_lzs_offset = align_up(
        len(patched_system),
        0x800,
    )

    patched_system.extend(
        b"\x00"
        * (
            new_lzs_offset
            - len(patched_system)
        )
    )
    patched_system.extend(
        new_lzs
    )

    entry_offset = int(
        start_entry["entry_offset"]
    )

    struct.pack_into(
        "<I",
        patched_system,
        entry_offset + 0x20,
        new_lzs_offset,
    )
    struct.pack_into(
        "<I",
        patched_system,
        entry_offset + 0x24,
        len(new_lzs),
    )

    patched_system_bytes = bytes(
        patched_system
    )

    OUTPUT_SYSTEM.write_bytes(
        patched_system_bytes
    )

    verified_entry = parse_nispack_start_entry(
        patched_system_bytes
    )
    verified_offset = int(
        verified_entry["data_offset"]
    )
    verified_size = int(
        verified_entry["size"]
    )

    verified_start, _ = decompress_buffer(
        patched_system_bytes[
            verified_offset:
            verified_offset + verified_size
        ]
    )

    if verified_start != rebuilt_start:
        raise ValueError(
            "SYSTEM.DAT 내부 start.dat 검증 실패"
        )

    save_preview_sheet(
        previews
    )

    manifest = {
        "format": (
            "prinny_multihangul_test_v1"
        ),
        "original_text": ORIGINAL_TEXT,
        "new_text": EXPECTED_HANGUL,
        "resource": DEMO_RESOURCE,
        "offset": DEMO_OFFSET,
        "offset_hex": (
            f"0x{DEMO_OFFSET:X}"
        ),
        "original_bytes": (
            original_text_bytes
            .hex(" ")
            .upper()
        ),
        "new_bytes": (
            new_text_bytes
            .hex(" ")
            .upper()
        ),
        "font_path": str(
            font_path
        ),
        "txp": {
            "width": width,
            "height": height,
            "original_size": len(
                original_txp
            ),
            "patched_size": len(
                patched_txp
            ),
            "original_sha1": sha1(
                original_txp
            ),
            "patched_sha1": sha1(
                bytes(patched_txp)
            ),
        },
        "start": {
            "original_size": len(
                original_start
            ),
            "patched_size": len(
                rebuilt_start
            ),
            "patched_sha1": sha1(
                rebuilt_start
            ),
        },
        "glyphs": glyph_results,
        "lzs_header": decoded_header,
        "outputs": {
            "start": str(
                OUTPUT_START
            ),
            "lzs": str(
                OUTPUT_LZS
            ),
            "system": str(
                OUTPUT_SYSTEM
            ),
            "preview": str(
                OUTPUT_PREVIEW
            ),
        },
        "status": "pass",
    }

    OUTPUT_MANIFEST.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("MULTI-HANGUL FONT TEST")
    print("======================")
    print(
        f"ORIGINAL TEXT : {ORIGINAL_TEXT}"
    )
    print(
        f"NEW TEXT      : {EXPECTED_HANGUL}"
    )
    print(
        f"DEMO OFFSET   : 0x{DEMO_OFFSET:X}"
    )
    print(
        f"GLYPHS        : {len(glyph_results)}"
    )
    print(
        f"TXP SIZE      : "
        f"0x{len(original_txp):X} -> "
        f"0x{len(patched_txp):X}"
    )
    print(
        f"TXP HEIGHT    : "
        f"{height} -> {height}"
    )
    print(
        f"START SIZE    : "
        f"0x{len(original_start):X} -> "
        f"0x{len(rebuilt_start):X}"
    )
    print()

    for item in glyph_results:
        print(
            f"{item['hangul']} "
            f"SJIS={item['sjis']} "
            f"GLYPH={item['glyph_index_hex']} "
            f"CHANGED={item['changed_bytes']}"
        )

    print()
    print("SYSTEM  :", OUTPUT_SYSTEM)
    print("PREVIEW :", OUTPUT_PREVIEW)
    print("MANIFEST:", OUTPUT_MANIFEST)
    print()
    print("SELF TEST: PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
