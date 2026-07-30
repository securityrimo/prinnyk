from __future__ import annotations

import hashlib
import json
import mmap
import struct
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOTS = [
    Path("workspace/unpack/START_runtime"),
    Path("workspace/iso/PSP_GAME"),
]

DEFAULT_OUTPUT_DIR = Path(
    "workspace/reports/assets"
)

EMBEDDED_SIGNATURES = [
    ("png", b"\x89PNG\r\n\x1A\n"),
    ("gim", b"MIG.00.1PSP"),
    ("tim2", b"TIM2"),
    ("jpeg", b"\xFF\xD8\xFF"),
    ("gif87a", b"GIF87a"),
    ("gif89a", b"GIF89a"),
]

EXTENSION_FORMATS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".bmp": "bmp",
    ".gif": "gif",
    ".gim": "gim",
    ".tm2": "tim2",
    ".tim2": "tim2",
    ".txp": "txp",
    ".pmf": "pmf",
    ".at3": "at3",
    ".wav": "wav",
    ".ogg": "ogg",
}

UI_NAME_TOKENS = {
    "ui",
    "menu",
    "title",
    "logo",
    "icon",
    "window",
    "select",
    "option",
    "config",
    "help",
    "tutorial",
    "demo",
    "stageinfo",
    "item",
    "skill",
    "status",
    "result",
    "clear",
    "gameover",
    "load",
    "save",
    "map",
    "common",
    "system",
    "message",
    "caption",
    "button",
}


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()

    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def identify_header(data: bytes, suffix: str) -> str:
    if data.startswith(b"\x89PNG\r\n\x1A\n"):
        return "png"

    if data.startswith(b"MIG.00.1PSP"):
        return "gim"

    if data.startswith(b"TIM2"):
        return "tim2"

    if data.startswith(b"\xFF\xD8\xFF"):
        return "jpeg"

    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"

    if data.startswith(b"BM"):
        return "bmp"

    if data.startswith(b"PSMF"):
        return "pmf"

    if data.startswith(b"OggS"):
        return "ogg"

    if data.startswith(b"RIFF"):
        if data[8:12] == b"WAVE":
            return "riff-wave"

        return "riff"

    return EXTENSION_FORMATS.get(
        suffix.casefold(),
        "unknown",
    )


def png_dimensions(
    data: bytes,
    offset: int = 0,
) -> tuple[int, int] | None:
    if (
        offset < 0
        or offset + 24 > len(data)
        or data[
            offset:
            offset + 8
        ] != b"\x89PNG\r\n\x1A\n"
        or data[
            offset + 12:
            offset + 16
        ] != b"IHDR"
    ):
        return None

    width, height = struct.unpack_from(
        ">II",
        data,
        offset + 16,
    )

    if (
        width <= 0
        or height <= 0
        or width > 16384
        or height > 16384
    ):
        return None

    return width, height


def ui_score(
    relative_path: str,
    detected_format: str,
    width: int | None,
    height: int | None,
) -> int:
    lowered = relative_path.casefold()
    score = 0

    for token in UI_NAME_TOKENS:
        if token in lowered:
            score += 2

    if detected_format in {
        "png",
        "gim",
        "tim2",
        "txp",
        "jpeg",
        "bmp",
        "gif",
    }:
        score += 1

    if width is not None and height is not None:
        if width >= 128 and height >= 32:
            score += 1

        if width >= 256 or height >= 128:
            score += 1

    return score


def validate_embedded(
    view: mmap.mmap,
    detected_format: str,
    offset: int,
) -> tuple[int | None, int | None]:
    if detected_format == "png":
        if (
            offset + 24 > len(view)
            or view[
                offset + 12:
                offset + 16
            ] != b"IHDR"
        ):
            return None, None

        width, height = struct.unpack_from(
            ">II",
            view,
            offset + 16,
        )

        if (
            width <= 0
            or height <= 0
            or width > 16384
            or height > 16384
        ):
            return None, None

        return width, height

    return None, None


def iter_signature_offsets(
    view: mmap.mmap,
    signature: bytes,
) -> Iterable[int]:
    position = 0

    while True:
        position = view.find(
            signature,
            position,
        )

        if position < 0:
            return

        yield position
        position += 1


def scan_file(
    *,
    path: Path,
    root: Path,
    root_name: str,
    scan_embedded: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    relative_path = str(
        path.relative_to(root)
    )

    size = path.stat().st_size

    with path.open("rb") as handle:
        header = handle.read(64)

    detected_format = identify_header(
        header,
        path.suffix,
    )

    width: int | None = None
    height: int | None = None

    if detected_format == "png":
        dimensions = png_dimensions(header)

        if dimensions is not None:
            width, height = dimensions

    score = ui_score(
        relative_path,
        detected_format,
        width,
        height,
    )

    file_record: dict[str, Any] = {
        "id": f"{root_name}:{relative_path}",
        "kind": "file",
        "root": root_name,
        "path": str(path),
        "relative_path": relative_path,
        "size": size,
        "size_hex": f"0x{size:X}",
        "extension": path.suffix.casefold(),
        "format": detected_format,
        "width": width,
        "height": height,
        "ui_score": score,
        "likely_ui": score >= 3,
        "sha1": sha1_file(path),
        "header_hex": header.hex(" ").upper(),
    }

    embedded: list[dict[str, Any]] = []

    if (
        not scan_embedded
        or size == 0
    ):
        return file_record, embedded

    with path.open("rb") as handle:
        with mmap.mmap(
            handle.fileno(),
            0,
            access=mmap.ACCESS_READ,
        ) as view:
            for (
                embedded_format,
                signature,
            ) in EMBEDDED_SIGNATURES:
                for offset in iter_signature_offsets(
                    view,
                    signature,
                ):
                    if (
                        offset == 0
                        and detected_format
                        in {
                            embedded_format,
                            "gif",
                        }
                    ):
                        continue

                    embedded_width, embedded_height = (
                        validate_embedded(
                            view,
                            embedded_format,
                            offset,
                        )
                    )

                    if (
                        embedded_format == "png"
                        and embedded_width is None
                    ):
                        continue

                    embedded_score = ui_score(
                        relative_path,
                        embedded_format,
                        embedded_width,
                        embedded_height,
                    )

                    embedded.append(
                        {
                            "id": (
                                f"{root_name}:"
                                f"{relative_path}"
                                f"@0x{offset:X}"
                            ),
                            "kind": "embedded",
                            "root": root_name,
                            "container_path": str(
                                path
                            ),
                            "relative_path": (
                                relative_path
                            ),
                            "offset": offset,
                            "offset_hex": (
                                f"0x{offset:X}"
                            ),
                            "format": (
                                embedded_format
                            ),
                            "width": (
                                embedded_width
                            ),
                            "height": (
                                embedded_height
                            ),
                            "ui_score": (
                                embedded_score
                            ),
                            "likely_ui": (
                                embedded_score >= 3
                            ),
                            "signature_hex": (
                                signature
                                .hex(" ")
                                .upper()
                            ),
                        }
                    )

    return file_record, embedded


def scan_assets(
    *,
    roots: list[Path] | None = None,
    scan_embedded: bool = True,
) -> dict[str, Any]:
    selected_roots = (
        roots
        if roots is not None
        else DEFAULT_ROOTS
    )

    existing_roots: list[
        tuple[str, Path]
    ] = []

    for root in selected_roots:
        if not root.is_dir():
            continue

        name = root.name

        if root == Path(
            "workspace/unpack/START_runtime"
        ):
            name = "start_runtime"
        elif root == Path(
            "workspace/iso/PSP_GAME"
        ):
            name = "psp_game"

        existing_roots.append(
            (
                name,
                root,
            )
        )

    if not existing_roots:
        raise FileNotFoundError(
            "조사할 자산 폴더가 없습니다. "
            "먼저 unpack-system과 unpack-start를 실행하세요."
        )

    files: list[dict[str, Any]] = []
    embedded: list[dict[str, Any]] = []

    for root_name, root in existing_roots:
        for path in sorted(
            root.rglob("*")
        ):
            if not path.is_file():
                continue

            file_record, embedded_records = (
                scan_file(
                    path=path,
                    root=root,
                    root_name=root_name,
                    scan_embedded=scan_embedded,
                )
            )

            files.append(
                file_record
            )
            embedded.extend(
                embedded_records
            )

    formats = Counter(
        record["format"]
        for record in files
    )

    embedded_formats = Counter(
        record["format"]
        for record in embedded
    )

    ui_candidates = sorted(
        [
            record
            for record in (
                files + embedded
            )
            if record["likely_ui"]
        ],
        key=lambda item: (
            -int(item["ui_score"]),
            str(
                item.get(
                    "relative_path",
                    "",
                )
            ),
            int(
                item.get(
                    "offset",
                    0,
                )
            ),
        ),
    )

    return {
        "format": "prinny_asset_inventory_v1",
        "roots": [
            {
                "name": name,
                "path": str(path),
            }
            for name, path in existing_roots
        ],
        "file_count": len(files),
        "embedded_asset_count": len(
            embedded
        ),
        "ui_candidate_count": len(
            ui_candidates
        ),
        "formats": dict(
            sorted(
                formats.items()
            )
        ),
        "embedded_formats": dict(
            sorted(
                embedded_formats.items()
            )
        ),
        "files": files,
        "embedded_assets": embedded,
        "ui_candidates": ui_candidates,
        "status": "pass",
    }


def save_asset_report(
    report: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> None:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = output_dir / "assets.json"
    text_path = output_dir / "assets.txt"

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
        "PRINNY ASSET INVENTORY",
        "======================",
        (
            f"FILES           : "
            f"{report['file_count']}"
        ),
        (
            f"EMBEDDED ASSETS : "
            f"{report['embedded_asset_count']}"
        ),
        (
            f"UI CANDIDATES   : "
            f"{report['ui_candidate_count']}"
        ),
        "",
        "FILE FORMATS",
        "------------",
    ]

    for name, count in report[
        "formats"
    ].items():
        lines.append(
            f"{count:6d}  {name}"
        )

    lines.extend(
        [
            "",
            "EMBEDDED FORMATS",
            "----------------",
        ]
    )

    for name, count in report[
        "embedded_formats"
    ].items():
        lines.append(
            f"{count:6d}  {name}"
        )

    lines.extend(
        [
            "",
            "TOP UI CANDIDATES",
            "-----------------",
        ]
    )

    for item in report[
        "ui_candidates"
    ][:100]:
        location = item.get(
            "relative_path",
            item.get(
                "path",
                "",
            ),
        )

        if item["kind"] == "embedded":
            location += (
                f"@{item['offset_hex']}"
            )

        dimensions = ""

        if (
            item.get("width") is not None
            and item.get("height") is not None
        ):
            dimensions = (
                f" "
                f"{item['width']}x"
                f"{item['height']}"
            )

        lines.append(
            f"SCORE={item['ui_score']:2d} "
            f"FORMAT={item['format']:8s} "
            f"{location}"
            f"{dimensions}"
        )

    lines.extend(
        [
            "",
            f"JSON   : {json_path}",
            f"REPORT : {text_path}",
            "STATUS : PASS",
        ]
    )

    text_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
