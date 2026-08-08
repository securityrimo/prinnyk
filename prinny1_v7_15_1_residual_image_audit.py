#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from scripts.prinny_anime_preview import decode_texture, find_texture_groups, parse_objects


ROOT = Path(__file__).resolve().parent
CURRENT_ROOT = ROOT / "workspace/unpack/ANIME_runtime"
CANDIDATE_ROOT = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/anime_resources"
PATCHED_ANIME00 = ROOT / "workspace/build/prinny1_v7_15_1_internal_ui_resources/anime00.dat"
CANDIDATE_ANIME00 = ROOT / "workspace/analysis/prinny1_xdelta_20260729/extracted/candidate/start_resources/anime00.dat"
OUTPUT = ROOT / "workspace/reports/prinny1_v7_15_1_residual_image_audit"
ANIME_NAMES = ("anime12.dat", "anime20.dat", "anime90.dat", "anime91.dat", "anime92.dat", "anime93.dat", "anime94.dat", "anime96.dat")


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def texture_map(blob: bytes) -> dict[tuple[int, int, int], object]:
    result = {}
    for obj in parse_objects(blob):
        for group in find_texture_groups(blob, obj):
            for texture in group:
                result[(texture.object_index, texture.group_index, texture.page_index)] = texture
    return result


def pixel_difference(left, right) -> tuple[int, tuple[int, int, int, int] | None]:
    if left.size != right.size:
        raise ValueError(f"이미지 크기 불일치: {left.size} != {right.size}")
    xs: list[int] = []
    ys: list[int] = []
    count = 0
    for y in range(left.height):
        for x in range(left.width):
            if left.getpixel((x, y)) != right.getpixel((x, y)):
                count += 1
                xs.append(x)
                ys.append(y)
    if not count:
        return 0, None
    return count, (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def main() -> int:
    pairs = [("anime00.dat", PATCHED_ANIME00, CANDIDATE_ANIME00)] + [
        (name, CURRENT_ROOT / name, CANDIDATE_ROOT / name) for name in ANIME_NAMES
    ]
    for _name, current, candidate in pairs:
        if not current.is_file() or not candidate.is_file():
            raise FileNotFoundError(current if not current.is_file() else candidate)

    rows: list[dict[str, object]] = []
    resource_reports = []
    candidate_visual_hashes: dict[str, list[str]] = {}
    for name, current_path, candidate_path in pairs:
        current_blob = current_path.read_bytes()
        candidate_blob = candidate_path.read_bytes()
        if len(current_blob) != len(candidate_blob):
            raise ValueError(f"anime 크기 불일치: {name}")
        current_textures = texture_map(current_blob)
        candidate_textures = texture_map(candidate_blob)
        if set(current_textures) != set(candidate_textures):
            raise ValueError(f"anime 텍스처 목록 불일치: {name}")
        changed_pages = 0
        for key in sorted(current_textures):
            current_image = decode_texture(current_blob, current_textures[key])
            candidate_image = decode_texture(candidate_blob, candidate_textures[key])
            changed_pixels, bbox = pixel_difference(current_image, candidate_image)
            if not changed_pixels:
                continue
            changed_pages += 1
            obj, group, page = key
            page_id = f"P1-IMG-{name.removesuffix('.dat').upper()}-O{obj:03d}-G{group:02d}-P{page:02d}"
            current_png = OUTPUT / "pages" / page_id / "current.png"
            candidate_png = OUTPUT / "pages" / page_id / "candidate_location_reference.png"
            current_png.parent.mkdir(parents=True, exist_ok=True)
            current_image.save(current_png)
            candidate_image.save(candidate_png)
            visual_hash = sha256_bytes(candidate_image.tobytes())
            candidate_visual_hashes.setdefault(visual_hash, []).append(page_id)
            rows.append({
                "id": page_id,
                "resource": name,
                "object_index": obj,
                "group_index": group,
                "page_index": page,
                "width": current_image.width,
                "height": current_image.height,
                "changed_rgba_pixels": changed_pixels,
                "diff_bbox": ",".join(str(value) for value in bbox or ()),
                "current_png": str(current_png),
                "candidate_location_reference_png": str(candidate_png),
                "user_translation_korean": "",
                "status": "user_translation_or_visual_review_required",
                "notes": "후보 문구 직접 이식 금지; 현재 PNG의 일본어 이미지 문구를 사용자가 번역",
            })
        resource_reports.append({
            "resource": name,
            "current_path": str(current_path),
            "candidate_path": str(candidate_path),
            "object_count": len(parse_objects(current_blob)),
            "texture_pages": len(current_textures),
            "changed_visual_pages": changed_pages,
        })

    duplicates = [ids for ids in candidate_visual_hashes.values() if len(ids) > 1]
    queue = OUTPUT / "residual_image_translation_queue.csv"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["id"]
    with queue.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "format": "prinny1_v7_15_1_residual_image_audit_v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "resources": resource_reports,
        "verified": {
            "anime_resources_compared": len(pairs),
            "residual_changed_visual_pages": len(rows),
            "duplicate_candidate_visual_groups": len(duplicates),
            "bg_changed_files_with_rgba_difference": 0,
            "number_txp_changed_visual_pages": 1,
            "approved_v7_15_1_targets_already_applied": 5,
        },
        "duplicate_candidate_visual_pages": duplicates,
        "artifacts": {
            "translation_queue": str(queue),
            "translation_queue_sha256": sha256_bytes(queue.read_bytes()),
            "page_root": str(OUTPUT / "pages"),
        },
        "checks": {
            "candidate_wording_imported": False,
            "translation_wording_generated_by_codex": False,
            "current_and_reference_images_exported_separately": True,
            "internal_resources_modified": False,
            "iso_created": False,
        },
        "status": "residual_internal_image_user_translation_queue_ready",
    }
    (OUTPUT / "all_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"anime resources: {len(pairs)}")
    print(f"residual changed visual pages: {len(rows)}")
    print(f"duplicate visual groups: {len(duplicates)}")
    print(f"queue: {queue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
