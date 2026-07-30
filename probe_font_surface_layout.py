#!/usr/bin/env python3

import struct
from pathlib import Path


INPUT_PATH = Path(
    "workspace/unpack/START_runtime/font.fnt"
)

MAX_WIDTH = 4096
CELL_SIZE = 16


def unpack_4bpp(
    packed: bytes,
    low_first: bool,
) -> bytearray:
    pixels = bytearray(len(packed) * 2)

    output = 0

    for value in packed:
        low = value & 0x0F
        high = value >> 4

        if low_first:
            pixels[output] = low
            pixels[output + 1] = high
        else:
            pixels[output] = high
            pixels[output + 1] = low

        output += 2

    return pixels


def unswizzle_psp(
    source: bytes,
    width_bytes: int,
    height: int,
) -> bytes | None:
    """
    PSP 기본 텍스처 swizzle 후보:

        블록 폭  16바이트
        블록 높이 8행
    """

    if width_bytes < 16:
        return None

    if width_bytes % 16:
        return None

    if height % 8:
        return None

    if len(source) != width_bytes * height:
        return None

    destination = bytearray(len(source))

    blocks_x = width_bytes // 16
    blocks_y = height // 8

    source_position = 0

    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            for row in range(8):
                destination_position = (
                    (block_y * 8 + row)
                    * width_bytes
                    + block_x * 16
                )

                destination[
                    destination_position:
                    destination_position + 16
                ] = source[
                    source_position:
                    source_position + 16
                ]

                source_position += 16

    if source_position != len(source):
        return None

    return bytes(destination)


def calculate_metrics(
    pixels: bytearray,
    width: int,
    height: int,
) -> dict:
    """
    사람 눈 대신 다음 특징을 측정한다.

    1. 세로 이웃 픽셀의 연속성
    2. 활성 픽셀끼리의 밝기 차이
    3. 16픽셀 주기 경계의 빈 공간 비율
    4. 한 행 끝과 다음 행 시작의 빈 공간 비율
    """

    vertical_pairs = 0
    vertical_equal = 0
    vertical_difference = 0

    active_pairs = 0
    active_equal = 0
    active_difference = 0

    # 전체 데이터의 약 1/4만 표본 조사한다.
    for y in range(0, height - 1, 2):
        row = y * width
        next_row = row + width

        for x in range(0, width, 2):
            first = pixels[row + x]
            second = pixels[next_row + x]

            difference = abs(first - second)

            vertical_pairs += 1
            vertical_difference += difference

            if first == second:
                vertical_equal += 1

            if first != 0 or second != 0:
                active_pairs += 1
                active_difference += difference

                if first == second:
                    active_equal += 1

    horizontal_pairs = 0
    horizontal_equal = 0
    horizontal_difference = 0

    for y in range(0, height, 2):
        row = y * width

        for x in range(0, width - 1, 2):
            first = pixels[row + x]
            second = pixels[row + x + 1]

            horizontal_pairs += 1
            horizontal_difference += abs(first - second)

            if first == second:
                horizontal_equal += 1

    border_samples = 0
    border_zeros = 0

    # 16×16 셀 경계 후보의 빈 공간 비율
    for y in range(0, height, 2):
        row = y * width

        for x in range(0, width, CELL_SIZE):
            for border_x in (x, min(x + CELL_SIZE - 1, width - 1)):
                border_samples += 1

                if pixels[row + border_x] == 0:
                    border_zeros += 1

    for y in range(0, height, CELL_SIZE):
        for border_y in (y, min(y + CELL_SIZE - 1, height - 1)):
            row = border_y * width

            for x in range(0, width, 2):
                border_samples += 1

                if pixels[row + x] == 0:
                    border_zeros += 1

    wrap_samples = 0
    wrap_zero_pairs = 0
    wrap_difference = 0

    for y in range(height - 1):
        first = pixels[
            y * width + width - 1
        ]

        second = pixels[
            (y + 1) * width
        ]

        wrap_samples += 1
        wrap_difference += abs(first - second)

        if first == 0 and second == 0:
            wrap_zero_pairs += 1

    def percentage(
        numerator: int,
        denominator: int,
    ) -> float:
        if denominator == 0:
            return 0.0

        return numerator * 100.0 / denominator

    vertical_equal_percent = percentage(
        vertical_equal,
        vertical_pairs,
    )

    horizontal_equal_percent = percentage(
        horizontal_equal,
        horizontal_pairs,
    )

    active_equal_percent = percentage(
        active_equal,
        active_pairs,
    )

    border_zero_percent = percentage(
        border_zeros,
        border_samples,
    )

    wrap_zero_percent = percentage(
        wrap_zero_pairs,
        wrap_samples,
    )

    average_vertical_difference = (
        vertical_difference / vertical_pairs
        if vertical_pairs
        else 0.0
    )

    average_horizontal_difference = (
        horizontal_difference / horizontal_pairs
        if horizontal_pairs
        else 0.0
    )

    average_active_difference = (
        active_difference / active_pairs
        if active_pairs
        else 0.0
    )

    average_wrap_difference = (
        wrap_difference / wrap_samples
        if wrap_samples
        else 0.0
    )

    # 팔레트값이 0~8이므로 차이 8을 최악으로 정규화한다.
    active_smoothness = max(
        0.0,
        100.0
        - average_active_difference * 12.5,
    )

    wrap_smoothness = max(
        0.0,
        100.0
        - average_wrap_difference * 12.5,
    )

    score = (
        active_equal_percent * 0.30
        + active_smoothness * 0.25
        + vertical_equal_percent * 0.15
        + border_zero_percent * 0.20
        + wrap_zero_percent * 0.05
        + wrap_smoothness * 0.05
    )

    return {
        "score": score,
        "vertical_equal": vertical_equal_percent,
        "horizontal_equal": horizontal_equal_percent,
        "active_equal": active_equal_percent,
        "vertical_difference": average_vertical_difference,
        "horizontal_difference": average_horizontal_difference,
        "active_difference": average_active_difference,
        "border_zero": border_zero_percent,
        "wrap_zero": wrap_zero_percent,
        "wrap_difference": average_wrap_difference,
    }


def main() -> int:
    if not INPUT_PATH.is_file():
        print(
            "ERROR: 파일이 없습니다:",
            INPUT_PATH,
        )
        return 1

    data = INPUT_PATH.read_bytes()

    palette_count = struct.unpack_from(
        "<H",
        data,
        0x00,
    )[0]

    header_size = (
        0x10
        + palette_count * 4
    )

    payload = data[header_size:]

    total_pixels = len(payload) * 2

    candidate_widths = [
        width
        for width in range(
            CELL_SIZE,
            MAX_WIDTH + 1,
            CELL_SIZE,
        )
        if total_pixels % width == 0
    ]

    print("FONT SURFACE AUTO PROBE")
    print("=======================")
    print("FILE SIZE       :", f"0x{len(data):X}")
    print("HEADER SIZE     :", f"0x{header_size:X}")
    print("PAYLOAD SIZE    :", f"0x{len(payload):X}")
    print("PIXEL FORMAT    :", "4bpp")
    print("TOTAL PIXELS    :", total_pixels)
    print(
        "CANDIDATE WIDTHS:",
        " ".join(
            str(width)
            for width in candidate_widths
        ),
    )

    results = []

    for width in candidate_widths:
        height = total_pixels // width
        width_bytes = width // 2

        packed_variants = [
            ("LINEAR", payload),
        ]

        unswizzled = unswizzle_psp(
            payload,
            width_bytes,
            height,
        )

        if unswizzled is not None:
            packed_variants.append(
                ("UNSWIZZLE", unswizzled)
            )

        for storage_mode, packed in packed_variants:
            for low_first in (True, False):
                pixels = unpack_4bpp(
                    packed,
                    low_first,
                )

                metrics = calculate_metrics(
                    pixels,
                    width,
                    height,
                )

                results.append(
                    {
                        "width": width,
                        "height": height,
                        "storage": storage_mode,
                        "order": (
                            "LOW"
                            if low_first
                            else "HIGH"
                        ),
                        **metrics,
                    }
                )

    results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    print()
    print("TOP 24 CANDIDATES")
    print("=================")

    for rank, item in enumerate(
        results[:24],
        start=1,
    ):
        print(
            f'{rank:02d}. '
            f'{item["width"]:4d}x{item["height"]:<5d} '
            f'{item["storage"]:<9} '
            f'{item["order"]:<4} '
            f'SCORE={item["score"]:6.2f} '
            f'ACTIVE_EQ={item["active_equal"]:6.2f}% '
            f'ACTIVE_DIFF={item["active_difference"]:5.2f} '
            f'VERT_EQ={item["vertical_equal"]:6.2f}% '
            f'BORDER_ZERO={item["border_zero"]:6.2f}% '
            f'WRAP_ZERO={item["wrap_zero"]:6.2f}%'
        )

    print()
    print("BEST RESULT PER WIDTH")
    print("=====================")

    seen_widths = set()

    for item in results:
        width = item["width"]

        if width in seen_widths:
            continue

        seen_widths.add(width)

        print(
            f'{item["width"]:4d}x{item["height"]:<5d} '
            f'{item["storage"]:<9} '
            f'{item["order"]:<4} '
            f'SCORE={item["score"]:6.2f}'
        )

    print()
    print("다음 단계에서는 TOP 24 중 상위 후보만 렌더링합니다.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
