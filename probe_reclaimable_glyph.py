#!/usr/bin/env python3
from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path


RUNTIME_DIR = Path(
    "workspace/unpack/START_runtime"
)

SCAN_ROOTS = [
    Path("workspace/unpack/START_runtime"),
    Path("workspace/unpack/SCRIPT_fixed"),
    Path("workspace/nsf"),
]

FNT_PATH = RUNTIME_DIR / "font.fnt"
JIS2UCS_PATH = RUNTIME_DIR / "jis2ucs.bin"

REPORT_PATH = Path(
    "workspace/reports/reclaimable_glyphs.json"
)

GLYPH_COUNT = 2348
MAX_RESULTS = 30


def read_u16(
    data: bytes,
    offset: int,
) -> int:
    return struct.unpack_from(
        "<H",
        data,
        offset,
    )[0]


def jis_to_sjis(
    row: int,
    cell: int,
) -> bytes:
    row_index = row - 0x21
    lead = row_index // 2 + 0x81

    if lead > 0x9F:
        lead += 0x40

    if row_index % 2 == 0:
        trail = cell + 0x1F

        if trail >= 0x7F:
            trail += 1
    else:
        trail = cell + 0x7E

    return bytes(
        [lead, trail]
    )


def table_index(
    row: int,
    cell: int,
) -> int:
    return (
        100
        + (row - 0x21) * 94
        + (cell - 0x21)
    )


def collect_scan_files() -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue

            resolved = path.resolve()

            if resolved in seen:
                continue

            seen.add(resolved)
            files.append(path)

    return files


def is_preferred_character(
    character: str,
) -> bool:
    codepoint = ord(character)

    # 우선 희귀 한자를 선택한다.
    return (
        0x4E00 <= codepoint <= 0x9FFF
        or 0x3400 <= codepoint <= 0x4DBF
    )


def main() -> int:
    if not FNT_PATH.is_file():
        raise FileNotFoundError(
            f"font.fnt 없음: {FNT_PATH}"
        )

    if not JIS2UCS_PATH.is_file():
        raise FileNotFoundError(
            f"jis2ucs.bin 없음: {JIS2UCS_PATH}"
        )

    fnt = FNT_PATH.read_bytes()
    jis2ucs = JIS2UCS_PATH.read_bytes()

    table_count = read_u16(
        fnt,
        0,
    )

    glyph_table = [
        read_u16(
            fnt,
            2 + index * 2,
        )
        for index in range(table_count)
    ]

    glyph_reference_counts = Counter(
        glyph_table
    )

    scan_files = collect_scan_files()
    scan_blobs: list[tuple[Path, bytes]] = []

    for path in scan_files:
        try:
            scan_blobs.append(
                (
                    path,
                    path.read_bytes(),
                )
            )
        except OSError as error:
            print(
                f"SKIP: {path}: {error}"
            )

    candidates: list[dict[str, object]] = []

    # 후반부 JIS 행부터 내려오며 희귀 문자 우선 조사
    for row in range(0x74, 0x20, -1):
        for cell in range(0x21, 0x7F):
            jis = (
                row << 8
            ) | cell

            index = table_index(
                row,
                cell,
            )

            if index >= table_count:
                continue

            sjis = jis_to_sjis(
                row,
                cell,
            )

            # 구조상 가능하더라도 실제 Shift-JIS에서
            # 미할당이면 여기에서 제외된다.
            try:
                decoded = sjis.decode(
                    "shift_jis",
                    errors="strict",
                )
            except UnicodeDecodeError:
                continue

            if len(decoded) != 1:
                continue

            unicode_value = read_u16(
                jis2ucs,
                jis * 2,
            )

            if unicode_value == 0:
                continue

            if unicode_value != ord(decoded):
                continue

            glyph_index = glyph_table[index]

            if (
                glyph_index == 0
                or glyph_index >= GLYPH_COUNT
            ):
                continue

            reference_count = (
                glyph_reference_counts[
                    glyph_index
                ]
            )

            # 같은 글리프를 여러 코드가 공유하면 제외
            if reference_count != 1:
                continue

            occurrences: list[dict[str, object]] = []
            total_occurrences = 0

            for path, blob in scan_blobs:
                count = blob.count(sjis)

                if count == 0:
                    continue

                total_occurrences += count
                occurrences.append(
                    {
                        "path": str(path),
                        "count": count,
                    }
                )

            if total_occurrences != 0:
                continue

            candidates.append(
                {
                    "character": decoded,
                    "unicode": unicode_value,
                    "unicode_hex": (
                        f"U+{unicode_value:04X}"
                    ),
                    "jis": jis,
                    "jis_hex": (
                        f"0x{jis:04X}"
                    ),
                    "sjis_hex": (
                        sjis.hex(" ").upper()
                    ),
                    "table_index": index,
                    "table_index_hex": (
                        f"0x{index:04X}"
                    ),
                    "glyph_index": glyph_index,
                    "glyph_index_hex": (
                        f"0x{glyph_index:04X}"
                    ),
                    "glyph_reference_count": (
                        reference_count
                    ),
                    "occurrences": (
                        total_occurrences
                    ),
                    "preferred_kanji": (
                        is_preferred_character(
                            decoded
                        )
                    ),
                }
            )

    candidates.sort(
        key=lambda item: (
            not bool(
                item["preferred_kanji"]
            ),
            -int(item["jis"]),
        )
    )

    selected = candidates[
        :MAX_RESULTS
    ]

    if not selected:
        raise SystemExit(
            "재활용 가능한 유효 글리프를 "
            "찾지 못했습니다."
        )

    report = {
        "format": (
            "prinny_reclaimable_glyph_probe_v1"
        ),
        "table_count": table_count,
        "glyph_count": GLYPH_COUNT,
        "scanned_files": len(scan_blobs),
        "candidate_count": len(candidates),
        "candidates": selected,
        "status": "pass",
    }

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("RECLAIMABLE GLYPH CANDIDATES")
    print("============================")
    print(
        f"SCANNED FILES  : "
        f"{len(scan_blobs)}"
    )
    print(
        f"TOTAL CANDIDATES: "
        f"{len(candidates)}"
    )
    print()

    for number, item in enumerate(
        selected,
        start=1,
    ):
        print(
            f"{number:2d}. "
            f"CHAR={item['character']!r} "
            f"{item['unicode_hex']} "
            f"JIS={item['jis_hex']} "
            f"SJIS={item['sjis_hex']} "
            f"TABLE={item['table_index_hex']} "
            f"GLYPH={item['glyph_index_hex']} "
            f"REFS={item['glyph_reference_count']} "
            f"USES={item['occurrences']}"
        )

    print()
    print("REPORT:", REPORT_PATH)
    print("STATUS: PASS")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
