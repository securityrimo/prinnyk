from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from psp_localization.util import atomic_write_json


SAFE_RELATIVE_DIRS = (
    Path("workspace/strings"),
    Path("workspace/translations/recovered"),
    Path("workspace/psp_toolkit/game1/iso"),
    Path("workspace/psp_toolkit/game2/iso"),
)

SAFE_RELATIVE_FILES = (
    Path("workspace/translations/catalog/catalog.jsonl"),
    Path("workspace/translations/catalog/translation_template.json"),
    Path("workspace/reports/ppsspp_v4_smoke_console.txt"),
    Path("workspace/reports/ppsspp_v4_smoke.log"),
)

PROTECTED_RELATIVE_FILES = (
    Path("game.iso"),
    Path("game2.iso"),
    Path("build_galmuri14_v5.py"),
    Path("workspace/translations/export/translation_master.csv"),
    Path("workspace/translations/export/translation_master.json"),
    Path("workspace/translations/catalog/catalog.json"),
    Path("workspace/font/audited_allocation_977/hangul_allocation.json"),
    Path("workspace/reports/csv_revision_v4_iso_injection_977.json"),
    Path("workspace/build/final_system_csv_revision_977_v4/start.dat"),
    Path("workspace/build/final_system_csv_revision_977_v4/SYSTEM.DAT"),
    Path("workspace/build/prinny_korean_v4_977.iso"),
)


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def safe_cleanup(root: Path, *, apply: bool, report_path: Path | None = None) -> dict[str, Any]:
    root = root.expanduser().resolve()
    if not root.is_dir() or not (root / "core").is_dir():
        raise ValueError(f"PSP/Prinny 프로젝트 루트가 아닙니다: {root}")

    actions: list[dict[str, Any]] = []
    freed = 0
    for relative in SAFE_RELATIVE_DIRS:
        target = (root / relative).resolve()
        if root not in target.parents:
            raise ValueError(f"프로젝트 밖 경로 거부: {target}")
        size = directory_size(target)
        status = "missing"
        if target.is_dir():
            status = "would_remove"
            if apply:
                shutil.rmtree(target)
                status = "removed"
                freed += size
        actions.append({"kind": "directory", "path": str(relative), "size": size, "status": status})

    for relative in SAFE_RELATIVE_FILES:
        target = (root / relative).resolve()
        if root not in target.parents:
            raise ValueError(f"프로젝트 밖 경로 거부: {target}")
        size = target.stat().st_size if target.is_file() else 0
        status = "missing"
        if target.is_file():
            status = "would_remove"
            if apply:
                target.unlink()
                status = "removed"
                freed += size
        actions.append({"kind": "file", "path": str(relative), "size": size, "status": status})

    # 캐시는 파일 단위로 계산하며 프로젝트 밖 심볼릭 링크는 따라가지 않는다.
    cache_paths = [
        item for item in root.rglob("*")
        if (
            (item.is_dir() and item.name in {"__pycache__", ".pytest_cache"})
            or (item.is_file() and item.suffix == ".pyc")
        )
    ]
    # 상위 캐시 디렉터리를 먼저 선택해 중복 삭제를 방지한다.
    selected: list[Path] = []
    for item in sorted(cache_paths, key=lambda p: len(p.parts)):
        if any(parent == item or parent in item.parents for parent in selected):
            continue
        selected.append(item)
    for target in selected:
        size = directory_size(target) if target.is_dir() else target.stat().st_size
        relative = target.relative_to(root)
        status = "would_remove"
        if apply:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            status = "removed"
            freed += size
        actions.append({"kind": "cache", "path": str(relative), "size": size, "status": status})

    protected = []
    for relative in PROTECTED_RELATIVE_FILES:
        target = root / relative
        protected.append({
            "path": str(relative),
            "present": target.exists(),
            "size": target.stat().st_size if target.is_file() else 0,
        })

    report = {
        "format": "psp_safe_cleanup_v2",
        "root": str(root),
        "apply": apply,
        "freed_bytes": freed,
        "actions": actions,
        "protected": protected,
        "status": "pass",
    }
    if report_path is not None:
        atomic_write_json(report_path, report)
    return report
