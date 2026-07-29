from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import struct
from pathlib import Path
from typing import Any

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


DEFAULT_ALLOCATION = Path(
    "workspace/font/hangul_map.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "workspace/build/font"
)


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def read_u16(
    data: bytes,
    offset: int,
) -> int:
    return struct.unpack_from(
        "<H",
        data,
        offset,
    )[0]


def parse_offset(value: int | str) -> int:
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        result = int(
            value.strip(),
            0,
        )
    else:
        raise ValueError(
            f"잘못된 offset 형식: {value!r}"
        )

    if result < 0:
        raise ValueError(
            f"offset은 음수일 수 없습니다: {result}"
        )

    return result


def lead_slot(lead: int) -> int:
    if 0x81 <= lead <= 0x9F:
        return lead - 0x81

    if 0xE0 <= lead <= 0xFC:
        return lead - 0xC1

    raise ValueError(
        f"잘못된 Shift-JIS 리드 바이트: "
        f"0x{lead:02X}"
    )


def table_index_from_sjis(
    lead: int,
    trail: int,
) -> int:
    return (
        0x1F
        + trail
        + lead_slot(lead) * 0xC0
    )


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"JSON 파일이 없습니다: {path}"
        )

    data = json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )

    if not isinstance(data, dict):
        raise ValueError(
            f"JSON 최상위 값이 객체가 아닙니다: {path}"
        )

    return data


def get_resource(
    start_data: bytes,
    records: list[dict[str, Any]],
    name: str,
) -> bytes:
    matches = [
        record
        for record in records
        if (
            str(record["name"]).casefold()
            == name.casefold()
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            f"START 리소스 {name!r}의 "
            f"레코드 수가 {len(matches)}개입니다."
        )

    return resource_blob(
        start_data,
        matches[0],
    )


def render_character(
    font_path: Path,
    character: str,
):
    function = hangul_canary.render_hangul

    parameters = list(
        inspect.signature(
            function
        ).parameters
    )

    if len(parameters) >= 2:
        return function(
            font_path,
            character,
        )

    preferred_names = (
        "CHARACTER",
        "HANGUL_CHARACTER",
        "CANARY_CHARACTER",
        "TARGET_CHARACTER",
    )

    changed: dict[str, object] = {}

    for name in preferred_names:
        if not hasattr(
            hangul_canary,
            name,
        ):
            continue

        changed[name] = getattr(
            hangul_canary,
            name,
        )
        setattr(
            hangul_canary,
            name,
            character,
        )

    if not changed:
        for name, value in list(
            vars(
                hangul_canary
            ).items()
        ):
            if value != "가":
                continue

            changed[name] = value
            setattr(
                hangul_canary,
                name,
                character,
            )

    if not changed:
        raise RuntimeError(
            "render_hangul의 대상 문자 변수를 "
            "찾지 못했습니다."
        )

    try:
        return function(
            font_path
        )
    finally:
        for name, old_value in changed.items():
            setattr(
                hangul_canary,
                name,
                old_value,
            )


def encode_mapped_text(
    text: str,
    encoded_map: dict[str, str],
) -> bytes:
    result = bytearray()

    for character in text:
        mapped = encoded_map.get(
            character
        )

        if mapped is not None:
            result.extend(
                bytes.fromhex(
                    mapped
                )
            )
            continue

        try:
            result.extend(
                character.encode(
                    "shift_jis",
                    errors="strict",
                )
            )
        except UnicodeEncodeError as error:
            raise ValueError(
                "배정표에 없는 문자를 "
                "Shift-JIS로 인코딩할 수 없습니다: "
                f"{character!r}"
            ) from error

    return bytes(result)


def save_preview_sheet(
    previews: list[tuple[str, Image.Image]],
    output_path: Path,
) -> None:
    if not previews:
        return

    scale = 6
    gap = 8

    rendered: list[Image.Image] = []

    for _, preview in previews:
        image = preview.convert("L")

        rendered.append(
            image.resize(
                (
                    image.width * scale,
                    image.height * scale,
                ),
                Image.Resampling.NEAREST,
            )
        )

    width = (
        sum(
            image.width
            for image in rendered
        )
        + gap * (
            len(rendered) - 1
        )
    )
    height = max(
        image.height
        for image in rendered
    )

    sheet = Image.new(
        "L",
        (width, height),
        0,
    )

    x = 0

    for image in rendered:
        sheet.paste(
            image,
            (x, 0),
        )
        x += image.width + gap

    sheet.save(
        output_path
    )


def build_font_patch(
    *,
    allocation_path: Path,
    patches_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    allocation = load_json(
        allocation_path
    )
    patch_document = load_json(
        patches_path
    )

    if allocation.get("status") != "pass":
        raise ValueError(
            "한글 배정표 상태가 pass가 아닙니다."
        )

    allocations = allocation.get(
        "allocations"
    )

    if not isinstance(
        allocations,
        list,
    ) or not allocations:
        raise ValueError(
            "한글 배정표에 allocations가 없습니다."
        )

    patch_entries = patch_document.get(
        "patches"
    )

    if not isinstance(
        patch_entries,
        list,
    ) or not patch_entries:
        raise ValueError(
            "패치 문서에 patches가 없습니다."
        )

    encoded_map = {
        str(item["hangul"]):
            str(item["sjis"]).upper()
        for item in allocations
    }

    if output_dir.exists():
        shutil.rmtree(
            output_dir
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_start = (
        output_dir / "start.dat"
    )
    output_lzs = (
        output_dir / "start.lzs"
    )
    output_system = (
        output_dir / "SYSTEM.DAT"
    )
    output_preview = (
        output_dir / "preview.png"
    )
    output_manifest = (
        output_dir / "manifest.json"
    )

    original_start = (
        SOURCE_START.read_bytes()
    )
    original_system = (
        SOURCE_SYSTEM.read_bytes()
    )

    records = parse_start_records(
        original_start
    )

    original_fnt = get_resource(
        original_start,
        records,
        "font.fnt",
    )
    original_txp = get_resource(
        original_start,
        records,
        "font.txp",
    )

    table_count = read_u16(
        original_fnt,
        0,
    )

    width = read_u16(
        original_txp,
        0x00,
    )
    height = read_u16(
        original_txp,
        0x02,
    )

    if width != 20:
        raise ValueError(
            f"예상하지 못한 TXP 너비: {width}"
        )

    patched_txp = bytearray(
        original_txp
    )

    font_path = (
        hangul_canary.find_korean_font()
    )

    preview_items: list[
        tuple[str, Image.Image]
    ] = []

    glyph_results: list[
        dict[str, Any]
    ] = []

    seen_glyphs: set[int] = set()

    for item in allocations:
        hangul = str(
            item["hangul"]
        )
        sjis = bytes.fromhex(
            str(item["sjis"])
        )
        table_index = int(
            item["table_index"]
        )
        glyph_index = int(
            item["glyph_index"]
        )

        if len(sjis) != 2:
            raise ValueError(
                f"{hangul}의 Shift-JIS 코드가 "
                "2바이트가 아닙니다."
            )

        calculated_table = (
            table_index_from_sjis(
                sjis[0],
                sjis[1],
            )
        )

        if calculated_table != table_index:
            raise ValueError(
                f"{hangul} 테이블 인덱스 불일치: "
                f"map=0x{table_index:04X}, "
                f"calculated=0x{calculated_table:04X}"
            )

        if not (
            0 <= table_index
            < table_count
        ):
            raise ValueError(
                f"{hangul} 테이블 인덱스가 "
                "범위를 벗어났습니다."
            )

        actual_glyph = read_u16(
            original_fnt,
            2 + table_index * 2,
        )

        if actual_glyph != glyph_index:
            raise ValueError(
                f"{hangul}의 font.fnt 매핑 불일치: "
                f"expected=0x{glyph_index:04X}, "
                f"actual=0x{actual_glyph:04X}"
            )

        if glyph_index in seen_glyphs:
            raise ValueError(
                "중복 글리프 슬롯: "
                f"0x{glyph_index:04X}"
            )

        seen_glyphs.add(
            glyph_index
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

        if glyph_end > len(
            patched_txp
        ):
            raise ValueError(
                f"{hangul} 글리프 슬롯이 "
                "TXP 범위를 벗어났습니다."
            )

        pixels, preview = (
            render_character(
                font_path,
                hangul,
            )
        )

        encoded_glyph = encode_4bpp(
            pixels
        )

        if (
            len(encoded_glyph)
            != BYTES_PER_GLYPH
        ):
            raise ValueError(
                f"{hangul} 글리프 크기 오류: "
                f"{len(encoded_glyph)}"
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
                encoded_glyph,
            )
        )

        if changed_bytes == 0:
            raise ValueError(
                f"{hangul} 글리프가 기존 슬롯과 "
                "동일합니다."
            )

        patched_txp[
            glyph_offset:
            glyph_end
        ] = encoded_glyph

        preview_items.append(
            (
                hangul,
                preview,
            )
        )

        glyph_results.append(
            {
                "hangul": hangul,
                "sjis": (
                    sjis.hex(" ").upper()
                ),
                "table_index": table_index,
                "table_index_hex": (
                    f"0x{table_index:04X}"
                ),
                "glyph_index": glyph_index,
                "glyph_index_hex": (
                    f"0x{glyph_index:04X}"
                ),
                "glyph_offset": glyph_offset,
                "glyph_offset_hex": (
                    f"0x{glyph_offset:X}"
                ),
                "changed_bytes": (
                    changed_bytes
                ),
                "glyph_sha1": sha1(
                    encoded_glyph
                ),
                "replaced_character": str(
                    item.get(
                        "replaced_character",
                        "",
                    )
                ),
            }
        )

    if len(patched_txp) != len(
        original_txp
    ):
        raise ValueError(
            "font.txp 크기가 변경됐습니다."
        )

    if read_u16(
        patched_txp,
        0x02,
    ) != height:
        raise ValueError(
            "font.txp 높이가 변경됐습니다."
        )

    patched_resources: dict[
        str,
        bytearray
    ] = {}

    used_ranges: dict[
        str,
        list[tuple[int, int]]
    ] = {}

    patch_results: list[
        dict[str, Any]
    ] = []

    for number, patch in enumerate(
        patch_entries,
        start=1,
    ):
        if not isinstance(
            patch,
            dict,
        ):
            raise ValueError(
                f"patches[{number - 1}]가 "
                "객체가 아닙니다."
            )

        resource_name = str(
            patch["resource"]
        )
        offset = parse_offset(
            patch["offset"]
        )
        source_text = str(
            patch["source"]
        )
        translated_text = str(
            patch["translation"]
        )

        key = resource_name.casefold()

        if key not in patched_resources:
            original_resource = get_resource(
                original_start,
                records,
                resource_name,
            )
            patched_resources[key] = bytearray(
                original_resource
            )
            used_ranges[key] = []

        resource_data = patched_resources[
            key
        ]

        source_bytes = source_text.encode(
            "shift_jis",
            errors="strict",
        )
        translated_bytes = encode_mapped_text(
            translated_text,
            encoded_map,
        )

        if (
            len(source_bytes)
            != len(translated_bytes)
        ):
            raise ValueError(
                f"{resource_name}+0x{offset:X}: "
                "고정 크기 조건 위반: "
                f"source={len(source_bytes)}, "
                f"translation={len(translated_bytes)}"
            )

        end = (
            offset
            + len(source_bytes)
        )

        if end > len(resource_data):
            raise ValueError(
                f"{resource_name}+0x{offset:X}: "
                "패치 범위가 파일을 벗어났습니다."
            )

        for old_start, old_end in used_ranges[
            key
        ]:
            if (
                offset < old_end
                and end > old_start
            ):
                raise ValueError(
                    f"{resource_name}: "
                    "패치 범위가 서로 겹칩니다."
                )

        actual_bytes = bytes(
            resource_data[
                offset:
                end
            ]
        )

        if actual_bytes != source_bytes:
            raise ValueError(
                f"{resource_name}+0x{offset:X}: "
                "원본 문자열이 예상과 다릅니다.\n"
                f"actual  : "
                f"{actual_bytes.hex(' ').upper()}\n"
                f"expected: "
                f"{source_bytes.hex(' ').upper()}"
            )

        resource_data[
            offset:
            end
        ] = translated_bytes

        used_ranges[key].append(
            (
                offset,
                end,
            )
        )

        patch_results.append(
            {
                "resource": resource_name,
                "offset": offset,
                "offset_hex": (
                    f"0x{offset:X}"
                ),
                "source": source_text,
                "translation": translated_text,
                "source_bytes": (
                    source_bytes
                    .hex(" ")
                    .upper()
                ),
                "translation_bytes": (
                    translated_bytes
                    .hex(" ")
                    .upper()
                ),
                "byte_length": len(
                    source_bytes
                ),
            }
        )

    replacements: dict[str, bytes] = {
        "font.txp": bytes(
            patched_txp
        ),
    }

    for key, data in (
        patched_resources.items()
    ):
        replacements[key] = bytes(
            data
        )

    rebuilt_start = rebuild_start_archive(
        original_start,
        records,
        replacements,
    )

    if (
        len(rebuilt_start)
        != len(original_start)
    ):
        raise ValueError(
            "start.dat 크기가 변경됐습니다: "
            f"0x{len(original_start):X} -> "
            f"0x{len(rebuilt_start):X}"
        )

    output_start.write_bytes(
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

    if rebuilt_txp != bytes(
        patched_txp
    ):
        raise ValueError(
            "재구성된 font.txp가 "
            "패치 결과와 다릅니다."
        )

    for key, expected_data in (
        patched_resources.items()
    ):
        rebuilt_resource = get_resource(
            rebuilt_start,
            rebuilt_records,
            key,
        )

        if rebuilt_resource != bytes(
            expected_data
        ):
            raise ValueError(
                f"재구성된 {key}가 "
                "패치 결과와 다릅니다."
            )

    StartRuntimeArchive.load(
        output_start
    )

    start_entry = (
        parse_nispack_start_entry(
            original_system
        )
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

    output_lzs.write_bytes(
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

    output_system.write_bytes(
        patched_system_bytes
    )

    verified_entry = (
        parse_nispack_start_entry(
            patched_system_bytes
        )
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
            verified_offset
            + verified_size
        ]
    )

    if verified_start != rebuilt_start:
        raise ValueError(
            "SYSTEM.DAT 내부 start.dat "
            "검증 실패"
        )

    save_preview_sheet(
        preview_items,
        output_preview,
    )

    manifest: dict[str, Any] = {
        "format": (
            "prinny_font_build_v1"
        ),
        "allocation": str(
            allocation_path
        ),
        "patches": str(
            patches_path
        ),
        "font_path": str(
            font_path
        ),
        "glyph_count": len(
            glyph_results
        ),
        "text_patch_count": len(
            patch_results
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
        "system": {
            "patched_size": len(
                patched_system_bytes
            ),
            "patched_sha1": sha1(
                patched_system_bytes
            ),
        },
        "glyphs": glyph_results,
        "text_patches": patch_results,
        "lzs_header": decoded_header,
        "outputs": {
            "start": str(
                output_start
            ),
            "lzs": str(
                output_lzs
            ),
            "system": str(
                output_system
            ),
            "preview": str(
                output_preview
            ),
            "manifest": str(
                output_manifest
            ),
        },
        "status": "pass",
    }

    output_manifest.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return manifest
