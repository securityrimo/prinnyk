#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from scripts.prinny_txp_preview import decode_txp


ROOT = Path(__file__).resolve().parents[1]
ISO_ROOT = ROOT / "workspace/iso"
UNPACK_ROOT = ROOT / "workspace/unpack"
OUTPUT = ROOT / "workspace/exports/prinny1_v7_14_15_images"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_verified(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if source.stat().st_size != target.stat().st_size or sha256(source) != sha256(target):
        raise ValueError(f"복사 검증 실패: {source}")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    for required in (
        ISO_ROOT,
        UNPACK_ROOT / "START_runtime",
        UNPACK_ROOT / "BG_runtime",
        UNPACK_ROOT / "ANIME_runtime",
    ):
        if not required.exists():
            raise FileNotFoundError(required)

    rows: list[dict[str, Any]] = []
    decoded = 0
    unsupported = 0

    for source in sorted(ISO_ROOT.rglob("*.PNG")):
        relative = source.relative_to(ISO_ROOT)
        target = OUTPUT / "png_editable/iso_direct" / relative
        copy_verified(source, target)
        with Image.open(target) as image:
            width, height = image.size
        rows.append(
            {
                "category": "iso_direct_png",
                "container": "ISO",
                "source": str(source),
                "raw_export": "",
                "png_export": str(target),
                "width": width,
                "height": height,
                "source_size": source.stat().st_size,
                "source_sha256": sha256(source),
                "conversion_status": "copied_verified",
                "notes": "원본 PNG; 같은 캔버스 크기로 수정",
            }
        )

    txp_roots = (
        ("START.DAT", UNPACK_ROOT / "START_runtime"),
        ("BG.DAT", UNPACK_ROOT / "BG_runtime"),
    )
    for container, source_root in txp_roots:
        for source in sorted(source_root.rglob("*")):
            if not source.is_file() or source.suffix.casefold() != ".txp":
                continue
            relative = source.relative_to(source_root)
            raw_target = OUTPUT / "raw_txp" / container.replace(".", "_") / relative
            png_target = (
                OUTPUT
                / "png_editable"
                / container.replace(".", "_")
                / relative.with_suffix(".png")
            )
            copy_verified(source, raw_target)
            status = "decoded"
            notes = "PNG 수정 후 동일 이름으로 반환; 원본 TXP 재삽입은 별도 검증"
            width: int | str = ""
            height: int | str = ""
            try:
                image = decode_txp(source)
                png_target.parent.mkdir(parents=True, exist_ok=True)
                image.save(png_target)
                width, height = image.size
                decoded += 1
            except ValueError as error:
                status = "raw_only_unsupported_layout"
                notes = str(error)
                png_target = Path("")
                unsupported += 1
            rows.append(
                {
                    "category": "txp",
                    "container": container,
                    "source": str(source),
                    "raw_export": str(raw_target),
                    "png_export": str(png_target) if str(png_target) != "." else "",
                    "width": width,
                    "height": height,
                    "source_size": source.stat().st_size,
                    "source_sha256": sha256(source),
                    "conversion_status": status,
                    "notes": notes,
                }
            )

    anime_sources = [UNPACK_ROOT / "START_runtime/anime00.dat"] + sorted(
        (UNPACK_ROOT / "ANIME_runtime").glob("anime*.dat")
    )
    for source in anime_sources:
        container = "START.DAT" if source.name == "anime00.dat" else "ANIME.DAT"
        raw_target = OUTPUT / "anime_containers" / container.replace(".", "_") / source.name
        copy_verified(source, raw_target)
        rows.append(
            {
                "category": "anime_container",
                "container": container,
                "source": str(source),
                "raw_export": str(raw_target),
                "png_export": "",
                "width": "",
                "height": "",
                "source_size": source.stat().st_size,
                "source_sha256": sha256(source),
                "conversion_status": "container_copied_sprite_decode_pending",
                "notes": "여러 팔레트·스프라이트가 포함된 전용 컨테이너",
            }
        )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT / "image_inventory.csv", rows)
    report = {
        "format": "prinny1_v7_14_15_image_export_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_iso_tree": str(ISO_ROOT),
        "counts": {
            "inventory_rows": len(rows),
            "direct_iso_png": sum(row["category"] == "iso_direct_png" for row in rows),
            "txp_total": sum(row["category"] == "txp" for row in rows),
            "txp_decoded_png": decoded,
            "txp_raw_only": unsupported,
            "anime_containers": len(anime_sources),
            "external_runtime_texture_exports": 0,
        },
        "checks": {
            "all_raw_copies_hash_verified": True,
            "source_files_modified": 0,
            "iso_created": False,
        },
        "status": (
            "editable_png_export_complete_anime_sprite_decode_pending"
            if unsupported or anime_sources
            else "complete"
        ),
    }
    (OUTPUT / "all_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT / "README.md").write_text(
        "# Prinny 1 이미지 편집 작업 폴더\n\n"
        "- `png_editable/`: 직접 수정할 PNG입니다. 캔버스 크기와 알파 채널을 유지하세요.\n"
        "- `raw_txp/`: PNG의 원본 TXP입니다. 삭제하거나 수정하지 마세요.\n"
        "- `anime_containers/`: 전용 애니메이션 원본입니다. 내부 스프라이트 추출은 진행 중입니다.\n"
        "- `image_inventory.csv`: 원본 경로, 해시, 크기, 변환 상태 목록입니다.\n"
        "- 이 폴더에는 PPSSPP 외부 텍스처 교체 파일이 포함되지 않습니다.\n\n"
        "수정한 PNG는 파일명과 크기를 유지한 채 별도 폴더에 모아 주세요. 적용 시 ISO 내부 원본 TXP/컨테이너에 재삽입하고 Expected Write를 다시 검증합니다.\n",
        encoding="utf-8",
    )
    print(f"목록 행: {len(rows)}")
    print(f"TXP: {decoded + unsupported} (PNG {decoded}, raw-only {unsupported})")
    print(f"애니메이션 컨테이너: {len(anime_sources)}")
    print("외부 런타임 텍스처: 0")
    print(f"출력: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
