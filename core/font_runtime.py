#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


DEFAULT_FNT = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

DEFAULT_TXP = Path(
    "workspace/unpack/START_runtime/font.txp"
)

DEFAULT_REPORT = Path(
    "workspace/reports/font_runtime_verify.json"
)

DEFAULT_IMAGE = Path(
    "workspace/reports/font_runtime_verify.png"
)

TXP_HEADER_SIZE = 0x10
GLYPH_HEIGHT = 14

# BOOT.BIN 실행 코드와 실제 렌더링으로 확인한 값
KNOWN = {
    "の": (0x01AB, 0x011A),
    "ウ": (0x01E4, 0x0142),
    "サ": (0x01F3, 0x0151),
    "ワ": (0x022E, 0x018A),
    "命": (0x109C, 0x0835),
}


class FontRuntimeError(RuntimeError):
    """Prinny 폰트 구조가 예상과 다를 때 발생한다."""


class FontRuntime:
    """
    Prinny의 font.fnt + font.txp 런타임 폰트 처리기.

    font.fnt:
        +0x00  uint16 테이블 항목 수
        +0x02  uint16 글리프 인덱스 테이블

    font.txp:
        +0x00  TXP 헤더
        +0x10  팔레트
        +0x50  4bpp 픽셀 데이터

    글리프:
        20×14
        4bpp
        행당 10바이트
        글리프당 0x8C바이트
    """

    def __init__(
        self,
        fnt_path: Path,
        txp_path: Path,
        table: list[int],
        txp_data: bytes,
        txp: dict,
    ) -> None:
        self.fnt_path = fnt_path
        self.txp_path = txp_path
        self.table = table
        self.txp_data = txp_data
        self.txp = txp

    @classmethod
    def load(
        cls,
        fnt_path: Path | str = DEFAULT_FNT,
        txp_path: Path | str = DEFAULT_TXP,
    ) -> "FontRuntime":
        fnt_path = Path(fnt_path)
        txp_path = Path(txp_path)

        if not fnt_path.is_file():
            raise FileNotFoundError(
                f"font.fnt 없음: {fnt_path}"
            )

        if not txp_path.is_file():
            raise FileNotFoundError(
                f"font.txp 없음: {txp_path}"
            )

        fnt_data = fnt_path.read_bytes()
        txp_data = txp_path.read_bytes()

        return cls(
            fnt_path=fnt_path,
            txp_path=txp_path,
            table=cls._parse_fnt(fnt_data),
            txp_data=txp_data,
            txp=cls._parse_txp(txp_data),
        )

    @staticmethod
    def _u16(
        data: bytes,
        offset: int,
    ) -> int:
        if (
            offset < 0
            or offset + 2 > len(data)
        ):
            raise FontRuntimeError(
                f"uint16 범위 초과: "
                f"0x{offset:X}"
            )

        return struct.unpack_from(
            "<H",
            data,
            offset,
        )[0]

    @classmethod
    def _parse_fnt(
        cls,
        data: bytes,
    ) -> list[int]:
        if len(data) < 2:
            raise FontRuntimeError(
                "font.fnt가 너무 작습니다."
            )

        count = cls._u16(
            data,
            0,
        )

        expected_size = (
            2 + count * 2
        )

        if len(data) != expected_size:
            raise FontRuntimeError(
                "font.fnt 크기 불일치: "
                f"actual=0x{len(data):X}, "
                f"expected=0x{expected_size:X}"
            )

        return list(
            struct.unpack_from(
                f"<{count}H",
                data,
                2,
            )
        )

    @classmethod
    def _parse_txp(
        cls,
        data: bytes,
    ) -> dict:
        if len(data) < TXP_HEADER_SIZE:
            raise FontRuntimeError(
                "font.txp가 너무 작습니다."
            )

        width = cls._u16(
            data,
            0x00,
        )

        height = cls._u16(
            data,
            0x02,
        )

        pixel_format = cls._u16(
            data,
            0x04,
        )

        palette_width = cls._u16(
            data,
            0x08,
        )

        palette_height = cls._u16(
            data,
            0x0A,
        )

        palette_size = (
            palette_width
            * palette_height
            * 4
        )

        pixel_offset = (
            TXP_HEADER_SIZE
            + palette_size
        )

        bytes_per_row = (
            width + 1
        ) // 2

        expected_pixel_size = (
            bytes_per_row
            * height
        )

        actual_pixel_size = (
            len(data)
            - pixel_offset
        )

        if (
            actual_pixel_size
            != expected_pixel_size
        ):
            raise FontRuntimeError(
                "font.txp 픽셀 크기 불일치: "
                f"actual=0x{actual_pixel_size:X}, "
                f"expected=0x{expected_pixel_size:X}"
            )

        if height % GLYPH_HEIGHT:
            raise FontRuntimeError(
                "font.txp 높이가 글리프 높이 "
                "14의 배수가 아닙니다."
            )

        bytes_per_glyph = (
            bytes_per_row
            * GLYPH_HEIGHT
        )

        glyph_count = (
            height
            // GLYPH_HEIGHT
        )

        return {
            "width": width,
            "height": height,
            "pixel_format": pixel_format,
            "palette_width": palette_width,
            "palette_height": palette_height,
            "palette_size": palette_size,
            "pixel_offset": pixel_offset,
            "bytes_per_row": bytes_per_row,
            "glyph_height": GLYPH_HEIGHT,
            "bytes_per_glyph": bytes_per_glyph,
            "glyph_count": glyph_count,
        }

    @staticmethod
    def _lead_slot(
        lead: int,
    ) -> int:
        if 0x81 <= lead <= 0x9F:
            return lead - 0x81

        if 0xE0 <= lead <= 0xFC:
            return lead - 0xC1

        raise FontRuntimeError(
            "잘못된 Shift-JIS 리드 바이트: "
            f"0x{lead:02X}"
        )

    @classmethod
    def table_index_from_sjis(
        cls,
        encoded: bytes,
    ) -> int:
        """
        Shift-JIS 문자를 font.fnt 테이블 인덱스로 변환한다.

        단일 바이트:
            index = value - 0x20

        2바이트:
            index =
                0x5F
                + lead_slot * 0xC0
                + (trail - 0x40)
        """

        if len(encoded) == 1:
            value = encoded[0]

            if 0x20 <= value <= 0x7E:
                return value - 0x20

            raise FontRuntimeError(
                "지원하지 않는 단일 바이트 문자: "
                f"{encoded.hex(' ').upper()}"
            )

        if len(encoded) != 2:
            raise FontRuntimeError(
                "Shift-JIS 문자 길이는 "
                "1 또는 2여야 합니다."
            )

        lead = encoded[0]
        trail = encoded[1]

        if not 0x40 <= trail <= 0xFC:
            raise FontRuntimeError(
                "잘못된 Shift-JIS 트레일 바이트: "
                f"0x{trail:02X}"
            )

        return (
            0x5F
            + cls._lead_slot(lead) * 0xC0
            + (trail - 0x40)
        )

    def mapping_for_char(
        self,
        character: str,
    ) -> dict:
        if len(character) != 1:
            raise ValueError(
                "문자 하나만 전달해야 합니다."
            )

        try:
            encoded = character.encode(
                "shift_jis"
            )

        except UnicodeEncodeError as error:
            raise FontRuntimeError(
                "Shift-JIS에 없는 문자: "
                f"{character!r} "
                f"U+{ord(character):04X}"
            ) from error

        table_index = (
            self.table_index_from_sjis(
                encoded
            )
        )

        if table_index >= len(self.table):
            raise FontRuntimeError(
                "font.fnt 인덱스 범위 초과: "
                f"0x{table_index:X}"
            )

        glyph_index = self.table[
            table_index
        ]

        glyph_offset = (
            self.txp["pixel_offset"]
            + glyph_index
            * self.txp["bytes_per_glyph"]
        )

        glyph_valid = (
            glyph_index
            < self.txp["glyph_count"]
        )

        return {
            "character": character,
            "unicode": (
                f"U+{ord(character):04X}"
            ),
            "shift_jis": (
                encoded.hex(" ").upper()
            ),
            "table_index": table_index,
            "table_offset": (
                2 + table_index * 2
            ),
            "glyph_index": glyph_index,
            "glyph_offset": glyph_offset,
            "glyph_valid": glyph_valid,
        }

    def decode_glyph(
        self,
        glyph_index: int,
    ) -> Image.Image:
        if not (
            0 <= glyph_index
            < self.txp["glyph_count"]
        ):
            raise FontRuntimeError(
                "글리프 범위 초과: "
                f"0x{glyph_index:04X}"
            )

        start = (
            self.txp["pixel_offset"]
            + glyph_index
            * self.txp["bytes_per_glyph"]
        )

        end = (
            start
            + self.txp["bytes_per_glyph"]
        )

        blob = self.txp_data[
            start:end
        ]

        image = Image.new(
            "L",
            (
                self.txp["width"],
                self.txp["glyph_height"],
            ),
            0,
        )

        pixels = image.load()

        for y in range(
            self.txp["glyph_height"]
        ):
            row_offset = (
                y
                * self.txp["bytes_per_row"]
            )

            for byte_index in range(
                self.txp["bytes_per_row"]
            ):
                value = blob[
                    row_offset + byte_index
                ]

                x = byte_index * 2

                # 왼쪽 픽셀 = low nibble
                # 오른쪽 픽셀 = high nibble
                left = value & 0x0F
                right = (
                    value >> 4
                ) & 0x0F

                if x < self.txp["width"]:
                    pixels[x, y] = (
                        left * 17
                    )

                if (
                    x + 1
                    < self.txp["width"]
                ):
                    pixels[x + 1, y] = (
                        right * 17
                    )

        return image

    def render_sample(
        self,
        text: Iterable[str],
        output: Path | str,
        scale: int = 8,
    ) -> list[dict]:
        mappings = [
            self.mapping_for_char(
                character
            )
            for character in text
        ]

        if not mappings:
            raise ValueError(
                "출력할 문자가 없습니다."
            )

        if scale <= 0:
            raise ValueError(
                "scale은 1 이상이어야 합니다."
            )

        cell_width = max(
            self.txp["width"]
            * scale
            + 30,
            190,
        )

        cell_height = (
            self.txp["glyph_height"]
            * scale
            + 43
        )

        sheet = Image.new(
            "RGB",
            (
                cell_width
                * len(mappings),
                cell_height,
            ),
            "black",
        )

        draw = ImageDraw.Draw(
            sheet
        )

        label_font = (
            ImageFont.load_default()
        )

        for column, mapping in enumerate(
            mappings
        ):
            glyph = self.decode_glyph(
                mapping["glyph_index"]
            )

            glyph = glyph.resize(
                (
                    self.txp["width"]
                    * scale,
                    self.txp["glyph_height"]
                    * scale,
                ),
                Image.Resampling.NEAREST,
            ).convert("RGB")

            cell_x = (
                column
                * cell_width
            )

            glyph_x = (
                cell_x
                + (
                    cell_width
                    - glyph.width
                ) // 2
            )

            sheet.paste(
                glyph,
                (
                    glyph_x,
                    4,
                ),
            )

            labels = [
                mapping["unicode"],
                (
                    "SJIS "
                    + mapping[
                        "shift_jis"
                    ].replace(
                        " ",
                        "",
                    )
                ),
                (
                    f"T="
                    f"{mapping['table_index']:04X} "
                    f"G="
                    f"{mapping['glyph_index']:04X}"
                ),
            ]

            label_y = (
                self.txp["glyph_height"]
                * scale
                + 5
            )

            for row, label in enumerate(
                labels
            ):
                draw.text(
                    (
                        cell_x + 5,
                        label_y
                        + row * 11,
                    ),
                    label,
                    fill="white",
                    font=label_font,
                )

            draw.rectangle(
                (
                    cell_x,
                    0,
                    cell_x
                    + cell_width
                    - 1,
                    cell_height
                    - 1,
                ),
                outline="white",
            )

        output = Path(output)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        sheet.save(
            output
        )

        return mappings

    def verify(
        self,
    ) -> dict:
        checks = []

        for character, (
            expected_table,
            expected_glyph,
        ) in KNOWN.items():
            mapping = (
                self.mapping_for_char(
                    character
                )
            )

            table_match = (
                mapping["table_index"]
                == expected_table
            )

            glyph_match = (
                mapping["glyph_index"]
                == expected_glyph
            )

            ok = (
                table_match
                and glyph_match
                and mapping["glyph_valid"]
            )

            checks.append(
                {
                    **mapping,
                    "expected_table_index":
                        expected_table,
                    "expected_glyph_index":
                        expected_glyph,
                    "table_match":
                        table_match,
                    "glyph_match":
                        glyph_match,
                    "ok": ok,
                }
            )

        return {
            "font_fnt": str(
                self.fnt_path
            ),
            "font_txp": str(
                self.txp_path
            ),
            "table_entries":
                len(self.table),
            "table_count_match":
                len(self.table)
                == 0x2D5F,
            "table_value_max":
                max(self.table),
            "txp":
                self.txp,
            "glyph_count_match":
                self.txp["glyph_count"]
                == 0x092C,
            "invalid_table_values":
                sum(
                    value
                    >= self.txp[
                        "glyph_count"
                    ]
                    for value in self.table
                ),
            "checks":
                checks,
            "matched":
                sum(
                    check["ok"]
                    for check in checks
                ),
            "total":
                len(checks),
        }


def run_verify(
    args: argparse.Namespace,
) -> int:
    runtime = FontRuntime.load(
        args.font_fnt,
        args.font_txp,
    )

    result = runtime.verify()

    runtime.render_sample(
        KNOWN.keys(),
        args.output,
        args.scale,
    )

    report_path = Path(
        args.report
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "FONT RUNTIME INTEGRATION VERIFY"
    )

    print(
        "==============================="
    )

    print(
        "FONT.FNT ENTRIES :",
        f"0x{result['table_entries']:X}",
        f"({result['table_entries']})",
    )

    print(
        "TABLE COUNT MATCH:",
        result["table_count_match"],
    )

    print(
        "TXP              :",
        f"{runtime.txp['width']}×"
        f"{runtime.txp['height']}",
    )

    print(
        "PIXEL OFFSET     :",
        f"0x{runtime.txp['pixel_offset']:X}",
    )

    print(
        "GLYPH            :",
        f"{runtime.txp['width']}×"
        f"{runtime.txp['glyph_height']},",
        f"0x{runtime.txp['bytes_per_glyph']:X}",
        "bytes",
    )

    print(
        "GLYPH COUNT      :",
        f"0x{runtime.txp['glyph_count']:X}",
        f"({runtime.txp['glyph_count']})",
    )

    print(
        "GLYPH COUNT MATCH:",
        result["glyph_count_match"],
    )

    print(
        "INVALID MAP VALUES:",
        result["invalid_table_values"],
    )

    print()

    for check in result["checks"]:
        state = (
            "MATCH"
            if check["ok"]
            else "MISMATCH"
        )

        print(
            f"{check['character']} "
            f"SJIS={check['shift_jis']} "
            f"TABLE=0x"
            f"{check['table_index']:04X} "
            f"GLYPH=0x"
            f"{check['glyph_index']:04X} "
            f"{state}"
        )

    print()

    print(
        "SELF TEST:",
        f"{result['matched']}/"
        f"{result['total']}",
    )

    print(
        "REPORT   :",
        report_path,
    )

    print(
        "IMAGE    :",
        args.output,
    )

    if (
        result["matched"]
        == result["total"]
    ):
        return 0

    return 1


def run_sample(
    args: argparse.Namespace,
) -> int:
    runtime = FontRuntime.load(
        args.font_fnt,
        args.font_txp,
    )

    mappings = runtime.render_sample(
        args.text,
        args.output,
        args.scale,
    )

    for mapping in mappings:
        print(
            f"{mapping['character']} "
            f"{mapping['unicode']} "
            f"SJIS="
            f"{mapping['shift_jis']} "
            f"TABLE=0x"
            f"{mapping['table_index']:04X} "
            f"GLYPH=0x"
            f"{mapping['glyph_index']:04X}"
        )

    print(
        "IMAGE:",
        args.output,
    )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prinny 런타임 폰트 분석기"
        )
    )

    parser.add_argument(
        "--font-fnt",
        type=Path,
        default=DEFAULT_FNT,
    )

    parser.add_argument(
        "--font-txp",
        type=Path,
        default=DEFAULT_TXP,
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    verify = commands.add_parser(
        "verify",
        help=(
            "확정된 다섯 글자로 "
            "폰트 구조를 검증합니다."
        ),
    )

    verify.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_IMAGE,
    )

    verify.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
    )

    verify.add_argument(
        "--scale",
        type=int,
        default=8,
    )

    verify.set_defaults(
        handler=run_verify,
    )

    sample = commands.add_parser(
        "sample",
        help=(
            "문자열의 글리프를 "
            "PNG로 생성합니다."
        ),
    )

    sample.add_argument(
        "text",
    )

    sample.add_argument(
        "--output",
        type=Path,
        default=Path(
            "workspace/reports/"
            "font_sample.png"
        ),
    )

    sample.add_argument(
        "--scale",
        type=int,
        default=8,
    )

    sample.set_defaults(
        handler=run_sample,
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.handler(
            args
        )

    except (
        FileNotFoundError,
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
