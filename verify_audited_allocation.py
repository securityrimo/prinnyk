#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from probe_textaware_font_capacity import (
    table_index_from_sjis,
)


ALLOCATION_PATH = Path(
    "workspace/font/audited_allocation/"
    "hangul_allocation.json"
)

RUNTIME_DIR = Path(
    "workspace/unpack/START_runtime"
)

OUTPUT_DIR = Path(
    "workspace/font/audited_allocation/"
    "verification"
)

TXP_PIXEL_OFFSET = 0x50
BYTES_PER_GLYPH = 140
EXPECTED_GLYPH_COUNT = 2348
EXPECTED_ALLOCATION_COUNT = 975


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()

    with path.open("rb") as handle:
        while True:
            block = handle.read(
                1024 * 1024
            )

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def read_u16(
    data: bytes,
    offset: int,
) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise ValueError(
            f"u16 범위 초과: 0x{offset:X}"
        )

    return struct.unpack_from(
        "<H",
        data,
        offset,
    )[0]


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"배정 파일이 없습니다: {path}"
        )

    document = json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )

    if not isinstance(document, dict):
        raise ValueError(
            "배정 JSON 최상위 값이 객체가 아닙니다."
        )

    return document


def locate_unique(
    root: Path,
    filename: str,
) -> Path:
    matches = [
        path
        for path in root.rglob(filename)
        if path.is_file()
    ]

    if not matches:
        raise FileNotFoundError(
            f"{filename}을 찾지 못했습니다: {root}"
        )

    if len(matches) > 1:
        descriptions = "\n".join(
            f"  - {path}"
            for path in matches
        )

        raise RuntimeError(
            f"{filename}이 여러 개 발견되었습니다:\n"
            f"{descriptions}"
        )

    return matches[0]


def parse_sjis(
    allocation: dict[str, Any],
) -> tuple[int, int, int]:
    value = allocation.get(
        "sjis_value"
    )

    if isinstance(value, int):
        sjis_value = value
    else:
        text = str(
            allocation.get(
                "sjis",
                "",
            )
        ).replace(
            " ",
            "",
        )

        if len(text) != 4:
            raise ValueError(
                "잘못된 SJIS 문자열: "
                f"{allocation.get('sjis')!r}"
            )

        sjis_value = int(
            text,
            16,
        )

    lead = (
        sjis_value >> 8
    ) & 0xFF

    trail = sjis_value & 0xFF

    return lead, trail, sjis_value


def main() -> int:
    allocation_document = load_json(
        ALLOCATION_PATH
    )

    status = str(
        allocation_document.get(
            "status",
            "",
        )
    ).casefold()

    if status != "pass":
        raise ValueError(
            f"배정 상태가 PASS가 아닙니다: {status!r}"
        )

    allocations = allocation_document.get(
        "allocations"
    )

    if not isinstance(
        allocations,
        list,
    ):
        raise ValueError(
            "allocations 목록이 없습니다."
        )

    required_count = int(
        allocation_document.get(
            "required_count",
            -1,
        )
    )

    selected_count = int(
        allocation_document.get(
            "selected_count",
            len(allocations),
        )
    )

    if required_count != EXPECTED_ALLOCATION_COUNT:
        raise ValueError(
            "필요 한글 수가 예상과 다릅니다: "
            f"{required_count}"
        )

    if selected_count != EXPECTED_ALLOCATION_COUNT:
        raise ValueError(
            "선택 글리프 수가 예상과 다릅니다: "
            f"{selected_count}"
        )

    if len(allocations) != EXPECTED_ALLOCATION_COUNT:
        raise ValueError(
            "실제 allocations 수가 예상과 다릅니다: "
            f"{len(allocations)}"
        )

    font_fnt = locate_unique(
        RUNTIME_DIR,
        "font.fnt",
    )

    font_txp = locate_unique(
        RUNTIME_DIR,
        "font.txp",
    )

    fnt_data = font_fnt.read_bytes()
    txp_data = font_txp.read_bytes()

    table_count = read_u16(
        fnt_data,
        0,
    )

    expected_fnt_size = (
        2 + table_count * 2
    )

    if len(fnt_data) < expected_fnt_size:
        raise ValueError(
            "font.fnt가 테이블 전체보다 작습니다: "
            f"file={len(fnt_data)}, "
            f"required={expected_fnt_size}"
        )

    pixel_size = (
        len(txp_data)
        - TXP_PIXEL_OFFSET
    )

    if pixel_size < 0:
        raise ValueError(
            "font.txp가 픽셀 시작 위치보다 작습니다."
        )

    if (
        pixel_size
        % BYTES_PER_GLYPH
        != 0
    ):
        raise ValueError(
            "font.txp 픽셀 영역이 "
            "140바이트 단위가 아닙니다: "
            f"{pixel_size}"
        )

    glyph_count = (
        pixel_size
        // BYTES_PER_GLYPH
    )

    if glyph_count != EXPECTED_GLYPH_COUNT:
        raise ValueError(
            "글리프 수가 예상과 다릅니다: "
            f"{glyph_count}"
        )

    source_translation = Path(
        str(
            allocation_document.get(
                "source_translation",
                "",
            )
        )
    )

    expected_translation_sha1 = str(
        allocation_document.get(
            "source_translation_sha1",
            "",
        )
    )

    translation_hash_status = (
        "not-recorded"
    )

    if (
        source_translation.is_file()
        and expected_translation_sha1
    ):
        actual_translation_sha1 = sha1_file(
            source_translation
        )

        if (
            actual_translation_sha1
            != expected_translation_sha1
        ):
            raise ValueError(
                "번역 CSV가 배정 후 변경되었습니다.\n"
                f"기록 SHA1: "
                f"{expected_translation_sha1}\n"
                f"현재 SHA1: "
                f"{actual_translation_sha1}\n"
                "문자셋 계획과 배정을 다시 실행해야 합니다."
            )

        translation_hash_status = "match"

    seen_hangul: set[str] = set()
    seen_sjis: set[int] = set()
    seen_tables: set[int] = set()
    seen_glyphs: set[int] = set()

    errors: list[str] = []
    safety_counts: Counter[str] = Counter()

    minimum_glyph = glyph_count
    maximum_glyph = -1

    for position, allocation in enumerate(
        allocations,
        start=1,
    ):
        hangul = str(
            allocation.get(
                "hangul",
                "",
            )
        )

        if len(hangul) != 1:
            errors.append(
                f"#{position}: 한글 값이 한 글자가 아님 "
                f"{hangul!r}"
            )
            continue

        codepoint = ord(hangul)

        if not (
            0xAC00
            <= codepoint
            <= 0xD7A3
        ):
            errors.append(
                f"#{position}: 현대 한글 음절이 아님 "
                f"{hangul!r}"
            )

        if hangul in seen_hangul:
            errors.append(
                f"#{position}: 중복 한글 {hangul!r}"
            )

        seen_hangul.add(hangul)

        try:
            (
                lead,
                trail,
                sjis_value,
            ) = parse_sjis(
                allocation
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            errors.append(
                f"#{position}: {error}"
            )
            continue

        table_index = int(
            allocation.get(
                "table_index",
                -1,
            )
        )

        glyph_index = int(
            allocation.get(
                "glyph_index",
                -1,
            )
        )

        safety = str(
            allocation.get(
                "safety",
                "",
            )
        )

        safety_counts[safety] += 1

        if sjis_value in seen_sjis:
            errors.append(
                f"#{position}: 중복 SJIS "
                f"{lead:02X} {trail:02X}"
            )

        seen_sjis.add(sjis_value)

        if table_index in seen_tables:
            errors.append(
                f"#{position}: 중복 테이블 "
                f"0x{table_index:04X}"
            )

        seen_tables.add(table_index)

        if glyph_index in seen_glyphs:
            errors.append(
                f"#{position}: 중복 글리프 "
                f"0x{glyph_index:04X}"
            )

        seen_glyphs.add(glyph_index)

        computed_table_index = (
            table_index_from_sjis(
                lead,
                trail,
            )
        )

        if (
            computed_table_index
            != table_index
        ):
            errors.append(
                f"#{position}: SJIS→테이블 불일치 "
                f"stored=0x{table_index:04X}, "
                f"computed=0x{computed_table_index:04X}"
            )

        if not (
            0 <= table_index
            < table_count
        ):
            errors.append(
                f"#{position}: 테이블 범위 초과 "
                f"0x{table_index:04X}"
            )
            continue

        actual_glyph_index = read_u16(
            fnt_data,
            2 + table_index * 2,
        )

        if (
            actual_glyph_index
            != glyph_index
        ):
            errors.append(
                f"#{position}: font.fnt 매핑 불일치 "
                f"table=0x{table_index:04X}, "
                f"allocation=0x{glyph_index:04X}, "
                f"font=0x{actual_glyph_index:04X}"
            )

        if not (
            0 < glyph_index
            < glyph_count
        ):
            errors.append(
                f"#{position}: 글리프 범위 초과 "
                f"0x{glyph_index:04X}"
            )
            continue

        glyph_start = (
            TXP_PIXEL_OFFSET
            + glyph_index
            * BYTES_PER_GLYPH
        )

        glyph_end = (
            glyph_start
            + BYTES_PER_GLYPH
        )

        if glyph_end > len(
            txp_data
        ):
            errors.append(
                f"#{position}: TXP 기록 범위 초과 "
                f"0x{glyph_start:X}..0x{glyph_end:X}"
            )

        minimum_glyph = min(
            minimum_glyph,
            glyph_index,
        )

        maximum_glyph = max(
            maximum_glyph,
            glyph_index,
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    report = {
        "format": (
            "prinny_audited_allocation_verification_v1"
        ),
        "allocation": str(
            ALLOCATION_PATH
        ),
        "allocation_sha1": sha1_file(
            ALLOCATION_PATH
        ),
        "font_fnt": str(font_fnt),
        "font_fnt_sha1": sha1_file(
            font_fnt
        ),
        "font_txp": str(font_txp),
        "font_txp_sha1": sha1_file(
            font_txp
        ),
        "table_count": table_count,
        "glyph_count": glyph_count,
        "allocation_count": len(
            allocations
        ),
        "unique_hangul": len(
            seen_hangul
        ),
        "unique_sjis": len(
            seen_sjis
        ),
        "unique_tables": len(
            seen_tables
        ),
        "unique_glyphs": len(
            seen_glyphs
        ),
        "minimum_glyph": (
            minimum_glyph
        ),
        "maximum_glyph": (
            maximum_glyph
        ),
        "safety_counts": dict(
            sorted(
                safety_counts.items()
            )
        ),
        "translation_hash_status": (
            translation_hash_status
        ),
        "error_count": len(errors),
        "errors": errors,
        "status": (
            "pass"
            if not errors
            else "fail"
        ),
    }

    json_path = (
        OUTPUT_DIR
        / "verification.json"
    )

    text_path = (
        OUTPUT_DIR
        / "verification.txt"
    )

    json_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "AUDITED HANGUL ALLOCATION VERIFICATION",
        "======================================",
        (
            "ALLOCATION COUNT      : "
            f"{len(allocations)}"
        ),
        (
            "UNIQUE HANGUL         : "
            f"{len(seen_hangul)}"
        ),
        (
            "UNIQUE SJIS           : "
            f"{len(seen_sjis)}"
        ),
        (
            "UNIQUE TABLES         : "
            f"{len(seen_tables)}"
        ),
        (
            "UNIQUE GLYPHS         : "
            f"{len(seen_glyphs)}"
        ),
        (
            "FONT TABLE COUNT      : "
            f"{table_count}"
        ),
        (
            "FONT GLYPH COUNT      : "
            f"{glyph_count}"
        ),
        (
            "MINIMUM GLYPH         : "
            f"0x{minimum_glyph:04X}"
        ),
        (
            "MAXIMUM GLYPH         : "
            f"0x{maximum_glyph:04X}"
        ),
        (
            "TRANSLATION SHA1      : "
            f"{translation_hash_status}"
        ),
        (
            "AUDITED-STRICT        : "
            f"{safety_counts.get('audited-strict', 0)}"
        ),
        (
            "ERRORS                : "
            f"{len(errors)}"
        ),
    ]

    if errors:
        lines.extend(
            [
                "",
                "ERROR DETAILS",
                "-------------",
            ]
        )

        lines.extend(
            errors[:100]
        )

    lines.extend(
        [
            "",
            f"JSON   : {json_path}",
            (
                "STATUS : PASS"
                if not errors
                else "STATUS : FAIL"
            ),
        ]
    )

    output = "\n".join(lines)

    text_path.write_text(
        output + "\n",
        encoding="utf-8",
    )

    print(output)

    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
